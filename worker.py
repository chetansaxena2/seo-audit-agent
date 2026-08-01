"""Background queue.

A fixed pool of asyncio workers drains a queue of audits. Queue state lives in
the database, so a restart re-queues anything that was mid-flight — which is
what makes 500 audits/day survivable on one box.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx

from . import db
from .audit import run_audit
from .config import settings
from .report import html as html_report
from .report import pdf as pdf_report

log = logging.getLogger("seoagent.worker")


class AuditQueue:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.workers: list[asyncio.Task] = []
        self.active: dict[str, str] = {}

    async def start(self, count: int | None = None) -> None:
        count = count or settings.worker_count
        for i in range(count):
            self.workers.append(asyncio.create_task(self._loop(i)))
        for audit_id in await asyncio.to_thread(db.pending_audits):
            await self.queue.put(audit_id)
        log.info("started %s workers", count)

    async def stop(self) -> None:
        for w in self.workers:
            w.cancel()
        self.workers.clear()

    async def enqueue(self, audit_id: str) -> int:
        await self.queue.put(audit_id)
        return self.queue.qsize()

    @property
    def depth(self) -> int:
        return self.queue.qsize()

    async def _loop(self, worker_id: int) -> None:
        while True:
            audit_id = await self.queue.get()
            self.active[str(worker_id)] = audit_id
            try:
                await self._process(audit_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # never let one audit kill a worker
                log.exception("audit %s failed", audit_id)
                await asyncio.to_thread(
                    db.update, audit_id, status="failed", error=f"{type(exc).__name__}: {exc}",
                    finished_at=datetime.now(timezone.utc))
            finally:
                self.active.pop(str(worker_id), None)
                self.queue.task_done()

    async def _process(self, audit_id: str) -> None:
        audit = await asyncio.to_thread(db.get, audit_id)
        if not audit or audit.status == "completed":
            return
        options = audit.options or {}
        await asyncio.to_thread(db.update, audit_id, status="running", progress=1,
                                stage="starting", started_at=datetime.now(timezone.utc))

        last: dict[str, int] = {"pct": -1}

        async def progress(stage: str, pct: int) -> None:
            if pct != last["pct"]:
                last["pct"] = pct
                await asyncio.to_thread(db.update, audit_id, stage=stage, progress=pct)

        try:
            result = await asyncio.wait_for(
                run_audit(
                    audit.url,
                    max_pages=options.get("max_pages"),
                    target_keywords=options.get("target_keywords"),
                    competitor_urls=options.get("competitors"),
                    include_competitors=options.get("include_competitors", True),
                    include_screenshots=options.get("include_screenshots", True),
                    audit_id=audit_id,
                    progress=progress,
                ),
                timeout=settings.audit_timeout_sec,
            )
        except asyncio.TimeoutError:
            await asyncio.to_thread(db.update, audit_id, status="failed",
                                    error=f"Audit exceeded {settings.audit_timeout_sec}s timeout",
                                    finished_at=datetime.now(timezone.utc))
            return

        if result.get("status") == "failed":
            await asyncio.to_thread(db.update, audit_id, status="failed",
                                    error=result.get("error"), result=result,
                                    finished_at=datetime.now(timezone.utc))
            await self._webhook(audit.webhook_url, result)
            return

        await progress("Rendering report", 98)
        html_path = await asyncio.to_thread(html_report.write, result, audit_id)
        html_text = await asyncio.to_thread(lambda: open(html_path, encoding="utf-8").read())
        pdf_path, engine = await pdf_report.generate(result, audit_id, html_text)
        result["report"] = {"html": html_path, "pdf": pdf_path, "pdf_engine": engine}

        await asyncio.to_thread(db.save_result, audit_id, result)
        await asyncio.to_thread(db.update, audit_id, html_path=html_path, pdf_path=pdf_path)
        fresh = await asyncio.to_thread(db.get, audit_id)
        await self._webhook(audit.webhook_url, fresh.summary() if fresh else result)

    @staticmethod
    async def _webhook(url: str | None, payload: dict) -> None:
        if not url:
            return
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                await client.post(url, json=payload)
        except Exception:
            log.warning("webhook delivery failed for %s", url)


queue = AuditQueue()
