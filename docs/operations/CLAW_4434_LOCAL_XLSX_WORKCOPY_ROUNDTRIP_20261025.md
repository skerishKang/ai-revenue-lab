# #4434 — local XLSX workcopy revision and staging (2026-10-25, COM2 LOCAL1)

Scope record for the PC side of the web -> PC -> web Excel round trip. Public
technical evidence only: no credentials, no device identifiers, no customer data.

## What was already there

`kagent.local_xlsx_revision_pdf` already owned the revision *contract* — an
approved source handoff, literal `ReviewedCellRevision` edits, an editor port, an
independent verifier port, and canonical artifact/lineage registration. The
selected-root runtime already performed authorized real reads and writes, the
chunk publisher already staged bounded 48 KiB parts over the pinned HTTPS/443
broker transport, and the Chat side already reassembled and re-verified them.
The two ports had no production implementation, and nothing ordered the steps
so that the original file could not be the write target.

## What this change adds

- `kagent/local_xlsx_python_copy_editor.py`
  - `PythonXlsxValueCopyEditor` — the production editor for the ordinary Python
    path. It rewrites only the worksheet part that holds a target cell and copies
    every other package member byte-for-byte, so styles, theme, merged ranges,
    print settings and every untouched cell are preserved by construction rather
    than by promise. Text replacements are written as `inlineStr` so
    `xl/sharedStrings.xml` is never mutated.
  - `IndependentZipXlsxRevisionVerifier` — proves from the two byte blobs alone
    that the part set is unchanged, exactly the expected parts differ, every
    non-target cell keeps its value, and each target cell holds the reviewed
    replacement.
  - `OfficeFidelityRequired` — a workbook that carries any formula, or a
    calculation chain, is refused before a byte is written and routed to the
    existing Office/Local Runner path (`windows_excel_pdf_renderer`,
    `supervised_windows_excel_pdf`), because replacing an input makes the cached
    results of dependent formulas stale. `classify_xlsx` stays the untrusted-input
    gate; `REJECT` is refused, and a DTD or entity declaration in any part is
    refused before parsing.
- `kagent/local_xlsx_workcopy_roundtrip.py`
  - `revise_and_stage_approved_xlsx_workcopy` — one ordered composition over the
    existing authorities: approved READ (canonical P01) -> source handoff ->
    editor -> independent verifier -> canonical `working.xlsx` record -> approved
    WRITE to a *derived* path -> staging through `LocalOfficeChunkPublisher`.
  - `revised_path_for` derives the only legal result name (`<source>_revised.xlsx`
    beside the source). The caller cannot supply a target, the original can never
    be the write target, and an existing result file is refused instead of
    silently overwritten.
  - The WRITE is approved against the exact result bytes, so the host validates
    the built request against the verified bytes, the derived path, and the
    source's device, root and run before performing it.

No second parser, no second store, no new ceiling, no new approval step: the
result's integrity comes from the runtime's atomic write (temp file, `fsync`,
`os.replace`) rather than from an extra customer-facing approval.

## Verified on COM2 (real files, real disk, real P01 evidence)

`python scripts/kagent_local_test.py -- -p "test_4434_local_xlsx_workcopy_roundtrip.py"`
→ 13 tests OK, `IMPORT_ORIGIN_CHECK=PASS`.

- Revision on disk: `quote\book.xlsx` -> `quote\book_revised.xlsx`; original SHA-256
  unchanged; result SHA-256 equals the canonical record; merged range and untouched
  cells preserved; Korean text kept.
- Only `xl/worksheets/sheet1.xml` differs between original and result;
  `xl/styles.xml` is byte-identical.
- Formula workbook → `OfficeFidelityRequired`, no result file, nothing staged.
- Stale `previous_value`, unapproved WRITE, non-derived target, pre-existing result
  file, cross-run/cross-device request, and a non-OOXML source are each refused with
  no write and no staging call.
- Staged parts reassemble to the verified digest; each `part_sha256` matches; the
  wire carries run/command ids only — no path, no destination, no Drive claim. A
  broker-refused part yields no receipt, and an explicit retry of the same bytes
  produces identical part digests.
- The production editor and verifier satisfy the existing
  `revise_and_render_local_xlsx_pdf` ports and its lineage registration.

## Still not enabled, and who owns it

| Item | State | Owner |
|---|---|---|
| Resident process injects the editor/verifier/publisher | not composed here; `RESIDENT_OFFICE_PAIR_PROVIDER_PRODUCTION_CONFIGURED` and `LOCAL_OFFICE_CHUNK_PUBLISHER_RESIDENT_COMPOSED` stay `False` | requires the executor/connector lane (#5573) to be repaired first |
| Broker staging gate `LOCAL_AGENT_OFFICE_CHUNK_TRANSFER_ENABLED` | unset in every environment; route answers `503 office_transfer_not_configured` | operator configuration, CENTRAL |
| Web `claw_office_chooser_source` composition | still `None`, so `/api/claw/office/candidates` answers 503 | Chat `worker.py`/`app_factory.py`, held while #5817 is open |
| Device row `ACTION_REQUIRED` / executor poll refusal | observed live on COM2 on 2026-10-25 | CENTRAL operational recovery (#5573) |
| Full web -> PC -> web E2E with an approved write | not run; blocked by the two rows above | after the above clear, with the Owner performing the approval |
