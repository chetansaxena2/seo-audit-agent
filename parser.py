"""Turns raw HTML into a PageData object. Every check reads from this
structure, so parsing happens exactly once per URL."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

from . import textutil as T

BOILERPLATE_TAGS = {"script", "style", "noscript", "template", "svg", "iframe"}
NAV_TAGS = {"nav", "header", "footer", "aside"}
PHONE_RE = re.compile(r"(\+?\d[\d\s().-]{7,}\d)")
POSTCODE_RE = re.compile(r"\b(\d{5,6}|[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2})\b")
CTA_WORDS = re.compile(
    r"\b(book|call|contact|get a quote|get quote|request|hire|order|buy|enquire|inquire|"
    r"schedule|reserve|start|sign up|subscribe|whatsapp|download)\b", re.I)


def _txt(el: Any) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)) if el else ""


@dataclass
class ImageInfo:
    src: str
    alt: str | None
    title: str | None
    width: str | None
    height: str | None
    loading: str | None
    in_content: bool = True

    @property
    def filename(self) -> str:
        return urlparse(self.src).path.rsplit("/", 1)[-1]

    @property
    def selector(self) -> str:
        return f'img[src="{self.src_attr}"]'

    src_attr: str = ""


@dataclass
class LinkInfo:
    url: str
    anchor: str
    rel: str
    internal: bool
    raw_href: str = ""

    @property
    def nofollow(self) -> bool:
        return "nofollow" in (self.rel or "").lower()

    @property
    def selector(self) -> str:
        return f'a[href="{self.raw_href}"]'


@dataclass
class HeadingInfo:
    level: int
    text: str
    index: int  # 1-based index among headings of the same level

    @property
    def selector(self) -> str:
        return f"xpath=(//h{self.level})[{self.index}]"


@dataclass
class PageData:
    url: str
    final_url: str = ""
    status: int = 0
    depth: int = 0
    ok: bool = False
    error: str = ""
    ttfb_ms: int = 0
    load_ms: int = 0
    bytes: int = 0
    headers: dict[str, str] = field(default_factory=dict)
    redirect_chain: list[str] = field(default_factory=list)
    html: str = ""

    # parsed
    title: str = ""
    meta_description: str = ""
    meta_robots: str = ""
    x_robots: str = ""
    canonical: str = ""
    viewport: str = ""
    lang: str = ""
    charset: str = ""
    og: dict[str, str] = field(default_factory=dict)
    twitter: dict[str, str] = field(default_factory=dict)
    headings: list[HeadingInfo] = field(default_factory=list)
    images: list[ImageInfo] = field(default_factory=list)
    links: list[LinkInfo] = field(default_factory=list)
    jsonld: list[dict] = field(default_factory=list)
    jsonld_errors: list[str] = field(default_factory=list)
    microdata_types: list[str] = field(default_factory=list)
    text: str = ""
    main_text: str = ""
    word_count: int = 0
    intro_text: str = ""
    css_count: int = 0
    js_count: int = 0
    render_blocking: int = 0
    inline_style_bytes: int = 0
    has_form: bool = False
    tel_links: list[str] = field(default_factory=list)
    mailto_links: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    cta_texts: list[str] = field(default_factory=list)
    lists_count: int = 0
    tables_count: int = 0
    shingles: set[str] = field(default_factory=set)

    # ---------------------------------------------------------------- helpers
    @property
    def h1s(self) -> list[HeadingInfo]:
        return [h for h in self.headings if h.level == 1]

    @property
    def subheadings(self) -> list[HeadingInfo]:
        return [h for h in self.headings if h.level in (2, 3, 4)]

    @property
    def heading_text(self) -> str:
        return " ".join(h.text for h in self.headings)

    @property
    def question_headings(self) -> list[HeadingInfo]:
        return [h for h in self.headings if T.is_question(h.text)]

    @property
    def path(self) -> str:
        return urlparse(self.final_url or self.url).path or "/"

    @property
    def is_indexable(self) -> bool:
        robots = f"{self.meta_robots} {self.x_robots}".lower()
        return self.ok and "noindex" not in robots

    @property
    def internal_links(self) -> list[LinkInfo]:
        return [l for l in self.links if l.internal]

    @property
    def external_links(self) -> list[LinkInfo]:
        return [l for l in self.links if not l.internal]

    @property
    def schema_types(self) -> list[str]:
        out: list[str] = []
        def walk(node: Any) -> None:
            if isinstance(node, dict):
                t = node.get("@type")
                if isinstance(t, str):
                    out.append(t)
                elif isinstance(t, list):
                    out.extend(x for x in t if isinstance(x, str))
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)
        for block in self.jsonld:
            walk(block)
        out.extend(self.microdata_types)
        return T.dedupe_keep_order(out)

    def has_schema(self, *names: str) -> bool:
        low = {s.lower() for s in self.schema_types}
        return any(n.lower() in low for n in names)

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.final_url or self.url,
            "status": self.status,
            "depth": self.depth,
            "title": self.title,
            "title_length": len(self.title),
            "meta_description": self.meta_description,
            "meta_description_length": len(self.meta_description),
            "h1": [h.text for h in self.h1s],
            "h2": [h.text for h in self.headings if h.level == 2],
            "word_count": self.word_count,
            "images": len(self.images),
            "images_missing_alt": sum(1 for i in self.images if not (i.alt or "").strip()),
            "images_missing_title": sum(1 for i in self.images if not (i.title or "").strip()),
            "internal_links": len(self.internal_links),
            "external_links": len(self.external_links),
            "canonical": self.canonical,
            "indexable": self.is_indexable,
            "schema_types": self.schema_types,
            "load_ms": self.load_ms,
            "ttfb_ms": self.ttfb_ms,
            "bytes": self.bytes,
            "readability": T.readability(self.main_text),
        }


def parse_page(page: PageData, root_netloc: str) -> PageData:
    """Populate the parsed fields of a fetched PageData."""
    if not page.html:
        return page
    soup = BeautifulSoup(page.html, "lxml")
    base = page.final_url or page.url

    if soup.title and soup.title.string:
        page.title = re.sub(r"\s+", " ", soup.title.string).strip()

    html_tag = soup.find("html")
    if html_tag:
        page.lang = (html_tag.get("lang") or "").strip()

    for m in soup.find_all("meta"):
        name = (m.get("name") or m.get("property") or m.get("http-equiv") or "").lower()
        content = (m.get("content") or "").strip()
        if name == "description":
            page.meta_description = content
        elif name == "robots":
            page.meta_robots = content
        elif name == "viewport":
            page.viewport = content
        elif name.startswith("og:"):
            page.og[name] = content
        elif name.startswith("twitter:"):
            page.twitter[name] = content
        elif name in {"article:published_time", "article:modified_time", "date"} and content:
            page.dates.append(content)
        if m.get("charset"):
            page.charset = m.get("charset")

    page.x_robots = page.headers.get("x-robots-tag", "")

    link_canon = soup.find("link", rel=lambda v: v and "canonical" in [x.lower() for x in (v if isinstance(v, list) else [v])])
    if link_canon and link_canon.get("href"):
        page.canonical = urljoin(base, link_canon["href"].strip())

    # headings
    counters = {i: 0 for i in range(1, 7)}
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        lvl = int(tag.name[1])
        counters[lvl] += 1
        text = _txt(tag)
        if text:
            page.headings.append(HeadingInfo(level=lvl, text=text, index=counters[lvl]))

    # images
    for img in soup.find_all("img"):
        raw = (img.get("src") or img.get("data-src") or "").strip()
        if not raw or raw.startswith("data:"):
            continue
        in_content = not any(p.name in NAV_TAGS for p in img.parents if p and p.name)
        info = ImageInfo(
            src=urljoin(base, raw),
            alt=img.get("alt"),
            title=img.get("title"),
            width=img.get("width"),
            height=img.get("height"),
            loading=img.get("loading"),
            in_content=in_content,
        )
        info.src_attr = raw
        page.images.append(info)

    # links
    for a in soup.find_all("a", href=True):
        raw = a["href"].strip()
        if raw.startswith("tel:"):
            page.tel_links.append(raw[4:])
            continue
        if raw.startswith("mailto:"):
            page.mailto_links.append(raw[7:])
            continue
        if raw.startswith(("javascript:", "#")) or not raw:
            continue
        absolute = urldefrag(urljoin(base, raw))[0]
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https"):
            continue
        rel = a.get("rel")
        rel_s = " ".join(rel) if isinstance(rel, list) else (rel or "")
        anchor = _txt(a)
        page.links.append(LinkInfo(
            url=absolute,
            anchor=anchor,
            rel=rel_s,
            internal=parsed.netloc.replace("www.", "") == root_netloc.replace("www.", ""),
            raw_href=raw,
        ))
        if anchor and CTA_WORDS.search(anchor) and len(anchor) < 40:
            page.cta_texts.append(anchor)

    for b in soup.find_all(["button", "input"]):
        label = _txt(b) or (b.get("value") or "")
        if label and CTA_WORDS.search(label):
            page.cta_texts.append(label.strip())

    # structured data
    for s in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        raw = s.string or s.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            page.jsonld_errors.append(f"{e.msg} (line {e.lineno})")
            continue
        page.jsonld.extend(data if isinstance(data, list) else [data])

    for el in soup.find_all(attrs={"itemtype": True}):
        t = (el.get("itemtype") or "").rsplit("/", 1)[-1]
        if t:
            page.microdata_types.append(t)

    # resources
    for l in soup.find_all("link", rel=lambda v: v and "stylesheet" in (v if isinstance(v, list) else [v])):
        page.css_count += 1
        if not l.get("media") or l.get("media") == "all":
            page.render_blocking += 1
    for s in soup.find_all("script", src=True):
        page.js_count += 1
        head_parent = any(p.name == "head" for p in s.parents if p and p.name)
        if head_parent and not (s.get("async") is not None or s.get("defer") is not None):
            page.render_blocking += 1
    page.inline_style_bytes = sum(len(s.get_text() or "") for s in soup.find_all("style"))

    page.has_form = bool(soup.find("form"))
    page.lists_count = len(soup.find_all(["ul", "ol"]))
    page.tables_count = len(soup.find_all("table"))
    for t in soup.find_all("time"):
        val = t.get("datetime") or _txt(t)
        if val:
            page.dates.append(val)

    # text
    body = soup.body or soup
    for tag in body.find_all(list(BOILERPLATE_TAGS)):
        tag.decompose()
    page.text = _txt(body)
    main_el = soup.find("main") or soup.find("article") or None
    if main_el is None:
        clone = BeautifulSoup(str(body), "lxml")
        for tag in clone.find_all(list(NAV_TAGS)):
            tag.decompose()
        page.main_text = _txt(clone)
    else:
        page.main_text = _txt(main_el)
    if len(page.main_text.split()) < 60:
        page.main_text = page.text
    page.word_count = len(T.tokens(page.main_text))
    page.intro_text = " ".join(page.main_text.split()[:120])
    page.shingles = T.shingles(page.main_text)
    page.phones = [p.strip() for p in PHONE_RE.findall(page.text)][:5]
    return page
