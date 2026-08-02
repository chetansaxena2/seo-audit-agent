"""Visual evidence.

For issues where seeing the page explains the problem faster than reading
about it, the agent opens the URL in headless Chromium, highlights the
offending element in red and clips a screenshot for the report.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from pathlib import Path

from .config import settings
from .issues import CATALOG, SEVERITY_ORDER, Finding

HIGHLIGHT_JS = """
(opts) => {
  const {sel, label} = opts;
  const el = sel.startsWith('xpath=')
    ? document.evaluate(sel.slice(6), document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue
    : document.querySelector(sel);
  if (!el) return null;
  el.scrollIntoView({block: 'center', behavior: 'instant'});

  const RED = '#E5484D';
  const r = el.getBoundingClientRect();
  const box = {
    left: r.left + scrollX, top: r.top + scrollY,
    width: Math.max(r.width, 24), height: Math.max(r.height, 18)
  };
  const add = (css, html) => {
    const d = document.createElement('div');
    d.setAttribute('data-seo-audit-mark', '1');
    d.style.cssText = 'position:absolute;z-index:2147483647;pointer-events:none;' + css;
    if (html) d.innerHTML = html;
    document.body.appendChild(d);
    return d;
  };

  // 1. dim everything except the flagged element
  add(`left:${box.left - 6}px;top:${box.top - 6}px;width:${box.width + 12}px;
       height:${box.height + 12}px;border:2px solid ${RED};border-radius:4px;
       box-shadow:0 0 0 9999px rgba(8,20,34,.55);`);

  // 2. thick brackets on all four corners
  const C = 26, T = 5;
  const corners = [
    [box.left - 10,                 box.top - 10,                  `border-left:${T}px solid ${RED};border-top:${T}px solid ${RED};border-top-left-radius:5px;`],
    [box.left + box.width + 10 - C, box.top - 10,                  `border-right:${T}px solid ${RED};border-top:${T}px solid ${RED};border-top-right-radius:5px;`],
    [box.left - 10,                 box.top + box.height + 10 - C, `border-left:${T}px solid ${RED};border-bottom:${T}px solid ${RED};border-bottom-left-radius:5px;`],
    [box.left + box.width + 10 - C, box.top + box.height + 10 - C, `border-right:${T}px solid ${RED};border-bottom:${T}px solid ${RED};border-bottom-right-radius:5px;`]
  ];
  corners.forEach(([x, y, style]) =>
    add(`left:${x}px;top:${y}px;width:${C}px;height:${C}px;${style}`));

  // 3. arrow + label, placed wherever there is room around the element
  const above = box.top - scrollY > 150;
  const AW = 150, AH = 74;
  const ax = Math.max(scrollX + 12, box.left - 30);
  const ay = above ? box.top - AH - 14 : box.top + box.height + 14;
  // arrow points down-right toward the box when above it, up-right when below
  const path = above
    ? `M12,14 C12,52 46,58 84,64`
    : `M12,64 C12,26 46,20 84,14`;
  const head = above ? `84,64 72,56 74,70` : `84,14 72,8 74,22`;
  add(`left:${ax}px;top:${ay}px;width:${AW}px;height:${AH}px;`,
      `<svg width="${AW}" height="${AH}" viewBox="0 0 ${AW} ${AH}" fill="none"
            xmlns="http://www.w3.org/2000/svg">
         <path d="${path}" stroke="${RED}" stroke-width="4" fill="none" stroke-linecap="round"/>
         <polygon points="${head}" fill="${RED}"/>
       </svg>`);

  const labelY = above ? ay - 26 : ay + AH + 4;
  add(`left:${ax}px;top:${labelY}px;max-width:420px;background:${RED};color:#fff;
       font:700 13px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;
       padding:5px 11px;border-radius:5px;white-space:nowrap;overflow:hidden;
       text-overflow:ellipsis;box-shadow:0 2px 8px rgba(0,0,0,.35);`,
      (label || 'Issue found').replace(/[<>&]/g, ''));

  // bounds of everything drawn, so the screenshot clip includes the annotation
  const top = Math.min(box.top - 14, labelY - 6, ay - 6);
  const bottom = Math.max(box.top + box.height + 14, ay + AH + 30, labelY + 30);
  return {
    x: Math.max(0, Math.min(box.left - 40, ax - 12)),
    y: Math.max(0, top),
    width: Math.max(box.width + 80, AW + 40),
    height: bottom - Math.max(0, top)
  };
}
"""

CLEAN_JS = """
() => { document.querySelectorAll('[data-seo-audit-mark]').forEach(e => e.remove()); }
"""


CODE_CARD = """
<!doctype html><html><head><meta charset="utf-8"><style>
  body{margin:0;background:#F2F5F8;font:15px -apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif}
  .wrap{width:900px;padding:26px}
  .lbl{display:inline-flex;align-items:center;gap:9px;background:#E5484D;color:#fff;
       font-weight:700;font-size:15px;padding:9px 15px;border-radius:7px;
       box-shadow:0 3px 10px rgba(0,0,0,.2)}
  .arrow{margin:2px 0 -6px 34px}
  .code{background:#0E1B27;color:#DCE9F5;border-radius:10px;padding:20px 22px;
        font:14px/1.75 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
        white-space:pre-wrap;word-break:break-word;border:3px solid #E5484D}
  mark{background:#E5484D;color:#fff;padding:1px 5px;border-radius:3px}
  .cap{color:#5C6B7C;font-size:13px;margin-top:12px}
</style></head><body><div class="wrap">
  <div class="lbl">__LABEL__</div>
  <div class="arrow"><svg width="60" height="42" viewBox="0 0 60 42" fill="none"
      xmlns="http://www.w3.org/2000/svg">
      <path d="M8,4 C8,26 18,32 40,36" stroke="#E5484D" stroke-width="4"
            stroke-linecap="round" fill="none"/>
      <polygon points="46,37 32,30 34,42" fill="#E5484D"/></svg></div>
  <div class="code">__CODE__</div>
  <div class="cap">__CAP__</div>
</div></body></html>
"""


def _card_html(label: str, code: str, mark: str, caption: str) -> str:
    def esc(t: str) -> str:
        return (t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    body = esc(code[:1400])
    if mark:
        marked = esc(mark[:80])
        if marked in body:
            body = body.replace(marked, f"<mark>{marked}</mark>", 1)
    return (CODE_CARD.replace("__LABEL__", esc(label))
            .replace("__CODE__", body)
            .replace("__CAP__", esc(caption)))


def browser_args() -> list[str]:
    """Chromium flags. LOW_MEMORY trims it enough to run inside a 512 MB
    instance (Render's free tier) at the cost of some rendering speed."""
    args = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
            "--disable-extensions", "--disable-background-networking",
            "--disable-features=TranslateUI,BackForwardCache", "--mute-audio"]
    if settings.low_memory:
        args += ["--single-process", "--no-zygote", "--renderer-process-limit=1",
                 "--disable-software-rasterizer", "--js-flags=--max-old-space-size=128"]
    return args


async def capture(findings: list[Finding], audit_id: str,
                  cover_url: str | None = None,
                  base_dir: str | Path | None = None) -> dict[str, str]:
    """Attach screenshots to findings. Returns {'cover': path} extras."""
    extras: dict[str, str] = {}
    if not settings.screenshots_enabled:
        return extras
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return extras

    out_dir = Path(base_dir or settings.data_dir) / "screenshots" / audit_id
    out_dir.mkdir(parents=True, exist_ok=True)

    by_url: dict[str, list[Finding]] = defaultdict(list)
    for f in findings:
        if not f.url or not CATALOG[f.code].screenshot:
            continue
        by_url[f.url].append(f)

    # Spend the budget on issues that point at a visible element first — an
    # annotated heading or image explains itself, a full-page shot of a <head>
    # problem does not.
    def rank(f: Finding) -> tuple[int, int]:
        visible = 0 if (f.selector and f.selector not in ("head", "body")) else 1
        return visible, SEVERITY_ORDER[CATALOG[f.code].severity]

    for url in by_url:
        by_url[url].sort(key=rank)
    ordered_urls = sorted(by_url, key=lambda u: rank(by_url[u][0]))
    by_url = {u: by_url[u] for u in ordered_urls}

    # One picture per problem type. Nine pages missing an H1 is one screenshot,
    # not nine — the report states the count instead.
    captured_codes: set[str] = set()
    budget = settings.screenshot_max
    needs_cards = any(f.code_snippet or f.evidence for f in findings)
    if not by_url and not cover_url and not needs_cards:
        return extras

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=browser_args())
            context = await browser.new_context(
                viewport={"width": 1366, "height": 900},
                device_scale_factor=settings.screenshot_scale,
                user_agent=settings.user_agent, ignore_https_errors=True)
            page = await context.new_page()

            if cover_url:
                try:
                    await page.goto(cover_url, wait_until="load", timeout=40000)
                    await page.wait_for_timeout(1200)
                    path = out_dir / "cover.png"
                    await page.screenshot(path=str(path))
                    extras["cover"] = str(path)
                except Exception:
                    pass

            taken = 0
            for url, items in by_url.items():
                if taken >= budget:
                    break
                try:
                    await page.goto(url, wait_until="load", timeout=40000)
                    await page.wait_for_timeout(900)
                except Exception:
                    continue
                for finding in items[:3]:
                    if taken >= budget:
                        break
                    if finding.code in captured_codes:
                        continue      # already have a picture of this problem
                    name = f"{finding.code.lower()}_{taken}.png"
                    path = out_dir / name
                    try:
                        box = None
                        if finding.selector and finding.selector not in ("head", "body"):
                            box = await page.evaluate(
                                HIGHLIGHT_JS,
                                {"sel": finding.selector,
                                 "label": finding.annotation or CATALOG[finding.code].title})
                        if box and box.get("height", 0) > 8:
                            # clip coordinates are document-relative, which only
                            # holds with full_page=True — without it anything
                            # below the fold captures the wrong region
                            clip = {
                                "x": max(0, box["x"] - 30),
                                "y": max(0, box["y"] - 20),
                                "width": min(1366, box["width"] + 120),
                                "height": min(820, box["height"] + 60),
                            }
                            await page.screenshot(path=str(path), clip=clip, full_page=True)
                        else:
                            await page.screenshot(path=str(path))
                        finding.screenshot = str(path)
                        captured_codes.add(finding.code)
                        taken += 1
                    except Exception:
                        continue
                    finally:
                        try:
                            await page.evaluate(CLEAN_JS)
                        except Exception:
                            pass
            # second pass: problems you cannot see on the page (missing alt text,
            # empty description, no business data) become a picture of the real code
            remaining = [f for f in findings
                         if not f.screenshot and f.code not in captured_codes
                         and (f.code_snippet or f.evidence)]
            # worst problems first — they are the ones that reach the report
            remaining.sort(key=lambda f: SEVERITY_ORDER[CATALOG[f.code].severity])
            seen: set[str] = set()
            for finding in remaining:
                if finding.code in seen or len(seen) >= 24:
                    continue
                seen.add(finding.code)
                path = out_dir / f"code_{finding.code.lower()}.png"
                try:
                    await page.set_content(_card_html(
                        finding.annotation or CATALOG[finding.code].title,
                        finding.code_snippet or finding.evidence,
                        finding.snippet_mark,
                        f"From the code of {finding.url}" if finding.url else ""))
                    await page.wait_for_timeout(120)
                    box = await page.query_selector(".wrap")
                    if box:
                        await box.screenshot(path=str(path))
                        finding.screenshot = str(path)
                        captured_codes.add(finding.code)
                except Exception:
                    continue

            await browser.close()
    except Exception:
        return extras
    return extras


def screenshot_url(path: str | None) -> str | None:
    """Convert a stored screenshot path into a public URL.

    Returns None for screenshots written outside DATA_DIR (stateless runs use a
    temp directory that is deleted before the response is sent, so there is no
    URL to hand out)."""
    if not path:
        return None
    try:
        rel = Path(path).relative_to(Path(settings.data_dir))
    except ValueError:
        return None
    return f"{settings.public_base_url.rstrip('/')}/files/{rel.as_posix()}"
