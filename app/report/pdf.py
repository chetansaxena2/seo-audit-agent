"""PDF generation.

Engine order: headless Chromium (best fidelity, same rendering as the HTML
report) → WeasyPrint → a ReportLab summary that always works. The chosen
engine is reported back so the API can surface it.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from ..config import settings
from .html import render as render_html


async def _chromium(html: str, out_path: Path) -> bool:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return False
    tmp = out_path.with_suffix(".src.html")
    tmp.write_text(html, encoding="utf-8")
    try:
        async with async_playwright() as p:
            from ..screenshots import browser_args
            browser = await p.chromium.launch(args=browser_args())
            page = await browser.new_page()
            await page.goto(tmp.as_uri(), wait_until="load", timeout=90000)
            await page.emulate_media(media="print")
            await page.pdf(path=str(out_path), format="A4", print_background=True,
                           margin={"top": "12mm", "bottom": "14mm", "left": "0mm", "right": "0mm"},
                           display_header_footer=True,
                           header_template="<div></div>",
                           footer_template=(
                               "<div style='font:9px -apple-system,sans-serif;color:#5A6B80;"
                               "width:100%;padding:0 12mm;display:flex;justify-content:space-between'>"
                               "<span>SEO Audit Report</span>"
                               "<span class='pageNumber'></span></div>"))
            await browser.close()
        return out_path.exists()
    except Exception:
        return False
    finally:
        tmp.unlink(missing_ok=True)


def _weasyprint(html: str, out_path: Path) -> bool:
    try:
        from weasyprint import HTML  # type: ignore
    except Exception:
        return False
    try:
        HTML(string=html).write_pdf(str(out_path))
        return out_path.exists()
    except Exception:
        return False


def _reportlab(result: dict, out_path: Path) -> bool:
    """Always-available fallback: a clean text/table summary."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (Image, PageBreak, Paragraph, SimpleDocTemplate,
                                        Spacer, Table, TableStyle)
    except Exception:
        return False

    from xml.sax.saxutils import escape

    def esc(text: object) -> str:
        return escape(str(text or ""))

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1x", parent=styles["Heading1"], fontSize=20, spaceAfter=8,
                        textColor=colors.HexColor("#0B1F33"))
    h2 = ParagraphStyle("h2x", parent=styles["Heading2"], fontSize=13, spaceBefore=12,
                        textColor=colors.HexColor("#16324F"))
    body = ParagraphStyle("bodyx", parent=styles["BodyText"], fontSize=9.5, leading=13)
    small = ParagraphStyle("smallx", parent=body, fontSize=8, textColor=colors.HexColor("#5A6B80"))

    doc = SimpleDocTemplate(str(out_path), pagesize=A4, title="SEO Audit Report",
                            leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=14 * mm, bottomMargin=14 * mm)
    story = []
    site, scores = result["site"], result["scores"]
    story.append(Paragraph(f"SEO Audit — {esc(site.get('brand') or site['domain'])}", h1))
    story.append(Paragraph(f"{site['url']} · {result['generated_at'][:10]} · "
                           f"{result['crawl']['pages_crawled']} pages crawled", small))
    story.append(Spacer(1, 8))

    head = scores["headline"]
    rows = [["Overall", "Grade", "Authority", "AI score", "Error score", "Page speed", "Google opt."],
            [f"{scores['overall_score']:.0f}", scores["grade"],
             f"{head['authority']:.0f}", f"{head['ai_score']:.0f}", f"{head['error_score']:.0f}",
             f"{head['page_speed']:.0f}", f"{head['google_optimized']:.0f}"]]
    table = Table(rows, colWidths=[24 * mm] * 7)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B1F33")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#DCE4ED")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 6),
    ]))
    story += [table, Spacer(1, 10)]

    summary = result.get("summary", {})
    story.append(Paragraph("Executive summary", h2))
    story.append(Paragraph(esc(summary.get("verdict", "")), body))
    for label in ("strengths", "weaknesses", "opportunities", "first_30_days"):
        items = summary.get(label) or []
        if items:
            story.append(Paragraph(label.replace("_", " ").title(), h2))
            for i in items:
                story.append(Paragraph(f"• {esc(i)}", body))

    story.append(PageBreak())
    story.append(Paragraph("Priority fix roadmap", h1))
    for sev in ("critical", "high", "medium", "low"):
        items = result["roadmap"].get(sev, [])
        if not items:
            continue
        story.append(Paragraph(f"{sev.title()} ({len(items)})", h2))
        for issue in items[:20]:
            story.append(Paragraph(f"<b>{esc(issue['problem'])}</b>", body))
            story.append(Paragraph(esc(issue['url'] or ''), small))
            story.append(Paragraph(f"Found: {esc(issue['detail'])}", body))
            story.append(Paragraph(f"Why: {esc(issue['why_it_matters'])}", body))
            story.append(Paragraph(f"Fix: {esc(issue['recommended_fix'])}", body))
            story.append(Paragraph(f"Benefit: {esc(issue['expected_benefit'])}", small))
            shot = issue.get("screenshot")
            if shot and Path(shot).exists():
                try:
                    story.append(Image(shot, width=150 * mm, height=90 * mm, kind="proportional"))
                except Exception:
                    pass
            story.append(Spacer(1, 6))
        if len(items) > 20:
            story.append(Paragraph(f"+ {len(items) - 20} more in the JSON export", small))
    try:
        doc.build(story)
        return out_path.exists()
    except Exception:
        return False


async def generate(result: dict, audit_id: str, html: str | None = None,
                   out_dir: str | Path | None = None) -> tuple[str | None, str]:
    """Returns (path, engine_used)."""
    if not settings.pdf_enabled:
        return None, "disabled"
    out_dir = (Path(out_dir) if out_dir else Path(settings.data_dir) / "reports").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{audit_id}.pdf"
    html = html or render_html(result)

    if await _chromium(html, path):
        return str(path), "chromium"
    if await asyncio.to_thread(_weasyprint, html, path):
        return str(path), "weasyprint"
    if await asyncio.to_thread(_reportlab, result, path):
        return str(path), "reportlab"
    return None, "unavailable"
