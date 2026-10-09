# B66 certified quote template registry

This folder maintains the **decision and provenance for already-built, source-derived quotation templates**. It does not cause a new template to be synthesized per customer request.

## Model and template roles

- Sol 6.1 (gpt-6.1-sol): preferred CGI fixed-page template candidate; independently selected for B66 follow-up subject to remaining release gates.
- GLM 5.3 Flash: fully retained alternate for benchmark, not the customer-facing PDF path as currently implemented.
- Both models built template-generation code previously. **Normal repeat use needs neither model**. Existing QuoteCore determines the totals, and the selected deterministic renderer replaces the approved value fields.

See cgi/candidates.json for the sole machine-readable selection and cgi/decision-2026-10-09.md for the measured basis.

## Public vs private storage

Keep only documentation, JSON metadata, non-private tests and approval history in Git. The exact customer source PDF/XLSX, stamp, logo, bundled fonts, compiled templates, quotation outputs, R2 object keys, real company profile and hashes of generated confidential files remain in a separate access-controlled private vault.

Private on the authorized workstation: G:/downloads/b66-private/template-library/cgi/v1-20261009. Do **not** copy its contents under GitHub, a public Pages static root or a CI artifact. The local private archive includes both complete candidates, comparison PDFs, and a SHA256 manifest.

Git .gitignore is only a last-resort guard: it does not make a public checkout suitable for private assets. Never force-add ignored binaries.

## Integration boundaries

Product path after approval: authenticated Saved Quote Skill -> approved bundle identity/fingerprint -> normalized QuoteCore data -> deterministic Sol renderer -> PDF download. B66 HTML preview remains a UI surface; do not use a separate invented HTML form for the official PDF.

Hard limits of existing certified Sol CGI profile: one fixed A4 page and 1-3 item rows. Extra items and unsupported typography must reject before PDF generation, never silently truncate. Existing company assets must be supplied from the private approved bundle, not a model.

**This metadata registry is NOT an authorization to merge, deploy, activate a customer quote route, upload private assets or change model pricing/routing.** Independent bundle and product E2E verification is still required.
