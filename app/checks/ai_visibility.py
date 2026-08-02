"""AI search / GEO readiness.

Scores how likely the site is to be read, understood and cited by ChatGPT,
Claude, Perplexity, Gemini and Google AI Overviews, then explains the gaps.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .. import llm
from .. import textutil as T
from ..crawler import SiteContext
from ..issues import Finding
from ..parser import PageData

SAMEAS_RE = re.compile(r"(facebook|instagram|linkedin|twitter|x\.com|youtube|pinterest|yelp)\.com",
                       re.I)
DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2}|\d{1,2}\s+\w+\s+20\d{2}|\w+\s+\d{1,2},\s*20\d{2})\b")


@dataclass
class AIReport:
    score: float = 0.0
    components: dict[str, dict] = field(default_factory=dict)
    llms_txt: bool = False
    blocked_bots: list[str] = field(default_factory=list)
    answer_blocks: int = 0
    question_headings: int = 0
    entity_signals: list[str] = field(default_factory=list)
    citation_check: dict | None = None

    def to_dict(self) -> dict:
        return {
            "ai_visibility_score": round(self.score, 1),
            "components": self.components,
            "llms_txt_present": self.llms_txt,
            "ai_crawlers_blocked": self.blocked_bots,
            "extractable_answer_blocks": self.answer_blocks,
            "question_headings": self.question_headings,
            "entity_signals": self.entity_signals,
            "brand_citation_check": self.citation_check,
        }


def _answer_blocks(page: PageData) -> int:
    """Count question headings followed by a concise, self-contained answer."""
    if not page.html:
        return 0
    count = 0
    words = page.main_text.split()
    for h in page.question_headings:
        idx = page.main_text.find(h.text)
        if idx == -1:
            continue
        after = page.main_text[idx + len(h.text): idx + len(h.text) + 700]
        first_sentence_words = len(re.split(r"(?<=[.!?])\s", after.strip())[0].split()) if after.strip() else 0
        if 15 <= first_sentence_words <= 90 or 25 <= len(after.split()) <= 120:
            count += 1
    if not page.question_headings and words:
        # a page that opens with a clear definition also reads well to an LLM
        opener = " ".join(words[:60])
        if re.search(r"\b(is|are|means|refers to|provides|offers)\b", opener):
            count += 1 if page.word_count > 250 else 0
    return count


async def run(ctx: SiteContext, pages: list[PageData], brand: str,
              services: list[str], location: str) -> tuple[AIReport, list[Finding]]:
    findings: list[Finding] = []
    report = AIReport()
    html_pages = [p for p in pages if p.html and p.ok]
    comp: dict[str, dict] = {}

    def add(name: str, earned: float, weight: float, note: str) -> None:
        comp[name] = {"earned": round(earned, 1), "max": weight, "note": note}

    # 1. llms.txt (10)
    report.llms_txt = bool(ctx.llms_txt.strip())
    if report.llms_txt:
        add("llms_txt", 10, 10, "llms.txt published")
    else:
        add("llms_txt", 0, 10, "no /llms.txt found")
        findings.append(Finding("LLMS_TXT_MISSING", url=f"{ctx.base_url}/llms.txt",
                                detail=f"/llms.txt returned {ctx.llms_status or 'no response'}."))

    # 2. AI crawler access (12)
    report.blocked_bots = ctx.robots.blocked_ai_bots()
    if report.blocked_bots:
        add("ai_crawler_access", 0, 12, f"blocked: {', '.join(report.blocked_bots)}")
        findings.append(Finding("AI_BOTS_BLOCKED", url=ctx.robots_url,
                                detail=f"robots.txt blocks {', '.join(report.blocked_bots)}.",
                                evidence=ctx.robots.text[:400]))
    else:
        add("ai_crawler_access", 12, 12, "AI crawlers are allowed")

    # 3. Structured data for machines (20)
    types = {t.lower() for p in html_pages for t in p.schema_types}
    schema_pts = 0.0
    if types & {"organization", "localbusiness", "professionalservice", "store", "autorental"}:
        schema_pts += 8
    if "faqpage" in types:
        schema_pts += 6
    if types & {"service", "product", "article", "blogposting", "webpage", "itemlist"}:
        schema_pts += 4
    if "breadcrumblist" in types:
        schema_pts += 2
    add("structured_data", schema_pts, 20,
        f"schema types: {', '.join(sorted(types)[:6]) or 'none'}")

    # 4. Extractable answers (20)
    report.answer_blocks = sum(_answer_blocks(p) for p in html_pages)
    report.question_headings = sum(len(p.question_headings) for p in html_pages)
    ans_pts = min(20.0, report.answer_blocks * 2.5 + min(6, report.question_headings * 0.6))
    add("extractable_answers", ans_pts, 20,
        f"{report.answer_blocks} answer blocks, {report.question_headings} question headings")
    if ans_pts < 10:
        findings.append(Finding("AI_NO_ANSWER_BLOCKS",
                                url=html_pages[0].final_url if html_pages else ctx.base_url,
                                detail=(f"Only {report.answer_blocks} extractable answer blocks "
                                        f"across {len(html_pages)} pages.")))

    # 5. Entity signals (18)
    signals: list[str] = []
    sameas = [l.url for p in html_pages for l in p.external_links if SAMEAS_RE.search(l.url)]
    schema_sameas = any("sameas" in str(k).lower() for p in html_pages
                        for b in p.jsonld if isinstance(b, dict) for k in b)
    has_about = any(re.search(r"/about|/who-we-are|/our-story", (p.final_url or p.url), re.I)
                    for p in pages)
    has_author = any("author" in str(p.jsonld).lower() for p in html_pages)
    nap = bool(location) and any(p.phones or p.tel_links for p in html_pages)
    ent_pts = 0.0
    if sameas:
        ent_pts += 5; signals.append(f"{len(set(sameas))} social profiles linked")
    if schema_sameas:
        ent_pts += 4; signals.append("sameAs in schema")
    if has_about:
        ent_pts += 4; signals.append("about page present")
    if has_author:
        ent_pts += 2; signals.append("author markup")
    if nap:
        ent_pts += 3; signals.append("NAP visible")
    report.entity_signals = signals
    add("entity_signals", ent_pts, 18, ", ".join(signals) or "no strong entity signals")
    if ent_pts < 9:
        findings.append(Finding("AI_NO_ENTITY_SIGNALS", url=ctx.base_url,
                                detail="Weak entity signals: " + (", ".join(signals) or "none found")))

    # 6. Freshness (8)
    dated = [p for p in html_pages if p.dates or DATE_RE.search(p.text[:2500])]
    fresh_pts = 8.0 if len(dated) >= max(2, len(html_pages) // 3) else (4.0 if dated else 0.0)
    add("freshness", fresh_pts, 8, f"{len(dated)}/{len(html_pages)} pages show dates")
    if fresh_pts < 4:
        findings.append(Finding("AI_NO_FRESHNESS", url=ctx.base_url,
                                detail="No visible published/updated dates on crawled pages."))

    # 7. Content depth & structure (12)
    avg_words = sum(p.word_count for p in html_pages) / max(1, len(html_pages))
    struct = sum(p.lists_count + p.tables_count for p in html_pages)
    depth_pts = min(8.0, avg_words / 900 * 8) + min(4.0, struct * 0.4)
    add("content_depth", depth_pts, 12,
        f"avg {avg_words:.0f} words/page, {struct} lists+tables")

    report.components = comp
    report.score = sum(c["earned"] for c in comp.values())

    # 8. Optional live citation check (does the model actually know this brand?)
    if llm.available() and brand:
        query = f"{brand} {services[0] if services else ''} {location}".strip()
        data = await llm.complete_json(
            f"Search the web and answer: when someone asks an AI assistant about "
            f"\"{services[0] if services else 'this service'} in {location or 'their area'}\", "
            f"does the brand \"{brand}\" ({ctx.base_url}) appear as a recommended or cited source? "
            "Return JSON: {\"brand_found\": bool, \"cited_domains\": [str up to 5], "
            "\"visibility_note\": str}",
            tools=llm.WEB_SEARCH_TOOL, max_tokens=1200)
        if isinstance(data, dict):
            report.citation_check = {"query": query, **data}
    return report, findings


def build_llms_txt(ctx: SiteContext, brand: str, services: list[str], location: str,
                   pages: list[PageData]) -> str:
    """Ready-to-publish llms.txt the client can paste at /llms.txt."""
    lines = [f"# {brand}", ""]
    home = next((p for p in pages if p.html), None)
    summary = (home.meta_description or home.intro_text[:220]) if home else ""
    if summary:
        lines += [f"> {summary.strip()}", ""]
    if location:
        lines += [f"Location / service area: {location}", ""]
    if services:
        lines += ["## Services", ""] + [f"- {s}" for s in services[:12]] + [""]
    lines += ["## Key pages", ""]
    for p in pages[:10]:
        if not p.html:
            continue
        title = p.title or (p.h1s[0].text if p.h1s else p.path)
        desc = (p.meta_description or p.intro_text[:110]).strip()
        lines.append(f"- [{title}]({p.final_url or p.url}): {desc}")
    contact = next((t for p in pages for t in p.tel_links), "")
    email = next((m for p in pages for m in p.mailto_links), "")
    if contact or email:
        lines += ["", "## Contact", ""]
        if contact:
            lines.append(f"- Phone: {contact}")
        if email:
            lines.append(f"- Email: {email}")
    return "\n".join(lines) + "\n"
