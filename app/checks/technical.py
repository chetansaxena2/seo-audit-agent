"""Technical SEO: site-level infrastructure, indexability, canonicals,
redirects, broken links and site architecture."""
from __future__ import annotations

from urllib.parse import urlparse

from ..config import settings
from ..crawler import Crawler, SiteContext, normalize_url
from ..issues import Finding
from ..parser import PageData


def site_level(ctx: SiteContext, pages: list[PageData]) -> list[Finding]:
    out: list[Finding] = []
    base = ctx.base_url

    if not ctx.https_ok:
        out.append(Finding("HTTPS_MISSING", url=base,
                           detail="The site resolves over HTTP; no valid HTTPS response was found."))
    elif not ctx.http_redirects:
        out.append(Finding("HTTP_NOT_REDIRECTED", url=f"http://{ctx.netloc}/",
                           detail="The HTTP version does not 301-redirect to HTTPS."))

    if ctx.www_variant_status and 200 <= ctx.www_variant_status < 300 and not ctx.www_variant_redirects:
        other = ctx.netloc[4:] if ctx.netloc.startswith("www.") else f"www.{ctx.netloc}"
        out.append(Finding("WWW_DUPLICATE", url=f"{ctx.scheme}://{other}/",
                           detail="Both www and non-www return 200 without redirecting.",
                           evidence=f"status {ctx.www_variant_status}"))

    if not ctx.robots.exists:
        out.append(Finding("ROBOTS_MISSING", url=ctx.robots_url,
                           detail=f"/robots.txt returned status {ctx.robots.status}."))
    else:
        if ctx.robots.blocks_site("Googlebot") or ctx.robots.blocks_site("*"):
            out.append(Finding("ROBOTS_BLOCKS_SITE", url=ctx.robots_url,
                               detail="robots.txt disallows crawling of the whole site.",
                               evidence=ctx.robots.text[:400]))
        if not ctx.robots.sitemaps:
            out.append(Finding("ROBOTS_NO_SITEMAP", url=ctx.robots_url,
                               detail="No Sitemap: directive in robots.txt."))

    if not ctx.sitemap_locations:
        out.append(Finding("SITEMAP_MISSING", url=f"{base}/sitemap.xml",
                           detail="No XML sitemap found at the common locations or in robots.txt."))
    return out


def per_page(pages: list[PageData], ctx: SiteContext) -> list[Finding]:
    out: list[Finding] = []
    for page in pages:
        url = page.final_url or page.url
        if page.error and not page.status:
            out.append(Finding("PAGE_5XX", url=page.url,
                               detail=f"Request failed: {page.error}"))
            continue
        if 400 <= page.status < 500:
            out.append(Finding("PAGE_4XX", url=page.url,
                               detail=f"Returned HTTP {page.status}."))
            continue
        if page.status >= 500:
            out.append(Finding("PAGE_5XX", url=page.url,
                               detail=f"Returned HTTP {page.status}."))
            continue
        if not page.html:
            continue

        robots_directives = f"{page.meta_robots} {page.x_robots}".lower()
        if "noindex" in robots_directives:
            out.append(Finding("NOINDEX", url=url,
                               detail="Page carries a noindex directive.",
                               evidence=robots_directives.strip(), selector="head"))
        if not page.canonical:
            out.append(Finding("CANONICAL_MISSING", url=url,
                               detail="No rel=canonical link element."))
        elif normalize_url(page.canonical) != normalize_url(url):
            out.append(Finding("CANONICAL_CONFLICT", url=url,
                               detail=f"Canonical points to {page.canonical}",
                               evidence=page.canonical, selector="head"))
        if not page.viewport:
            out.append(Finding("VIEWPORT_MISSING", url=url,
                               detail="No mobile viewport meta tag."))
        if not page.lang:
            out.append(Finding("LANG_MISSING", url=url, detail="<html> has no lang attribute."))
        if len(page.redirect_chain) > 1:
            out.append(Finding("REDIRECT_CHAIN", url=page.url,
                               detail=f"{len(page.redirect_chain)} redirects before the final URL.",
                               evidence=" -> ".join(page.redirect_chain[:4] + [url])))
        if page.depth > 3:
            out.append(Finding("DEEP_PAGE", url=url,
                               detail=f"Page sits {page.depth} clicks from the homepage."))
    return out


async def link_health(crawler: Crawler, pages: list[PageData], ctx: SiteContext) -> tuple[list[Finding], dict]:
    """Check every discovered link (capped) and report broken ones."""
    internal: dict[str, list[tuple[str, str]]] = {}
    external: dict[str, list[tuple[str, str]]] = {}
    crawled = {normalize_url(p.final_url or p.url) for p in pages}
    statuses = {normalize_url(p.final_url or p.url): p.status for p in pages}

    for page in pages:
        src = page.final_url or page.url
        for link in page.links:
            key = normalize_url(link.url)
            bucket = internal if link.internal else external
            bucket.setdefault(key, []).append((src, link.anchor or link.raw_href))

    budget = settings.max_link_checks
    to_check = [u for u in internal if u not in crawled][:budget]
    ext_budget = max(0, budget - len(to_check))
    to_check += list(external)[:ext_budget]
    results = await crawler.check_links(to_check)
    results.update({u: s for u, s in statuses.items() if u in internal})

    findings: list[Finding] = []
    broken_int = {u: s for u, s in results.items() if u in internal and (s == 0 or s >= 400)}
    broken_ext = {u: s for u, s in results.items() if u in external and (s == 0 or s >= 400)}

    for url, status in list(broken_int.items())[:25]:
        sources = internal[url][:3]
        findings.append(Finding(
            "BROKEN_INTERNAL_LINK", url=sources[0][0],
            detail=f"Link to {url} returns {status or 'no response'}.",
            evidence=f"anchor: '{sources[0][1][:60]}' — linked from {len(internal[url])} place(s)",
            selector=f'a[href*="{urlparse(url).path[:60]}"]',
            extra={"target": url, "status": status,
                   "sources": [s for s, _ in internal[url][:8]]}))
    for url, status in list(broken_ext.items())[:15]:
        sources = external[url][:2]
        findings.append(Finding(
            "BROKEN_EXTERNAL_LINK", url=sources[0][0],
            detail=f"Outbound link to {url} returns {status or 'no response'}.",
            evidence=f"anchor: '{sources[0][1][:60]}'",
            extra={"target": url, "status": status}))

    stats = {
        "internal_links_found": len(internal),
        "external_links_found": len(external),
        "links_checked": len(results),
        "broken_internal": len(broken_int),
        "broken_external": len(broken_ext),
        "broken_urls": [{"url": u, "status": s} for u, s in
                        list(broken_int.items())[:25] + list(broken_ext.items())[:15]],
    }
    return findings, stats


def architecture(ctx: SiteContext, pages: list[PageData]) -> tuple[list[Finding], dict]:
    out: list[Finding] = []
    crawled = {normalize_url(p.final_url or p.url) for p in pages if p.html}
    linked: set[str] = set()
    for p in pages:
        for l in p.internal_links:
            linked.add(normalize_url(l.url))

    sitemap_norm = [normalize_url(u) for u in ctx.sitemap_urls]
    orphans = [u for u in sitemap_norm if u not in linked][:10]
    if orphans and ctx.sitemap_urls:
        out.append(Finding("ORPHAN_PAGE", url=orphans[0],
                           detail=f"{len(orphans)} sitemap URLs are not linked from any crawled page.",
                           evidence="; ".join(orphans[:5]), extra={"urls": orphans}))

    for p in pages:
        if p.html and len(p.internal_links) < 3:
            out.append(Finding("NO_INTERNAL_LINKS", url=p.final_url or p.url,
                               detail=f"Only {len(p.internal_links)} internal links on this page."))

    stats = {
        "pages_crawled": len([p for p in pages if p.html]),
        "sitemap_url_count": len(ctx.sitemap_urls),
        "max_depth": max((p.depth for p in pages), default=0),
        "orphan_candidates": len(orphans),
        "indexable_pages": len([p for p in pages if p.is_indexable and p.html]),
    }
    return out, stats
