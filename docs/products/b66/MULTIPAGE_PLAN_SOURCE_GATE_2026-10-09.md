# B66 #3839 — source-only multipage plan (2026-10-09)

**DRAFT. PRODUCT_UNLIMITED_ROWS_READY=NO; AUTHENTICATED_E2E=UNVERIFIED; PRODUCTION_RELEASE=NO.**

## Scope / safe boundaries

The selected Sol 6.1 source-derived CGI template is privately certified for
**1–3 rows on one A4 page**. This is a historical certificate, not a permanent
product cap and NOT a multipage certificate. PR #3838 is metadata-only.

The new source-only Python and browser/Node modules share contract
`b66.cgi.dynamic-a4-layout.v1`:

- `apps/b66-pdf-renderer/multipage_plan.py`
- `reference/business-66-padiem-quote-v1/quote-multipage-plan.js`

They partition QuoteCore-derived rows using trusted, **separately certified**
first/continuation A4 layout geometry and injected real-font width measurement.
Each row stays complete; descriptions wrap without truncation; printed item
numbering and row source indices remain consecutive, and only the final
page is flagged to receive totals/terms. They perform **no money arithmetic,
model selection, AI calls, output PDF creation or runtime activation**.

A measured 1 MiB input/body policy replaces a row-count ceiling **in this
planning contract only**; the pre-existing renderers, 3-row admission, 100-row
parser/skill ceilings and production HTTP request caps are deliberately not
altered by this Draft. Downstream generation must also respect the certified
geometry, resource/time bounds and 32 MiB PDF response cap.

## Certification and delivery gates before removing production caps

1. Create a new private versioned Sol multipage certificate and fixed/variable
   element map: maintain logo, seal, fonts, headers, A4 margins and vector
   identity; generate a verified continuation layout and page numbers.
2. Build the actual PDF page painter on the private certified assets. Redact
   superseded source text from PDF content streams rather than merely covering
   it; check extracted text for old recipient/item/amount leakage. Do not use
   the GLM overlay defect.
3. Independently compare rasterized PDF pages with HTML preview, test real font
   wrapping, totals/tax/settlement/terms on last page, row counts, layout overflow,
   1/2/3/4/10/25/100/101+ item boundaries and multiple templates.
4. Integrate feature-gated byte/resource checks through intake, extraction,
   Saved Skills, CGI authenticated routes, Pages/Worker POST, preview,
   PDF download, reopen/history. Replace arbitrary 3/100 row rejection only
   when a certified renderer is ready; never silently clip or truncate.
5. One authorized real-account CGI E2E, independent review and separate
   production promotion approval. No new paid provider/model requests during
   PDF rendering.

**Do not modify the existing `apps/b66-pdf-renderer/renderer.py` for this
slice. Its SHA-256 is pinned by the existing certified private bundle; a
change would invalidate that artifact.** Never commit original PDF/XLSX, Sol
vector resources, program, logo, stamp, fonts, sample company data or private
bundle.

## Network-free proof

Python `test_multipage_plan.py` and Node `quote-multipage-plan.test.cjs`
cover 1, 2, 3, 4, 10, 25, 100, 101, 125, 500 items; row order/uniqueness,
continuous indices/page labels, last-page-only totals flag, exact boundary,
long descriptions, hard line breaks, invalid glyph/geometry and byte ceiling.
The B66 PDF renderer's existing PR source gate runs both.

**This is the page-planning foundation, not a claim of a working multipage
customer PDF.** #3839 stays OPEN until the remaining gates actually pass.
