"""Polite async crawler.

Responsibilities: fetch site-level files (robots.txt, sitemap.xml, llms.txt),
crawl up to N HTML pages breadth-first with a relevance-aware frontier, and
verify the status of discovered links.
"""
from __future__ import annotations

import asyncio
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse

import httpx

from .config import settings
from .parser import PageData, parse_page

SKIP_EXT = (
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".zip", ".rar",
    ".mp4", ".mp3", ".avi", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".css",
    ".js", ".json", ".xml", ".rss", ".woff", ".woff2", ".ttf", ".dmg", ".exe", ".apk",
)

PRIORITY_HINTS = (
    "service", "product", "solution", "pricing", "about", "contact", "faq",
    "blog", "case", "location", "areas", "book", "quote", "package", "tour",
)

AI_BOTS = ["GPTBot", "ClaudeBot", "Claude-Web", "PerplexityBot", "Google-Extended",
           "CCBot", "anthropic-ai", "Applebot-Extended", "Bytespider", "meta-externalagent"]


def normalize_url(url: str) -> str:
    url = urldefrag(url.strip())[0]
    p = urlparse(url)
    path = p.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    query = p.query
    if query:
        drop = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
                "gclid", "fbclid", "msclkid", "ref"}
        parts = [kv for kv in query.split("&") if kv.split("=")[0] not in drop]
        query = "&".join(parts)
    return urlunparse((p.scheme.lower(), p.netloc.lower(), path, "", query, ""))


class RobotsRules:
    """Minimal robots.txt evaluation with per-user-agent visibility."""

    def __init__(self, text: str = "", status: int = 0):
        self.text = text or ""
        self.status = status
        self.exists = status == 200 and bool(text.strip())
        self.sitemaps: list[str] = []
        self.groups: dict[str, dict[str, list[str]]] = {}
        self._parse()

    def _parse(self) -> None:
        current: list[str] = []
        for raw in self.text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            field, _, value = line.partition(":")
            field, value = field.strip().lower(), value.strip()
            if field == "user-agent":
                ua = value.lower()
                current = [ua]
                self.groups.setdefault(ua, {"allow": [], "disallow": []})
            elif field in ("disallow", "allow") and current:
                for ua in current:
                    self.groups.setdefault(ua, {"allow": [], "disallow": []})[field].append(value)
            elif field == "sitemap":
                self.sitemaps.append(value)

    def _rules_for(self, agent: str) -> dict[str, list[str]]:
        a = agent.lower()
        for ua, rules in self.groups.items():
            if ua == a:
                return rules
        return self.groups.get("*", {"allow": [], "disallow": []})

    def allows(self, path: str, agent: str = "*") -> bool:
        rules = self._rules_for(agent)
        best_allow = max((len(p) for p in rules["allow"] if p and path.startswith(p)), default=-1)
        best_block = max((len(p) for p in rules["disallow"] if p and path.startswith(p)), default=-1)
        if any(p == "/" for p in rules["disallow"]) and best_allow < 1:
            return False
        return best_allow >= best_block

    def blocks_site(self, agent: str = "*") -> bool:
        return not self.allows("/", agent)

    def blocked_ai_bots(self) -> list[str]:
        return [b for b in AI_BOTS if b.lower() in self.groups and self.blocks_site(b)]


@dataclass
class SiteContext:
    input_url: str
    base_url: str = ""
    netloc: str = ""
    scheme: str = "https"
    robots: RobotsRules = field(default_factory=RobotsRules)
    robots_url: str = ""
    llms_txt: str = ""
    llms_status: int = 0
    sitemap_urls: list[str] = field(default_factory=list)
    sitemap_locations: list[str] = field(default_factory=list)
    sitemap_status: int = 0
    https_ok: bool = False
    http_redirects: bool = False
    www_variant_status: int | None = None
    www_variant_redirects: bool = False
    security_headers: dict[str, str] = field(default_factory=dict)

    @property
    def origin(self) -> str:
        return f"{self.scheme}://{self.netloc}"


class Crawler:
    def __init__(self, timeout: int | None = None, user_agent: str | None = None):
        self.timeout = timeout or settings.request_timeout
        self.user_agent = user_agent or settings.user_agent
        self._client: httpx.AsyncClient | None = None
        self._sem = asyncio.Semaphore(settings.crawl_concurrency)

    async def __aenter__(self) -> "Crawler":
        self._client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(self.timeout, connect=10.0),
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            verify=False,
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client:
            await self._client.aclose()

    # ------------------------------------------------------------------ fetch
    async def fetch(self, url: str, depth: int = 0, parse: bool = True,
                    root_netloc: str = "") -> PageData:
        page = PageData(url=url, depth=depth)
        assert self._client is not None
        async with self._sem:
            start = time.perf_counter()
            try:
                resp = await self._client.get(url)
                page.ttfb_ms = int((time.perf_counter() - start) * 1000)
                body = resp.content
                page.load_ms = int((time.perf_counter() - start) * 1000)
                page.status = resp.status_code
                page.final_url = str(resp.url)
                page.headers = {k.lower(): v for k, v in resp.headers.items()}
                page.redirect_chain = [str(r.url) for r in resp.history]
                page.bytes = len(body)
                page.ok = 200 <= resp.status_code < 300
                ctype = page.headers.get("content-type", "")
                if page.ok and "html" in ctype:
                    page.html = resp.text
                    if parse:
                        parse_page(page, root_netloc or urlparse(url).netloc)
            except Exception as exc:  # network, DNS, TLS, timeout
                page.error = f"{type(exc).__name__}: {exc}"
            await asyncio.sleep(settings.per_host_delay_ms / 1000)
        return page

    async def fetch_text(self, url: str) -> tuple[int, str]:
        assert self._client is not None
        try:
            resp = await self._client.get(url)
            text = resp.text if len(resp.content) < 3_000_000 else ""
            return resp.status_code, text
        except Exception:
            return 0, ""

    async def check_status(self, url: str) -> int:
        """HEAD with GET fallback, used for link checking."""
        assert self._client is not None
        async with self._sem:
            try:
                r = await self._client.head(url)
                if r.status_code in (403, 405, 501) or r.status_code >= 400:
                    r = await self._client.get(url, headers={"Range": "bytes=0-2048"})
                return r.status_code
            except Exception:
                return 0

    # ------------------------------------------------------------- site files
    async def load_site_context(self, input_url: str) -> SiteContext:
        if not input_url.startswith(("http://", "https://")):
            input_url = "https://" + input_url.strip()
        parsed = urlparse(input_url)
        ctx = SiteContext(input_url=input_url, netloc=parsed.netloc, scheme=parsed.scheme)

        home = await self.fetch(f"{parsed.scheme}://{parsed.netloc}/", parse=False)
        if not home.ok and parsed.scheme == "https":
            alt = await self.fetch(f"http://{parsed.netloc}/", parse=False)
            if alt.ok:
                ctx.scheme = "http"
                home = alt
        if home.final_url:
            fp = urlparse(home.final_url)
            ctx.scheme, ctx.netloc = fp.scheme, fp.netloc
        ctx.base_url = f"{ctx.scheme}://{ctx.netloc}"
        ctx.https_ok = ctx.scheme == "https"
        ctx.security_headers = {
            k: v for k, v in home.headers.items()
            if k in {"strict-transport-security", "content-security-policy", "x-frame-options"}
        }

        http_probe = await self.fetch(f"http://{ctx.netloc}/", parse=False)
        ctx.http_redirects = bool(http_probe.final_url.startswith("https://"))

        other = ctx.netloc[4:] if ctx.netloc.startswith("www.") else f"www.{ctx.netloc}"
        probe = await self.fetch(f"{ctx.scheme}://{other}/", parse=False)
        ctx.www_variant_status = probe.status
        ctx.www_variant_redirects = urlparse(probe.final_url).netloc == ctx.netloc if probe.final_url else False

        status, text = await self.fetch_text(urljoin(ctx.base_url, "/robots.txt"))
        ctx.robots = RobotsRules(text if "<html" not in text[:400].lower() else "", status)
        ctx.robots_url = urljoin(ctx.base_url, "/robots.txt")

        status, text = await self.fetch_text(urljoin(ctx.base_url, "/llms.txt"))
        if status == 200 and "<html" not in text[:400].lower():
            ctx.llms_txt, ctx.llms_status = text, status
        else:
            ctx.llms_status = status

        await self._load_sitemaps(ctx)
        return ctx

    async def _load_sitemaps(self, ctx: SiteContext) -> None:
        candidates = list(dict.fromkeys(
            ctx.robots.sitemaps + [urljoin(ctx.base_url, p) for p in
                                   ("/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml",
                                    "/wp-sitemap.xml", "/sitemap/sitemap.xml")]
        ))
        seen_sitemaps: set[str] = set()
        urls: list[str] = []
        for cand in candidates:
            if len(urls) > 3000 or len(ctx.sitemap_locations) >= 6:
                break
            found = await self._read_sitemap(cand, seen_sitemaps, depth=0)
            if found:
                ctx.sitemap_locations.append(cand)
                urls.extend(found)
        ctx.sitemap_urls = list(dict.fromkeys(urls))
        ctx.sitemap_status = 200 if ctx.sitemap_locations else 404

    async def _read_sitemap(self, url: str, seen: set[str], depth: int) -> list[str]:
        if url in seen or depth > 2:
            return []
        seen.add(url)
        status, text = await self.fetch_text(url)
        if status != 200 or not text.strip().startswith("<"):
            return []
        try:
            root = ET.fromstring(text.encode("utf-8", "ignore"))
        except ET.ParseError:
            return []
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        out: list[str] = []
        for sm in root.findall(".//sm:sitemap/sm:loc", ns) or root.findall(".//sitemap/loc"):
            if sm.text:
                out.extend(await self._read_sitemap(sm.text.strip(), seen, depth + 1))
        for loc in root.findall(".//sm:url/sm:loc", ns) or root.findall(".//url/loc"):
            if loc.text:
                out.append(loc.text.strip())
        return out

    # ------------------------------------------------------------------ crawl
    async def crawl(self, ctx: SiteContext, max_pages: int | None = None) -> list[PageData]:
        max_pages = max_pages or settings.max_pages
        start = normalize_url(ctx.base_url + "/")
        frontier: list[tuple[int, int, str]] = [(0, 0, start)]  # (priority, depth, url)
        seen: set[str] = {start}
        pages: list[PageData] = []

        # seed with sitemap URLs so we still find pages on link-poor sites
        for u in ctx.sitemap_urls[:60]:
            n = normalize_url(u)
            if urlparse(n).netloc.replace("www.", "") != ctx.netloc.replace("www.", ""):
                continue
            if n not in seen and not n.lower().endswith(SKIP_EXT):
                seen.add(n)
                frontier.append((self._priority(n) + 1, 1, n))

        def html_count() -> int:
            return sum(1 for p in pages if p.html)

        fetch_cap = max_pages * 3
        while frontier and html_count() < max_pages and len(pages) < fetch_cap:
            frontier.sort(key=lambda x: (x[0], x[1]))
            batch = [frontier.pop(0) for _ in range(min(settings.crawl_concurrency,
                                                        len(frontier),
                                                        max(1, max_pages - html_count())))]
            results = await asyncio.gather(*[
                self.fetch(u, depth=d, root_netloc=ctx.netloc) for _, d, u in batch
            ])
            for page in results:
                if settings.respect_robots and not ctx.robots.allows(urlparse(page.url).path, "*"):
                    continue
                pages.append(page)
                if not page.html:
                    continue
                for link in page.internal_links:
                    n = normalize_url(link.url)
                    if n in seen or n.lower().endswith(SKIP_EXT):
                        continue
                    if urlparse(n).netloc.replace("www.", "") != ctx.netloc.replace("www.", ""):
                        continue
                    seen.add(n)
                    frontier.append((self._priority(n), page.depth + 1, n))

        # keep every HTML page plus the error pages we hit (they are findings too)
        html_pages = [p for p in pages if p.html][:max_pages]
        error_pages = [p for p in pages if not p.html]
        return html_pages + error_pages

    @staticmethod
    def _priority(url: str) -> int:
        path = urlparse(url).path.strip("/")
        if not path:
            return 0
        segs = path.split("/")
        score = 10 + len(segs) * 5
        low = path.lower()
        if any(h in low for h in PRIORITY_HINTS):
            score -= 8
        if len(low) > 80:
            score += 5
        return score

    async def check_links(self, urls: list[str], limit: int | None = None) -> dict[str, int]:
        limit = limit or settings.max_link_checks
        targets = list(dict.fromkeys(urls))[:limit]
        results = await asyncio.gather(*[self.check_status(u) for u in targets])
        return dict(zip(targets, results))
