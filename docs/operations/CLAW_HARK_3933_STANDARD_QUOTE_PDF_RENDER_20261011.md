# Hark WEB-FIRST: approved XLSX → standard quote summary PDF

**2026-10-11 KST. Source-level PDF delivery, opt-in OFF by default.**

## Supported print profile

This is NOT arbitrary XLSX print fidelity and MUST NOT be marketed as an
Excel-identical reproduction. Hark's previously approved editor only admits a
bounded, single-sheet XLSX with A1:D1 merged header and cells A1, B4, B5,
B6, B7. PDF export further restricts the sheet to **exactly those five
cells** with no pageSetup/printOptions/pageMargins/headerFooter/other user
objects. More complex workbook assets/rows are rejected with HTTP 422;
the original and owner-approved revised XLSX download remain available.

The output is a standard, A4 one-page **견적 요약 PDF**: recipient name,
supply, VAT (10%) and total. It explicitly states that the format is
not a reproduction of Excel's original print layout.

## Server / security

- Authenticated owner's original READ P01 and independently confirmed WRITE
  revision D1 must both exist; on-demand PDF GET reuses the **same private
  R2 revision metadata, tenant, content hash and owner scope** validation
  as `/quote-edit/download`. Browser only provides the selection-ref URL.
- The server separately parses the saved XLSX, verifies its SHA-256,
  exact supported cell layout, school name and supply amount against the
  confirmed D1 edit, formula identifiers, cached VAT+total, and return
  values before creating any printable HTML.
- HTML escapes user cell strings and includes no remote URL, JS, fonts,
  external scripts or stylesheet; strict `default-src 'none'` CSP.
  PDF generator is only the explicitly configured Cloudflare Browser
  Rendering Quick Action `BROWSER.quickAction("pdf", {"html": ...})`.
  See Cloudflare Browser Run Quick Actions /pdf docs.
- PDF returned as bounded, verified `%PDF-` / `%%EOF` binary via the
  private owner-only `GET /api/claw/office/web-selections/{selection_ref}/quote-edit/pdf`.
  `Cache-Control: no-store`, attachment, same-origin CORP and no R2 write.
  No customer data, keys or storage IDs passed to a public renderer.
- A missing or failed binding returns HTTP 503; unsafe unsupported XLSX
  returns 422; missing revision returns 404. Never manufactures a PDF
  when render output cannot be verified. XLSX remains downloadable.
- Browser shows the **standard quote summary PDF** link only when
  `pdf_download_available=true` from a confirmed owner write status
  and operator renderer enablement. Feature is OFF in `app_factory`.

## Cloudflare prerequisite (not applied by this PR)

Cloudflare Browser Rendering must be enabled/provisioned on the operator's
account. Declare a Worker Browser Rendering binding named **BROWSER**
using `[browser]\nbinding = "BROWSER"` in the authorized environment's
Wrangler configuration and verify account entitlements/billing/security.
Then, only after B62 D1 032/033/034, Engine D1 0010, independent WRITE
Core ToolRuntime, R2 and live account P01 acceptance are independently
verified, opt into `PADIEM_WEB_XLSX_QUOTE_PDF_ENABLED=true`. Keep it OFF
otherwise. This PR does not provision Browser Rendering, apply Production
migrations, enable P01/WRITE/PDF, change secrets, or deploy customer data.

## Acceptance evidence

- Local Chromium `page.setContent()` → `page.pdf(format="A4")`:
  **one page, 41,455 bytes**, successful pypdf extraction of Korean
  school name and exact supply/VAT/total amounts.
- Core Hark server mocked Cloudflare `BROWSER.quickAction("pdf",...) `
  tests check PDF response stream, file signature, bounds, failure behavior,
  same-owner authorization, pre-approval block and original R2 immutability.
- Shipped Hark JavaScript Node checks PDF link invisible before WRITE
  approval, visible after opt-in approved revision, and status refresh.
  No Production Browser Rendering call has occurred.

## Remaining before closing #3928/#3933/#3936

- Actual provisioned BROWSER Worker binding + operator opt-in,
  complete signed-in E2E on deployed B62/Engine with source workbook
  selected, approved WRITE, XLSX download, PDF render/download verified.
- Compare output screenshots against the **new approved standard quote
  summary template**. The original workbook may have Excel-specific styling
  that cannot be reproduced by this profile; do NOT claim pixel parity.
- Separate Hark conversation artifact cards and same-thread follow-up
  remain in #3932 and #3929. Keep issues OPEN.
