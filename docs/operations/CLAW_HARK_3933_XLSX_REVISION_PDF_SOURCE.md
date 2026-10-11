# Claw Hark #3933 — reviewed XLSX revision -> PDF, provider-free source gate

**2026-10-10 KST** · owner: B54 Claw / P01 artifact authority #3580

## Exact source milestone

`kagent.local_xlsx_revision_pdf.revise_and_render_local_xlsx_pdf` connects
existing canonical components **inside a trusted local resident host**, after
a separate P01/CP file authorization:

1. `LocalXlsxArtifactHandoff`: immutable, SHA-256-bound, exact-run selected-root
   **source** XLSX; rejects wrong workspace/run or untrusted OOXML.
2. `ReviewedCellRevision`: 1–16 explicitly reviewed, distinct literal cell
   changes; no formula-cell editing, formula-like string injection, raw Python
   execution, model-selected file path or hidden changes.
3. `TrustedXlsxCopyEditor`: approved in-memory copy editor port. It must never
   overwrite a source file. The independent
   `IndependentXlsxRevisionVerifier` checks source and revised workbook
   **separately**; a failed check prevents PDF and registration.
4. `TrustedLocalOfficePdfRenderer`: existing #3580 render port; verified PDF
   byte signature/size. No PDF is claimed faithful merely because it renders.
5. The existing canonical `register_canonical_artifact` and
   `declare_lineage` establish one **source**, one independent **revised XLSX**
   working copy, and one **PDF** output. Scoped `resolve_artifact_material`
   exposes either output only for a matching canonical artifact ID + hash +
   workspace + run. Existing #3580 Drive upload adapter is the *sole* future
   durable authority; this code performs **zero** network or Drive WRITE.

This is a **trusted composition seam**, not a new production route, converter,
authorization issuer or model planner. It changes no B66 quote templates and
does not accept .xls files.

## Verified evidence

- Synthetic workbook: school A1 changed `Existing School -> New School`;
  supply B2 `88,000,000 -> 99,200,000`.
- Genuine independent openpyxl semantic verification preserves unrequested
  formulas `=B2*0.1`, `=B2+B3`, styles, merged `A5:C5` and print range.
  Original XLSX bytes/hash unchanged. Result XLSX/PDF distinct canonical IDs,
  intact SHA-256 digests and source→working→PDF lineage.
- Focused test `tests/test_local_xlsx_revision_pdf_3933.py`: 8 PASS
  including changed/malicious source, cross-workspace/cross-run, duplicate
  artifacts, formula-like string attempts, unapproved edits, false validator,
  invalid PDF and tampered material.
- Independently **real Windows interactive Excel COM** exported the revised
  synthetic XLSX to a **1-page / 42,054-byte PDF**; text extraction saw
  `New School` and `99,200,000`, and source hash stayed intact.
  This is a real local Excel canary, **NOT** live Claw/Office/Broker invocation.
- CI should run only affected kagent suites initially; no arbitrary full
  4,000+ suite repetition solely for this source-only change.

## Required remaining work — NOT DONE

1. **#3929**: authenticated, owner/workspace/conversation-scoped source resolver
   for "the XLSX we just made" and **cross-run** lineage; this initial seam
   intentionally binds the source to the *same* authorized run.
2. **#3933 / #3580**: assemble actual production P01-approved Desktop/Office
   editor and verifier host, bounded cancellation/timeout, workbook-fidelity
   capability detection, real output bytes and download-facing artifact receipt.
   A test-only openpyxl editor and semantic verifier do not authorize a
   production copy engine.
3. **#2010 / #3580**: explicit Google Drive/Sheets WRITE or Telegram SEND
   approval and trusted provider composition. No workaround via a local path,
   fake Drive receipt or browser credential extraction.
4. **#3936**: real authenticated user-facing XLSX→PDF→file-card→preview/download
   and later same-thread followup. Verify formula cached values and PDF
   geometry/fonts/graphics for the actual input class; do not assert
   100%-identical output from this simple synthetic example.

```text
SOURCE_XLSX_UNCHANGED=PASS_SYNTHETIC
REVIEWED_EDIT_COPY=PASS_LOCAL_OFFLINE
INDEPENDENT_WORKBOOK_DIFF=PASS_LOCAL_OFFLINE
REAL_EXCEL_PDF=PASS_LOCAL_INTERACTIVE_SYNTHETIC
CANONICAL_XLSX_AND_PDF_MATERIAL=PASS_LOCAL_OFFLINE
PRODUCTION_HOST_COMPOSED=NO
PRODUCTION_DRIVE_WRITE=NO
PRODUCTION_TELEGRAM_SEND=NO
CROSS_RUN_SOURCE_SELECTION=NOT_IMPLEMENTED
HARK_FULL_E2E=NOT_PROVEN
```
