"""Local SEO signals and basic conversion-readiness checks."""
from __future__ import annotations

from .. import textutil as T
from ..crawler import SiteContext
from ..issues import Finding
from ..parser import PageData


def run(ctx: SiteContext, pages: list[PageData], location: str) -> tuple[list[Finding], dict]:
    out: list[Finding] = []
    html_pages = [p for p in pages if p.html and p.ok]
    if not html_pages:
        return out, {}
    home = html_pages[0]
    home_url = home.final_url or home.url

    has_phone = any(p.tel_links or p.phones for p in html_pages)
    has_address = any(
        isinstance(b, dict) and b.get("address") for p in html_pages for b in p.jsonld
    ) or any(T.contains_phrase(p.text[-2500:], location) for p in html_pages if location)
    local_intent = bool(location) or has_phone or any(
        p.has_schema("LocalBusiness", "ProfessionalService", "Store") for p in html_pages)

    if local_intent and not (has_phone and has_address):
        out.append(Finding("NAP_MISSING", url=home_url,
                           detail=("Business phone and/or address is not clearly published "
                                   "on the crawled pages."),
                           evidence=f"phone found: {has_phone}, address found: {has_address}"))
    if local_intent and location:
        missing_local = [p.final_url or p.url for p in html_pages
                         if not T.contains_phrase(f"{p.title} {p.heading_text}", location)]
        if len(missing_local) > len(html_pages) / 2:
            out.append(Finding("NO_LOCAL_KEYWORDS", url=home_url,
                               detail=(f"{len(missing_local)} of {len(html_pages)} pages never "
                                       f"mention '{location}' in the title or headings."),
                               extra={"urls": missing_local[:10]}))

    if not home.cta_texts:
        out.append(Finding("NO_CTA", url=home_url,
                           detail="No obvious call-to-action link or button found on the homepage.",
                           selector="body"))
    if any(p.phones for p in html_pages) and not any(p.tel_links for p in html_pages):
        out.append(Finding("NO_PHONE_LINK", url=home_url,
                           detail="Phone numbers appear as plain text with no tel: link.",
                           evidence="; ".join(home.phones[:2])))

    stats = {
        "local_intent_detected": local_intent,
        "location": location,
        "phone_found": has_phone,
        "address_found": has_address,
        "click_to_call": any(p.tel_links for p in html_pages),
        "cta_examples": T.dedupe_keep_order(
            [c for p in html_pages for c in p.cta_texts])[:8],
        "has_contact_form": any(p.has_form for p in html_pages),
    }
    return out, stats
