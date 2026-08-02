"""Content quality: thin pages, near-duplicate bodies, FAQ coverage,
trust/E-E-A-T pages."""
from __future__ import annotations

from itertools import combinations

from .. import textutil as T
from ..issues import Finding
from ..parser import PageData

THIN_WORDS = 300
DUPLICATE_THRESHOLD = 0.72
MIN_WORDS_FOR_DUPLICATE = 120
TRUST_SLUGS = {
    "about": ("about", "who-we-are", "our-story", "company"),
    "contact": ("contact", "get-in-touch", "reach-us"),
    "privacy": ("privacy", "privacy-policy"),
    "terms": ("terms", "terms-and-conditions", "tnc"),
}


def run(pages: list[PageData]) -> tuple[list[Finding], dict]:
    out: list[Finding] = []
    html_pages = [p for p in pages if p.html and p.ok and p.is_indexable]

    for page in html_pages:
        url = page.final_url or page.url
        if page.word_count < THIN_WORDS:
            out.append(Finding("THIN_CONTENT", url=url,
                               detail=f"Only {page.word_count} words of main content.",
                               evidence=page.intro_text[:200]))

    # near-duplicate detection over shingle sets
    # Pages with very little unique text (search pages, empty listings) share only
    # boilerplate, so comparing them produces false 100% matches — skip those, and
    # report each page once so one templated section cannot flood the report.
    dupes: list[dict] = []
    comparable = [p for p in html_pages if p.word_count >= MIN_WORDS_FOR_DUPLICATE and p.shingles]
    already_reported: set[str] = set()
    for a, b in combinations(comparable, 2):
        sim = T.jaccard(a.shingles, b.shingles)
        if sim < DUPLICATE_THRESHOLD:
            continue
        ua, ub = a.final_url or a.url, b.final_url or b.url
        dupes.append({"a": ua, "b": ub, "similarity": round(sim * 100, 1)})
        if ua in already_reported or ub in already_reported:
            continue
        already_reported.add(ua)
        out.append(Finding("DUPLICATE_CONTENT", url=ua,
                           detail=f"{sim*100:.0f}% content overlap with {ub}.",
                           evidence=a.intro_text[:180],
                           extra={"other_url": ub, "similarity_pct": round(sim * 100, 1)}))

    # FAQ / question-led content
    faq_pages = [p for p in html_pages if len(p.question_headings) >= 2]
    if html_pages and not faq_pages:
        out.append(Finding("NO_FAQ_CONTENT", url=html_pages[0].final_url or html_pages[0].url,
                           detail="No page in the crawl has question-led headings or an FAQ block."))

    # trust pages
    all_paths = " ".join((p.final_url or p.url).lower() for p in pages)
    all_anchors = " ".join(l.url.lower() + " " + l.anchor.lower()
                           for p in pages for l in p.internal_links)
    missing = [name for name, slugs in TRUST_SLUGS.items()
               if not any(s in all_paths or s in all_anchors for s in slugs)]
    if missing:
        out.append(Finding("NO_TRUST_PAGES", url=pages[0].final_url or pages[0].url if pages else "",
                           detail=f"No link found to: {', '.join(missing)}.",
                           evidence="checked crawled URLs and internal anchors"))

    words = [p.word_count for p in html_pages] or [0]
    stats = {
        "avg_word_count": round(sum(words) / len(words)),
        "min_word_count": min(words),
        "max_word_count": max(words),
        "thin_pages": sum(1 for w in words if w < THIN_WORDS),
        "duplicate_pairs": dupes,
        "pages_with_faq_headings": len(faq_pages),
        "avg_readability": round(
            sum(T.readability(p.main_text) for p in html_pages) / max(1, len(html_pages)), 1),
        "missing_trust_pages": missing,
    }
    return out, stats
