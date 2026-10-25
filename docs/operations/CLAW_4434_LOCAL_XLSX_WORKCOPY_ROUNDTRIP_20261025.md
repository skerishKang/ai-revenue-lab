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

## Resident integration (2026-10-26 follow-up)

- `kagent/local_resident_xlsx_revision_delivery.py`
  - `TrustedP01XlsxRevisionPlan` — the P01 material for one revision of one
    acknowledged command: approved READ, literal reviewed edits, and an approved
    WRITE whose fingerprint binds the *expected result bytes*. It creates no
    approval; the pause, decision and local permission evidence are the existing
    canonical ones.
  - `TrustedP01XlsxRevisionBridge` — hands out that evidence once per file
    request and consumes one `(binding, command)` pair once, so a reconnect or a
    duplicate delivery cannot revise the workbook a second time.
  - `ResidentXlsxRevisionStager` / `compose_resident_xlsx_revision_stager` —
    post-ACK execution through the existing P01 file authority plus the canonical
    `LocalOfficeChunkPublisher`. It refuses an authorization port that is not
    `P01LocalPermissionWindowsFileAuthorizationPort`, so the deterministic test
    grant cannot enter this path.
- `local_agent_resident_process.build_resident_host` gained
  `xlsx_revision_plan_source`; the environment may only name an importable
  trusted factory (`PADIEM_AGENT_XLSX_REVISION_PLAN_SOURCE=module:attribute`),
  never a path or an approval, and `main()` resolves it with the same fail-closed
  convention as the text and Office lanes.
- `LocalAgentResidentRuntimeHost` invokes the lane after the acknowledgement,
  with the same discipline as its siblings: an acknowledged command keeps its
  truth, a staging refusal records `REVISION_REFUSED`, and nothing re-executes.
- Capability boundary confirmed by `test_4434_xlsx_capability_scope.py`: the
  Python path handles later-sheet edits, Korean text with leading and trailing
  spaces, negative and large integers, merges and styles (only the target
  worksheet part changes); anything with a formula, a calculation chain (matched
  case-insensitively, as Excel writes `xl/calcChain.xml`), or an
  `xlsx_fidelity_route.BLOCKED_PARTS` member (VBA, external links, pivots,
  charts, comments, custom XML) is routed to the Office path with no write. The
  literal-only `ReviewedCellRevision` contract still refuses floats, booleans and
  formula-like strings.
- Broker coupling: `apps/padiem-chat/tests/test_4434_office_chunk_broker_web_coupling.py`
  runs the real publisher over the real editor output and serves those recorded
  payloads to the real `BrokerOfficeBinaryReader` (the Durable Object rows are the
  only stand-in, and the store has its own SQLite contract test). It pins the
  shared wire schema against `local_agent_broker_office_chunks._WIRE` after the
  device route strips `binding_ref`/`credential_b64`, checks per-part and
  whole-file digests, two-command isolation, foreign owner/run/command/kind
  refusal, tamper refusal, and recovery after a missing part.

## Still not enabled, and who owns it

| Item | State | Owner |
|---|---|---|
| Resident revision lane composition | implemented and fail-closed: `build_resident_host(xlsx_revision_plan_source=...)`; `RESIDENT_XLSX_REVISION_LANE_PRODUCTION_CONFIGURED` stays `False` because no deployment supplies a trusted P01 plan source yet | CENTRAL with the #5573 executor/connector lane |
| Broker staging gate `LOCAL_AGENT_OFFICE_CHUNK_TRANSFER_ENABLED` | unset in every environment; route answers `503 office_transfer_not_configured` | operator configuration, CENTRAL |
| Web `claw_office_chooser_source` composition | still `None`, so `/api/claw/office/candidates` answers 503 | Chat `worker.py`/`app_factory.py`, held while #5817 is open |
| Device row `ACTION_REQUIRED` / executor poll refusal | observed live on COM2 on 2026-10-25 | CENTRAL operational recovery (#5573) |
| Full web -> PC -> web E2E with an approved write | not run; blocked by the rows above. The web routes were probed locally through the ASGI app and answer their bounded refusals without an authenticated device/owner session (`401 unauthorized`, `local_runner_result_forbidden`) | after the above clear, with the Owner performing the approval |
