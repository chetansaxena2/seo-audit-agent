---
title: SEO Audit Agent
emoji: 🔍
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
short_description: Paste a URL, get a full SEO audit with a downloadable PDF
---

# SEO Audit Agent

Paste a website URL and get a complete SEO audit: technical checks, titles and meta,
headings, images, schema, broken links, duplicate content, AI-search visibility,
page speed and competitors — with a downloadable PDF report.

Nothing is stored. Every audit runs in memory and the report is discarded after 30 minutes.

**API:** `POST /audit.pdf` with `{"url": "https://example.com"}` returns the PDF directly.
Full docs at `/docs`.
