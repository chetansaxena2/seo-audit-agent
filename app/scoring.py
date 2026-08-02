"""Scoring engine.

Produces the five headline stats (authority, AI score, error score, page
speed, Google optimised) plus section scores and an overall grade. Every
number is traceable to the findings that produced it — nothing is invented.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from .issues import CATALOG, SEVERITY_WEIGHT, Finding
from .parser import PageData

SECTION_WEIGHTS = {
    "technical": 0.25,
    "google_optimized": 0.20,
    "content": 0.20,
    "authority": 0.15,
    "ai_search": 0.10,
    "speed": 0.10,
}
GRADES = [(90, "A"), (80, "B"), (70, "C"), (60, "D"), (0, "F")]


def _penalty(findings: list[Finding], categories: set[str] | None = None) -> float:
    """Repeat instances of the same issue count less each time."""
    per_code: dict[str, int] = defaultdict(int)
    total = 0.0
    for f in findings:
        spec = CATALOG[f.code]
        if categories and spec.category not in categories:
            continue
        per_code[f.code] += 1
        n = per_code[f.code]
        factor = 1.0 if n == 1 else (0.5 if n <= 3 else 0.2)
        total += SEVERITY_WEIGHT[spec.severity] * factor
    return total


def _curve(penalty: float, k: float) -> float:
    """Smooth decay: 0 penalty = 100, and the score degrades without ever
    slamming to zero, so a long tail of small issues cannot wipe out a site
    that gets the fundamentals right."""
    return round(100.0 * k / (k + max(0.0, penalty)), 1)


def error_score(findings: list[Finding]) -> float:
    return _curve(_penalty(findings), 65.0)


def section_score(findings: list[Finding], *categories: str) -> float:
    return _curve(_penalty(findings, set(categories)), 32.0)


def google_optimized_score(findings: list[Finding], pages: list[PageData],
                           keyword_coverage: float, schema_stats: dict,
                           link_stats: dict) -> tuple[float, list[dict]]:
    """Checklist-style score: how well the site follows Google's documented basics."""
    html_pages = [p for p in pages if p.html and p.ok]
    n = max(1, len(html_pages))
    codes = Counter(f.code for f in findings)
    checks: list[dict] = []

    def add(name: str, earned: float, weight: float, note: str) -> None:
        checks.append({"check": name, "earned": round(earned, 1), "max": weight, "note": note})

    indexable = sum(1 for p in html_pages if p.is_indexable)
    add("Indexable pages", 10 * indexable / n, 10, f"{indexable}/{n} pages indexable")

    https_pts = 6 - (6 if codes["HTTPS_MISSING"] else 0) - (3 if codes["HTTP_NOT_REDIRECTED"] else 0)
    add("HTTPS everywhere", max(0, https_pts), 6, "HTTPS + redirect from HTTP")

    with_canonical = sum(1 for p in html_pages if p.canonical)
    add("Canonical tags", 6 * with_canonical / n - (3 if codes["CANONICAL_CONFLICT"] else 0),
        6, f"{with_canonical}/{n} pages have a canonical")

    good_titles = sum(1 for p in html_pages if p.title and 30 <= len(p.title) <= 60)
    add("Title tags (30-60 chars)", 10 * good_titles / n, 10, f"{good_titles}/{n} within range")

    good_meta = sum(1 for p in html_pages if 70 <= len(p.meta_description) <= 160)
    add("Meta descriptions (70-160)", 8 * good_meta / n, 8, f"{good_meta}/{n} within range")

    good_h1 = sum(1 for p in html_pages if len(p.h1s) == 1 and len(p.h1s[0].text) <= 60)
    add("Single H1 under 60 chars", 8 * good_h1 / n, 8, f"{good_h1}/{n} pages compliant")

    add("Keyword targeting", 12 * min(1.0, keyword_coverage / 80), 12,
        f"average on-page keyword placement {keyword_coverage:.0f}/100")

    imgs = [i for p in html_pages for i in p.images]
    alt_ok = sum(1 for i in imgs if (i.alt or "").strip())
    alt_ratio = alt_ok / len(imgs) if imgs else 1.0
    add("Image alt text", 8 * alt_ratio, 8,
        f"{alt_ok}/{len(imgs)} images have alt text" if imgs else "no images found")

    infra = 8 - (4 if codes["SITEMAP_MISSING"] else 0) - (3 if codes["ROBOTS_MISSING"] else 0) \
        - (1 if codes["ROBOTS_NO_SITEMAP"] else 0)
    add("robots.txt + XML sitemap", max(0, infra), 8, "site files present and linked")

    viewport = sum(1 for p in html_pages if p.viewport)
    add("Mobile viewport", 6 * viewport / n, 6, f"{viewport}/{n} pages")

    broken = link_stats.get("broken_internal", 0)
    add("No broken internal links", max(0.0, 8 - broken * 2), 8, f"{broken} broken internal links")

    dupes = codes["TITLE_DUPLICATE"] + codes["META_DUPLICATE"] + codes["H1_DUPLICATE"] \
        + codes["DUPLICATE_CONTENT"]
    add("Unique titles / content", max(0.0, 6 - dupes * 1.5), 6, f"{dupes} duplication issues")

    schema_pts = 0.0
    if schema_stats.get("has_entity_schema"):
        schema_pts += 2
    if schema_stats.get("has_page_type_schema"):
        schema_pts += 1
    schema_pts += 1 * schema_stats.get("pages_with_schema", 0) / n
    add("Structured data", min(4.0, schema_pts), 4,
        f"{schema_stats.get('pages_with_schema', 0)}/{n} pages carry schema")

    total = sum(max(0.0, c["earned"]) for c in checks)
    return round(min(100.0, total), 1), checks


def compute(findings: list[Finding], pages: list[PageData], ai_score: float,
            speed_score: float, authority: float, keyword_coverage: float,
            schema_stats: dict, link_stats: dict) -> dict:
    counts = Counter(CATALOG[f.code].severity for f in findings)
    tech = section_score(findings, "technical")
    content = section_score(findings, "content")
    onpage = section_score(findings, "on_page")
    schema = section_score(findings, "schema")
    local = section_score(findings, "local")
    cro = section_score(findings, "cro")
    google_opt, checklist = google_optimized_score(
        findings, pages, keyword_coverage, schema_stats, link_stats)

    overall = (
        tech * SECTION_WEIGHTS["technical"]
        + google_opt * SECTION_WEIGHTS["google_optimized"]
        + content * SECTION_WEIGHTS["content"]
        + authority * SECTION_WEIGHTS["authority"]
        + ai_score * SECTION_WEIGHTS["ai_search"]
        + speed_score * SECTION_WEIGHTS["speed"]
    )
    grade = next(g for threshold, g in GRADES if overall >= threshold)

    return {
        "overall_score": round(overall, 1),
        "grade": grade,
        "headline": {
            "authority": round(authority, 1),
            "ai_score": round(ai_score, 1),
            "error_score": error_score(findings),
            "page_speed": round(speed_score, 1),
            "google_optimized": google_opt,
        },
        "sections": {
            "technical": tech,
            "on_page": onpage,
            "content": content,
            "schema": schema,
            "local_seo": local,
            "conversion": cro,
        },
        "issue_counts": {
            "total": len(findings),
            "critical": counts.get("critical", 0),
            "high": counts.get("high", 0),
            "medium": counts.get("medium", 0),
            "low": counts.get("low", 0),
            "unique_issue_types": len({f.code for f in findings}),
        },
        "google_optimized_checklist": checklist,
        "weighting": SECTION_WEIGHTS,
    }
