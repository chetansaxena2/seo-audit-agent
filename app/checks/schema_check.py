"""Structured data / schema markup checks."""
from __future__ import annotations

from ..issues import Finding
from ..parser import PageData

ENTITY_TYPES = ("Organization", "LocalBusiness", "ProfessionalService", "Store",
                "Restaurant", "TravelAgency", "AutoRental", "Corporation", "Person")
PAGE_TYPES = ("Service", "Product", "Article", "BlogPosting", "NewsArticle", "WebPage",
              "CollectionPage", "ItemList", "Event", "Course", "Recipe")


def run(pages: list[PageData]) -> tuple[list[Finding], dict]:
    out: list[Finding] = []
    html_pages = [p for p in pages if p.html and p.ok]
    all_types: set[str] = set()
    pages_with_schema = 0

    for page in html_pages:
        url = page.final_url or page.url
        types = page.schema_types
        all_types.update(types)
        if types:
            pages_with_schema += 1
        else:
            out.append(Finding("SCHEMA_MISSING", url=url,
                               detail="No JSON-LD or microdata found on this page.",
                               selector="head"))
        if page.jsonld_errors:
            out.append(Finding("SCHEMA_INVALID", url=url,
                               detail=f"{len(page.jsonld_errors)} JSON-LD block(s) failed to parse.",
                               evidence="; ".join(page.jsonld_errors[:3])))

    site_url = (html_pages[0].final_url or html_pages[0].url) if html_pages else ""
    low = {t.lower() for t in all_types}

    if not any(t.lower() in low for t in ENTITY_TYPES):
        out.append(Finding("SCHEMA_ORG_MISSING", url=site_url,
                           detail="No Organization or LocalBusiness schema anywhere in the crawl."))
    if "faqpage" not in low:
        faq_candidates = [p for p in html_pages if len(p.question_headings) >= 2]
        detail = "No FAQPage schema found."
        if faq_candidates:
            detail += (f" {len(faq_candidates)} page(s) already have Q&A content that could be "
                       "marked up immediately.")
        out.append(Finding("SCHEMA_FAQ_MISSING", url=site_url, detail=detail,
                           extra={"ready_pages": [p.final_url or p.url for p in faq_candidates[:5]]}))
    if "breadcrumblist" not in low:
        out.append(Finding("SCHEMA_BREADCRUMB_MISSING", url=site_url,
                           detail="No BreadcrumbList markup detected."))

    stats = {
        "pages_with_schema": pages_with_schema,
        "pages_without_schema": len(html_pages) - pages_with_schema,
        "schema_types_found": sorted(all_types),
        "has_entity_schema": any(t.lower() in low for t in ENTITY_TYPES),
        "has_faq_schema": "faqpage" in low,
        "has_breadcrumb_schema": "breadcrumblist" in low,
        "has_page_type_schema": any(t.lower() in low for t in PAGE_TYPES),
        "invalid_blocks": sum(len(p.jsonld_errors) for p in html_pages),
    }
    return out, stats
