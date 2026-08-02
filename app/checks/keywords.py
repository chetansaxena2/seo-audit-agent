"""Service detection + keyword relevance.

Answers the question "does this site actually use the keywords its services
should rank for?" — first by deriving services and location from the site
itself, then by scoring where each target keyword appears on each page.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from .. import llm
from .. import textutil as T
from ..crawler import SiteContext
from ..issues import Finding
from ..parser import PageData

SERVICE_STOP = {"home", "contact", "about", "about us", "blog", "news", "privacy policy",
                "terms", "sitemap", "login", "cart", "search", "faq", "careers", "gallery"}

LOCATION_HINT = re.compile(
    r"\b(?:in|near|serving|based in|across)\s+([A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+){0,2})")


@dataclass
class PageKeywords:
    url: str
    primary: str
    matched: dict[str, bool] = field(default_factory=dict)
    density: float = 0.0
    score: float = 0.0
    found_keywords: list[str] = field(default_factory=list)
    missing_keywords: list[str] = field(default_factory=list)


@dataclass
class KeywordProfile:
    brand: str = ""
    location: str = ""
    services: list[str] = field(default_factory=list)
    primary_keywords: list[str] = field(default_factory=list)
    secondary_keywords: list[str] = field(default_factory=list)
    site_topics: list[str] = field(default_factory=list)
    user_supplied: list[str] = field(default_factory=list)
    source: str = "derived"
    pages: list[PageKeywords] = field(default_factory=list)
    coverage_score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "brand": self.brand,
            "location": self.location,
            "detected_services": self.services,
            "primary_keywords": self.primary_keywords,
            "secondary_keywords": self.secondary_keywords,
            "site_topics": self.site_topics,
            "user_supplied": self.user_supplied,
            "source": self.source,
            "coverage_score": round(self.coverage_score, 1),
            "pages": [
                {
                    "url": p.url,
                    "primary_keyword": p.primary,
                    "placement": p.matched,
                    "density_pct": round(p.density, 2),
                    "score": round(p.score, 1),
                    "keywords_found": p.found_keywords,
                    "keywords_missing": p.missing_keywords[:6],
                }
                for p in self.pages
            ],
        }


def _brand_from(ctx: SiteContext, home: PageData | None) -> str:
    if home:
        for block in home.jsonld:
            if isinstance(block, dict) and str(block.get("@type", "")).lower() in {
                    "organization", "localbusiness", "website", "professionalservice"}:
                name = block.get("name")
                if isinstance(name, str) and name.strip():
                    return name.strip()
        if home.og.get("og:site_name"):
            return home.og["og:site_name"]
        if home.title:
            parts = re.split(r"[|\-–—:]", home.title)
            if len(parts) > 1:
                return parts[-1].strip()
    host = ctx.netloc.replace("www.", "").split(".")[0]
    return host.replace("-", " ").title()


def _location_from(pages: list[PageData]) -> str:
    for p in pages:
        for block in p.jsonld:
            if not isinstance(block, dict):
                continue
            addr = block.get("address")
            if isinstance(addr, dict):
                loc = addr.get("addressLocality") or addr.get("addressRegion")
                if isinstance(loc, str) and loc.strip():
                    return loc.strip()
            area = block.get("areaServed")
            if isinstance(area, str) and area.strip():
                return area.strip()
    joined = " ".join((p.title or "") + " " + (p.meta_description or "") for p in pages[:6])
    hit = LOCATION_HINT.search(joined)
    if hit:
        cand = hit.group(1).strip()
        if len(cand.split()) <= 3 and cand.lower() not in SERVICE_STOP:
            return cand
    tail = " ".join(p.text[-1200:] for p in pages[:3])
    hit = LOCATION_HINT.search(tail)
    return hit.group(1).strip() if hit else ""


def _services_from(pages: list[PageData], brand: str) -> list[str]:
    cand: list[str] = []
    home = pages[0] if pages else None
    if home:
        for block in home.jsonld:
            if not isinstance(block, dict):
                continue
            for key in ("serviceType", "makesOffer", "hasOfferCatalog"):
                val = block.get(key)
                if isinstance(val, str):
                    cand.append(val)
                elif isinstance(val, dict):
                    items = val.get("itemListElement") or []
                    for it in items if isinstance(items, list) else []:
                        if isinstance(it, dict):
                            name = it.get("name") or (it.get("itemOffered") or {}).get("name") \
                                if isinstance(it.get("itemOffered"), dict) else it.get("name")
                            if isinstance(name, str):
                                cand.append(name)
        for h in home.headings:
            if h.level in (1, 2, 3) and 2 <= len(h.text.split()) <= 6:
                cand.append(h.text)
        for link in home.internal_links:
            slug = urlparse(link.url).path.strip("/").split("/")[-1]
            anchor = link.anchor.strip()
            if anchor and 1 < len(anchor.split()) <= 5 and anchor.lower() not in SERVICE_STOP:
                if any(k in urlparse(link.url).path.lower()
                       for k in ("service", "solution", "product", "package", "tour", "rental")):
                    cand.append(anchor)
                elif slug and len(slug) > 3 and "-" in slug:
                    cand.append(slug.replace("-", " "))
    for p in pages[1:]:
        title_head = re.split(r"[|\-–—]", p.title or "")[0].strip()
        if title_head and 1 < len(title_head.split()) <= 6 and title_head.lower() not in SERVICE_STOP:
            cand.append(title_head)

    cleaned: list[str] = []
    brand_low = brand.lower()
    for c in cand:
        c = re.sub(r"\.(html?|php|aspx?|jsp)$", "", c.strip(), flags=re.I)
        c = re.sub(r"\s+", " ", c).strip(" -–—|:•")
        low = c.lower()
        if not c or low in SERVICE_STOP or brand_low and brand_low in low:
            continue
        if len(c) > 60 or len(c.split()) < 2:
            continue
        if T.is_question(c):
            continue
        if re.search(r"\b(old|new|draft|test|page|index|untitled|copy|\d{4})\b", low):
            continue
        # section headings, not services: "Our Fleet", "Why Choose Us", "How It Works"
        if re.match(r"^(our|why|how|what|who|when|about|contact|get|book now|read)\b", low):
            continue
        cleaned.append(c.title() if c.islower() else c)
    return T.dedupe_keep_order(cleaned)[:12]


def _derive_keywords(services: list[str], location: str, corpus: str) -> tuple[list[str], list[str]]:
    topics = [k for k, _ in T.extract_keywords(corpus, top=30) if len(k.split()) > 1]
    primary: list[str] = []
    for s in services[:6]:
        s_low = s.lower()
        primary.append(s_low)
        if location and location.lower() not in s_low:
            primary.append(f"{s_low} in {location.lower()}")
    for t in topics:
        if len(primary) >= 12:
            break
        if not any(T.contains_phrase(p, t, fuzzy=False) for p in primary):
            primary.append(t)
    secondary = [t for t in topics if t not in primary][:15]
    return T.dedupe_keep_order(primary)[:12], T.dedupe_keep_order(secondary)[:15]


async def _llm_refine(brand: str, location: str, services: list[str],
                      pages: list[PageData]) -> dict | None:
    if not llm.available():
        return None
    sample = [{
        "url": p.final_url or p.url,
        "title": p.title[:120],
        "h1": [h.text[:100] for h in p.h1s],
        "intro": p.intro_text[:400],
    } for p in pages[:8]]
    prompt = (
        "Analyse this website crawl and identify what the business actually sells and which "
        "keywords each page should target.\n\n"
        f"Brand guess: {brand}\nLocation guess: {location or 'unknown'}\n"
        f"Service guesses: {services}\n\nPages:\n{sample}\n\n"
        "Return JSON: {\"business_type\": str, \"location\": str, \"services\": [str], "
        "\"primary_keywords\": [str up to 10], \"secondary_keywords\": [str up to 12], "
        "\"page_targets\": [{\"url\": str, \"primary_keyword\": str}]}"
    )
    return await llm.complete_json(prompt, max_tokens=1600)


def _assign_primary(page: PageData, profile_primary: list[str], overrides: dict[str, str]) -> str:
    url = page.final_url or page.url
    if url in overrides:
        return overrides[url]
    haystack = f"{page.title} {page.heading_text} {urlparse(url).path.replace('-', ' ')}"
    best, best_score = "", 0.0
    for kw in profile_primary:
        score = 0.0
        if T.contains_phrase(page.title, kw):
            score += 3
        if any(T.contains_phrase(h.text, kw) for h in page.h1s):
            score += 3
        if T.contains_phrase(urlparse(url).path.replace("-", " "), kw):
            score += 2
        if T.contains_phrase(haystack, kw):
            score += 1
        score += min(2.0, T.phrase_count(page.main_text.lower(), kw) * 0.4)
        if score > best_score:
            best, best_score = kw, score
    return best or (profile_primary[0] if profile_primary else "")


async def analyse(ctx: SiteContext, pages: list[PageData],
                  user_keywords: list[str] | None = None) -> tuple[KeywordProfile, list[Finding]]:
    findings: list[Finding] = []
    html_pages = [p for p in pages if p.html]
    home = html_pages[0] if html_pages else None
    profile = KeywordProfile()
    profile.brand = _brand_from(ctx, home)
    profile.location = _location_from(html_pages)
    profile.services = _services_from(html_pages, profile.brand)

    corpus = " ".join(p.main_text for p in html_pages)[:120_000]
    derived_primary, derived_secondary = _derive_keywords(profile.services, profile.location, corpus)
    profile.site_topics = [k for k, _ in T.extract_keywords(corpus, top=18)]

    overrides: dict[str, str] = {}
    if user_keywords:
        supplied = T.dedupe_keep_order([k.strip() for k in user_keywords if k and k.strip()])
        # Find the terms on the site that are actually related to what the client
        # asked for, so the audit widens beyond the exact phrases they typed.
        related: list[str] = []
        seed_words = {w for k in supplied for w in T.content_tokens(k)}
        for phrase, _ in T.extract_keywords(corpus, top=60):
            if phrase in supplied:
                continue
            words = set(T.content_tokens(phrase))
            if words & seed_words:                     # shares a real word with a seed
                related.append(phrase)
        for kw in supplied[:6]:                        # location variants of each seed
            if profile.location and profile.location.lower() not in kw.lower():
                related.append(f"{kw.lower()} in {profile.location.lower()}")
        profile.primary_keywords = supplied[:12]
        profile.secondary_keywords = T.dedupe_keep_order(related)[:15]
        profile.user_supplied = supplied
        profile.source = "your keywords + related terms found on the site"
    else:
        refined = await _llm_refine(profile.brand, profile.location, profile.services, html_pages)
        if refined and refined.get("primary_keywords"):
            profile.primary_keywords = T.dedupe_keep_order(
                [k for k in refined["primary_keywords"] if isinstance(k, str)])[:12]
            profile.secondary_keywords = T.dedupe_keep_order(
                [k for k in refined.get("secondary_keywords", []) if isinstance(k, str)])[:15]
            if refined.get("services"):
                profile.services = T.dedupe_keep_order(
                    [s for s in refined["services"] if isinstance(s, str)])[:12]
            profile.location = refined.get("location") or profile.location
            for t in refined.get("page_targets", []) or []:
                if isinstance(t, dict) and t.get("url") and t.get("primary_keyword"):
                    overrides[t["url"]] = t["primary_keyword"]
            profile.source = "llm-assisted"
        else:
            profile.primary_keywords = derived_primary
            profile.secondary_keywords = derived_secondary
            profile.source = "derived-from-content"

    secondary_pool = (profile.primary_keywords + profile.secondary_keywords)[:16]

    for page in html_pages:
        if not page.is_indexable:
            continue
        url = page.final_url or page.url
        primary = _assign_primary(page, profile.primary_keywords, overrides)
        pk = PageKeywords(url=url, primary=primary)
        if not primary:
            profile.pages.append(pk)
            continue

        slug_text = urlparse(url).path.replace("-", " ").replace("/", " ")
        alt_text = " ".join((i.alt or "") for i in page.images)
        anchors = " ".join(l.anchor for l in page.internal_links)
        body = page.main_text
        pk.matched = {
            "title": T.contains_phrase(page.title, primary),
            "meta_description": T.contains_phrase(page.meta_description, primary),
            "h1": any(T.contains_phrase(h.text, primary) for h in page.h1s),
            "h2_h3": any(T.contains_phrase(h.text, primary) for h in page.subheadings),
            "url_slug": T.contains_phrase(slug_text, primary),
            "first_100_words": T.contains_phrase(" ".join(body.split()[:100]), primary),
            "body": T.contains_phrase(body, primary),
            "image_alt": T.contains_phrase(alt_text, primary),
            "internal_anchors": T.contains_phrase(anchors, primary),
        }
        occurrences = T.phrase_count(body, primary)
        pk.density = (occurrences * len(primary.split()) / max(1, page.word_count)) * 100
        weights = {"title": 20, "h1": 18, "url_slug": 10, "meta_description": 10,
                   "h2_h3": 12, "first_100_words": 12, "body": 8, "image_alt": 5,
                   "internal_anchors": 5}
        pk.score = sum(w for k, w in weights.items() if pk.matched.get(k))
        pk.found_keywords = [k for k in secondary_pool if T.contains_phrase(body, k)]
        pk.missing_keywords = [k for k in secondary_pool if k not in pk.found_keywords]
        profile.pages.append(pk)

        placement_note = ", ".join(k for k, v in pk.matched.items() if not v) or "none"
        if not pk.matched["title"]:
            findings.append(Finding("TITLE_NO_KEYWORD", url=url,
                                    detail=f"Target keyword '{primary}' is not in the title.",
                                    evidence=page.title[:160],
                                    selector="xpath=(//h1)[1]"))
        if page.meta_description and not pk.matched["meta_description"]:
            findings.append(Finding("META_NO_KEYWORD", url=url,
                                    detail=f"Target keyword '{primary}' is not in the meta description.",
                                    evidence=page.meta_description[:200]))
        if page.h1s and not pk.matched["h1"]:
            findings.append(Finding("H1_NO_KEYWORD", url=url,
                                    detail=f"H1 does not contain '{primary}'.",
                                    evidence=page.h1s[0].text[:160],
                                    selector=page.h1s[0].selector))
        if page.subheadings and not pk.matched["h2_h3"]:
            findings.append(Finding("HEADING_NO_KEYWORD", url=url,
                                    detail=f"No H2/H3 uses '{primary}' or its variants.",
                                    evidence="; ".join(h.text for h in page.subheadings[:3])[:200]))
        if pk.score < 35 or occurrences == 0:
            findings.append(Finding("KEYWORD_MISSING_ONPAGE", url=url,
                                    detail=(f"'{primary}' appears {occurrences}x in body copy; "
                                            f"missing from: {placement_note}."),
                                    evidence=f"placement score {pk.score:.0f}/100"))
        if pk.density > 4.5 and occurrences > 6:
            findings.append(Finding("KEYWORD_STUFFING", url=url,
                                    detail=f"'{primary}' density is {pk.density:.1f}% ({occurrences} uses).",
                                    evidence=f"{occurrences} occurrences in {page.word_count} words"))

    scored = [p for p in profile.pages if p.primary]
    profile.coverage_score = sum(p.score for p in scored) / len(scored) if scored else 0.0

    # services with no dedicated page
    page_blob = " ".join((p.final_url or p.url) + " " + p.title + " " + p.heading_text
                         for p in html_pages)
    for service in profile.services[:8]:
        if not T.contains_phrase(page_blob, service):
            findings.append(Finding("MISSING_SERVICE_PAGE", url=ctx.base_url,
                                    detail=f"No crawled page targets '{service}'.",
                                    evidence=f"service detected from site content: {service}"))
    return profile, findings
