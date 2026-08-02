"""On-page checks: title tags, meta descriptions, heading structure, images."""
from __future__ import annotations

from collections import defaultdict

from .. import textutil as T
from ..issues import Finding
from ..parser import PageData

TITLE_MAX, TITLE_MIN = 60, 30
META_MAX, META_MIN = 160, 70
H1_MAX = 60
IMG_HEAVY_BYTES = 300_000


def run(pages: list[PageData]) -> list[Finding]:
    findings: list[Finding] = []
    html_pages = [p for p in pages if p.html and p.ok]

    titles: dict[str, list[str]] = defaultdict(list)
    metas: dict[str, list[str]] = defaultdict(list)
    h1s: dict[str, list[str]] = defaultdict(list)

    for page in html_pages:
        url = page.final_url or page.url
        findings.extend(_title(page, url))
        findings.extend(_meta(page, url))
        findings.extend(_headings(page, url))
        findings.extend(_images(page, url))

        if page.title:
            titles[T.normalize(page.title)].append(url)
        if page.meta_description:
            metas[T.normalize(page.meta_description)].append(url)
        for h in page.h1s:
            h1s[T.normalize(h.text)].append(url)

    for value, urls in titles.items():
        if len(urls) > 1:
            findings.append(Finding("TITLE_DUPLICATE", url=urls[0],
                                    detail=f"Same title on {len(urls)} pages: {', '.join(urls[:4])}",
                                    evidence=value[:160], extra={"urls": urls}))
    for value, urls in metas.items():
        if len(urls) > 1:
            findings.append(Finding("META_DUPLICATE", url=urls[0],
                                    detail=f"Same meta description on {len(urls)} pages.",
                                    evidence=value[:200], extra={"urls": urls}))
    for value, urls in h1s.items():
        if len(urls) > 1:
            findings.append(Finding("H1_DUPLICATE", url=urls[0],
                                    detail=f"Identical H1 on {len(urls)} pages: {', '.join(urls[:4])}",
                                    evidence=value[:160], extra={"urls": urls}))
    return findings


def _title(page: PageData, url: str) -> list[Finding]:
    out: list[Finding] = []
    title = page.title.strip()
    if not title:
        return [Finding("TITLE_MISSING", url=url, detail="No <title> element found.",
                        selector="head")]
    n = len(title)
    if n > TITLE_MAX:
        out.append(Finding("TITLE_TOO_LONG", url=url,
                           detail=f"Title is {n} characters (limit {TITLE_MAX}).",
                           evidence=title))
    elif n < TITLE_MIN:
        out.append(Finding("TITLE_TOO_SHORT", url=url,
                           detail=f"Title is only {n} characters.", evidence=title))
    return out


def _meta(page: PageData, url: str) -> list[Finding]:
    desc = page.meta_description.strip()
    if not desc:
        return [Finding("META_MISSING", url=url, detail="No meta description tag.")]
    n = len(desc)
    if n > META_MAX:
        return [Finding("META_TOO_LONG", url=url,
                        detail=f"Meta description is {n} characters (limit {META_MAX}).",
                        evidence=desc)]
    if n < META_MIN:
        return [Finding("META_TOO_SHORT", url=url,
                        detail=f"Meta description is only {n} characters.", evidence=desc)]
    return []


def _headings(page: PageData, url: str) -> list[Finding]:
    out: list[Finding] = []
    h1 = page.h1s
    if not h1:
        out.append(Finding("H1_MISSING", url=url, detail="Page has no H1 heading.",
                           selector="body"))
    else:
        if len(h1) > 1:
            out.append(Finding("H1_MULTIPLE", url=url,
                               detail=f"{len(h1)} H1 tags found: " +
                                      " | ".join(h.text[:50] for h in h1[:4]),
                               evidence=" | ".join(h.text for h in h1)[:240],
                               selector=h1[1].selector))
        first = h1[0]
        if len(first.text) > H1_MAX:
            out.append(Finding("H1_TOO_LONG", url=url,
                               detail=f"H1 is {len(first.text)} characters (limit {H1_MAX}).",
                               evidence=first.text, selector=first.selector))
    levels = [h.level for h in page.headings]
    for prev, cur in zip(levels, levels[1:]):
        if cur - prev > 1:
            out.append(Finding("HEADING_HIERARCHY", url=url,
                               detail=f"Heading jumps from H{prev} to H{cur}.",
                               evidence=" > ".join(f"H{l}" for l in levels[:12])))
            break
    return out


def _images(page: PageData, url: str) -> list[Finding]:
    out: list[Finding] = []
    imgs = page.images
    if not imgs:
        return out
    missing_alt = [i for i in imgs if not (i.alt or "").strip()]
    missing_title = [i for i in imgs if not (i.title or "").strip()]
    generic = [i for i in imgs if T.is_generic_filename(i.filename)]
    no_dims = [i for i in imgs if not (i.width and i.height)]

    if missing_alt:
        out.append(Finding("IMG_ALT_MISSING", url=url,
                           detail=f"{len(missing_alt)} of {len(imgs)} images have no alt text.",
                           evidence="; ".join(i.filename for i in missing_alt[:6]),
                           selector=missing_alt[0].selector,
                           extra={"images": [i.src for i in missing_alt[:20]]}))
    if missing_title:
        out.append(Finding("IMG_TITLE_MISSING", url=url,
                           detail=f"{len(missing_title)} of {len(imgs)} images have no title attribute.",
                           evidence="; ".join(i.filename for i in missing_title[:6]),
                           extra={"images": [i.src for i in missing_title[:20]]}))
    if generic:
        out.append(Finding("IMG_FILENAME_GENERIC", url=url,
                           detail=f"{len(generic)} images use non-descriptive filenames.",
                           evidence="; ".join(i.filename for i in generic[:6])))
    if len(no_dims) > max(2, len(imgs) // 2):
        out.append(Finding("IMG_NO_DIMENSIONS", url=url,
                           detail=f"{len(no_dims)} images lack width/height attributes.",
                           evidence="; ".join(i.filename for i in no_dims[:6])))
    return out


def image_weight_findings(page: PageData, weights: dict[str, int]) -> list[Finding]:
    heavy = [(src, size) for src, size in weights.items() if size > IMG_HEAVY_BYTES]
    if not heavy:
        return []
    heavy.sort(key=lambda x: -x[1])
    total = sum(s for _, s in heavy)
    return [Finding("IMG_HEAVY", url=page.final_url or page.url,
                    detail=f"{len(heavy)} images exceed 300 KB ({total/1_048_576:.1f} MB total).",
                    evidence="; ".join(f"{s.rsplit('/', 1)[-1]} {sz/1024:.0f}KB"
                                       for s, sz in heavy[:5]),
                    extra={"images": [s for s, _ in heavy[:10]]})]
