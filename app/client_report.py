"""Turns raw findings into the way a consultant actually talks.

Instead of "H1 missing" repeated on nine pages, the client sees one point:
what it is, why it costs them leads, one annotated screenshot, the exact text
to use — and a quiet note that six other pages have the same problem.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from .issues import CATALOG, SEVERITY_ORDER, Finding

# How to say each problem to a business owner, and what the fix looks like in
# their words. Anything not listed falls back to the catalogue wording.
CLIENT_VOICE: dict[str, dict[str, str]] = {
    "H1_MISSING": {
        "headline": "Your main heading is missing, so Google cannot tell what the page sells",
        "cost": "Google reads the main heading first. With no H1, it has to guess what you do "
                "— and it usually guesses wrong, so you rank for nothing.",
        "action": "Add one clear heading at the top of the page using your main keyword.",
    },
    "H1_MULTIPLE": {
        "headline": "There are several main headings competing on the same page",
        "cost": "When a page shouts three different things, Google splits its attention and "
                "ranks you for none of them properly.",
        "action": "Keep the one heading that matches what the page sells; turn the rest into "
                  "sub-headings.",
    },
    "H1_NO_KEYWORD": {
        "headline": "Your main heading does not contain the words customers search for",
        "cost": "People search for a service, not a slogan. If the heading does not carry that "
                "phrase, Google shows a competitor who does.",
        "action": "Rewrite the heading around the keyword customers actually type.",
    },
    "TITLE_MISSING": {
        "headline": "This page has no title — the blue clickable line in Google is empty",
        "cost": "The title is the first thing a searcher sees. No title means Google invents "
                "one, and nobody clicks it.",
        "action": "Write a 55-60 character title with your service and city.",
    },
    "TITLE_TOO_LONG": {
        "headline": "Your Google title is too long and gets cut off mid-sentence",
        "cost": "Google chops anything past ~60 characters. Your offer and phone-worthy words "
                "disappear before the searcher reads them.",
        "action": "Trim it to 55-60 characters with the keyword at the front.",
    },
    "TITLE_NO_KEYWORD": {
        "headline": "The Google title does not include the words people search for",
        "cost": "The title is the strongest match signal there is. Without the keyword you are "
                "invisible for that search.",
        "action": "Put the main keyword at the start of the title.",
    },
    "META_MISSING": {
        "headline": "No description under your Google listing",
        "cost": "Google scrapes a random sentence from the page instead. It reads badly, and "
                "fewer people click — even when you rank well.",
        "action": "Write a 150-character description ending with a clear reason to call you.",
    },
    "META_TOO_LONG": {
        "headline": "Your Google description is too long, so the call to action is cut off",
        "cost": "The part that convinces people to click is exactly the part Google hides.",
        "action": "Rewrite it in 150-160 characters with the offer up front.",
    },
    "IMG_ALT_MISSING": {
        "headline": "Your images are invisible to Google",
        "cost": "Every image without a description is a missed entry in Google Images, and it "
                "fails accessibility checks that Google now watches.",
        "action": "Add a short description to each image saying what it shows.",
    },
    "SCHEMA_MISSING": {
        "headline": "Your business details are not machine-readable",
        "cost": "Without this hidden data, Google and AI assistants like ChatGPT cannot confirm "
                "who you are, where you are, or what you charge — so they recommend someone else.",
        "action": "Add structured business data (name, address, phone, services) to the site.",
    },
    "SCHEMA_ORG_MISSING": {
        "headline": "Google has no confirmed profile of your business",
        "cost": "This is what powers the business panel on the right of search results and your "
                "chances in the local map pack.",
        "action": "Add LocalBusiness data with your real name, address, phone and hours.",
    },
    "SCHEMA_FAQ_MISSING": {
        "headline": "Your answers are not set up to be quoted by Google and AI",
        "cost": "FAQ markup is how you get extra space in search results and how ChatGPT and "
                "Gemini quote you instead of a competitor.",
        "action": "Add 5-6 real customer questions with short answers, marked up as FAQ data.",
    },
    "BROKEN_INTERNAL_LINK": {
        "headline": "Some links on your site lead nowhere",
        "cost": "A customer clicking a dead link usually leaves and calls someone else. Google "
                "treats it as a sign the site is unmaintained.",
        "action": "Point these links at the correct pages, or remove them.",
    },
    "PAGE_4XX": {
        "headline": "Pages on your site are returning an error",
        "cost": "Anyone landing there hits a dead end, and any ranking that page had is lost.",
        "action": "Restore the page or redirect it to the closest live page.",
    },
    "NOINDEX": {
        "headline": "A page is telling Google to ignore it completely",
        "cost": "However good that page is, it cannot appear in search at all while this tag is "
                "on it.",
        "action": "Remove the noindex instruction from that page.",
    },
    "CANONICAL_CONFLICT": {
        "headline": "A page is telling Google to rank a different page instead of itself",
        "cost": "You are handing your own traffic away. That page will never rank while this "
                "is set.",
        "action": "Point the page's canonical tag at its own address.",
    },
    "LLMS_TXT_MISSING": {
        "headline": "AI assistants have no guide to your business",
        "cost": "ChatGPT, Claude and Perplexity increasingly send customers. A simple llms.txt "
                "file tells them what you offer and which pages to read.",
        "action": "Publish an llms.txt file listing your services and key pages.",
    },
    "AI_BOTS_BLOCKED": {
        "headline": "You are blocking the AI assistants that could recommend you",
        "cost": "Your site currently tells ChatGPT and others to stay out, so they can never "
                "name you when someone asks for your service.",
        "action": "Allow the AI crawlers you want recommendations from.",
    },
    "AI_NO_ANSWER_BLOCKS": {
        "headline": "Your content is not written the way AI tools quote it",
        "cost": "AI answers pull short, direct answers under clear questions. Long unbroken "
                "paragraphs get skipped.",
        "action": "Rewrite key sections as a question followed by a 40-60 word answer.",
    },
    "THIN_CONTENT": {
        "headline": "Some pages are too thin to compete",
        "cost": "A few lines of text cannot outrank a competitor who answers every question a "
                "customer has.",
        "action": "Expand these pages to cover pricing, process, coverage area and FAQs.",
    },
    "DUPLICATE_CONTENT": {
        "headline": "Two pages carry nearly the same text",
        "cost": "Google picks one and buries the other. Both end up weaker than a single strong "
                "page would be.",
        "action": "Rewrite one page around a different angle, or merge them.",
    },
    "SITEMAP_MISSING": {
        "headline": "Google has no map of your website",
        "cost": "New and deep pages get discovered late, sometimes never.",
        "action": "Generate a sitemap and submit it in Google Search Console.",
    },
    "ROBOTS_MISSING": {
        "headline": "Your site gives search engines no crawl instructions",
        "cost": "Google wastes time on pages that do not matter and may miss the ones that do.",
        "action": "Add a robots.txt file pointing to your sitemap.",
    },
    "HTTPS_MISSING": {
        "headline": "Your website is not secure",
        "cost": "Browsers show a 'Not secure' warning next to your address. Most people leave "
                "before reading a word.",
        "action": "Install an SSL certificate and force every page to load securely.",
    },
    "SLOW_LCP": {
        "headline": "Your pages take too long to show up",
        "cost": "Every extra second loses customers on mobile data, and Google uses speed as a "
                "ranking factor.",
        "action": "Compress the large images and remove the scripts blocking the first paint.",
    },
    "NAP_MISSING": {
        "headline": "Your address and phone number are hard to find",
        "cost": "Local customers need to see you are nearby and reachable. Google needs it to "
                "trust you for local searches.",
        "action": "Put the full business name, address and phone in the footer of every page.",
    },
    "NO_CTA": {
        "headline": "There is no clear next step for a visitor",
        "cost": "Traffic without an obvious 'call now' or 'get a quote' button just leaves.",
        "action": "Add one prominent action button at the top of the page and repeat it below.",
    },
    "KEYWORD_MISSING_ONPAGE": {
        "headline": "The words customers search for barely appear on the page",
        "cost": "Google matches searches to the words on your page. If the phrase is not there, "
                "you are not in the race.",
        "action": "Work the main keyword naturally into the intro, one sub-heading and the body.",
    },
    "MISSING_SERVICE_PAGE": {
        "headline": "A service you offer has no page of its own",
        "cost": "One page cannot rank for every service. Each service needs its own page to "
                "compete for its own searches.",
        "action": "Create a dedicated page for this service with local keywords.",
    },
    "LOW_AUTHORITY": {
        "headline": "Other websites rarely mention or link to you",
        "cost": "Links and mentions are how Google judges whether a business is established. "
                "A thin profile caps how high you can ever rank.",
        "action": "Build local citations, directory listings and partner mentions.",
    },
}


@dataclass
class IssueGroup:
    """One talking point, however many pages it affects."""
    code: str
    severity: str
    headline: str
    cost: str
    action: str
    count: int
    example_url: str
    example_detail: str
    example_evidence: str
    screenshot: str | None
    other_urls: list[str] = field(default_factory=list)
    fix_text: str = ""          # exact wording the client can paste
    category: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "headline": self.headline,
            "cost": self.cost,
            "action": self.action,
            "pages_affected": self.count,
            "example_url": self.example_url,
            "example_detail": self.example_detail,
            "example_evidence": self.example_evidence,
            "screenshot": self.screenshot,
            "other_urls": self.other_urls,
            "fix_text": self.fix_text,
            "category": self.category,
        }


def _short(url: str) -> str:
    path = urlparse(url).path or "/"
    return "Homepage" if path in ("", "/") else path


def _unused_suggested_text(code: str, finding: Finding, keyword: str, brand: str,
                           location: str) -> str:
    """Kept for reference. Reports no longer hand the client ready-made text —
    they explain how to fix the problem instead."""
    kw = (keyword or "").strip()
    kw_title = kw[:1].upper() + kw[1:] if kw else ""
    where = f" in {location}" if location else ""
    if not kw:
        return ""
    if code in ("H1_MISSING", "H1_NO_KEYWORD", "H1_MULTIPLE", "H1_TOO_LONG"):
        return f"{kw_title}{where}"
    if code in ("TITLE_MISSING", "TITLE_TOO_LONG", "TITLE_NO_KEYWORD", "TITLE_TOO_SHORT"):
        line = f"{kw_title}{where} | {brand}" if brand else f"{kw_title}{where}"
        return line[:60]
    if code in ("META_MISSING", "META_TOO_LONG", "META_NO_KEYWORD", "META_TOO_SHORT"):
        base = (f"Looking for {kw.lower()}{where}? {brand} offers reliable service, "
                f"transparent pricing and quick response. Call now for a free quote.")
        return base[:158]
    if code == "IMG_ALT_MISSING":
        return f"{kw_title}{where} — describe what the picture actually shows"
    if code == "HEADING_NO_KEYWORD":
        return f"Why choose us for {kw.lower()}{where}"
    return ""


def annotation_for(code: str, keyword: str) -> str:
    """The short label drawn on the screenshot next to the arrow."""
    labels = {
        "H1_MISSING": "No main heading on this page",
        "H1_MULTIPLE": "A second main heading competing with the first",
        "H1_NO_KEYWORD": "This heading does not use the words customers search for",
        "H1_TOO_LONG": "This heading is too long — shorten it",
        "TITLE_MISSING": "No Google title set for this page",
        "TITLE_TOO_LONG": "Google cuts this title off here",
        "META_MISSING": "No Google description written for this page",
        "META_TOO_LONG": "Google hides the end of this description",
        "IMG_ALT_MISSING": "This image has no description for Google",
        "BROKEN_INTERNAL_LINK": "This link goes to a dead page",
        "PAGE_4XX": "This page returns an error",
        "NOINDEX": "This page is hidden from Google",
        "CANONICAL_CONFLICT": "This page points Google to a different page",
        "SCHEMA_MISSING": "No business data here for Google or AI to read",
        "NO_CTA": "No clear call-to-action for visitors",
    }
    return labels.get(code, CATALOG[code].title)


def code_snippet_for(finding: Finding, page: Any) -> tuple[str, str]:
    """Returns (source code to show, the part to mark red).

    For anything invisible on the page — a missing alt attribute, an empty
    description, no business data — the client sees the actual code behind
    their website instead of a screenshot of nothing.
    """
    code = finding.code
    fallback = finding.evidence or finding.detail or CATALOG[code].title

    if code == "HTTPS_MISSING":
        return (f"{finding.url}\n\n   Not secure — there is no https:// version of your site.\n"
                "   Browsers show a warning to every visitor."), "Not secure"
    if code in ("KEYWORD_MISSING_ONPAGE", "TITLE_NO_KEYWORD", "META_NO_KEYWORD",
                "H1_NO_KEYWORD", "HEADING_NO_KEYWORD", "NO_LOCAL_KEYWORDS"):
        if page is not None:
            lines = [f"<title>{page.title}</title>"] if page.title else []
            lines += [f"<h{h.level}>{h.text[:70]}</h{h.level}>" for h in page.headings[:4]]
            if lines:
                return "\n".join(lines), ""
        return fallback, ""
    if code == "MISSING_SERVICE_PAGE":
        return f"{finding.detail}\n\n   There is no page on the website targeting this service.", ""
    if code == "NO_INTERNAL_LINKS":
        return (f"{finding.url}\n\n   {finding.detail}\n"
                "   Visitors and Google have almost no way to move on from this page."), ""
    if code == "AI_BOTS_BLOCKED":
        return (finding.evidence or finding.detail)[:600], "Disallow: /"
    if code == "LOW_AUTHORITY":
        return f"{finding.detail}", ""

    if page is None:
        return fallback, ""

    head = getattr(page, "head_html", "") or ""

    if code in ("IMG_ALT_MISSING", "IMG_TITLE_MISSING", "IMG_FILENAME_GENERIC"):
        missing = [i for i in page.images if not (i.alt or "").strip()] or page.images
        lines = []
        for img in missing[:4]:
            bits = [f'<img src="{img.src_attr or img.src}"']
            if img.width:
                bits.append(f'width="{img.width}"')
            if img.height:
                bits.append(f'height="{img.height}"')
            lines.append(" ".join(bits) + ">")
        return "\n".join(lines), "<img"

    if code.startswith("TITLE_"):
        if page.title:
            return f"<title>{page.title}</title>", page.title[:60]
        return "<head>\n   ...no <title> tag on this page...\n</head>", "no <title> tag"

    if code.startswith("META_"):
        if page.meta_description:
            return (f'<meta name="description"\n      content="{page.meta_description}">',
                    page.meta_description[:60])
        return ("<head>\n   ...no <meta name=\"description\"> tag on this page...\n</head>",
                'no <meta name="description">')

    if code.startswith("SCHEMA_"):
        if head:
            return head[:900], ""
        return "...no business data (JSON-LD) found in the page code...", "no business data"

    if code == "NOINDEX":
        return f'<meta name="robots" content="{page.meta_robots}">', "noindex"

    if code.startswith("CANONICAL"):
        if page.canonical:
            return f'<link rel="canonical" href="{page.canonical}">', page.canonical
        return "<head>\n   ...no canonical tag on this page...\n</head>", "no canonical tag"

    if code.startswith("H1_") or code == "HEADING_NO_KEYWORD":
        lines = [f"<h{h.level}>{h.text[:70]}</h{h.level}>" for h in page.headings[:6]]
        return "\n".join(lines) or "...no headings found on this page...", "<h1>"

    if code == "VIEWPORT_MISSING":
        return head[:700] or "", "viewport"

    if code == "THIN_CONTENT":
        return f"Words of real content on this page: {page.word_count}", str(page.word_count)

    if code in ("LLMS_TXT_MISSING", "ROBOTS_MISSING", "SITEMAP_MISSING", "ROBOTS_NO_SITEMAP"):
        return f"{finding.url}\n\n   404 — this file does not exist on your website", "404"

    if code == "AI_BOTS_BLOCKED":
        return (finding.evidence or "")[:600], "Disallow: /"

    if code in ("PAGE_4XX", "PAGE_5XX", "BROKEN_INTERNAL_LINK"):
        return f"{finding.extra.get('target', finding.url)}\n\n   {finding.detail}", "404"

    return fallback, ""


def build_groups(findings: list[Finding], keyword_by_url: dict[str, str],
                 brand: str, location: str, limit: int = 18) -> list[IssueGroup]:
    """One group per issue type, ordered by how much it hurts."""
    buckets: dict[str, list[Finding]] = {}
    for f in findings:
        buckets.setdefault(f.code, []).append(f)

    groups: list[IssueGroup] = []
    for code, items in buckets.items():
        spec = CATALOG[code]
        voice = CLIENT_VOICE.get(code, {})
        # prefer an instance that actually has a screenshot as the example
        example = next((i for i in items if i.screenshot), items[0])
        url = example.url or ""
        keyword = keyword_by_url.get(url, "") or next(iter(keyword_by_url.values()), "")
        others = [i.url for i in items if i.url and i.url != url]

        groups.append(IssueGroup(
            code=code,
            severity=spec.severity,
            headline=voice.get("headline") or spec.title,
            cost=voice.get("cost") or spec.why,
            action=voice.get("action") or spec.fix,
            count=len(items),
            example_url=url,
            example_detail=example.detail,
            example_evidence=example.evidence,
            screenshot=example.screenshot,
            other_urls=list(dict.fromkeys(others))[:12],
            fix_text="",
            category=spec.category,
        ))

    groups.sort(key=lambda g: (SEVERITY_ORDER[g.severity], -g.count))
    return groups[:limit]


def business_bullets(brand: str, services: list[str], location: str,
                     home_description: str, pages: int, keywords: list[str]) -> list[str]:
    """What the client's website is, in short bullets."""
    loc = (location or "").strip()
    clean: list[str] = []
    for raw in services:
        name = re.sub(r"\s+", " ", (raw or "")).strip(" -–—|:•").lower()
        if loc:
            name = re.sub(rf"\b(in|near|across|around|for)\s+{re.escape(loc.lower())}\b",
                          "", name).strip()
        name = re.sub(r"\b(in|near|across|around)\s+[a-z]+(\s+ncr)?$", "", name).strip()
        name = re.sub(r"\s+", " ", name).strip(" ,-")
        if name and name not in clean and len(name.split()) >= 2:
            clean.append(name)
        if len(clean) == 5:
            break

    bullets: list[str] = []
    if clean:
        bullets.append("Services on the website: " + ", ".join(clean))
    if keywords:
        bullets.append("Searches this site should be winning: " + ", ".join(keywords[:4]))
    desc = re.sub(r"\s+", " ", (home_description or "")).strip()
    if desc and len(desc.split()) > 8:
        first = re.split(r"(?<=[.!?])\s", desc)[0]
        if len(first.split()) > 6:
            bullets.append("How the site describes itself: " + first.rstrip(" .") + ".")
    bullets.append(f"Pages I checked: {pages}")
    bullets.append("Goal of the website: turn people searching for these services into calls "
                   "and enquiries.")
    return bullets


def business_summary(brand: str, services: list[str], location: str,
                     home_description: str) -> str:
    """One paragraph on what the business sells. Services only — deliberately no
    mention of where they operate."""
    loc = (location or "").strip()
    clean: list[str] = []
    for raw in services:
        name = re.sub(r"\s+", " ", (raw or "")).strip(" -–—|:•").lower()
        if loc:                      # strip "in Delhi" style tails from service names
            name = re.sub(rf"\b(in|near|across|around|for)\s+{re.escape(loc.lower())}\b",
                          "", name).strip()
        name = re.sub(r"\b(in|near|across|around)\s+[a-z]+(\s+ncr)?$", "", name).strip()
        name = re.sub(r"\s+", " ", name).strip(" ,-")
        if name and name not in clean and len(name.split()) >= 2:
            clean.append(name)
        if len(clean) == 4:
            break

    if clean:
        listed = (", ".join(clean[:-1]) + " and " + clean[-1]) if len(clean) > 1 else clean[0]
        line = f"From what I can see, {brand} provides {listed}. "
    else:
        line = f"From what I can see, {brand} sells its services online. "

    desc = re.sub(r"\s+", " ", (home_description or "")).strip()
    if desc and len(desc.split()) > 8:
        first = re.split(r"(?<=[.!?])\s", desc)[0]
        if len(first.split()) > 6:
            line += first.rstrip(" .") + ". "

    line += ("So the job of your website is simple: when someone searches for these services, "
             "your page should be the one they find, trust and call.")
    return line
