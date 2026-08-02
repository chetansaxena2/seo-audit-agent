"""Authority / backlink analysis.

Providers are optional and pluggable. With no provider configured the agent
still returns an authority estimate, clearly labelled as on-site-signal based
so nobody mistakes it for real link data.
"""
from __future__ import annotations

import base64
import math
from dataclasses import dataclass, field

import httpx

from ..config import settings
from ..crawler import SiteContext
from ..issues import Finding
from ..parser import PageData


@dataclass
class AuthorityReport:
    score: float = 0.0
    source: str = "on-site-estimate"
    is_estimate: bool = True
    referring_domains: int | None = None
    backlinks: int | None = None
    domain_rating: float | None = None
    spam_score: float | None = None
    top_referrers: list[dict] = field(default_factory=list)
    anchors: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "authority_score": round(self.score, 1),
            "source": self.source,
            "is_estimate": self.is_estimate,
            "referring_domains": self.referring_domains,
            "backlinks": self.backlinks,
            "domain_rating": self.domain_rating,
            "spam_score": self.spam_score,
            "top_referring_domains": self.top_referrers[:10],
            "anchor_text_sample": self.anchors[:10],
            "notes": self.notes,
        }


async def _open_page_rank(domain: str) -> dict | None:
    if not settings.openpagerank_key:
        return None
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get("https://openpagerank.com/api/v1.0/getPageRank",
                            params={"domains[]": domain},
                            headers={"API-OPR": settings.openpagerank_key})
            r.raise_for_status()
            rows = r.json().get("response", [])
            return rows[0] if rows else None
    except Exception:
        return None


async def _dataforseo(domain: str) -> dict | None:
    if not (settings.dataforseo_login and settings.dataforseo_password):
        return None
    token = base64.b64encode(
        f"{settings.dataforseo_login}:{settings.dataforseo_password}".encode()).decode()
    payload = [{"target": domain, "internal_list_limit": 10, "backlinks_status_type": "live"}]
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post("https://api.dataforseo.com/v3/backlinks/summary/live",
                             json=payload, headers={"Authorization": f"Basic {token}"})
            r.raise_for_status()
            tasks = r.json().get("tasks", [])
            result = (tasks[0].get("result") or [{}])[0] if tasks else {}
            return result or None
    except Exception:
        return None


def _onsite_estimate(ctx: SiteContext, pages: list[PageData], content_stats: dict,
                     schema_stats: dict) -> tuple[float, list[str]]:
    """A defensible proxy when no link data is available."""
    notes: list[str] = []
    html_pages = [p for p in pages if p.html and p.ok]
    score = 0.0

    indexable = sum(1 for p in html_pages if p.is_indexable)
    score += min(20, indexable * 2)
    notes.append(f"{indexable} indexable pages crawled")

    depth = content_stats.get("avg_word_count", 0)
    score += min(20, depth / 900 * 20)
    notes.append(f"average {depth} words per page")

    if ctx.https_ok:
        score += 8
    if ctx.sitemap_locations:
        score += 6
    if ctx.robots.exists:
        score += 4
    if schema_stats.get("has_entity_schema"):
        score += 8
        notes.append("entity schema present")
    if not content_stats.get("missing_trust_pages"):
        score += 8
        notes.append("about/contact/policy pages present")

    outbound_quality = sum(1 for p in html_pages for l in p.external_links
                           if any(d in l.url for d in (".gov", ".edu", "wikipedia.org")))
    score += min(6, outbound_quality * 2)

    internal_links = sum(len(p.internal_links) for p in html_pages)
    score += min(10, internal_links / max(1, len(html_pages)) / 3)
    notes.append(f"{internal_links} internal links across the crawl")

    sitemap_size = len(ctx.sitemap_urls)
    score += min(10, math.log10(sitemap_size + 1) * 6)
    if sitemap_size:
        notes.append(f"{sitemap_size} URLs in sitemap")
    return min(100.0, score), notes


async def analyse(ctx: SiteContext, pages: list[PageData], content_stats: dict,
                  schema_stats: dict) -> tuple[AuthorityReport, list[Finding]]:
    domain = ctx.netloc.replace("www.", "")
    report = AuthorityReport()
    findings: list[Finding] = []

    dfs = await _dataforseo(domain)
    if dfs:
        report.source = "dataforseo"
        report.is_estimate = False
        report.referring_domains = dfs.get("referring_domains")
        report.backlinks = dfs.get("backlinks")
        report.domain_rating = dfs.get("rank")
        report.spam_score = dfs.get("broken_backlinks")
        rd = report.referring_domains or 0
        report.score = min(100.0, math.log10(rd + 1) * 33 + (report.domain_rating or 0) * 0.4)
        report.notes.append(f"{rd} referring domains, {report.backlinks or 0} backlinks (DataForSEO)")
    else:
        opr = await _open_page_rank(domain)
        if opr and opr.get("status_code") == 200:
            report.source = "openpagerank"
            report.is_estimate = False
            report.domain_rating = float(opr.get("page_rank_decimal") or 0) * 10
            report.score = min(100.0, report.domain_rating)
            report.notes.append(f"Open PageRank {opr.get('page_rank_decimal')}/10 "
                                f"(global rank {opr.get('rank')})")

    if report.source == "on-site-estimate":
        score, notes = _onsite_estimate(ctx, pages, content_stats, schema_stats)
        report.score, report.notes = score, notes
        report.notes.append(
            "No backlink API configured — score derived from on-site authority signals only. "
            "Connect DataForSEO, Semrush, Ahrefs or Open PageRank for true link metrics.")

    if report.score < 40:
        findings.append(Finding("LOW_AUTHORITY", url=ctx.base_url,
                                detail=(f"Authority score {report.score:.0f}/100 "
                                        f"({report.source}). "
                                        + (f"{report.referring_domains} referring domains."
                                           if report.referring_domains is not None else
                                           "No link data connected; estimate from on-site signals.")),
                                evidence="; ".join(report.notes[:3])))
    return report, findings
