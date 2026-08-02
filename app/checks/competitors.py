"""Competitor discovery and comparison.

Competitors are found from the site's own services + location (or supplied by
the caller), then crawled lightly and compared on the signals that actually
move rankings.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any
from urllib.parse import urlparse

import httpx

from .. import llm
from .. import textutil as T
from ..config import settings
from ..crawler import Crawler, SiteContext
from ..parser import PageData

AGGREGATORS = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com", "youtube.com",
    "wikipedia.org", "quora.com", "reddit.com", "pinterest.com", "yelp.com", "tripadvisor.com",
    "justdial.com", "indiamart.com", "sulekha.com", "amazon.com", "flipkart.com", "google.com",
    "maps.google.com", "yellowpages.com", "glassdoor.com", "indeed.com", "medium.com",
    "makemytrip.com", "goibibo.com", "booking.com", "trivago.com", "olx.in", "99acres.com",
}


BLOG_RE = re.compile(r"/(blog|news|article|articles|insights|resources|post|posts|guide)s?(/|$)", re.I)
SERVICE_RE = re.compile(
    r"/(service|services|solution|solutions|package|packages|product|products|hire|rental|"
    r"rent|booking|book|tour|tours|plan|plans|pricing|course|courses|treatment)s?(/|-|$)", re.I)
LOCATION_RE = re.compile(
    r"/(location|locations|area|areas|city|cities|branch|branches|serving|near-me)s?(/|-|$)"
    r"|/(in|near|at)-[a-z]{3,}", re.I)
SOCIAL_RE = re.compile(
    r"(facebook|instagram|linkedin|twitter|x\.com|youtube|pinterest|yelp|tiktok|whatsapp)\.", re.I)
COPYRIGHT_RE = re.compile(r"(?:©|&copy;|copyright)\s*(?:19|20)(\d{2})", re.I)
YEAR_RANGE_RE = re.compile(r"\b(19[89]\d|20[0-2]\d)\s*[–-]\s*(?:19|20)\d{2}")


@dataclass
class Competitor:
    domain: str
    url: str
    name: str = ""
    source: str = ""
    is_own: bool = False
    error: str = ""

    # size and structure
    pages_total: int = 0
    pages_checked: int = 0
    avg_words: int = 0
    service_pages: int = 0
    location_pages: int = 0
    blog_posts: int = 0

    # on-page quality
    meta_optimized_pct: float = 0.0
    images_with_alt_pct: float = 0.0
    images_total: int = 0
    h1_count: int = 0
    subheadings: int = 0
    question_headings: int = 0
    internal_links: int = 0
    duplicate_pairs: int = 0

    # machine readability
    schema_types: list[str] = field(default_factory=list)
    has_faq_schema: bool = False
    has_llms_txt: bool = False
    ai_ready_score: float = 0.0
    ai_content_score: float = 0.0

    # trust and reach
    social_links: int = 0
    social_names: list[str] = field(default_factory=list)
    since_year: int = 0
    https: bool = False
    has_robots: bool = False

    # speed
    load_ms: int = 0
    page_kb: float = 0.0

    title: str = ""
    meta_description: str = ""
    h1: str = ""
    keyword_hits: dict[str, bool] = field(default_factory=dict)
    strengths: list[str] = field(default_factory=list)

    @property
    def schema_count(self) -> int:
        return len(self.schema_types)

    @property
    def website_age(self) -> str:
        from datetime import datetime
        if not self.since_year:
            return "not stated"
        return f"{max(0, datetime.now().year - self.since_year)} yrs"

    def to_dict(self) -> dict:
        return {
            "domain": self.domain, "url": self.url, "name": self.name,
            "found_via": self.source, "is_own": self.is_own, "error": self.error,
            "pages_total": self.pages_total, "pages_checked": self.pages_checked,
            "avg_words": self.avg_words, "service_pages": self.service_pages,
            "location_pages": self.location_pages, "blog_posts": self.blog_posts,
            "meta_optimized_pct": round(self.meta_optimized_pct, 1),
            "images_with_alt_pct": round(self.images_with_alt_pct, 1),
            "images_total": self.images_total, "h1_count": self.h1_count,
            "subheadings": self.subheadings, "question_headings": self.question_headings,
            "internal_links": self.internal_links, "duplicate_pairs": self.duplicate_pairs,
            "schema_types": self.schema_types, "schema_count": self.schema_count,
            "has_faq_schema": self.has_faq_schema, "has_llms_txt": self.has_llms_txt,
            "ai_ready_score": round(self.ai_ready_score), 
            "ai_content_score": round(self.ai_content_score),
            "social_links": self.social_links, "social_names": self.social_names,
            "since_year": self.since_year, "website_age": self.website_age,
            "https": self.https, "has_robots": self.has_robots,
            "load_ms": self.load_ms, "page_kb": round(self.page_kb, 1),
            "title": self.title, "title_length": len(self.title),
            "meta_description_length": len(self.meta_description), "h1": self.h1,
            "keyword_coverage": self.keyword_hits, "strengths": self.strengths,
        }


def profile_from_pages(comp: Competitor, pages: list[PageData], sitemap_urls: list[str],
                       keywords: list[str], ai_bots_blocked: bool = False) -> Competitor:
    """Everything the comparison needs, measured the same way for every site."""
    html_pages = [p for p in pages if p.html]
    if not html_pages:
        comp.error = comp.error or "no readable pages"
        return comp
    home = html_pages[0]

    comp.pages_checked = len(html_pages)
    comp.pages_total = len(sitemap_urls) or len(html_pages)
    words = [p.word_count for p in html_pages]
    comp.avg_words = round(sum(words) / len(words))

    urls = sitemap_urls or [(p.final_url or p.url) for p in html_pages]
    link_urls = urls + [l.url for p in html_pages for l in p.internal_links]
    link_urls = list(dict.fromkeys(link_urls))
    comp.blog_posts = sum(1 for u in link_urls if BLOG_RE.search(urlparse(u).path))
    comp.service_pages = sum(1 for u in link_urls if SERVICE_RE.search(urlparse(u).path))
    comp.location_pages = sum(1 for u in link_urls if LOCATION_RE.search(urlparse(u).path))

    good_meta = 0
    for p in html_pages:
        score = 0
        if p.title and 25 <= len(p.title) <= 65:
            score += 1
        if p.meta_description and 60 <= len(p.meta_description) <= 165:
            score += 1
        if p.canonical:
            score += 1
        if p.viewport:
            score += 1
        if p.og:
            score += 1
        good_meta += score / 5
    comp.meta_optimized_pct = 100 * good_meta / len(html_pages)

    imgs = [i for p in html_pages for i in p.images]
    comp.images_total = len(imgs)
    comp.images_with_alt_pct = (100 * sum(1 for i in imgs if (i.alt or "").strip()) / len(imgs)
                                if imgs else 0.0)

    comp.h1_count = len(home.h1s)
    comp.subheadings = sum(len(p.subheadings) for p in html_pages)
    comp.question_headings = sum(len(p.question_headings) for p in html_pages)
    comp.internal_links = len(home.internal_links)

    for a, b in combinations(html_pages, 2):
        if a.word_count >= 120 and b.word_count >= 120 and \
                T.jaccard(a.shingles, b.shingles) >= 0.72:
            comp.duplicate_pairs += 1

    comp.schema_types = T.dedupe_keep_order([t for p in html_pages for t in p.schema_types])
    comp.has_faq_schema = any(p.has_schema("FAQPage") for p in html_pages)

    socials = {SOCIAL_RE.search(l.url).group(1).lower()
               for p in html_pages for l in p.external_links if SOCIAL_RE.search(l.url)}
    comp.social_names = sorted(socials)
    comp.social_links = len(socials)

    years = []
    for p in html_pages:
        for m in COPYRIGHT_RE.finditer(p.text[-2500:]):
            years.append(int(("19" if int(m.group(1)) > 60 else "20") + m.group(1)))
        for m in YEAR_RANGE_RE.finditer(p.text[-2500:]):
            years.append(int(m.group(1)))
    if years:
        comp.since_year = min(years)

    comp.load_ms = home.load_ms
    comp.page_kb = home.bytes / 1024
    comp.title = home.title
    comp.meta_description = home.meta_description
    comp.h1 = home.h1s[0].text if home.h1s else ""

    # AI readiness: can machines find, read and quote this site
    ai = 0.0
    if comp.has_llms_txt:
        ai += 25
    if not ai_bots_blocked:
        ai += 25
    if comp.has_faq_schema:
        ai += 25
    if comp.schema_types:
        ai += 15
    if comp.question_headings >= 2:
        ai += 10
    comp.ai_ready_score = min(100.0, ai)

    # AI content: is the writing shaped the way AI answers quote it
    lists_tables = sum(p.lists_count + p.tables_count for p in html_pages)
    content = (min(35.0, comp.question_headings * 7)
               + min(30.0, comp.avg_words / 900 * 30)
               + min(20.0, lists_tables * 2)
               + min(15.0, comp.subheadings * 1.5))
    comp.ai_content_score = min(100.0, content)

    blob = " ".join(f"{p.title} {p.heading_text} {p.main_text}" for p in html_pages)
    comp.keyword_hits = {k: T.contains_phrase(blob, k) for k in keywords[:8]}
    _score_strengths(comp)
    return comp


def _score_strengths(comp: Competitor) -> None:
    if comp.blog_posts >= 5:
        comp.strengths.append(f"publishes regularly ({comp.blog_posts} blog pages) so Google "
                              "sees the site as active")
    if comp.location_pages >= 2:
        comp.strengths.append(f"{comp.location_pages} location pages capturing 'near me' searches")
    if comp.service_pages >= 3:
        comp.strengths.append(f"{comp.service_pages} separate service pages, one per search term")
    if comp.avg_words > 600:
        comp.strengths.append(f"long pages ({comp.avg_words} words on average) that answer more "
                              "customer questions")
    if comp.has_faq_schema:
        comp.strengths.append("FAQ markup, so Google shows their answers directly in results")
    if comp.schema_count >= 3:
        comp.strengths.append(f"business data in code ({', '.join(comp.schema_types[:3])})")
    if comp.has_llms_txt:
        comp.strengths.append("an llms.txt file guiding ChatGPT and Perplexity")
    if comp.images_with_alt_pct > 85:
        comp.strengths.append("descriptions on nearly every image, earning image search traffic")
    if comp.social_links >= 3:
        comp.strengths.append(f"linked social profiles ({', '.join(comp.social_names[:4])}) "
                              "confirming the brand is real")
    if comp.load_ms and comp.load_ms < 1200:
        comp.strengths.append(f"a fast homepage ({comp.load_ms} ms)")
    if comp.since_year:
        comp.strengths.append(f"an established brand, online since {comp.since_year}")
    if comp.meta_optimized_pct > 80:
        comp.strengths.append("clean titles and descriptions on every page")


async def _serper(query: str, count: int) -> list[dict]:
    if not settings.serper_api_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post("https://google.serper.dev/search",
                             json={"q": query, "num": max(10, count * 3)},
                             headers={"X-API-KEY": settings.serper_api_key,
                                      "Content-Type": "application/json"})
            r.raise_for_status()
            data = r.json()
    except Exception:
        return []
    out = []
    for item in data.get("organic", []):
        out.append({"url": item.get("link", ""), "name": item.get("title", ""),
                    "source": "serper/google"})
    return out


async def _google_cse(query: str, count: int) -> list[dict]:
    if not (settings.google_api_key and settings.google_cse_id):
        return []
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get("https://www.googleapis.com/customsearch/v1",
                            params={"key": settings.google_api_key, "cx": settings.google_cse_id,
                                    "q": query, "num": 10})
            r.raise_for_status()
            data = r.json()
    except Exception:
        return []
    return [{"url": i.get("link", ""), "name": i.get("title", ""), "source": "google-cse"}
            for i in data.get("items", [])]


async def _llm_search(query: str, own_domain: str, count: int) -> list[dict]:
    if not llm.available():
        return []
    data = await llm.complete_json(
        f"Search the web for businesses competing for the query: \"{query}\". "
        f"Ignore the domain {own_domain}, directories, marketplaces and social networks. "
        f"Return the {count} strongest direct competitor businesses as JSON: "
        "[{\"name\": str, \"url\": str}]",
        tools=llm.WEB_SEARCH_TOOL, max_tokens=1200)
    if not isinstance(data, list):
        return []
    return [{"url": d.get("url", ""), "name": d.get("name", ""), "source": "llm-web-search"}
            for d in data if isinstance(d, dict) and d.get("url")]


def _clean(cands: list[dict], own_domain: str, count: int) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for c in cands:
        url = c.get("url") or ""
        if not url.startswith("http"):
            continue
        host = urlparse(url).netloc.lower().replace("www.", "")
        if not host or host in seen:
            continue
        if host == own_domain or own_domain in host or host in own_domain:
            continue
        if any(host == a or host.endswith("." + a) for a in AGGREGATORS):
            continue
        seen.add(host)
        scheme = urlparse(url).scheme or "https"
        out.append({"domain": host, "url": f"{scheme}://{host}/",
                    "name": c.get("name", host), "source": c.get("source", "")})
        if len(out) >= count:
            break
    return out


async def discover(ctx: SiteContext, services: list[str], location: str,
                   supplied: list[str] | None, count: int) -> list[dict]:
    if supplied:
        return _clean([{"url": u if u.startswith("http") else f"https://{u}",
                        "name": u, "source": "user-supplied"} for u in supplied],
                      ctx.netloc.replace("www.", ""), count)
    own = ctx.netloc.replace("www.", "")
    service = services[0] if services else "services"
    query = f"{service} {location}".strip() or own
    results = await _serper(query, count)
    if not results:
        results = await _google_cse(query, count)
    if not results:
        results = await _llm_search(query, own, count)
    cleaned = _clean(results, own, count)
    if len(cleaned) < count and len(services) > 1:
        more = await _serper(f"{services[1]} {location}".strip(), count) \
            or await _google_cse(f"{services[1]} {location}".strip(), count)
        cleaned = _clean([{"url": c["url"], "name": c.get("name", ""), "source": c.get("source", "")}
                          for c in cleaned] + more, own, count)
    return cleaned


async def profile_one(crawler: Crawler, cand: dict, keywords: list[str],
                      max_pages: int = 5) -> Competitor:
    comp = Competitor(domain=cand["domain"], url=cand["url"],
                      name=cand.get("name", ""), source=cand.get("source", ""))
    home: PageData = await crawler.fetch(cand["url"], root_netloc=cand["domain"])
    if not home.html and cand["url"].startswith("https://"):
        home = await crawler.fetch(cand["url"].replace("https://", "http://", 1),
                                   root_netloc=cand["domain"])
    if not home.html:
        comp.error = home.error or f"HTTP {home.status}"
        return comp

    base = (home.final_url or home.url)
    origin = base[:base.index("/", 8)] if "/" in base[8:] else base.rstrip("/")
    comp.https = origin.startswith("https")

    # follow a few of their own pages so word counts and meta quality are fair
    seen = {base.rstrip("/")}
    candidates: list[str] = []
    for link in home.internal_links:
        u = link.url.split("#")[0].rstrip("/")
        if u in seen or any(u.lower().endswith(e) for e in (".pdf", ".jpg", ".png")):
            continue
        seen.add(u)
        rank = 0 if SERVICE_RE.search(urlparse(u).path) else (
            1 if LOCATION_RE.search(urlparse(u).path) else (
                2 if BLOG_RE.search(urlparse(u).path) else 3))
        candidates.append((rank, u))
    candidates.sort()
    extra = [u for _, u in candidates[:max_pages - 1]]
    others = await asyncio.gather(*[crawler.fetch(u, root_netloc=comp.domain) for u in extra]) \
        if extra else []
    pages = [home] + [p for p in others if p.html]

    status, text = await crawler.fetch_text(f"{origin}/llms.txt")
    comp.has_llms_txt = status == 200 and "<html" not in text[:300].lower()
    status, robots = await crawler.fetch_text(f"{origin}/robots.txt")
    comp.has_robots = status == 200 and "<html" not in robots[:300].lower()
    ai_blocked = bool(re.search(r"user-agent:\s*(gptbot|claudebot|perplexitybot|google-extended)",
                                robots, re.I)) and "disallow: /" in robots.lower()

    sitemap_urls: list[str] = []
    for path in ("/sitemap.xml", "/sitemap_index.xml", "/wp-sitemap.xml", "/sitemap-index.xml"):
        status, xml = await crawler.fetch_text(f"{origin}{path}")
        if status == 200 and "<loc" in xml:
            sitemap_urls = re.findall(r"<loc>\s*([^<\s]+)", xml)
            if len(sitemap_urls) < 3 and "sitemap" in xml.lower():   # index file
                child = sitemap_urls[0] if sitemap_urls else ""
                if child:
                    st2, xml2 = await crawler.fetch_text(child)
                    if st2 == 200:
                        sitemap_urls += re.findall(r"<loc>\s*([^<\s]+)", xml2)
            break

    return profile_from_pages(comp, pages, sitemap_urls, keywords, ai_blocked)


def build_own(ctx: SiteContext, pages: list[PageData], keywords: list[str],
              llms_txt: bool) -> Competitor:
    """The client's own site, measured with exactly the same ruler."""
    own = Competitor(domain=ctx.netloc, url=ctx.base_url, name="Your website",
                     source="this audit", is_own=True)
    own.https = ctx.https_ok
    own.has_robots = ctx.robots.exists
    own.has_llms_txt = llms_txt
    return profile_from_pages(own, [p for p in pages if p.html], ctx.sitemap_urls, keywords,
                              bool(ctx.robots.blocked_ai_bots()))


ROWS: list[tuple[str, str, str, str]] = [
    # (label, attribute, higher|lower|bool, why it matters, in the client's words)
    ("Pages on the website", "pages_total", "higher",
     "Every extra useful page is another search you can turn up for."),
    ("Average words per page", "avg_words", "higher",
     "Google ranks the page that answers more of the customer's questions."),
    ("Service pages", "service_pages", "higher",
     "One page per service. A single page cannot rank for everything you sell."),
    ("Location pages", "location_pages", "higher",
     "Separate pages per area are how you win 'near me' and city searches."),
    ("Blog pages published", "blog_posts", "higher",
     "Regular posts tell Google the business is active and build topical trust."),
    ("Business data in code (schema)", "schema_count", "higher",
     "This is how Google confirms who you are, what you sell and where you work."),
    ("FAQ markup", "has_faq_schema", "bool",
     "Puts your answers directly into search results and AI replies."),
    ("AI search readiness", "ai_ready_score", "higher",
     "Whether ChatGPT, Gemini and Perplexity can read and recommend you. Out of 100."),
    ("Content written for AI answers", "ai_content_score", "higher",
     "Question headings and clear short answers are what AI tools quote. Out of 100."),
    ("Guide for AI assistants (llms.txt)", "has_llms_txt", "bool",
     "A simple file telling AI tools what you offer and which pages to read."),
    ("Titles and descriptions optimised", "meta_optimized_pct", "higher",
     "The blue line and grey text in Google. Weak ones lose the click even when you rank."),
    ("Images with descriptions", "images_with_alt_pct", "higher",
     "Described images bring image search traffic and pass accessibility checks."),
    ("Question-style headings", "question_headings", "higher",
     "These are what Google shows as featured answers."),
    ("Internal links on homepage", "internal_links", "higher",
     "Links pass ranking power through to the pages that make you money."),
    ("Social profiles linked", "social_links", "higher",
     "Confirms to Google that a real, established business is behind the website."),
    ("Website age", "since_year", "older",
     "Older domains carry more trust. It is also what customers judge you on."),
    ("Duplicate content", "duplicate_pairs", "lower",
     "Repeated text makes your own pages compete with each other and both lose."),
    ("Homepage load time", "load_ms", "lower",
     "Slow pages lose customers on mobile data and rank lower."),
    ("Page weight", "page_kb", "lower",
     "Heavy pages crawl slowly on mobile networks, where most customers are."),
    ("Secure site (HTTPS)", "https", "bool",
     "Browsers warn visitors away from sites without it."),
]


def _value(comp: Competitor, attr: str) -> Any:
    if attr == "schema_count":
        return comp.schema_count
    return getattr(comp, attr, 0)


def _display(attr: str, comp: Competitor) -> str:
    value = _value(comp, attr)
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if attr == "since_year":
        return f"since {value} ({comp.website_age})" if value else "not stated"
    if attr in ("images_with_alt_pct", "meta_optimized_pct"):
        return f"{value:.0f}%"
    if attr in ("ai_ready_score", "ai_content_score"):
        return f"{value:.0f}/100"
    if attr == "load_ms":
        return f"{value} ms" if value else "—"
    if attr == "page_kb":
        return f"{value:.0f} KB" if value else "—"
    return str(value)


def compare_table(own: Competitor, comps: list[Competitor]) -> dict:
    """Row by row, measured identically, with a plain reading of who is ahead."""
    live = [c for c in comps if not c.error]
    rows: list[dict] = []
    losing: list[dict] = []
    winning: list[str] = []

    for label, attr, direction, why in ROWS:
        mine = _value(own, attr)
        theirs = [(c, _value(c, attr)) for c in live]
        cells = [{"domain": c.domain, "value": _display(attr, c)} for c, _ in theirs]

        beaten_by, ahead_of = [], []
        for c, v in theirs:
            if direction == "higher":
                if v > mine * 1.15 and v > 0:
                    beaten_by.append(c.domain)
                elif mine > v * 1.15 and mine > 0:
                    ahead_of.append(c.domain)
            elif direction == "lower":
                if mine and v and v < mine * 0.8:
                    beaten_by.append(c.domain)
                elif mine and v and mine < v * 0.8:
                    ahead_of.append(c.domain)
            elif direction == "older":
                if v and (not mine or v < mine):
                    beaten_by.append(c.domain)
                elif mine and (not v or mine < v):
                    ahead_of.append(c.domain)
            else:  # bool
                if v and not mine:
                    beaten_by.append(c.domain)
                elif mine and not v:
                    ahead_of.append(c.domain)

        verdict = "Behind" if beaten_by else ("Ahead" if ahead_of else "Level")
        rows.append({"label": label, "why": why, "you": _display(attr, own),
                     "competitors": cells, "verdict": verdict, "beaten_by": beaten_by})
        if beaten_by:
            gap = ""
            if direction in ("higher", "lower") and theirs:
                best = max(v for _, v in theirs) if direction == "higher" else min(
                    v for _, v in theirs if v) if any(v for _, v in theirs) else 0
                if isinstance(best, (int, float)) and isinstance(mine, (int, float)):
                    gap = f"{_display(attr, own)} vs {best:.0f}" if best else ""
            losing.append({"label": label, "who": beaten_by, "gap": gap, "why": why})
        elif ahead_of:
            winning.append(label.lower())

    per_competitor = []
    for c in live:
        edge = [k for k, hit in c.keyword_hits.items() if hit and not own.keyword_hits.get(k)]
        per_competitor.append({
            "domain": c.domain, "url": c.url, "title": c.title,
            "doing_well": c.strengths[:8] or ["nothing beyond the basics"],
            "keyword_edge": edge,
            "profile": (f"{c.pages_total} pages · {c.avg_words} words per page · "
                        f"{c.service_pages} service pages · {c.location_pages} location pages · "
                        f"{c.blog_posts} blog pages · AI readiness {c.ai_ready_score:.0f}/100"),
        })

    behind, ahead = len(losing), len(winning)
    level = len(rows) - behind - ahead
    top = [l["label"].lower() for l in losing[:3]]
    if behind == 0:
        verdict_line = ("Your website matches or beats the competitors on every signal I "
                        "measured. The work now is keeping that lead.")
    elif behind <= 4:
        verdict_line = (f"You are close. Out of {len(rows)} signals you are behind on {behind} — "
                        f"mainly {', '.join(top)}. These are quick to close.")
    else:
        verdict_line = (f"Out of {len(rows)} things Google compares, your competitors are ahead "
                        f"on {behind}. The biggest gaps are {', '.join(top)}. That is the real "
                        "reason they appear above you.")

    return {
        "rows": rows,
        "summary": {
            "behind": behind, "ahead": ahead, "level": level, "total": len(rows),
            "verdict": verdict_line,
            "biggest_gaps": [{"label": l["label"], "gap": l["gap"], "why": l["why"]}
                             for l in losing[:5]],
        },
        "you_are_behind_on": [
            f"{l['label']} — {', '.join(l['who'])} ahead" + (f" ({l['gap']})" if l["gap"] else "")
            for l in losing],
        "you_are_ahead_on": winning,
        "per_competitor": per_competitor,
        "checked": [c.domain for c in live],
        "failed": [{"domain": c.domain, "error": c.error} for c in comps if c.error],
    }


async def analyse(ctx: SiteContext, pages: list[PageData], services: list[str], location: str,
                  keywords: list[str], supplied: list[str] | None = None) -> dict:
    if not settings.competitors_enabled and not supplied:
        return {"enabled": False, "competitors": [], "comparison": {}}

    count = max(settings.competitor_count, len(supplied or []))
    cands = await discover(ctx, services, location, supplied, count)
    own = build_own(ctx, pages, keywords, bool(ctx.llms_txt.strip()))

    if not cands:
        return {
            "enabled": True, "competitors": [], "comparison": {},
            "own": own.to_dict(),
            "note": ("No competitors given. Paste up to three competitor website addresses, "
                     "or connect a search provider so I can find them automatically."),
        }

    async with Crawler() as crawler:
        comps = await asyncio.gather(*[profile_one(crawler, c, keywords) for c in cands])

    comps = list(comps)
    table = compare_table(own, comps)
    return {
        "enabled": True,
        "query_used": f"{services[0] if services else ''} {location}".strip(),
        "own": own.to_dict(),
        "competitors": [c.to_dict() for c in comps],
        "table": table,
        "comparison": {"gaps": table["you_are_behind_on"], "wins": table["you_are_ahead_on"]},
    }
