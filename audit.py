"""Audit orchestrator: runs the full pipeline for one website."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from . import llm, scoring
from .checks import (ai_visibility, backlinks, competitors, content, keywords,
                     local_cro, onpage, pagespeed, schema_check, technical)
from .config import settings
from .crawler import Crawler
from .issues import CATALOG, Finding, group_by_severity, sort_findings
from .parser import PageData
from .screenshots import capture, screenshot_url


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _suggest_title(primary: str, brand: str, location: str, current: str) -> str:
    kw = (primary or current or brand).strip()
    kw = kw[:1].upper() + kw[1:]
    parts = [kw]
    if location and location.lower() not in kw.lower():
        parts[0] = f"{kw} in {location}"
    candidate = f"{parts[0]} | {brand}" if brand else parts[0]
    if len(candidate) > 60:
        candidate = f"{parts[0][:57 - len(brand) - 3]}… | {brand}" if brand else parts[0][:60]
    return candidate[:60]


def _suggest_meta(primary: str, brand: str, location: str, page: PageData) -> str:
    kw = primary or (page.h1s[0].text if page.h1s else brand)
    where = f" in {location}" if location else ""
    cta = "Get a free quote today."
    base = (f"Looking for {kw.lower()}{where}? {brand} offers reliable, transparent service with "
            f"fast response times. {cta}")
    if len(base) > 158:
        base = base[:155].rsplit(" ", 1)[0] + "…"
    if len(base) < 120:
        base = base[:-1] + f" Trusted by local customers{where}. {cta}"
    return base[:160]


def _local_business_schema(brand: str, base_url: str, location: str, page: PageData,
                           services: list[str]) -> dict:
    phone = (page.tel_links or page.phones or [""])[0]
    return {
        "@context": "https://schema.org",
        "@type": "LocalBusiness",
        "name": brand,
        "url": base_url,
        "telephone": phone,
        "address": {"@type": "PostalAddress", "addressLocality": location or "YOUR CITY",
                    "streetAddress": "YOUR STREET ADDRESS", "postalCode": "YOUR PIN/ZIP",
                    "addressCountry": "IN"},
        "areaServed": location or "YOUR SERVICE AREA",
        "description": (page.meta_description or page.intro_text[:200]).strip(),
        "makesOffer": [{"@type": "Offer", "itemOffered": {"@type": "Service", "name": s}}
                       for s in services[:6]],
        "sameAs": ["https://www.facebook.com/YOURPAGE", "https://www.instagram.com/YOURPAGE"],
        "openingHoursSpecification": [{
            "@type": "OpeningHoursSpecification",
            "dayOfWeek": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                          "Saturday", "Sunday"],
            "opens": "09:00", "closes": "18:00"}],
    }


def _faq_schema(pages: list[PageData]) -> dict:
    qas = []
    for p in pages:
        for h in p.question_headings[:3]:
            idx = p.main_text.find(h.text)
            answer = p.main_text[idx + len(h.text): idx + len(h.text) + 260].strip() if idx >= 0 else ""
            qas.append({"@type": "Question", "name": h.text,
                        "acceptedAnswer": {"@type": "Answer",
                                           "text": answer or "ADD A 40-60 WORD DIRECT ANSWER HERE"}})
        if len(qas) >= 6:
            break
    if not qas:
        qas = [{"@type": "Question", "name": "ADD A REAL CUSTOMER QUESTION",
                "acceptedAnswer": {"@type": "Answer", "text": "ADD A DIRECT 40-60 WORD ANSWER."}}]
    return {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": qas[:6]}


async def _executive_summary(payload: dict) -> dict | None:
    if not llm.available():
        return None
    slim = {
        "url": payload["site"]["url"],
        "scores": payload["scores"]["headline"],
        "overall": payload["scores"]["overall_score"],
        "top_issues": [{"problem": i["problem"], "impact": i["impact"], "url": i["url"]}
                       for i in payload["issues"][:18]],
        "keywords": payload["keywords"]["primary_keywords"][:8],
        "services": payload["keywords"]["detected_services"][:8],
        "competitor_gaps": payload.get("competitors", {}).get("comparison", {}).get("gaps", [])[:5],
        "speed": payload["page_speed"],
    }
    data = await llm.complete_json(
        "You are a senior SEO consultant writing the executive summary of a client audit. "
        f"Audit data:\n{json.dumps(slim)[:12000]}\n\n"
        "Return JSON: {\"verdict\": one sentence, \"strengths\": [3 strings], "
        "\"weaknesses\": [3 strings], \"opportunities\": [3 strings], "
        "\"first_30_days\": [4 concrete actions in priority order]}. "
        "Be specific and reference real numbers from the data. No fluff.",
        max_tokens=1400)
    return data if isinstance(data, dict) else None


def _fallback_summary(payload: dict) -> dict:
    s = payload["scores"]
    counts = s["issue_counts"]
    roadmap = payload["roadmap"]
    strengths, weaknesses = [], []
    head = s["headline"]
    for label, value in head.items():
        text = f"{label.replace('_', ' ').title()} at {value}/100"
        (strengths if value >= 70 else weaknesses).append(text)
    top = [i["problem"] for i in (roadmap["critical"] + roadmap["high"])[:3]]
    return {
        "verdict": (f"Overall SEO score {s['overall_score']}/100 (grade {s['grade']}) with "
                    f"{counts['critical']} critical and {counts['high']} high-priority issues "
                    f"across {payload['crawl']['pages_crawled']} crawled pages."),
        "strengths": strengths[:3] or ["Site is reachable and crawlable."],
        "weaknesses": weaknesses[:3] or ["No major weaknesses detected in the crawled sample."],
        "opportunities": top or ["Expand keyword-targeted content."],
        "first_30_days": [i["recommended_fix"] for i in
                          (roadmap["critical"] + roadmap["high"] + roadmap["medium"])[:4]],
    }


async def run_audit(url: str, *, max_pages: int | None = None,
                    target_keywords: list[str] | None = None,
                    competitor_urls: list[str] | None = None,
                    include_competitors: bool = True,
                    include_screenshots: bool = True,
                    audit_id: str | None = None,
                    workdir: str | None = None,
                    progress: Any = None) -> dict:
    started = time.time()
    audit_id = audit_id or uuid.uuid4().hex[:16]
    max_pages = max_pages or settings.max_pages

    async def step(name: str, pct: int) -> None:
        if progress:
            await progress(name, pct)

    findings: list[Finding] = []

    await step("Resolving site and reading robots.txt / sitemap / llms.txt", 5)
    async with Crawler() as crawler:
        ctx = await crawler.load_site_context(url)
        await step(f"Crawling up to {max_pages} pages", 15)
        pages = await crawler.crawl(ctx, max_pages)
        if not any(p.html for p in pages):
            return {
                "audit_id": audit_id, "status": "failed", "url": url,
                "error": "No HTML page could be fetched. Check the URL, DNS, TLS or firewall.",
                "pages_attempted": [{"url": p.url, "status": p.status, "error": p.error}
                                    for p in pages[:5]],
                "finished_at": _now(),
            }

        await step("Running technical, on-page and content checks", 35)
        findings += technical.site_level(ctx, pages)
        findings += technical.per_page(pages, ctx)
        findings += onpage.run(pages)
        content_findings, content_stats = content.run(pages)
        findings += content_findings
        schema_findings, schema_stats = schema_check.run(pages)
        findings += schema_findings
        arch_findings, arch_stats = technical.architecture(ctx, pages)
        findings += arch_findings

        await step("Checking links for 404s and redirect chains", 50)
        link_findings, link_stats = await technical.link_health(crawler, pages, ctx)
        findings += link_findings

        await step("Analysing keywords, services and relevance", 60)
        kw_profile, kw_findings = await keywords.analyse(ctx, pages, target_keywords)
        findings += kw_findings

        await step("Scoring AI search visibility", 68)
        ai_report, ai_findings = await ai_visibility.run(
            ctx, pages, kw_profile.brand, kw_profile.services, kw_profile.location)
        findings += ai_findings

        local_findings, local_stats = local_cro.run(ctx, pages, kw_profile.location)
        findings += local_findings

        await step("Measuring page speed and Core Web Vitals", 75)
        speed_report, speed_findings = await pagespeed.analyse(pages)
        findings += speed_findings
        home = next(p for p in pages if p.html)
        weights = speed_report.image_weights or await pagespeed.image_weights(crawler, home)
        findings += onpage.image_weight_findings(home, weights)

        await step("Estimating authority and backlink profile", 82)
        authority_report, auth_findings = await backlinks.analyse(
            ctx, pages, content_stats, schema_stats)
        findings += auth_findings

    comp_data: dict = {"enabled": False, "competitors": []}
    if include_competitors and settings.competitors_enabled:
        await step("Researching competitors", 88)
        try:
            comp_data = await asyncio.wait_for(
                competitors.analyse(ctx, pages, kw_profile.services, kw_profile.location,
                                    kw_profile.primary_keywords, competitor_urls),
                timeout=180)
        except asyncio.TimeoutError:
            comp_data = {"enabled": True, "competitors": [], "note": "competitor research timed out"}

    cover = None
    if include_screenshots and settings.screenshots_enabled:
        await step("Capturing screenshot evidence", 92)
        try:
            extras = await asyncio.wait_for(
                capture(findings, audit_id, cover_url=ctx.base_url, base_dir=workdir),
                timeout=180)
            cover = extras.get("cover")
        except asyncio.TimeoutError:
            pass

    await step("Scoring and building the report", 96)
    findings = sort_findings(findings)
    scores = scoring.compute(
        findings, pages, ai_report.score, speed_report.score, authority_report.score,
        kw_profile.coverage_score, schema_stats, link_stats)

    grouped = group_by_severity(findings)
    roadmap = {sev: [f.to_dict() for f in items] for sev, items in grouped.items()}

    # ready-to-paste fixes for the worst offending pages
    fixes: list[dict] = []
    kw_by_url = {p.url: p for p in kw_profile.pages}
    for page in [p for p in pages if p.html and p.ok][:10]:
        url_ = page.final_url or page.url
        pk = kw_by_url.get(url_)
        primary = pk.primary if pk else ""
        issues_here = [f.code for f in findings if f.url == url_]
        needs = {c for c in issues_here if c.startswith(("TITLE", "META", "H1"))}
        if not needs:
            continue
        fixes.append({
            "url": url_,
            "primary_keyword": primary,
            "current_title": page.title,
            "suggested_title": _suggest_title(primary, kw_profile.brand, kw_profile.location,
                                              page.title),
            "current_meta_description": page.meta_description,
            "suggested_meta_description": _suggest_meta(primary, kw_profile.brand,
                                                        kw_profile.location, page),
            "current_h1": page.h1s[0].text if page.h1s else "",
            "suggested_h1": (f"{primary.title()} in {kw_profile.location}"
                             if primary and kw_profile.location else
                             (primary.title() or (page.h1s[0].text if page.h1s else ""))) [:60],
            "issues_addressed": sorted(needs),
        })

    payload: dict[str, Any] = {
        "audit_id": audit_id,
        "status": "completed",
        "generated_at": _now(),
        "duration_sec": round(time.time() - started, 1),
        "site": {
            "input_url": url,
            "url": ctx.base_url,
            "domain": ctx.netloc,
            "brand": kw_profile.brand,
            "location": kw_profile.location,
            "https": ctx.https_ok,
            "robots_txt": ctx.robots.exists,
            "robots_url": ctx.robots_url,
            "sitemap_found": bool(ctx.sitemap_locations),
            "sitemap_locations": ctx.sitemap_locations,
            "sitemap_url_count": len(ctx.sitemap_urls),
            "llms_txt": bool(ctx.llms_txt.strip()),
            "cover_screenshot": screenshot_url(cover),
        },
        "scores": scores,
        "crawl": {
            "pages_crawled": len([p for p in pages if p.html]),
            "pages_requested": max_pages,
            "pages": [p.to_dict() for p in pages],
            **arch_stats,
        },
        "keywords": kw_profile.to_dict(),
        "ai_visibility": ai_report.to_dict(),
        "page_speed": speed_report.to_dict(),
        "authority": authority_report.to_dict(),
        "content": content_stats,
        "schema": schema_stats,
        "links": link_stats,
        "local_seo": local_stats,
        "competitors": comp_data,
        "issues": [
            {**f.to_dict(), "screenshot_url": screenshot_url(f.screenshot)}
            for f in findings
        ],
        "roadmap": {
            sev: [{**i, "screenshot_url": screenshot_url(i.get("screenshot"))} for i in items]
            for sev, items in roadmap.items()
        },
        "recommended_fixes": fixes,
        "generated_assets": {
            "llms_txt": ai_visibility.build_llms_txt(
                ctx, kw_profile.brand, kw_profile.services, kw_profile.location, pages),
            "local_business_schema": _local_business_schema(
                kw_profile.brand, ctx.base_url, kw_profile.location, home, kw_profile.services),
            "faq_schema": _faq_schema([p for p in pages if p.html]),
        },
        "data_sources": {
            "page_speed": speed_report.source,
            "authority": authority_report.source,
            "keywords": kw_profile.source,
            "competitors": comp_data.get("competitors") and comp_data["competitors"][0].get("found_via")
                           or comp_data.get("note", "not run"),
            "llm_assist": llm.available(),
        },
    }

    summary = await _executive_summary(payload) or _fallback_summary(payload)
    payload["summary"] = summary
    await step("Done", 100)
    return payload
