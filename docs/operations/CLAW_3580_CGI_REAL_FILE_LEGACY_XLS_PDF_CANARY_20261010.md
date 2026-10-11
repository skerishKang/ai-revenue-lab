# Hark #3580 — CGI quote real file canary and bounded legacy XLS PDF export

Date: 2026-10-10. Scope: real local read-only Office smoke for previously used B66 CGI quote files, and a source-only supervised **legacy .xls → PDF** renderer. No customer data or sample bytes committed.

## Why the particular file matters

Hark should not need an operator to name an arbitrary file on every invocation, but it **must** know the selected-root scope and receive a separate exact P01-approved READ request before accessing local bytes. Existing `WindowsSelectedRootFileRuntime` deliberately declares `DIRECTORY_ENUMERATION_SUPPORTED=False`: therefore this change does **not** enumerate a PC, infer permissions from chat text, or secretly broaden the selected-root permission. A product-grade candidate chooser requires explicit, separately authorized selected-root file listing (metadata-only, bounded) and a visible file selection; no such operating permission is introduced here.

Found one previously used B66 CGI legacy `.xls` sample (770,560 bytes, genuine OLE2/BIFF8) and two related usable `.xlsx` quotes (101,479 and 64,778 bytes) inside one operator-selected Windows folder. **No local pathname, customer filename, source file, page content, or workbook data is committed or transmitted.**

## Local evidence, Windows PC with installed Excel

- Original CGI legacy XLS (770,560 bytes) opened in isolated Office read-only mode with update-links/VBA disabled, and directly exported PDF: **131,951 bytes; valid PDF header/tail; original SHA-256 + size + modification time unchanged**.
- An attempt to `SaveAs(FileFormat=51)` into editable XLSX was **refused by Excel**; this must not be described as a successful workbook migration and there is no invented/partial fallback XLSX.
- Both related CGI XLSX files rendered through the already merged `SupervisedWindowsExcelPdfRenderer`: 101,479→201,890 PDF bytes; 64,778→320,787 PDF bytes; both original SHA/time/size unchanged.
- Existing `WindowsSelectedRootFileRuntime` with canonical *synthetic test-only* P01 `ApprovalPause`/`VerifiedApprovalDecision` and local permission grant opened the real 101,479-byte CGI XLSX from the explicit local selected root. `capture_local_xlsx_for_handoff` plus the real supervised Excel and canonical PDF output succeeded (201,890 bytes) with its source integrity unchanged. This **does not prove a real customer/Engine P01 approval**, because the fixture was synthetic and isolated.

## Code introduced

- `windows_excel_legacy_xls_child.py`: a separate, fixed-entrypoint Windows child that accepts only **parent-owned temporary** `source.xls` and `output.pdf`, verifies bounded OLE2 header, opens Excel with ReadOnly, disables events, update-links, VBA and alerts, exports PDF with `ExportAsFixedFormat`, closes workbook without saving, hides COM exception/path data.
- `supervised_windows_legacy_xls_pdf.py`: bounded 5–120s timeout (default 45s), Windows Job-bound Python child with restricted environment (never inheriting device credential/Drive OAuth/model tokens), 1MiB XLS input cap from existing P01 selected-root file runtime, 8MiB PDF output cap and PDF validation, auto-delete private temporary source/output. Source bytes are never modified.
- Unit tests verify bounded source/refusal, timeout, job cleanup, no secrets inherited and valid PDF; Linux safely skips actual Excel execution.

**Operational limit:** Kill-on-close proves termination of Python Job child, **not guaranteed cleanup of Excel's detached out-of-process COM instance**. This renderer is opt-in and `PRODUCTION_LEGACY_XLS_RENDERER_ACTIVATED=False`. It is **not** wired to the existing XLSX+PDF pair staging protocol, since that protocol cannot honestly label `.xls` as original `.xlsx`. To deliver legacy source, add explicitly typed XLS/derived PDF artifacts and canonical source+lineage with correct client download; do not silently discard or relabel source bytes.

## Remaining for real Hark usage

1. User-approved selected-root file discovery/selection UI with a separate bounded list permission; no whole-PC scan.
2. Genuine P01 Engine `filesystem.read` approval source for the exact chosen file, carried securely into Resident. Existing #3140 loopback acceptance is a non-production fixture and **cannot authorize this step**.
3. Canonical original `.xls` + derived PDF pair/type and stage/upload/Drive consent, full idle/hung Excel COM cleanup proof and owner-only Claw file cards/preview.
4. Live paired Resident/Broker end-to-end and separately authorized Drive WRITE only when the owner agrees. All relevant issues remain open.

No Production deploy, Secrets update, user file overwrite, Drive WRITE or paid model call.
