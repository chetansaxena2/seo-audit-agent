# START HERE — Get your SEO agent live (no coding)

Follow these in order. Do not skip. Total time: about 25 minutes, most of it waiting.

At the end you get a web link like `https://yourname-seo-audit-agent.hf.space` that
anyone can open, paste a website into, and download a PDF report with red-marked
screenshots of the errors.

---

## PART 1 — Get the folder ready (2 minutes)

**1.1** Download the `seo-audit-agent` folder (it arrives as a ZIP file).

**1.2** Right-click the ZIP → **Extract All** (Windows) or double-click it (Mac).

**1.3** Open the extracted folder. You should see these inside:

```
app          deploy       examples     tests
Dockerfile   README.md    requirements.txt
```

If you see those, you are good. If you only see one folder inside another folder,
go deeper until you see the list above.

---

## PART 2 — Put it on GitHub (5 minutes)

GitHub stores your code. It cannot run the agent by itself — Part 3 does that.

**2.1** Go to **github.com** → click **Sign up** → create a free account.

**2.2** Log in. Look at the **top-right corner**. Click the **+** symbol → **New repository**.

**2.3** On that page:
- **Repository name:** type `seo-audit-agent`
- Select **Public**
- Do **NOT** tick "Add a README file"
- Click the green **Create repository**

**2.4** The next page shows some blue links in a sentence. Click **uploading an existing file**.

**2.5** Open your extracted folder on your computer. Select **everything inside it**
(press Ctrl+A on Windows, Cmd+A on Mac) and **drag it all** into the grey box on GitHub.

> Drag what is INSIDE the folder, not the folder itself.

**2.6** Wait until every file finishes uploading and appears in a list.

**2.7** Scroll to the bottom → click the green **Commit changes**.

**2.8** Write down your GitHub username. You need it in Part 3.

---

## PART 3 — Make it live on Hugging Face (10 minutes, mostly waiting)

Hugging Face runs the agent for free and has enough memory for the screenshots.

**3.1** Go to **huggingface.co** → **Sign Up** → free account, no card needed.

**3.2** Click your **profile picture (top right)** → **New Space**.

**3.3** Fill in the form:
- **Space name:** `seo-audit-agent`
- **License:** MIT
- **Select the Space SDK:** click **Docker**, then choose **Blank**
- **Space hardware:** CPU basic · FREE
- Select **Public**
- Click **Create Space**

**3.4** On your new Space page, click the **Files** tab at the top.

**3.5** Click **+ Add file** → **Create a new file**.

**3.6** In the **Name your file** box type exactly this (capital D, nothing after it):

```
Dockerfile
```

**3.7** Now open this file from your downloaded folder:

```
deploy → huggingface → Dockerfile
```

Open it with Notepad (Windows) or TextEdit (Mac). Select all, copy, and paste it into
the big empty box on the Hugging Face page.

**3.8** Find this line near the top of what you pasted:

```
ARG GITHUB_REPO=https://github.com/YOUR-GITHUB-USERNAME/seo-audit-agent.git
```

Replace **YOUR-GITHUB-USERNAME** with your real GitHub username from step 2.8.
Change nothing else.

**3.9** Scroll to the bottom → click **Commit new file to main**.

**3.10** Click the **App** tab. It says *Building*. **Wait 8–10 minutes.** It is downloading
a browser. Go do something else.

**3.11** When it says **Running**, your live link is:

```
https://YOUR-HUGGINGFACE-USERNAME-seo-audit-agent.hf.space
```

Open it. You should see a page saying "Paste a website. Get the full audit."

---

## PART 4 — Use it

**4.1** Open your link.

**4.2** Type a website address, e.g. `https://cabrentalhub.in`

**4.3** Click **Run free audit**.

**4.4** Wait about 90 seconds. Do not close the tab.

**4.5** Click **Download PDF report**.

The PDF contains the scores, every issue with how to fix it, and screenshots where the
error is circled in red with an arrow pointing at it.

Share your link with anyone. It works for them the same way.

---

## PART 5 — If something goes wrong

| What you see | What to do |
|---|---|
| Build failed: `Repository not found` | The username in step 3.8 is wrong, or your GitHub repo is Private. Fix: GitHub repo → **Settings** → scroll to the bottom → **Change visibility** → **Public**. |
| Build failed: mentions `requirements.txt` | Some files did not upload. Check your GitHub page shows an `app` folder and a `requirements.txt` file. Re-upload anything missing. |
| Page says "Sleeping" | Nobody used it for ~48 hours. Click **Restart this Space**, or just wait 30 seconds after opening the link. |
| Audit fails or takes forever | Space → **Settings** → **Variables and secrets** → **New variable** → name `PUBLIC_MAX_PAGES`, value `5`. |
| "Rate limit reached" | You ran 3 audits within an hour. Add a variable `RATE_LIMIT_PER_HOUR` with value `10`. |

**To change any setting later:** Space → **Settings** → **Variables and secrets** → **New variable**.
The Space restarts by itself.

**To update the agent later:** upload the new files to GitHub the same way as Part 2, then in
your Space click **Settings** → **Factory rebuild**.

---

## What you can add later (all optional, all free)

Add these in **Settings → Variables and secrets → New secret**:

| Secret name | Where to get it | What improves |
|---|---|---|
| `PAGESPEED_API_KEY` | console.cloud.google.com → enable "PageSpeed Insights API" → create key | Real Google speed scores instead of estimates |
| `SERPER_API_KEY` | serper.dev → free signup | The competitor section actually finds 3 competitors |
| `ANTHROPIC_API_KEY` | console.anthropic.com | A written expert summary at the top of the report |

Nothing breaks without them — those sections just say "estimate" instead of showing
measured numbers.
