# #3580 — B62 WEB-FIRST XLSX original-source intake

Date: 2026-10-11 KST. Implements **W1: explicit browser XLSX upload, private original-byte preservation, owner-scoped list and download**, not W2–W4 processing or Production-live acceptance.

## Shipped source contract

- B62 authenticated owner visits the independent, collapsible web XLSX panel (NO Windows/Resident connection required), selects one bounded .xlsx file and explicitly presses **원본 보관**.
- New `GET/POST /api/claw/office/web-sources` and owner-only `GET /api/claw/office/web-sources/{document_id}/download`. POST accepts *only* `name, base64`, never browser-supplied owner, workspace, device, P01 decision, Drive destination or local file path.
- Server derives owner from the authenticated session and workspace from existing canonical owner/tenant authority. Fail closed without the D1+private R2 workspace document store, or on missing/partial canonical identity.
- Reuses **existing migration 008** D1 document metadata and private R2 original bytes. R2 object key includes server-validated tenant, owner and workspace, unpredictable generated document ID and SHA-256 original digest. Cross-owner/workspace/cross-tenant requests return non-disclosing missing. Re-read verifies exact hash before returning original. Storage rejects ZIP unsafe/malformed/encrypted/oversized archive via existing Core OOXML guard; only a workbook-shaped XLSX <= 1 MiB can be saved.
- Maximum source retention 24 hours. Source original remains unchanged, and the UI explicitly says `processing_started=false`, `p01_approved=false` and `drive_uploaded=false`. File upload consent authorizes storage of the explicitly selected source, **NOT** editing, local file operations, model execution or Drive WRITE.
- Browser list/disclosure is bounded to 40, filename/size/opaque document ref/SHA256 only. No raw workspace object key, actual file bytes, device tokens or approval evidence appear in JSON. Browsers can obtain their own original workbook bytes only from the authenticated download endpoint.
- Existing `/api/claw/office/candidates` PC chooser, first-party P01 approval and Windows fallback are unchanged. The new web selector displays a selected item locally for the next workflow milestone but **does not claim a runnable Engine approval**.

## Focused evidence

- Local Windows Python B62 + existing workspace and chooser tests: **26 PASS**.
- Node browser contract: **PASS**; JS syntax and `git diff --check` clean.
- Includes actual existing D1 schema SQL + R2-style store recreation; owner/foreign/anonymous access, original byte identity, expiry, corrupted bytes, path traversal and malformed/extra JSON authority field rejection.
- Test input is a generated synthetic workbook. No Production deployment, actual customer files, Secrets changes, Drive WRITE or paid providers.

## NEXT implementation (do not defer to Windows)

**W2:** A user-approved web file should be promoted from immutable stored source to a separately scoped work-copy and a real owner/session/run/source-fingerprint P01 Engine approval. Reuse existing B62 continuation/handoff and P01 verification; never use synthetic approval in a live web path.

**W3–W4:** Server-safe deterministic edit/export (honestly reject unsupported Office-fidelity paths), XLSX/PDF artifact lineage/preview/download, follow-up and authenticated browser E2E. Drive READ picker is a separate W1 source requiring real connected OAuth READ capability. Windows Resident remains **optional** for expressly requested local-PC files or unsupported fidelity.

#3580/#3928/#3933/#3936 stay OPEN. `WEB_SOURCE_INTAKE=SOURCE_TEST_PASS`, `PRODUCTION_WEB_E2E=NOT_PROVEN`.
