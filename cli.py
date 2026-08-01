"""Command line interface.

    python -m app.cli audit https://example.com --pages 10 --pdf
    python -m app.cli batch clients.txt --concurrency 3
    python -m app.cli serve
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from pathlib import Path

from . import db
from .audit import run_audit
from .config import settings
from .report import html as html_report
from .report import pdf as pdf_report


async def _one(url: str, args: argparse.Namespace, quiet: bool = False) -> dict:
    async def progress(stage: str, pct: int) -> None:
        if not quiet:
            print(f"  [{pct:3d}%] {stage}", file=sys.stderr)

    result = await run_audit(
        url,
        max_pages=args.pages,
        target_keywords=args.keywords.split(",") if args.keywords else None,
        competitor_urls=args.competitors.split(",") if args.competitors else None,
        include_competitors=not args.no_competitors,
        include_screenshots=not args.no_screenshots,
        progress=progress,
    )
    if result.get("status") != "completed":
        print(f"FAILED {url}: {result.get('error')}", file=sys.stderr)
        return result

    audit_id = result["audit_id"]
    out_dir = Path(args.out or settings.data_dir / "reports")
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / f"{audit_id}.json"
    json_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    html_path = html_report.write(result, audit_id, out_dir)
    line = f"{result['site']['domain']}  overall {result['scores']['overall_score']} " \
           f"({result['scores']['grade']})  json={json_path}  html={html_path}"
    if args.pdf:
        pdf_path, engine = await pdf_report.generate(result, audit_id, out_dir=out_dir)
        line += f"  pdf={pdf_path} [{engine}]"
    print(line)
    return result


async def _batch(args: argparse.Namespace) -> None:
    source = Path(args.file)
    urls = [u.strip() for u in source.read_text().splitlines() if u.strip()
            and not u.strip().startswith("#")]
    sem = asyncio.Semaphore(args.concurrency)
    rows: list[dict] = []

    async def worker(url: str) -> None:
        async with sem:
            result = await _one(url, args, quiet=True)
            scores = result.get("scores", {})
            rows.append({
                "url": url,
                "status": result.get("status"),
                "overall": scores.get("overall_score"),
                "grade": scores.get("grade"),
                **(scores.get("headline") or {}),
                "critical": (scores.get("issue_counts") or {}).get("critical"),
                "total_issues": (scores.get("issue_counts") or {}).get("total"),
                "audit_id": result.get("audit_id"),
                "error": result.get("error", ""),
            })

    print(f"Auditing {len(urls)} sites, {args.concurrency} at a time…", file=sys.stderr)
    await asyncio.gather(*[worker(u) for u in urls])

    out = Path(args.csv or "audit-summary.csv")
    if rows:
        with out.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"Summary written to {out}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="seo-audit-agent",
                                     description="Run SEO audits from the command line.")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--pages", type=int, default=settings.max_pages, help="pages to crawl")
    common.add_argument("--keywords", default="", help="comma separated target keywords")
    common.add_argument("--competitors", default="", help="comma separated competitor URLs")
    common.add_argument("--no-competitors", action="store_true")
    common.add_argument("--no-screenshots", action="store_true")
    common.add_argument("--pdf", action="store_true", help="also render a PDF")
    common.add_argument("--out", default="", help="output directory")

    one = sub.add_parser("audit", parents=[common], help="audit a single site")
    one.add_argument("url")

    batch = sub.add_parser("batch", parents=[common], help="audit a file of URLs")
    batch.add_argument("file", help="text file, one URL per line")
    batch.add_argument("--concurrency", type=int, default=3)
    batch.add_argument("--csv", default="", help="summary CSV path")

    sub.add_parser("serve", help="run the API + dashboard")

    args = parser.parse_args()
    db.init_db()

    if args.command == "audit":
        asyncio.run(_one(args.url, args))
    elif args.command == "batch":
        asyncio.run(_batch(args))
    elif args.command == "serve":
        import uvicorn
        uvicorn.run("app.api:app", host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
