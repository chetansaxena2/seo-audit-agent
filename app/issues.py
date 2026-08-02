"""Issue catalogue.

Every check in the engine emits an issue code from this catalogue. The
catalogue carries the five client-facing fields a consultant-grade audit
needs (problem, why it matters, impact, fix, expected benefit) so findings
stay consistent across audits and are ready to hand to a client.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

CRITICAL, HIGH, MEDIUM, LOW = "critical", "high", "medium", "low"

SEVERITY_WEIGHT = {CRITICAL: 12.0, HIGH: 6.0, MEDIUM: 2.5, LOW: 0.8}
SEVERITY_ORDER = {CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3}

# category -> which score the issue drags down
TECHNICAL, ONPAGE, CONTENT, SCHEMA, AI, SPEED, AUTHORITY, LOCAL, CRO = (
    "technical",
    "on_page",
    "content",
    "schema",
    "ai_search",
    "speed",
    "authority",
    "local",
    "cro",
)


@dataclass(frozen=True)
class IssueSpec:
    code: str
    title: str
    category: str
    severity: str
    why: str
    fix: str
    benefit: str
    screenshot: bool = False  # capture visual evidence for this issue


def _s(*args: Any, **kw: Any) -> IssueSpec:
    return IssueSpec(*args, **kw)


CATALOG: dict[str, IssueSpec] = {s.code: s for s in [
    # ---------------------------------------------------------------- technical
    _s("ROBOTS_MISSING", "robots.txt is missing", TECHNICAL, HIGH,
       "Without robots.txt, search engines get no crawl directives and you cannot point them at your sitemap.",
       "Publish /robots.txt with crawl rules and a Sitemap: line pointing at your XML sitemap.",
       "Cleaner crawling and faster discovery of new pages."),
    _s("ROBOTS_BLOCKS_SITE", "robots.txt blocks search engines from the site", TECHNICAL, CRITICAL,
       "A site-wide Disallow stops Google crawling the site at all, which removes it from search results.",
       "Remove the blanket Disallow: / rule for Googlebot and re-submit the site in Search Console.",
       "Restores indexing and organic visibility."),
    _s("ROBOTS_NO_SITEMAP", "robots.txt does not reference the sitemap", TECHNICAL, LOW,
       "The Sitemap directive is the cheapest way to hand crawlers a complete URL list.",
       "Add a line: Sitemap: https://yourdomain.com/sitemap.xml",
       "Faster discovery and re-crawl of updated pages."),
    _s("SITEMAP_MISSING", "XML sitemap is missing", TECHNICAL, HIGH,
       "Without a sitemap, crawlers rely purely on internal links, so deep or new pages get found late or not at all.",
       "Generate /sitemap.xml with all indexable URLs, reference it in robots.txt and submit it in Search Console.",
       "Faster and more complete indexing."),
    _s("SITEMAP_ERRORS", "Sitemap contains URLs that do not return 200", TECHNICAL, MEDIUM,
       "Broken or redirected sitemap entries waste crawl budget and signal a stale sitemap.",
       "Regenerate the sitemap so it lists only live, canonical, indexable URLs.",
       "Better crawl efficiency and cleaner Search Console coverage reports."),
    _s("HTTPS_MISSING", "Site is not served over HTTPS", TECHNICAL, CRITICAL,
       "HTTPS is a ranking signal and browsers warn users on insecure forms, which kills conversions.",
       "Install a TLS certificate and 301-redirect all HTTP URLs to HTTPS.",
       "Removes browser warnings, protects rankings and conversion rate."),
    _s("HTTP_NOT_REDIRECTED", "HTTP version does not redirect to HTTPS", TECHNICAL, HIGH,
       "Two accessible protocols create duplicate URLs and split link equity.",
       "Add a server-level 301 from http:// to https:// for every URL.",
       "Consolidates ranking signals onto one URL set."),
    _s("WWW_DUPLICATE", "www and non-www both resolve without redirecting", TECHNICAL, MEDIUM,
       "Duplicate hostnames dilute authority and can cause inconsistent indexing.",
       "Pick one canonical hostname and 301-redirect the other.",
       "Consolidated authority on a single hostname."),
    _s("PAGE_4XX", "Page returns a 4xx error", TECHNICAL, CRITICAL,
       "Users and crawlers hit a dead end; any links pointing there are wasted.",
       "Restore the page or 301-redirect it to the closest relevant live URL.",
       "Recovers lost traffic and link equity."),
    _s("PAGE_5XX", "Page returns a server error", TECHNICAL, CRITICAL,
       "Repeated 5xx responses cause Google to slow crawling and eventually drop pages.",
       "Investigate server logs, fix the failing route, and monitor uptime.",
       "Stops de-indexing and restores crawl rate."),
    _s("BROKEN_INTERNAL_LINK", "Broken internal links", TECHNICAL, HIGH,
       "Internal 404s break crawl paths and frustrate users mid-journey.",
       "Update or remove the broken hrefs, or redirect the target URLs.",
       "Better crawl flow, lower bounce, recovered link equity.", screenshot=True),
    _s("BROKEN_EXTERNAL_LINK", "Broken outbound links", TECHNICAL, LOW,
       "Dead outbound links are a quality signal and a poor user experience.",
       "Replace with a live source or remove the link.",
       "Improves perceived content quality and trust."),
    _s("REDIRECT_CHAIN", "Redirect chains detected", TECHNICAL, MEDIUM,
       "Each extra hop loses a little equity and adds latency for users and crawlers.",
       "Point the first URL directly at the final destination in one 301.",
       "Faster page loads and cleaner equity flow."),
    _s("NOINDEX", "Page is set to noindex", TECHNICAL, CRITICAL,
       "A noindex tag removes the page from Google entirely, however good the content is.",
       "Remove the noindex directive from the meta robots tag or X-Robots-Tag header.",
       "Page becomes eligible to rank again.", screenshot=True),
    _s("CANONICAL_MISSING", "Canonical tag missing", TECHNICAL, MEDIUM,
       "Without a canonical, parameter and duplicate URLs can be indexed instead of the page you want.",
       "Add a self-referencing <link rel=\"canonical\"> to every indexable page.",
       "Prevents duplicate-content dilution."),
    _s("CANONICAL_CONFLICT", "Canonical points to a different page", TECHNICAL, HIGH,
       "A cross-canonical tells Google to ignore this page and rank another one instead.",
       "Point the canonical at the page's own URL unless the duplication is intentional.",
       "Page regains its own ranking ability.", screenshot=True),
    _s("VIEWPORT_MISSING", "Mobile viewport meta tag missing", TECHNICAL, HIGH,
       "Without a viewport tag pages render desktop-width on phones and fail mobile usability.",
       "Add <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">.",
       "Mobile usability pass and better mobile rankings."),
    _s("LANG_MISSING", "html lang attribute missing", TECHNICAL, LOW,
       "Language declaration helps search engines and screen readers serve the right audience.",
       "Add lang=\"en\" (or your locale) to the <html> element.",
       "Cleaner internationalisation and accessibility signals."),
    _s("DEEP_PAGE", "Important pages are more than 3 clicks deep", TECHNICAL, MEDIUM,
       "Deep pages get crawled less and receive less internal link equity.",
       "Link key pages from the main navigation, hub pages, or footer.",
       "More crawl attention and stronger rankings for money pages."),
    _s("ORPHAN_PAGE", "Sitemap URLs with no internal links pointing to them", TECHNICAL, MEDIUM,
       "Orphan pages rely on the sitemap alone and rarely accumulate authority.",
       "Add contextual internal links from related pages.",
       "Improved indexation and keyword strength."),

    # ---------------------------------------------------------------- on-page
    _s("TITLE_MISSING", "Title tag missing", ONPAGE, CRITICAL,
       "The title is the single strongest on-page ranking element and the clickable line in search results.",
       "Write a unique 50-60 character title containing the primary keyword.",
       "Direct ranking and click-through improvement.", screenshot=True),
    _s("TITLE_TOO_LONG", "Title tag longer than 60 characters", ONPAGE, MEDIUM,
       "Google truncates long titles, so the keyword and value proposition can be cut off.",
       "Trim to 50-60 characters, keyword first, brand last.",
       "Higher click-through rate from search.", screenshot=True),
    _s("TITLE_TOO_SHORT", "Title tag under 30 characters", ONPAGE, LOW,
       "Short titles waste prime keyword real estate.",
       "Expand to 50-60 characters with the primary keyword plus a qualifier or location.",
       "More keyword coverage and better CTR."),
    _s("TITLE_DUPLICATE", "Duplicate title tags across pages", ONPAGE, HIGH,
       "Identical titles make pages look interchangeable and cause keyword cannibalisation.",
       "Write a distinct, page-specific title for each URL.",
       "Removes cannibalisation and clarifies page targeting."),
    _s("TITLE_NO_KEYWORD", "Title does not contain a target keyword", ONPAGE, HIGH,
       "Google reads the title first when matching a page to a query.",
       "Place the page's primary keyword in the first half of the title.",
       "Stronger relevance for the target query."),
    _s("META_MISSING", "Meta description missing", ONPAGE, HIGH,
       "Google writes its own snippet, which often ignores your offer and hurts click-through.",
       "Write a 140-160 character description with the keyword and a call to action.",
       "Higher CTR from the same ranking position.", screenshot=True),
    _s("META_TOO_LONG", "Meta description longer than 160 characters", ONPAGE, MEDIUM,
       "Anything past ~160 characters is cut off, so the call to action disappears.",
       "Rewrite to 140-160 characters with the keyword early.",
       "Complete, persuasive snippet in search results.", screenshot=True),
    _s("META_TOO_SHORT", "Meta description under 70 characters", ONPAGE, LOW,
       "Very short descriptions leave persuasive space unused.",
       "Expand to 140-160 characters covering benefit, keyword and CTA.",
       "Better snippet quality and CTR."),
    _s("META_DUPLICATE", "Duplicate meta descriptions", ONPAGE, MEDIUM,
       "Repeated descriptions signal templated, low-effort pages.",
       "Write unique descriptions per page.",
       "Improves CTR and perceived page quality."),
    _s("META_NO_KEYWORD", "Meta description has no target keyword", ONPAGE, MEDIUM,
       "Keywords in the description are bolded in results, which lifts click-through.",
       "Work the primary keyword naturally into the first sentence.",
       "Better CTR and query relevance."),
    _s("H1_MISSING", "H1 heading missing", ONPAGE, HIGH,
       "The H1 tells users and crawlers what the page is about in one line.",
       "Add exactly one H1 containing the primary keyword, under 60 characters.",
       "Clearer topical relevance.", screenshot=True),
    _s("H1_MULTIPLE", "Multiple H1 tags on one page", ONPAGE, MEDIUM,
       "Several H1s split the page's topical focus and confuse heading hierarchy.",
       "Keep one H1 and demote the rest to H2.",
       "Sharper topical focus per page.", screenshot=True),
    _s("H1_TOO_LONG", "H1 longer than 60 characters", ONPAGE, LOW,
       "Long headings dilute the keyword and read poorly on mobile.",
       "Tighten the H1 to under 60 characters, keyword first.",
       "Stronger keyword signal and better scanability."),
    _s("H1_NO_KEYWORD", "H1 does not contain a target keyword", ONPAGE, MEDIUM,
       "The H1 is a primary relevance signal for the page's main query.",
       "Rewrite the H1 around the page's primary keyword.",
       "Improved ranking for the target term."),
    _s("H1_DUPLICATE", "Same H1 used on multiple pages", ONPAGE, MEDIUM,
       "Duplicate H1s make pages compete with each other for the same query.",
       "Give each page a unique H1 matched to its own keyword.",
       "Removes internal competition."),
    _s("HEADING_NO_KEYWORD", "Subheadings (H2/H3) never use target keywords", ONPAGE, MEDIUM,
       "Subheadings map the page's subtopics; keyword-free headings weaken semantic coverage.",
       "Work primary and secondary keywords into two or three H2/H3 headings.",
       "Better topical depth and featured-snippet eligibility."),
    _s("HEADING_HIERARCHY", "Heading levels skip (e.g. H2 to H4)", ONPAGE, LOW,
       "Broken hierarchy hurts accessibility and machine parsing of the page structure.",
       "Use sequential heading levels without skipping.",
       "Cleaner structure for crawlers and screen readers."),
    _s("IMG_ALT_MISSING", "Images missing alt text", ONPAGE, HIGH,
       "Alt text is required for accessibility and is how images earn image-search traffic.",
       "Add descriptive alt text (5-12 words) to every meaningful image; leave decorative images alt=\"\".",
       "Image search traffic plus accessibility compliance.", screenshot=True),
    _s("IMG_TITLE_MISSING", "Images missing title attribute", ONPAGE, LOW,
       "Title attributes add hover context and a small extra relevance signal.",
       "Add a short title attribute to key content images.",
       "Marginal relevance and UX gain."),
    _s("IMG_FILENAME_GENERIC", "Generic image filenames (IMG_1234.jpg)", ONPAGE, LOW,
       "Descriptive filenames help image search understand the picture.",
       "Rename files to keyword-descriptive slugs before upload.",
       "Better image search visibility."),
    _s("IMG_HEAVY", "Oversized images slowing the page", SPEED, MEDIUM,
       "Large images are the most common cause of slow LCP on content sites.",
       "Compress, resize to display dimensions and serve WebP/AVIF with lazy loading.",
       "Faster LCP and better Core Web Vitals."),
    _s("IMG_NO_DIMENSIONS", "Images without width/height attributes", SPEED, LOW,
       "Missing dimensions cause layout shift as images load, hurting CLS.",
       "Set explicit width and height (or CSS aspect-ratio) on images.",
       "Lower CLS score."),

    # ---------------------------------------------------------------- content
    _s("THIN_CONTENT", "Thin content (under 300 words)", CONTENT, HIGH,
       "Thin pages rarely satisfy search intent and struggle to rank for competitive terms.",
       "Expand to 700+ words covering the questions searchers actually ask, with proof and examples.",
       "Higher rankings and more long-tail coverage."),
    _s("DUPLICATE_CONTENT", "Near-duplicate content between pages", CONTENT, HIGH,
       "Duplicate bodies force Google to pick one page and suppress the others.",
       "Rewrite the overlapping sections so each page has a distinct angle, or consolidate and redirect.",
       "Removes cannibalisation, concentrates authority."),
    _s("KEYWORD_MISSING_ONPAGE", "Target keywords barely used on the page", CONTENT, HIGH,
       "If the service keyword is absent from copy, Google has little to match against the query.",
       "Work the primary and two secondary keywords into the intro, one H2, and the body naturally.",
       "Directly improves keyword relevance and rankings."),
    _s("KEYWORD_STUFFING", "Keyword density unnaturally high", CONTENT, MEDIUM,
       "Over-repetition reads as spam and can trigger quality demotions.",
       "Reduce exact-match repetition; use synonyms and natural variants.",
       "Avoids spam signals while keeping relevance."),
    _s("NO_FAQ_CONTENT", "No FAQ or question-led content", CONTENT, MEDIUM,
       "Question-led blocks are what AI answers and featured snippets quote.",
       "Add 5-8 real customer questions with direct 40-60 word answers.",
       "Snippet and AI-answer eligibility."),
    _s("NO_INTERNAL_LINKS", "Page has almost no internal links", CONTENT, MEDIUM,
       "Internal links pass authority and tell Google which pages matter.",
       "Add 3-5 contextual links to related service or money pages.",
       "Better crawl depth and stronger money-page rankings."),
    _s("MISSING_SERVICE_PAGE", "No dedicated page for a service you offer", CONTENT, HIGH,
       "One page cannot rank for every service; each service needs its own targeted page.",
       "Create a dedicated, keyword-targeted page per service with local modifiers.",
       "Opens a new ranking surface per service."),
    _s("NO_TRUST_PAGES", "Missing about / contact / policy pages", CONTENT, MEDIUM,
       "These pages are core E-E-A-T signals Google uses to judge trustworthiness.",
       "Publish detailed About, Contact, Privacy and Terms pages with real business details.",
       "Stronger E-E-A-T and conversion trust."),

    # ---------------------------------------------------------------- schema
    _s("SCHEMA_MISSING", "No structured data on the page", SCHEMA, HIGH,
       "Schema is how machines read your entity, services and offers; without it you lose rich results and AI citations.",
       "Add JSON-LD for Organization or LocalBusiness plus page-type schema (Service, Article, Product).",
       "Rich results eligibility and better AI/entity understanding.", screenshot=True),
    _s("SCHEMA_FAQ_MISSING", "FAQPage schema not implemented", SCHEMA, MEDIUM,
       "FAQ schema makes your answers machine-readable for AI answers and SERP features.",
       "Add FAQPage JSON-LD matching visible on-page Q&A content.",
       "AI-answer and rich-result eligibility."),
    _s("SCHEMA_ORG_MISSING", "Organization / LocalBusiness schema missing", SCHEMA, HIGH,
       "Entity schema is the foundation of Knowledge Graph and local pack understanding.",
       "Add LocalBusiness (or Organization) JSON-LD with name, address, phone, hours, sameAs profiles.",
       "Stronger entity recognition and local visibility."),
    _s("SCHEMA_BREADCRUMB_MISSING", "BreadcrumbList schema missing", SCHEMA, LOW,
       "Breadcrumb markup improves how the URL line renders in results.",
       "Add BreadcrumbList JSON-LD reflecting the site hierarchy.",
       "Cleaner SERP presentation."),
    _s("SCHEMA_INVALID", "Structured data has syntax errors", SCHEMA, MEDIUM,
       "Invalid JSON-LD is ignored entirely, so you get none of the benefit.",
       "Fix the JSON syntax and validate in Google's Rich Results Test.",
       "Restores rich-result eligibility."),

    # ---------------------------------------------------------------- AI / GEO
    _s("LLMS_TXT_MISSING", "llms.txt is missing", AI, MEDIUM,
       "llms.txt is the emerging standard for telling AI assistants what your site offers and which pages to read.",
       "Publish /llms.txt with a short business summary, key service URLs and contact details.",
       "Better representation in ChatGPT, Claude and Perplexity answers."),
    _s("AI_BOTS_BLOCKED", "AI crawlers are blocked in robots.txt", AI, HIGH,
       "Blocking GPTBot, ClaudeBot, PerplexityBot or Google-Extended removes you from AI answers entirely.",
       "Allow the AI user-agents you want citations from (keep blocks only where you intend them).",
       "Eligibility to be cited in AI assistants and AI Overviews."),
    _s("AI_NO_ANSWER_BLOCKS", "Content is not written as extractable answers", AI, MEDIUM,
       "AI systems quote self-contained 40-60 word answers under question headings.",
       "Restructure key sections: question heading, direct answer first, detail after.",
       "Much higher chance of being quoted in AI answers."),
    _s("AI_NO_ENTITY_SIGNALS", "Weak entity signals (no sameAs / about / author)", AI, MEDIUM,
       "AI models resolve brands through consistent entity data across the web.",
       "Add sameAs links to your profiles, a detailed About page and named authors with bios.",
       "Stronger brand recognition in AI and Knowledge Graph."),
    _s("AI_NO_FRESHNESS", "No published/updated dates on content", AI, LOW,
       "Perplexity and AI Overviews favour content with visible freshness signals.",
       "Show published and updated dates and mirror them in schema (datePublished/dateModified).",
       "Better inclusion in freshness-sensitive AI answers."),

    # ---------------------------------------------------------------- speed
    _s("SLOW_LCP", "Largest Contentful Paint is slow", SPEED, HIGH,
       "LCP over 2.5s fails Core Web Vitals and correlates with lost conversions.",
       "Optimise the hero image, preload it, cut render-blocking CSS/JS and improve server response.",
       "Passes CWV, better rankings and conversion."),
    _s("SLOW_TTFB", "Server response time is slow", SPEED, MEDIUM,
       "A slow TTFB delays everything else on the page and limits crawl rate.",
       "Add caching/CDN, tune the database and upgrade hosting if needed.",
       "Faster loads across every page."),
    _s("HIGH_CLS", "Layout shifts during load", SPEED, MEDIUM,
       "Content jumping around causes misclicks and fails Core Web Vitals.",
       "Reserve space for images, ads and embeds; avoid injecting content above existing content.",
       "Passes CLS, better usability."),
    _s("PAGE_WEIGHT", "Page weight is heavy", SPEED, MEDIUM,
       "Heavy pages are slow on mobile networks, which is how most users arrive.",
       "Compress images, split bundles, defer non-critical JS and remove unused CSS.",
       "Faster mobile experience and better CWV."),
    _s("RENDER_BLOCKING", "Render-blocking resources in the head", SPEED, MEDIUM,
       "Blocking CSS/JS delays first paint on every page.",
       "Inline critical CSS, defer or async non-critical scripts.",
       "Faster first paint and LCP."),

    # ---------------------------------------------------------------- authority / local / CRO
    _s("LOW_AUTHORITY", "Weak backlink profile", AUTHORITY, HIGH,
       "Links remain a primary ranking factor; a thin profile caps how competitive you can be.",
       "Build citations, digital PR, partner and directory links relevant to your service area.",
       "Higher domain authority and ranking ceiling."),
    _s("NAP_MISSING", "No visible business address or phone", LOCAL, HIGH,
       "Consistent name/address/phone is the backbone of local ranking and trust.",
       "Publish full NAP in the footer and on the contact page, matching your Google Business Profile exactly.",
       "Better local pack visibility."),
    _s("NO_LOCAL_KEYWORDS", "Location keywords not used on key pages", LOCAL, MEDIUM,
       "Local intent queries need the city/area in titles, headings and copy.",
       "Add city and service-area terms to titles, H1s and body copy on service pages.",
       "Improved local rankings."),
    _s("NO_CTA", "No clear call to action above the fold", CRO, MEDIUM,
       "Traffic without a visible next step does not convert.",
       "Add a single prominent primary CTA (call, book, quote) in the hero and repeat it down the page.",
       "Higher conversion rate from existing traffic."),
    _s("NO_PHONE_LINK", "Phone number is not click-to-call", CRO, LOW,
       "Mobile users expect to tap to call; plain text adds friction.",
       "Wrap numbers in <a href=\"tel:...\"> links.",
       "More calls from mobile traffic."),
]}


@dataclass
class Finding:
    """A concrete instance of a catalogue issue."""
    code: str
    url: str | None = None
    detail: str = ""
    evidence: str = ""          # raw snippet / value observed
    selector: str | None = None  # CSS selector for screenshot highlighting
    annotation: str = ""         # label drawn next to the arrow on the screenshot
    code_snippet: str = ""       # real source code shown when nothing is visible
    snippet_mark: str = ""       # part of the snippet to highlight in red
    screenshot: str | None = None  # relative path once captured
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def spec(self) -> IssueSpec:
        return CATALOG[self.code]

    def to_dict(self) -> dict[str, Any]:
        s = self.spec
        return {
            "code": self.code,
            "problem": s.title,
            "category": s.category,
            "impact": s.severity,
            "why_it_matters": s.why,
            "recommended_fix": s.fix,
            "expected_benefit": s.benefit,
            "url": self.url,
            "detail": self.detail,
            "evidence": self.evidence,
            "selector": self.selector,
            "screenshot": self.screenshot,
            **({"extra": self.extra} if self.extra else {}),
        }


def sort_findings(findings: Iterable[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: (SEVERITY_ORDER[f.spec.severity], f.code, f.url or ""))


def group_by_severity(findings: Iterable[Finding]) -> dict[str, list[Finding]]:
    out: dict[str, list[Finding]] = {CRITICAL: [], HIGH: [], MEDIUM: [], LOW: []}
    for f in findings:
        out[f.spec.severity].append(f)
    return out
