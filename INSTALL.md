# SEO Audit Agent — Installation Guide

Paste a website URL, get a full SEO audit with a downloadable report.
No coding needed. About 15 minutes, most of it waiting for the installer.

---

## What you need

- A Windows PC or Mac
- Internet connection
- About 2 GB free disk space
- **No credit card. No account. No coding.**

---

# WINDOWS

## Step 1 — Install Python (5 minutes, one time only)

1. Go to **https://www.python.org/downloads/release/python-3129/**
2. Scroll to the bottom of the page
3. Click **Windows installer (64-bit)**
4. Open the downloaded file
5. ⚠️ **IMPORTANT:** On the first screen, tick the box at the bottom that says
   **"Add python.exe to PATH"**. If you miss this, nothing will work.
6. Click **Install Now**
7. When it finishes, click **Close**

> **Why version 3.12 and not the newest?** Newer versions like 3.13/3.14 are too fresh —
> some components have no build for them yet and the install fails.

## Step 2 — Unpack the agent (1 minute)

1. Right-click **seo-audit-agent.zip**
2. Click **Extract All…**
3. Click **Extract**
4. Open the folder that appears — it is called `seo-audit-agent`

## Step 3 — Start it (first run: 5–8 minutes)

1. Inside that folder, find the file **`start-windows.bat`**
2. **Double-click it**
3. A black window opens and starts installing. Leave it alone and wait.
4. Windows may show "Windows protected your PC" → click **More info** → **Run anyway**
5. When you see this, it is ready:

```
Open your browser at:  http://localhost:8000
```

> Every time after this, it starts in about 5 seconds.

## Step 4 — Run your first audit

1. Open Chrome and go to **http://localhost:8000**
2. Type a website address, for example `https://example.com`
3. Click **Run free audit**
4. Wait 30–90 seconds. Do not close the black window.
5. Click **Download report (HTML)**

The downloaded file opens in any browser and can be emailed as-is — the screenshots are
stored inside the file itself.

## Step 5 — Stopping and restarting

- **To stop:** close the black window, or press **Ctrl+C** inside it
- **To start again:** double-click `start-windows.bat`

---

# MAC

1. Install Python 3.12 from **https://www.python.org/downloads/release/python-3129/**
   (choose **macOS 64-bit universal2 installer**)
2. Double-click **seo-audit-agent.zip** to unpack it
3. Open **Terminal** (press Cmd+Space, type "terminal", press Enter)
4. Type `cd ` (with a space after it), then drag the `seo-audit-agent` folder into the
   Terminal window, then press Enter
5. Type this and press Enter:

```
bash start-mac-linux.sh
```

6. Open **http://localhost:8000** in your browser

---

# If something goes wrong

| What you see | What it means | Fix |
|---|---|---|
| `Python is not installed` | PATH box was not ticked | Reinstall Python, tick **Add python.exe to PATH** |
| `No module named uvicorn` | Install did not finish | Delete the `.venv` folder, run `start-windows.bat` again |
| `Install failed... Python 3.14 is too new` | Wrong Python version | Install Python 3.12 (Step 1), delete `.venv`, run again |
| Browser download failed | Firewall blocked it | Not fatal — reports still work, just without screenshots |
| Page does not open | Agent not running | The black window must stay open while you use it |
| `Port 8000 already in use` | Already running | Check for another black window, or restart your PC |
| Audit says "Could not finish" | Site blocked the crawler | Try a different website first, e.g. `https://example.com` |

---

# Optional: make the reports better (free)

Open the file **`.env`** in the project folder with Notepad. Find these lines near the
bottom, remove the `#`, and paste your key after the `=`:

| Key | Get it from | What it adds |
|---|---|---|
| `SERPER_API_KEY` | serper.dev — free signup, 2 minutes | Finds and compares 3 real competitors |
| `PAGESPEED_API_KEY` | console.cloud.google.com → enable "PageSpeed Insights API" → create key | Real Google speed scores instead of estimates |
| `ANTHROPIC_API_KEY` | console.anthropic.com | Adds a written expert summary at the top |

Save the file and restart the agent. Nothing breaks without these — those sections simply
say "estimate" instead.

Other settings you can change in `.env`:

| Setting | Meaning |
|---|---|
| `MAX_PAGES=10` | How many pages to crawl per audit |
| `SCREENSHOTS_ENABLED=true` | Red-boxed screenshots in the report |
| `PDF_ENABLED=true` | Also produce a PDF |
| `COMPETITORS_ENABLED=true` | Research competitors |

---

# Putting it online (optional)

The laptop version is best for real client reports. If you also want a public link anyone
can use, see **deploy/DEPLOY.md**. Short version: put the code on GitHub, then deploy free
on Render. Note that free hosting has too little memory for screenshots — those work on
your laptop or on a paid server.

---

# What each file in the folder does

| File / folder | What it is |
|---|---|
| `start-windows.bat` | Double-click this to run the agent on Windows |
| `start-mac-linux.sh` | Same, for Mac and Linux |
| `.env` | Your settings — edit with Notepad |
| `app/` | The agent itself (do not edit) |
| `examples/` | Two sample reports so you can see the output |
| `deploy/` | Files for putting it online |
| `README.md` | Full technical documentation |
| `INSTALL.md` | This guide |
