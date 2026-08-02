# Put the agent on a live public link (free)

You want a URL anyone can open, type a website into, and get a PDF audit back.

**GitHub Pages cannot do this.** Pages only serves static files — this agent is a Python
server that also runs a headless Chromium browser. GitHub is still where the code lives;
the free host below is what actually runs it.

Recommended: **Hugging Face Spaces** — free, no credit card, generous RAM (Chromium needs
it), and a permanent public URL.

---

## Step 1 — Put the code on GitHub (5 minutes)

```bash
cd seo-audit-agent
git init
git add .
git commit -m "SEO Audit Agent"
```

Create an empty repo on github.com, then:

```bash
git remote add origin https://github.com/YOUR-NAME/seo-audit-agent.git
git branch -M main
git push -u origin main
```

> `.gitignore` already excludes `.env` and `data/`, so no keys or reports get committed.

---

## Step 2a — Deploy on Hugging Face Spaces (best free option)

1. Sign up at **huggingface.co** (free, no card).
2. Click your avatar → **New Space**.
   - **Space name:** `seo-audit-agent`
   - **License:** MIT
   - **Space SDK:** **Docker** → *Blank*
   - **Hardware:** CPU basic (free) · **Visibility:** Public
3. Clone the empty Space and copy the project into it:

```bash
git clone https://huggingface.co/spaces/YOUR-NAME/seo-audit-agent hf-space
cp -r seo-audit-agent/{app,integrations,requirements.txt,Dockerfile} hf-space/
cp seo-audit-agent/deploy/huggingface/README.md hf-space/README.md   # required config header
cd hf-space && git add . && git commit -m "Deploy SEO Audit Agent" && git push
```

4. In the Space → **Settings → Variables and secrets**, add these **variables**:

| Name | Value |
|---|---|
| `STATELESS` | `true` |
| `REQUIRE_AUTH` | `false` |
| `DATA_DIR` | `/tmp/seoagent` |
| `PUBLIC_BASE_URL` | `https://YOUR-NAME-seo-audit-agent.hf.space` |
| `RATE_LIMIT_PER_HOUR` | `3` |
| `PUBLIC_MAX_PAGES` | `8` |

Add any API keys (`PAGESPEED_API_KEY`, `SERPER_API_KEY`, `ANTHROPIC_API_KEY`) as **secrets**,
not variables.

5. Wait for the build (5–8 minutes the first time). Your live link:

```
https://YOUR-NAME-seo-audit-agent.hf.space
```

Share that link with anyone. They paste a URL, wait ~90 seconds, download the PDF.

**Note:** free Spaces sleep after ~48 hours of no visitors and wake on the next request
(first load then takes ~30 seconds).

---

## Step 2b — Deploy on Render (alternative)

1. Sign up at **render.com** with GitHub.
2. **New → Blueprint** → pick your repo. Render reads `deploy/render.yaml` automatically.
   (Or **New → Web Service** → Docker → set the env vars from that file by hand.)
3. Deploy. Your link is `https://seo-audit-agent-XXXX.onrender.com`.

Free-tier caveats worth knowing:
- The instance **sleeps after 15 minutes idle**; the first request afterwards takes ~50 seconds.
- 512 MB RAM is tight for Chromium. If audits fail, set `SCREENSHOTS_ENABLED=false` —
  the PDF still generates via the ReportLab engine, just without screenshots.

---

## Step 2c — Deploy on Fly.io (most control, needs a card for verification)

```bash
curl -L https://fly.io/install.sh | sh
fly auth signup
cp deploy/fly.toml .
fly launch --copy-config --no-deploy      # pick a unique app name
fly deploy
fly open
```

`fly.toml` requests 1 GB RAM (enough for Chromium) and sleeps the machine when idle, which
keeps it inside the free allowance.

---

## Step 3 — Check it works

Open your link. You should see the audit page. Then test the API:

```bash
curl -X POST https://YOUR-LINK/audit.pdf \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com"}' \
  --max-time 300 --output audit.pdf
```

Interactive API docs are at `https://YOUR-LINK/docs`.

---

## Protecting a public link

`REQUIRE_AUTH=false` means anyone can run audits on your instance, which costs CPU. The
agent already limits each visitor with `RATE_LIMIT_PER_HOUR` (default 5). Tune these:

| Variable | Effect |
|---|---|
| `RATE_LIMIT_PER_HOUR` | Audits allowed per IP per hour |
| `PUBLIC_MAX_PAGES` | Caps how many pages a public visitor can crawl |
| `SCREENSHOTS_ENABLED=false` | Roughly halves CPU and memory per audit |
| `COMPETITORS_ENABLED=false` | Skips competitor crawling |
| `REQUIRE_AUTH=true` | Locks it back down to your API keys |

If you flip `REQUIRE_AUTH=true`, the home page switches from the public audit form to the
operator dashboard, and visitors need a key from `API_KEYS`.

---

## Which host should you pick?

| Host | Free? | RAM | Screenshots work? | Sleeps? |
|---|---|---|---|---|
| **Hugging Face Spaces** | Yes, no card | 16 GB | Yes | After ~48h idle |
| **Render** | Yes, no card | 512 MB | Only with screenshots off | After 15 min idle |
| **Fly.io** | Free allowance, card to verify | 1 GB (configurable) | Yes | Configurable |
| **Koyeb** | Yes | 512 MB | No — set `SCREENSHOTS_ENABLED=false` | No |
| **Your own VPS** (₹400/mo+) | No | 2 GB+ | Yes | No |

Start with Hugging Face. Move to a small VPS once you are doing hundreds of audits a day —
free tiers are not built for that kind of sustained CPU use.
