"""REST API.

Auth: send `X-API-Key: <key>` (or `?api_key=`). Share links and static report
files are public by design so clients can open them without credentials.
OpenAPI lives at /openapi.json, which is what makes this drop into Zapier,
Make, n8n, Retool or any internal tool without extra glue.
"""
from __future__ import annotations

import asyncio
import secrets
import tempfile
import time
from collections import OrderedDict, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse, PlainTextResponse,
                               Response)
from pydantic import BaseModel, Field, field_validator

from . import db
from .audit import run_audit
from .config import settings
from .report import html as html_report
from .report import pdf as pdf_report
from .worker import queue

app = FastAPI(
    title="SEO Audit Agent",
    version="1.0.0",
    description=("Give it a website URL, get a full SEO audit: crawl, on-page, technical, "
                 "schema, AI-search visibility, speed, authority, competitors, screenshots, "
                 "and a shareable HTML/PDF report."),
)


# ----------------------------------------------------------------- schemas
class AuditRequest(BaseModel):
    url: str = Field(..., description="Website URL to audit", examples=["https://example.com"])
    max_pages: int | None = Field(None, ge=1, le=200, description="Pages to crawl (default 10)")
    target_keywords: list[str] | None = Field(None, description="Optional: skip keyword derivation")
    competitors: list[str] | None = Field(None, description="Optional: audit these competitors")
    include_competitors: bool = True
    include_screenshots: bool = True
    webhook_url: str | None = Field(None, description="POSTed the summary when the audit finishes")
    client_ref: str | None = Field(None, description="Your own client/job id, echoed back")

    @field_validator("url")
    @classmethod
    def _valid(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("url is required")
        if not v.startswith(("http://", "https://")):
            v = "https://" + v
        return v


class AuditAccepted(BaseModel):
    audit_id: str
    status: str
    queue_position: int
    status_url: str
    result_url: str
    report_html: str
    report_pdf: str
    share_url: str


# ----------------------------------------------------------------- auth
def _reject_if_stateless() -> None:
    if settings.stateless:
        raise HTTPException(
            409, "This instance runs in STATELESS mode: nothing is stored, so there is no "
                 "audit history. Use POST /audit.pdf, /audit.html or /audit.json instead.")


# --- abuse protection for open, no-key deployments -----------------------
_hits: dict[str, list[float]] = defaultdict(list)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    return (forwarded.split(",")[0].strip() if forwarded
            else (request.client.host if request.client else "unknown"))


def rate_limit(request: Request) -> None:
    """Per-IP hourly cap. Only enforced when the link is public."""
    if not settings.public_mode or settings.rate_limit_per_hour <= 0:
        return
    ip = _client_ip(request)
    now = time.time()
    recent = [t for t in _hits[ip] if now - t < 3600]
    if len(recent) >= settings.rate_limit_per_hour:
        wait = int((3600 - (now - recent[0])) / 60) + 1
        raise HTTPException(
            429, f"Rate limit reached ({settings.rate_limit_per_hour} audits per hour). "
                 f"Try again in about {wait} minutes.")
    recent.append(now)
    _hits[ip] = recent
    if len(_hits) > 5000:  # keep the table from growing forever
        for key in [k for k, v in _hits.items() if not v or now - v[-1] > 3600]:
            _hits.pop(key, None)


# --- RAM-only report cache: lets the browser download the PDF without -----
# --- re-running the audit, while still writing nothing to disk -----------
_cache: "OrderedDict[str, dict]" = OrderedDict()


def _cache_put(html: str, pdf: bytes | None, filename: str) -> str:
    token = secrets.token_urlsafe(16)
    _cache[token] = {"html": html, "pdf": pdf, "filename": filename,
                     "expires": time.time() + settings.report_cache_minutes * 60}
    while len(_cache) > settings.report_cache_max:
        _cache.popitem(last=False)
    return token


def _cache_get(token: str) -> dict:
    entry = _cache.get(token)
    if not entry or entry["expires"] < time.time():
        _cache.pop(token, None)
        raise HTTPException(404, "This report has expired. Nothing is stored on the server, "
                                 "so please run the audit again.")
    return entry


async def require_key(request: Request,
                      x_api_key: str | None = Header(default=None),
                      api_key: str | None = Query(default=None)) -> str:
    if not settings.require_auth:
        return "anonymous"
    key = x_api_key or api_key or ""
    if key not in settings.api_keys:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return key


# ----------------------------------------------------------------- lifecycle
@app.on_event("startup")
async def _startup() -> None:
    if settings.stateless:
        return  # no database, no queue, no files — nothing to initialise
    db.init_db()
    await queue.start()


# --------------------------------------------------------- stateless mode
async def _run_and_render(req: AuditRequest) -> tuple[dict, str, bytes | None]:
    """Run an audit entirely inside a temp directory and return
    (result, html, pdf_bytes). The directory is deleted before this returns,
    so nothing touches disk beyond the life of the request."""
    with tempfile.TemporaryDirectory(prefix="seoaudit-") as tmp:
        result = await run_audit(
            req.url,
            max_pages=req.max_pages,
            target_keywords=req.target_keywords,
            competitor_urls=req.competitors,
            include_competitors=req.include_competitors,
            include_screenshots=req.include_screenshots,
            workdir=tmp,
        )
        if result.get("status") != "completed":
            raise HTTPException(422, result.get("error", "Audit failed"))
        html = html_report.render(result)   # screenshots are inlined as base64 here
        pdf_bytes = None
        if settings.pdf_enabled:
            path, engine = await pdf_report.generate(result, result["audit_id"], html,
                                                     out_dir=tmp)
            if path:
                pdf_bytes = Path(path).read_bytes()
                result.setdefault("report", {})["pdf_engine"] = engine
        # strip local file paths so nothing leaks a location that no longer exists
        for issue in result.get("issues", []):
            issue.pop("screenshot", None)
        for items in result.get("roadmap", {}).values():
            for issue in items:
                issue.pop("screenshot", None)
        result["site"]["cover_screenshot"] = None
    return result, html, pdf_bytes


@app.post("/audit.pdf", summary="Run an audit and return the PDF — nothing is stored")
async def audit_pdf(req: AuditRequest, request: Request,
                    key: str = Depends(require_key)) -> Any:
    """One call in, one PDF out. No database row, no saved report, no
    screenshots left on disk. Expect 60-180 seconds."""
    rate_limit(request)
    result, _html, pdf_bytes = await _run_and_render(req)
    if not pdf_bytes:
        raise HTTPException(503, "PDF engine unavailable on this host")
    domain = (result["site"]["domain"] or "site").replace(".", "-").replace(":", "-")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="seo-audit-{domain}.pdf"',
            "X-Overall-Score": str(result["scores"]["overall_score"]),
            "X-Grade": result["scores"]["grade"],
            "X-Critical-Issues": str(result["scores"]["issue_counts"]["critical"]),
        },
    )


@app.post("/audit.html", response_class=HTMLResponse,
          summary="Run an audit and return the HTML report — nothing is stored")
async def audit_html(req: AuditRequest, request: Request,
                     key: str = Depends(require_key)) -> Any:
    rate_limit(request)
    _result, html, _pdf = await _run_and_render(req)
    return HTMLResponse(html)


@app.post("/audit.json", summary="Run an audit and return the JSON — nothing is stored")
async def audit_json(req: AuditRequest, request: Request,
                     key: str = Depends(require_key)) -> Any:
    rate_limit(request)
    result, _html, _pdf = await _run_and_render(req)
    return result


@app.post("/audit", summary="Run an audit and get links to the report (public UI uses this)")
async def audit_public(req: AuditRequest, request: Request,
                       key: str = Depends(require_key)) -> Any:
    """Runs the audit, keeps the rendered report in memory only for
    REPORT_CACHE_MINUTES so the browser can fetch the PDF without paying for a
    second crawl, and returns the headline results."""
    rate_limit(request)
    if settings.public_mode:
        req.max_pages = min(req.max_pages or settings.public_max_pages,
                            settings.public_max_pages)
    result, html, pdf_bytes = await _run_and_render(req)
    domain = (result["site"]["domain"] or "site").replace(".", "-").replace(":", "-")
    token = _cache_put(html, pdf_bytes, f"seo-audit-{domain}.pdf")
    return {
        "audit_id": result["audit_id"],
        "site": result["site"],
        "scores": result["scores"],
        "summary": result["summary"],
        "keywords": result["keywords"],
        "ai_visibility": result["ai_visibility"],
        "page_speed": result["page_speed"],
        "issues": result["issues"],
        "recommended_fixes": result["recommended_fixes"],
        "generated_assets": result["generated_assets"],
        "report_html_url": f"/report/{token}",
        "report_html_download_url": f"/report/{token}.html",
        "report_pdf_url": f"/report/{token}.pdf" if pdf_bytes else None,
        "pdf_available": bool(pdf_bytes),
        "expires_in_minutes": settings.report_cache_minutes,
        "stored": False,
    }


@app.get("/report/{token}.html", include_in_schema=False)
async def cached_report_download(token: str) -> Any:
    """Same report, but as a file download rather than opening in the tab."""
    entry = _cache_get(token)
    filename = entry["filename"].replace(".pdf", ".html")
    return HTMLResponse(
        entry["html"],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/report/{token}.pdf", include_in_schema=False)
async def cached_report_pdf(token: str) -> Any:
    entry = _cache_get(token)
    if not entry["pdf"]:
        raise HTTPException(503, "PDF engine unavailable on this host")
    return Response(content=entry["pdf"], media_type="application/pdf",
                    headers={"Content-Disposition":
                             f'attachment; filename="{entry["filename"]}"'})


@app.get("/report/{token}", response_class=HTMLResponse, include_in_schema=False)
async def cached_report(token: str) -> Any:
    return HTMLResponse(_cache_get(token)["html"])


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict:
    return {"status": "ok", "queue_depth": queue.depth,
            "time": datetime.now(timezone.utc).isoformat()}


@app.get("/", include_in_schema=False)
async def home() -> HTMLResponse:
    """Public landing page when the link is open; the operator dashboard when
    the instance is key-protected and storing audits."""
    static = Path(__file__).parent / "static"
    page = "public.html" if (settings.public_mode or settings.stateless) else "dashboard.html"
    return HTMLResponse((static / page).read_text(encoding="utf-8"))


@app.get("/dashboard", include_in_schema=False)
async def operator_dashboard() -> HTMLResponse:
    static = Path(__file__).parent / "static"
    return HTMLResponse((static / "dashboard.html").read_text(encoding="utf-8"))


# ----------------------------------------------------------------- audits
@app.post("/audits", response_model=AuditAccepted, status_code=202,
          summary="Queue an audit")
async def create_audit(req: AuditRequest, key: str = Depends(require_key)) -> Any:
    _reject_if_stateless()
    used = await asyncio.to_thread(db.count_today)
    if used >= settings.daily_audit_quota:
        raise HTTPException(status_code=429,
                            detail=f"Daily quota of {settings.daily_audit_quota} audits reached")
    audit = await asyncio.to_thread(
        db.create_audit, req.url,
        {
            "max_pages": req.max_pages or settings.max_pages,
            "target_keywords": req.target_keywords,
            "competitors": req.competitors,
            "include_competitors": req.include_competitors,
            "include_screenshots": req.include_screenshots,
        },
        key, req.webhook_url or "", req.client_ref or "")
    position = await queue.enqueue(audit.id)
    base = settings.public_base_url.rstrip("/")
    return {
        "audit_id": audit.id,
        "status": "queued",
        "queue_position": position,
        "status_url": f"{base}/audits/{audit.id}",
        "result_url": f"{base}/audits/{audit.id}/result",
        "report_html": f"{base}/audits/{audit.id}/report.html",
        "report_pdf": f"{base}/audits/{audit.id}/report.pdf",
        "share_url": f"{base}/share/{audit.share_token}",
    }


@app.post("/audits/sync", summary="Run an audit and wait for the result")
async def create_audit_sync(req: AuditRequest, key: str = Depends(require_key)) -> Any:
    """Blocking variant for tools that cannot poll. Expect 60-180 seconds."""
    _reject_if_stateless()
    audit = await asyncio.to_thread(
        db.create_audit, req.url,
        {"max_pages": req.max_pages or settings.max_pages,
         "target_keywords": req.target_keywords, "competitors": req.competitors,
         "include_competitors": req.include_competitors,
         "include_screenshots": req.include_screenshots},
        key, "", req.client_ref or "")
    result = await run_audit(
        req.url, max_pages=req.max_pages, target_keywords=req.target_keywords,
        competitor_urls=req.competitors, include_competitors=req.include_competitors,
        include_screenshots=req.include_screenshots, audit_id=audit.id)
    if result.get("status") == "failed":
        await asyncio.to_thread(db.update, audit.id, status="failed", error=result.get("error"))
        raise HTTPException(status_code=422, detail=result.get("error"))
    html_path = await asyncio.to_thread(html_report.write, result, audit.id)
    pdf_path, engine = await pdf_report.generate(result, audit.id)
    result["report"] = {"html": html_path, "pdf": pdf_path, "pdf_engine": engine}
    await asyncio.to_thread(db.save_result, audit.id, result)
    await asyncio.to_thread(db.update, audit.id, html_path=html_path, pdf_path=pdf_path)
    return result


@app.get("/audits", summary="List audits")
async def list_audits(limit: int = Query(50, le=500), offset: int = 0,
                      status: str | None = None, domain: str | None = None,
                      client_ref: str | None = None,
                      key: str = Depends(require_key)) -> Any:
    _reject_if_stateless()
    rows = await asyncio.to_thread(db.list_audits, limit, offset, status, domain, client_ref)
    return {"count": len(rows), "audits": rows}


@app.get("/audits/{audit_id}", summary="Audit status and headline scores")
async def get_audit(audit_id: str, key: str = Depends(require_key)) -> Any:
    _reject_if_stateless()
    audit = await asyncio.to_thread(db.get, audit_id)
    if not audit:
        raise HTTPException(404, "Audit not found")
    return audit.summary()


@app.get("/audits/{audit_id}/result", summary="Full audit JSON")
async def get_result(audit_id: str, key: str = Depends(require_key)) -> Any:
    _reject_if_stateless()
    audit = await asyncio.to_thread(db.get, audit_id)
    if not audit:
        raise HTTPException(404, "Audit not found")
    if not audit.result:
        return JSONResponse({"status": audit.status, "progress": audit.progress,
                             "stage": audit.stage, "error": audit.error}, status_code=202)
    return audit.result


@app.get("/audits/{audit_id}/issues", summary="Issues only, optionally filtered")
async def get_issues(audit_id: str, severity: str | None = None, category: str | None = None,
                     key: str = Depends(require_key)) -> Any:
    _reject_if_stateless()
    audit = await asyncio.to_thread(db.get, audit_id)
    if not audit or not audit.result:
        raise HTTPException(404, "No completed audit with that id")
    issues = audit.result.get("issues", [])
    if severity:
        issues = [i for i in issues if i["impact"] == severity.lower()]
    if category:
        issues = [i for i in issues if i["category"] == category.lower()]
    return {"count": len(issues), "issues": issues}


@app.get("/audits/{audit_id}/report.html", response_class=HTMLResponse,
         summary="Rendered HTML report")
async def report_html(audit_id: str, key: str = Depends(require_key)) -> Any:
    _reject_if_stateless()
    audit = await asyncio.to_thread(db.get, audit_id)
    if not audit or not audit.result:
        raise HTTPException(404, "No completed audit with that id")
    if audit.html_path and Path(audit.html_path).exists():
        return HTMLResponse(Path(audit.html_path).read_text(encoding="utf-8"))
    return HTMLResponse(html_report.render(audit.result))


@app.get("/audits/{audit_id}/report.pdf", summary="Downloadable PDF report")
async def report_pdf(audit_id: str, key: str = Depends(require_key)) -> Any:
    _reject_if_stateless()
    audit = await asyncio.to_thread(db.get, audit_id)
    if not audit or not audit.result:
        raise HTTPException(404, "No completed audit with that id")
    path = audit.pdf_path
    if not path or not Path(path).exists():
        path, _ = await pdf_report.generate(audit.result, audit_id)
        if not path:
            raise HTTPException(503, "PDF engine unavailable on this host")
        await asyncio.to_thread(db.update, audit_id, pdf_path=path)
    domain = (audit.domain or "site").replace(".", "-")
    return FileResponse(path, media_type="application/pdf",
                        filename=f"seo-audit-{domain}-{audit_id[:6]}.pdf")


@app.get("/audits/{audit_id}/llms.txt", response_class=PlainTextResponse,
         summary="Generated llms.txt for the audited site")
async def generated_llms(audit_id: str, key: str = Depends(require_key)) -> Any:
    _reject_if_stateless()
    audit = await asyncio.to_thread(db.get, audit_id)
    if not audit or not audit.result:
        raise HTTPException(404, "No completed audit with that id")
    return audit.result["generated_assets"]["llms_txt"]


@app.delete("/audits/{audit_id}", summary="Delete an audit and its artefacts")
async def delete_audit(audit_id: str, key: str = Depends(require_key)) -> Any:
    _reject_if_stateless()
    audit = await asyncio.to_thread(db.get, audit_id)
    if not audit:
        raise HTTPException(404, "Audit not found")
    for p in (audit.pdf_path, audit.html_path):
        if p:
            Path(p).unlink(missing_ok=True)
    shots = Path(settings.data_dir) / "screenshots" / audit_id
    if shots.exists():
        for f in shots.iterdir():
            f.unlink(missing_ok=True)
        shots.rmdir()
    with db.SessionLocal() as s:
        row = s.get(db.Audit, audit_id)
        if row:
            s.delete(row)
            s.commit()
    return {"deleted": audit_id}


# ----------------------------------------------------------------- sharing
@app.get("/share/{token}", response_class=HTMLResponse, summary="Public shareable report")
async def share(token: str) -> Any:
    _reject_if_stateless()
    audit = await asyncio.to_thread(db.get_by_token, token)
    if not audit or not audit.result:
        raise HTTPException(404, "Report not found")
    if audit.html_path and Path(audit.html_path).exists():
        return HTMLResponse(Path(audit.html_path).read_text(encoding="utf-8"))
    return HTMLResponse(html_report.render(audit.result))


@app.get("/share/{token}/pdf", summary="Public PDF download")
async def share_pdf(token: str) -> Any:
    _reject_if_stateless()
    audit = await asyncio.to_thread(db.get_by_token, token)
    if not audit or not audit.result:
        raise HTTPException(404, "Report not found")
    path = audit.pdf_path
    if not path or not Path(path).exists():
        path, _ = await pdf_report.generate(audit.result, audit.id)
        if not path:
            raise HTTPException(503, "PDF engine unavailable on this host")
        await asyncio.to_thread(db.update, audit.id, pdf_path=path)
    return FileResponse(path, media_type="application/pdf",
                        filename=f"seo-audit-{(audit.domain or 'site').replace('.', '-')}.pdf")


@app.get("/files/{path:path}", include_in_schema=False)
async def files(path: str) -> Any:
    target = (Path(settings.data_dir) / path).resolve()
    if not str(target).startswith(str(Path(settings.data_dir).resolve())) or not target.exists():
        raise HTTPException(404, "Not found")
    return FileResponse(target)


# ----------------------------------------------------------------- ops
@app.get("/stats", summary="Throughput and quota")
async def stats(key: str = Depends(require_key)) -> Any:
    _reject_if_stateless()
    data = await asyncio.to_thread(db.stats)
    data.update({"queue_depth": queue.depth, "workers": len(queue.workers),
                 "in_flight": list(queue.active.values())})
    return data


@app.get("/config", summary="Effective configuration and connected providers")
async def config(key: str = Depends(require_key)) -> Any:
    return {
        "max_pages_default": (settings.public_max_pages if settings.public_mode
                              else settings.max_pages),
        "worker_count": settings.worker_count,
        "daily_audit_quota": settings.daily_audit_quota,
        "public_mode": settings.public_mode,
        "stateless": settings.stateless,
        "rate_limit_per_hour": settings.rate_limit_per_hour,
        "report_cache_minutes": settings.report_cache_minutes,
        "screenshots_enabled": settings.screenshots_enabled,
        "competitors_enabled": settings.competitors_enabled,
        "providers": {
            "pagespeed_insights": bool(settings.psi_api_key),
            "serper": bool(settings.serper_api_key),
            "google_cse": bool(settings.google_api_key and settings.google_cse_id),
            "anthropic_llm": bool(settings.anthropic_api_key),
            "openpagerank": bool(settings.openpagerank_key),
            "dataforseo": bool(settings.dataforseo_login),
        },
    }
