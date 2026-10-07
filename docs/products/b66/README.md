# B66 Padiem Quote

~~~text
DOC_STATUS = CURRENT_PRODUCT
OWNER = B66 product
PRODUCT = B66 Padiem Quote
CANONICAL_PRODUCT_PARENT = #3389
TEMPLATE_LIFECYCLE_AUTHORITY = TEMPLATE_LIFECYCLE.md
REPRODUCTION_CERTIFICATION_AUTHORITY = REPRODUCTION_CERTIFICATION.md
~~~

B66 is Padiem's standalone quotation product for businesses that already have quotation formats they use repeatedly. Its primary promise is not to make the user design a new template; it is to learn the business's existing quotation, prove that the learned rendering reproduces it faithfully, and then generate future quotations from new business facts quickly.

## Product boundary

~~~text
B66_PRODUCT_INDEPENDENT = YES
PADIEM_CHAT_REQUIRED_FOR_B66 = NO
PADIEM_CLAW_REQUIRED_FOR_B66 = NO
SHARED_PLATFORM_REUSE = YES
~~~

B66 owns quotation-specific UX, Saved Quote Skill lifecycle, quotation drafts/history, source-derived template onboarding, reproduction certification and quote presentation. It reuses shared Padiem identity/storage/AI authorities and QuoteCore calculation authority rather than creating duplicates.

## User-facing model

The routine user should think in terms of **내 견적서 / Saved Quote Skill**, not internal TemplateProfile/Canonical/renderer terminology.

~~~text
initial onboarding:
existing quotation
-> analyze
-> reproduce
-> compare/certify
-> approve "내 견적서"

repeat use:
new quote facts
-> assigned Saved Quote Skill
-> QuoteDraft
-> QuoteCore
-> certified template
-> Preview / PDF
~~~

An editable XLSX or Google Sheet may also be generated where supported, but it is an output channel, not a mandatory intermediate step for every PDF.

## Canonical documents

- [PRODUCT_CONTRACT.md](PRODUCT_CONTRACT.md) — product promise, ownership and runtime contract.
- [TEMPLATE_LIFECYCLE.md](TEMPLATE_LIFECYCLE.md) — source → analysis → reproduction → certification → execution.
- [REPRODUCTION_CERTIFICATION.md](REPRODUCTION_CERTIFICATION.md) — fidelity evidence and certification states.
- #3180 — Saved Quote Skill epic.
- #3542 — source analysis.
- #3595 — reproduction/certification implementation authority.
- #3574/#3578/#3581/#3584 — CGI renderer/normalization evidence lineage.

## Historical evidence

Completed customer-handoff and earlier fidelity issues remain historical evidence. Adopting the stronger lifecycle does not rewrite a completed handoff or silently claim that old evidence satisfied a later standard.
