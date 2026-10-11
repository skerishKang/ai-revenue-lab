# #3580/#3933 — Hark Office XLSX+PDF to authorized Drive and D1 (2026-10-10)

## Scope of this merged-code candidate

New `ClawOfficeDriveCompletion.upload_completed_revision` joins existing, previously tested components:

1. `LocalRevisedXlsxPdf`: source artifact, immutable revised XLSX, immutable PDF, exact bytes and original→working→PDF lineage from a separately authorized local Office host.
2. The existing `GoogleDriveArtifactUploadAdapter`: validates approved current binding, folder proof, source bytes/checksum, *per-file* write intent and verified Drive provider receipt.
3. The existing `ClawDurableDriveOutputPipeline`: checks the server D1 conversation owner + completed Claw run, uploads one artifact, verifies receipt and registers its immutable file reference in D1.

The new completion composes (2) and (3) once per file. It preflights **both** source material refs, lineage and exact intent fingerprints before the first upload, refuses shared idempotency/approval references, and requires the same connector binding and actor. The App factory exposes this only when an **explicit** trusted uploader is injected. The shipped Cloudflare Worker does not inject that uploader.

## Evidence (real SQLite index, fake Drive and fake Office renderer)

- `python -m unittest -q test_3933_office_drive_completion test_3929_claw_drive_output_registration test_3929_claw_drive_read_delivery` → **20 PASS**.
- Tests cover two distinct PDF/XLSX durable records with different SHA-256 and Drive receipts; source/run/workspace checks, foreign owner, noncompleted run, invalid output bytes, mismatched second intent, no implicit activation, second-upload ambiguous failure and refusal of pair replay.
- Prior `test_local_xlsx_revision_pdf_3933.py` separately tests workbook semantic edits and a fake PDF renderer. None of these tests calls licensed Excel, a paid model or live Google Drive.

## Non-atomic pair, strict recovery

Drive does **not** supply a transaction spanning both uploads + D1. If XLSX succeeds and PDF fails, an XLSX record may already be durable. The method intentionally does not claim both indexed, rollback, retry or make a second uncontrolled upload. Recovery must use a separately authorized reconciler against provider receipts and D1 and a durable cross-Worker idempotency store.

## Not implemented or activated

- No live P01/Local Runner callback carries `LocalRevisedXlsxPdf` back into this host: current broker terminal result is status/correlation only. A legitimate local-host callback with verified binary artifact material is a necessary next deliverable.
- No production Windows/Office PDF renderer invocation, not even when Tabbit Drive browser is signed in.
- No Control Plane WRITE grant/read grant, no operational OAuth permission increase, no Drive HTTP transport injected into Worker, no Secret changes.
- No new route, no actual user-file write or download, no Production rollout, no D1 migration.
- No attestation of PDF layout fidelity, formula cache recalculation or completed Hark end-to-end UX. Do not close #3580/#3933/#3928/#3936 merely from this PR.

## Next acceptance

1. Define broker/Local Runner artifact manifest bound to server-derived owner, workspace, run, exact filenames/size/SHA, not model JSON, and an approved binary handoff channel.
2. Run authorized Windows Office edit/export and compare changed fields, formula caches, graphics and PDF pagination; reject unsupported fidelity instead of silently degrading.
3. Compose distinct CP-approved Drive WRITE and READ ports, cross-isolate idempotency/reconciliation, and Claw file cards in a live session.
4. After explicit user permission for real Drive write/OAuth or deployment changes, verify a one-time production E2E with independent D1/Drive readback and unauthorized denials.
