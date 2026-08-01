# SEO Audit Agent

Give it a URL. It does the rest.

A self-hosted agent that crawls a website, audits it the way a senior SEO consultant would, scores it, captures screenshot evidence of the errors it finds, and returns a shareable HTML report plus a downloadable PDF. It runs as a REST API with a live dashboard, so it plugs into any tool you already use and comfortably handles **500 audits a day** on one box.

```bash
curl -X POST https://your-host/audits \
  -H "X-API-Key: your-key" -H "Content-Type: application/json" \
  -d '{"url": "https://clientsite.com"}'
```

That single call produces everything below.

---

## What it checks

**Crawl** — up to N pages (default 10), breadth-first, robots-aware, service-page prioritised, seeded from the XML sitemap so link-poor sites still get covered.

| Area | Checks |
|---|---|
| **Site files** | robots.txt present + correct, blanket `Disallow` detection, `Sitemap:` directive, XML sitemap (incl. sitemap indexes), **llms.txt**, HTTPS, HTTP→HTTPS redirect, www/non-www duplication |
| **Indexability** | 4xx/5xx pages, `noindex`, canonical missing, canonical pointing elsewhere, redirect chains, crawl depth, orphan pages |
| **Titles** | missing, **over 60 characters**, under 30, duplicated across pages, **target keyword present or not** |
| **Meta descriptions** | missing, **over 160 characters**, under 70, duplicated, **keyword present or not** |
| **Headings** | missing H1, **multiple H1s**, **duplicate H1s across pages**, H1 over 60 chars, **keyword in H1**, **keyword in H2/H3**, broken hierarchy (H2→H4) |
| **Images** | **missing alt text**, **missing title attribute**, generic filenames (`IMG_2381.jpg`), missing width/height, oversized files |
| **Content** | thin pages, **near-duplicate content between pages** (shingle similarity), keyword density and stuffing, FAQ/question coverage, internal linking, About/Contact/Privacy trust pages, services with no dedicated page |
| **Schema** | any structured data, **Organization/LocalBusiness**, **FAQPage**, BreadcrumbList, invalid JSON-LD |
| **Links** | **broken internal links**, broken outbound links, per-link source page and anchor text |
| **AI search (GEO)** | llms.txt, **AI crawlers blocked** (GPTBot, ClaudeBot, PerplexityBot, Google-Extended, CCBot…), extractable answer blocks, question-led headings, entity signals (sameAs, About, author, NAP), freshness dates, content depth |
| **Speed** | LCP, FCP, CLS, TTFB, TBT, page weight, requests, render-blocking resources, Lighthouse opportunities |
| **Authority** | referring domains, backlinks, domain rating (or a labelled on-site estimate when no link API is connected) |
| **Local & CRO** | NAP visibility, location keywords on key pages, call-to-action presence, click-to-call links, contact form |
| **Competitors** | **3 competitors found automatically** from the site's own services + location, then crawled and compared on content depth, schema, FAQ markup, llms.txt, alt coverage, speed and keyword overlap |

Every finding carries the five fields a client needs: **problem, why it matters, impact level, recommended fix, expected benefit** — plus the exact URL, the evidence, and often a screenshot.

## What it gives back

**Five headline stats**, each 0–100:

| Stat | How it is derived |
|---|---|
| **Authority** | Backlink data from your provider; otherwise a clearly-labelled estimate from indexable pages, content depth, entity schema, trust pages, internal link volume and sitemap size |
| **AI Score** | llms.txt (10) + AI crawler access (12) + structured data (20) + extractable answers (20) + entity signals (18) + freshness (8) + depth (12) |
| **Error Score** | 100 decaying against weighted issue penalties (critical 12 / high 6 / medium 2.5 / low 0.8), repeats discounted so one sitewide mistake cannot zero the score |
| **Page Speed** | PageSpeed Insights when a key is set; otherwise a headless-Chrome lab measurement; otherwise crawl timings — the source is always printed |
| **Google Optimized** | A 13-point checklist score: indexability, HTTPS, canonicals, title length, meta length, single H1, keyword targeting, alt text, robots+sitemap, viewport, broken links, uniqueness, structured data |

Plus an **overall score and grade** (technical 25% · on-page 20% · content 20% · authority 15% · AI search 10% · speed 10%), section scores, and a full **priority fix roadmap** grouped critical → high → medium → low.

**Ready-to-paste deliverables**, generated per audit:
- rewritten titles (≤60 chars), meta descriptions (≤160 chars) and H1s for every page that needs one
- a complete `llms.txt` for the site
- `LocalBusiness` JSON-LD filled with the site's real details
- `FAQPage` JSON-LD built from the site's existing Q&A content

**Screenshot evidence** — for issues where seeing it explains it, headless Chromium opens the page, rings the offending element in red, and embeds the clip in the report.

---

## Put it on a free public link

Want a URL anyone can use? See **[deploy/DEPLOY.md](deploy/DEPLOY.md)** — step-by-step for
Hugging Face Spaces (free, no card, enough RAM for Chromium), Render and Fly.io.

Set `REQUIRE_AUTH=false` and the home page becomes a public audit form: visitor pastes a URL,
waits ~90 seconds, downloads the PDF. Per-IP rate limiting (`RATE_LIMIT_PER_HOUR`) and a page
cap (`PUBLIC_MAX_PAGES`) keep the instance from being abused. Set `REQUIRE_AUTH=true` and the
same URL serves the key-protected operator dashboard instead.

GitHub Pages cannot host this — it serves static files only, and the agent is a Python server
that also drives a headless browser. Keep the code on GitHub, run it on one of the hosts above.

---

## Stateless mode — PDF in, PDF out, nothing stored

Set `STATELESS=true` and the agent keeps nothing at all: no database, no saved reports, no screenshots on disk. The whole audit runs inside a temp directory that is deleted before the response is sent, and the screenshots are embedded in the PDF itself as base64.

```bash
curl -X POST https://your-host/audit.pdf \
  -H "X-API-Key: your-key" -H "Content-Type: application/json" \
  -d '{"url": "https://clientsite.com"}' \
  --output audit.pdf
```

One call, one file. The response also carries the headline numbers in headers, so a script can read the score without parsing the PDF:

```
X-Overall-Score: 46.4
X-Grade: F
X-Critical-Issues: 3
```

| Stateless endpoint | Returns |
|---|---|
| `POST /audit.pdf` | The PDF report as a download |
| `POST /audit.html` | The HTML report (screenshots inlined) |
| `POST /audit.json` | The full JSON result |

Same request body as `/audits`. Expect 60–180 seconds per call — it is doing the whole audit before it answers, so set your client timeout to at least 300 seconds.

In stateless mode the dashboard, share links, audit history and webhooks are switched off (those endpoints return `409` explaining why), because all of them depend on storing something. Run with `STATELESS=false` if you want them back.

---

## See it working in two minutes

```bash
./demo.sh
```

Serves the bundled test site (24 deliberate SEO faults planted in it), audits it, and writes
a real HTML + PDF report into `demo-output/`. Open the PDF — that is exactly what a client gets.

Then point it at anything real:

```bash
python -m app.cli audit https://yoursite.com --pdf
```

Pre-generated samples live in [`examples/`](examples/): one audit of a **live public site**
(pypi.org — grade D, 109 findings, real Core Web Vitals) and one of the fault-seeded test site
(showing every check firing, with screenshot evidence).

---

## Quick start

### Docker (recommended)

```bash
cp .env.example .env        # set API_KEYS and PUBLIC_BASE_URL at minimum
docker compose up -d --build
open http://localhost:8000  # dashboard
```

### Local

```bash
./run.sh                    # venv + deps + chromium + server
```

or manually:

```bash
pip install -r requirements.txt
python -m playwright install chromium     # screenshots + PDF
cp .env.example .env
uvicorn app.api:app --host 0.0.0.0 --port 8000
```

### Verify the engine

```bash
python tests/test_engine.py
```

Spins up a demo site seeded with 24 known SEO faults and asserts every one is caught.

---

## Using it

### Dashboard

`http://localhost:8000` — enter a URL, watch live progress, see the five stats, open the report, download the PDF. "Queue a list of URLs" takes a pasted list and queues them all, which is how you feed it 500 sites.

### API

Auth: `X-API-Key: <key>` header, or `?api_key=` for links you want to click. OpenAPI schema at `/openapi.json`, interactive docs at `/docs`.

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/audits` | Queue an audit → returns `audit_id` and every result URL |
| `POST` | `/audits/sync` | Run and wait (60–180s) — for tools that can't poll |
| `GET` | `/audits/{id}` | Status, progress %, current stage, headline scores |
| `GET` | `/audits/{id}/result` | Full JSON |
| `GET` | `/audits/{id}/issues?severity=critical&category=on_page` | Filtered issues |
| `GET` | `/audits/{id}/report.html` | Rendered report |
| `GET` | `/audits/{id}/report.pdf` | PDF download |
| `GET` | `/audits/{id}/llms.txt` | Generated llms.txt |
| `GET` | `/audits` | List audits (filter by `status`, `domain`, `client_ref`) |
| `DELETE` | `/audits/{id}` | Delete audit + artefacts |
| `GET` | `/share/{token}` | **Public report — no key needed**, safe to send a client |
| `GET` | `/share/{token}/pdf` | Public PDF download |
| `GET` | `/stats` | Throughput, quota, queue depth |
| `GET` | `/config` | Which providers are connected |

Request body:

```json
{
  "url": "https://clientsite.com",
  "max_pages": 10,
  "target_keywords": ["outstation cab delhi"],   // optional; auto-detected if omitted
  "competitors": ["rival.com"],                  // optional; auto-researched if omitted
  "include_competitors": true,
  "include_screenshots": true,
  "webhook_url": "https://your-app/hooks/seo",   // POSTed the summary when finished
  "client_ref": "crm-1234"                       // echoed back on every response
}
```

Poll pattern:

```bash
ID=$(curl -s -X POST http://localhost:8000/audits -H "X-API-Key: k" \
  -H "Content-Type: application/json" -d '{"url":"https://example.com"}' | jq -r .audit_id)

curl -s "http://localhost:8000/audits/$ID?api_key=k" | jq '{status, progress, stage, scores}'
curl -sL "http://localhost:8000/audits/$ID/report.pdf?api_key=k" -o report.pdf
```

### CLI

```bash
python -m app.cli audit https://example.com --pages 10 --pdf
python -m app.cli batch clients.txt --concurrency 3 --csv summary.csv
python -m app.cli serve
```

`batch` takes one URL per line and writes a CSV of every score — the fastest way to audit a client list overnight.

### Integrations

- **Any tool** — the OpenAPI schema at `/openapi.json` imports directly into Zapier, Make, n8n, Retool, Postman and most internal tools.
- **Webhooks** — pass `webhook_url` and the agent POSTs the summary (scores, issue counts, report links) the moment an audit finishes. No polling.
- **Claude / Cursor / any MCP client** — `integrations/mcp_server.py` exposes `run_seo_audit`, `get_audit_result`, `list_recent_audits` and `agent_stats` as MCP tools:
  ```bash
  pip install "mcp[cli]"
  SEO_AGENT_URL=http://localhost:8000 SEO_AGENT_KEY=your-key python integrations/mcp_server.py
  ```
- **Spreadsheets / CRM** — `client_ref` on the request comes back on every response and in `/audits?client_ref=`, so results map straight onto your own records.

---

## Configuration

All via environment variables (see `.env.example`).

| Variable | Default | Notes |
|---|---|---|
| `API_KEYS` | `demo-key` | Comma-separated. Change this before exposing the service. |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | Used to build share links and screenshot URLs |
| `MAX_PAGES` | `10` | Default crawl size; override per request |
| `WORKER_COUNT` | `4` | Concurrent audits |
| `DAILY_AUDIT_QUOTA` | `500` | Returns HTTP 429 once reached |
| `AUDIT_TIMEOUT_SEC` | `600` | Hard stop per audit |
| `PER_HOST_DELAY_MS` | `250` | Politeness delay between requests to the same host |
| `RESPECT_ROBOTS` | `true` | Honour robots.txt while crawling |
| `SCREENSHOTS_ENABLED` / `SCREENSHOT_MAX` | `true` / `12` | Turn off to roughly halve audit time |
| `DATABASE_URL` | SQLite in `DATA_DIR` | Point at Postgres for high volume |
| `STATELESS` | `false` | `true` = store nothing; use `POST /audit.pdf` |
| `REQUIRE_AUTH` | `true` | `false` = open public link, no API key needed |
| `RATE_LIMIT_PER_HOUR` | `5` | Per-IP cap, only enforced on public links |
| `PUBLIC_MAX_PAGES` | `8` | Crawl cap for public visitors |
| `REPORT_CACHE_MINUTES` | `30` | How long an in-memory report stays downloadable |

**Optional providers.** Every one of these upgrades a section from *estimate* to *measured*; none is required.

| Key | Unlocks |
|---|---|
| `PAGESPEED_API_KEY` | Real Core Web Vitals field data + Lighthouse opportunities (free from Google) |
| `SERPER_API_KEY` *or* `GOOGLE_API_KEY` + `GOOGLE_CSE_ID` | Competitor discovery from live Google results |
| `ANTHROPIC_API_KEY` | LLM-assisted service/keyword detection, written executive summary, live "does AI cite this brand" check, competitor discovery fallback |
| `OPENPAGERANK_API_KEY` or `DATAFORSEO_LOGIN`/`PASSWORD` | Real backlink and domain-rating data |

Without them the audit still runs end to end — it just labels those numbers as estimates rather than inventing figures.

---

## Running 500 audits a day

- Roughly 60–180 seconds per audit with screenshots on; 4 workers clears ~1,500/day of headroom.
- The queue lives in the database, so a restart re-queues anything mid-flight.
- Scale by raising `WORKER_COUNT` (CPU-bound on Chromium) or running several containers against one Postgres.
- Set `SCREENSHOTS_ENABLED=false` for bulk prospecting runs and back on for client deliverables.
- `GET /stats` exposes queue depth and quota use for your own monitoring.
- Reports and screenshots live in `DATA_DIR` — mount it on a volume and prune old audits with `DELETE /audits/{id}`.

## Layout

```
app/
  crawler.py          robots, sitemap, llms.txt, BFS crawl, link status checks
  parser.py           one-pass HTML → PageData
  issues.py           the issue catalogue (problem/why/impact/fix/benefit)
  checks/
    technical.py      site files, indexability, canonicals, links, architecture
    onpage.py         titles, meta, headings, images
    content.py        thin + duplicate content, FAQ, trust pages
    schema_check.py   structured data
    keywords.py       service detection + per-page keyword placement
    ai_visibility.py  GEO scoring + llms.txt generation
    pagespeed.py      PSI → headless Chrome → crawl-timing estimate
    backlinks.py      authority providers + on-site estimate
    competitors.py    discovery, profiling, gap analysis
    local_cro.py      NAP, local keywords, CTAs
  scoring.py          the five headline stats + overall grade
  screenshots.py      element-highlighted evidence capture
  audit.py            orchestrator
  report/             HTML template + PDF (Chromium → WeasyPrint → ReportLab)
  api.py              REST API + share links
  worker.py           queue, workers, quota, webhooks
  cli.py              audit / batch / serve
  static/             dashboard
integrations/         MCP server
tests/                demo site + end-to-end assertions
```

## Honest limits

- Backlink, ranking and Search Console history need data only you or a paid API can supply. The agent labels every estimate rather than guessing a number.
- The crawl samples the pages you ask for, not the whole site — findings describe the sample.
- Competitor discovery is only as good as the query it builds from the site's own services and location; pass `competitors` explicitly when you already know them.
- Field Core Web Vitals require enough real traffic for Google to hold CrUX data; without it the report shows lab numbers and says so.
