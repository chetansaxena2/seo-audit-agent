"""Page speed and Core Web Vitals.

Preference order:
1. PageSpeed Insights API (field + lab data) when PAGESPEED_API_KEY is set.
2. Headless Chromium lab measurement (LCP, CLS, TTFB, weight).
3. Crawl-timing estimate from the HTTP responses we already made.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import httpx

from ..config import settings
from ..issues import Finding
from ..parser import PageData

PSI_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


@dataclass
class SpeedReport:
    score: float = 0.0
    source: str = "estimate"
    mobile_score: float | None = None
    desktop_score: float | None = None
    metrics: dict[str, float] = field(default_factory=dict)
    opportunities: list[dict] = field(default_factory=list)
    page_weight_kb: float = 0.0
    requests: int = 0
    image_weights: dict[str, int] = field(default_factory=dict)
    tested_url: str = ""

    def to_dict(self) -> dict:
        return {
            "page_speed_score": round(self.score, 1),
            "source": self.source,
            "mobile_score": self.mobile_score,
            "desktop_score": self.desktop_score,
            "metrics": {k: round(v, 3) for k, v in self.metrics.items()},
            "page_weight_kb": round(self.page_weight_kb, 1),
            "requests": self.requests,
            "top_opportunities": self.opportunities[:6],
            "tested_url": self.tested_url,
        }


async def _psi(url: str, strategy: str) -> dict | None:
    params = {"url": url, "strategy": strategy, "category": "performance",
              "key": settings.psi_api_key}
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            r = await client.get(PSI_URL, params=params)
            r.raise_for_status()
            return r.json()
    except Exception:
        return None


def _psi_extract(data: dict) -> tuple[float, dict, list[dict]]:
    lh = data.get("lighthouseResult", {})
    audits = lh.get("audits", {})
    score = (lh.get("categories", {}).get("performance", {}).get("score") or 0) * 100
    metrics = {}
    for key, audit in (("lcp", "largest-contentful-paint"), ("fcp", "first-contentful-paint"),
                       ("cls", "cumulative-layout-shift"), ("tbt", "total-blocking-time"),
                       ("si", "speed-index"), ("ttfb", "server-response-time")):
        val = audits.get(audit, {}).get("numericValue")
        if val is not None:
            metrics[key] = val / 1000 if key not in ("cls", "tbt") else val
    field_data = data.get("loadingExperience", {}).get("metrics", {})
    for key, name in (("field_lcp", "LARGEST_CONTENTFUL_PAINT_MS"),
                      ("field_inp", "INTERACTION_TO_NEXT_PAINT"),
                      ("field_cls", "CUMULATIVE_LAYOUT_SHIFT_SCORE")):
        m = field_data.get(name)
        if m and m.get("percentile") is not None:
            metrics[key] = m["percentile"] / (1000 if "MS" in name else
                                              (100 if "SHIFT" in name else 1))
    opps = []
    for aid, audit in audits.items():
        saving = (audit.get("details") or {}).get("overallSavingsMs")
        if saving and saving > 150:
            opps.append({"id": aid, "title": audit.get("title", aid),
                         "savings_ms": round(saving)})
    opps.sort(key=lambda o: -o["savings_ms"])
    return score, metrics, opps


async def _lab(url: str) -> tuple[dict, float, int, dict[str, int]] | None:
    """Measure with headless Chromium if Playwright and a browser are available."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return None
    script = """
    () => new Promise(resolve => {
      let lcp = 0, cls = 0;
      try {
        new PerformanceObserver(l => { for (const e of l.getEntries()) lcp = e.startTime; })
          .observe({type: 'largest-contentful-paint', buffered: true});
        new PerformanceObserver(l => { for (const e of l.getEntries())
            if (!e.hadRecentInput) cls += e.value; })
          .observe({type: 'layout-shift', buffered: true});
      } catch (e) {}
      setTimeout(() => {
        const nav = performance.getEntriesByType('navigation')[0] || {};
        const paints = performance.getEntriesByType('paint');
        const fcp = (paints.find(p => p.name === 'first-contentful-paint') || {}).startTime || 0;
        resolve({lcp: lcp/1000, cls: cls, fcp: fcp/1000,
                 ttfb: (nav.responseStart || 0)/1000,
                 dcl: (nav.domContentLoadedEventEnd || 0)/1000,
                 load: (nav.loadEventEnd || 0)/1000});
      }, 2500);
    })
    """
    weights: dict[str, int] = {}
    total = 0
    count = 0
    try:
        async with async_playwright() as p:
            from ..screenshots import browser_args
            browser = await p.chromium.launch(args=browser_args())
            page = await browser.new_page(
                viewport={"width": 412, "height": 915}, device_scale_factor=1,
                user_agent=("Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/124 Mobile Safari/537.36"))

            async def on_response(resp):
                nonlocal total, count
                try:
                    length = int(resp.headers.get("content-length") or 0)
                    if not length:
                        return
                    total += length
                    count += 1
                    if resp.request.resource_type == "image":
                        weights[resp.url] = length
                except Exception:
                    pass

            page.on("response", lambda r: asyncio.create_task(on_response(r)))
            await page.goto(url, wait_until="load", timeout=45000)
            metrics = await page.evaluate(script)
            await browser.close()
        return metrics, total / 1024, count, weights
    except Exception:
        return None


def _score_from_metrics(m: dict) -> float:
    """Lighthouse-like weighting of the metrics we can measure."""
    def curve(value: float, good: float, poor: float) -> float:
        if value <= good:
            return 100.0
        if value >= poor:
            return 10.0
        return 100 - (value - good) / (poor - good) * 90

    lcp = curve(m.get("lcp", m.get("load", 4.0)), 2.5, 6.0)
    fcp = curve(m.get("fcp", 2.5), 1.8, 4.0)
    ttfb = curve(m.get("ttfb", 0.8), 0.8, 2.5)
    cls = curve(m.get("cls", 0.1), 0.1, 0.4)
    return round(lcp * 0.4 + fcp * 0.2 + ttfb * 0.2 + cls * 0.2, 1)


async def analyse(pages: list[PageData]) -> tuple[SpeedReport, list[Finding]]:
    findings: list[Finding] = []
    report = SpeedReport()
    target = next((p for p in pages if p.html and p.ok), None)
    if not target:
        return report, findings
    url = target.final_url or target.url
    report.tested_url = url

    if settings.psi_api_key:
        mobile, desktop = await asyncio.gather(_psi(url, "mobile"), _psi(url, "desktop"))
        if mobile:
            m_score, metrics, opps = _psi_extract(mobile)
            report.mobile_score = round(m_score, 1)
            report.metrics.update(metrics)
            report.opportunities = opps
            if desktop:
                d_score, _, _ = _psi_extract(desktop)
                report.desktop_score = round(d_score, 1)
            report.score = round(
                (report.mobile_score * 0.65 + (report.desktop_score or report.mobile_score) * 0.35), 1)
            report.source = "pagespeed-insights"

    if report.source == "estimate":
        lab = await _lab(url)
        if lab:
            metrics, weight_kb, requests, weights = lab
            report.metrics.update({k: v for k, v in metrics.items() if isinstance(v, (int, float))})
            report.page_weight_kb = weight_kb
            report.requests = requests
            report.image_weights = weights
            report.score = _score_from_metrics(report.metrics)
            report.mobile_score = report.score
            report.source = "headless-chrome-lab"

    if report.source == "estimate":
        report.metrics = {
            "ttfb": target.ttfb_ms / 1000,
            "load": target.load_ms / 1000,
        }
        report.page_weight_kb = target.bytes / 1024
        report.score = _score_from_metrics(report.metrics)
        report.source = "crawl-timing-estimate"

    m = report.metrics
    lcp = m.get("field_lcp") or m.get("lcp")
    if lcp and lcp > 2.5:
        findings.append(Finding("SLOW_LCP", url=url,
                                detail=f"Largest Contentful Paint is {lcp:.1f}s (target under 2.5s).",
                                evidence=f"source: {report.source}"))
    ttfb = m.get("ttfb")
    if ttfb and ttfb > 0.9:
        findings.append(Finding("SLOW_TTFB", url=url,
                                detail=f"Server responded in {ttfb*1000:.0f}ms (target under 800ms)."))
    cls = m.get("field_cls") or m.get("cls")
    if cls and cls > 0.1:
        findings.append(Finding("HIGH_CLS", url=url,
                                detail=f"Cumulative Layout Shift is {cls:.2f} (target under 0.1)."))
    if report.page_weight_kb > 3000:
        findings.append(Finding("PAGE_WEIGHT", url=url,
                                detail=f"Page weighs {report.page_weight_kb/1024:.1f} MB across "
                                       f"{report.requests} requests."))
    blocking = max((p.render_blocking for p in pages if p.html), default=0)
    if blocking > 4:
        findings.append(Finding("RENDER_BLOCKING", url=url,
                                detail=f"{blocking} render-blocking CSS/JS files in the head."))
    return report, findings


async def image_weights(crawler, page: PageData, limit: int = 12) -> dict[str, int]:
    """HEAD the biggest candidate images when no browser measurement is available."""
    out: dict[str, int] = {}
    srcs = [i.src for i in page.images][:limit]
    if not srcs:
        return out
    async def one(src: str) -> None:
        try:
            assert crawler._client is not None
            r = await crawler._client.head(src)
            size = int(r.headers.get("content-length") or 0)
            if size:
                out[src] = size
        except Exception:
            pass
    await asyncio.gather(*[one(s) for s in srcs])
    return out
