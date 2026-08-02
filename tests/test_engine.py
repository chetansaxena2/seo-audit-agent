"""End-to-end smoke test.

Serves tests/demo_site (a site seeded with known SEO faults) and asserts the
engine finds each one. Run it after any change to the checks:

    python tests/test_engine.py
"""
from __future__ import annotations

import asyncio
import http.server
import os
import socketserver
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("COMPETITORS_ENABLED", "false")
os.environ.setdefault("SCREENSHOTS_ENABLED", "false")
os.environ.setdefault("PER_HOST_DELAY_MS", "0")

from app.audit import run_audit  # noqa: E402

PORT = 8912
ROOT = Path(__file__).parent / "demo_site"

EXPECTED = {
    "TITLE_TOO_LONG": "homepage title is 100+ characters",
    "TITLE_TOO_SHORT": "services.html has a 8-character title",
    "META_MISSING": "homepage has no meta description",
    "META_TOO_SHORT": "services.html description is too short",
    "H1_MULTIPLE": "homepage has two H1 tags",
    "H1_TOO_LONG": "homepage H1 exceeds 60 characters",
    "IMG_ALT_MISSING": "hero image has no alt attribute",
    "IMG_TITLE_MISSING": "images have no title attribute",
    "IMG_FILENAME_GENERIC": "IMG_2381.jpg is a generic filename",
    "PAGE_4XX": "blog-old.html and pricing-old.html are 404",
    "BROKEN_INTERNAL_LINK": "links point at the 404 pages",
    "NOINDEX": "airport.html is noindex",
    "CANONICAL_MISSING": "services.html has no canonical",
    "CANONICAL_CONFLICT": "airport.html canonicalises to the homepage",
    "DUPLICATE_CONTENT": "packages.html and packages-duplicate.html match",
    "SCHEMA_FAQ_MISSING": "Q&A content exists with no FAQPage schema",
    "SCHEMA_MISSING": "most pages carry no structured data",
    "LLMS_TXT_MISSING": "no /llms.txt",
    "AI_BOTS_BLOCKED": "robots.txt disallows GPTBot",
    "ROBOTS_NO_SITEMAP": "robots.txt has no Sitemap line",
    "HEADING_HIERARCHY": "homepage jumps H2 to H4",
    "THIN_CONTENT": "several pages are under 300 words",
    "ORPHAN_PAGE": "hidden-orphan.html is in the sitemap only",
}


class QuietHandler(http.server.BaseHTTPRequestHandler):
    """Serves the demo site, rewriting its absolute URLs to this port."""

    TYPES = {".html": "text/html", ".xml": "application/xml", ".txt": "text/plain",
             ".jpg": "image/jpeg", ".png": "image/png"}

    def log_message(self, *args):  # noqa: D102
        pass

    def do_GET(self):  # noqa: N802
        rel = self.path.lstrip("/").split("?")[0] or "index.html"
        target = (ROOT / rel).resolve()
        if not str(target).startswith(str(ROOT.resolve())) or not target.is_file():
            self.send_error(404)
            return
        suffix = target.suffix.lower()
        data = target.read_bytes()
        if suffix in (".html", ".xml", ".txt"):
            data = data.replace(b"127.0.0.1:8901", f"127.0.0.1:{PORT}".encode())
        self.send_response(200)
        self.send_header("Content-Type", self.TYPES.get(suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_HEAD(self):  # noqa: N802
        rel = self.path.lstrip("/").split("?")[0] or "index.html"
        target = (ROOT / rel).resolve()
        self.send_response(200 if target.is_file() else 404)
        self.end_headers()


def serve() -> socketserver.TCPServer:
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), QuietHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


async def main() -> int:
    httpd = serve()
    try:
        result = await run_audit(f"http://127.0.0.1:{PORT}/", max_pages=8,
                                 include_competitors=False, include_screenshots=False)
    finally:
        httpd.shutdown()

    if result.get("status") != "completed":
        print("FAIL: audit did not complete —", result.get("error"))
        return 1

    found = {i["code"] for i in result["issues"]}
    missing = [(code, why) for code, why in EXPECTED.items() if code not in found]

    scores = result["scores"]
    print(f"pages crawled : {result['crawl']['pages_crawled']}")
    print(f"issues found  : {len(result['issues'])} across {len(found)} types")
    print(f"overall       : {scores['overall_score']} (grade {scores['grade']})")
    for name, value in scores["headline"].items():
        print(f"  {name:18s}: {value}")
    for key in ("brand", "location"):
        print(f"{key:14s}: {result['site'][key]}")
    print(f"services      : {result['keywords']['detected_services'][:5]}")
    print(f"keywords      : {result['keywords']['primary_keywords'][:5]}")

    assert result["crawl"]["pages_crawled"] >= 6, "crawler should reach at least 6 pages"
    assert 0 <= scores["overall_score"] <= 100
    assert result["generated_assets"]["llms_txt"].startswith("#")
    assert result["generated_assets"]["faq_schema"]["@type"] == "FAQPage"
    assert result["recommended_fixes"], "expected ready-to-paste title/meta fixes"

    if missing:
        print("\nMISSED checks:")
        for code, why in missing:
            print(f"  - {code}: {why}")
        return 1
    print("\nOK — every planted issue was detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
