# Hark P01 / Office / Google Drive: durable-file delivery boundary (2026-10-10)

Issues: #3929, #3580, #3933, #3936, #3928.

## Verified in this change

- Source branch based on exact `main` `c6f58efbb8d9d8344dedf6839e98bf55f0683216`.
- An existing `ClawDurableDriveOutputPipeline` can register receipts from an explicitly approved `GoogleDriveArtifactUploadAdapter` in D1 after a completed owner-scoped Claw run. This is a test-proven source contract, **not** a Production WRITE grant.
- New `D1HistoryStore.get_owner_conversation_artifact` performs an exact-ID lookup requiring the active conversation owner, tenant workspace, and completed source run.
- `GET /api/claw/conversations/{conversation_id}/artifacts/{artifact_id}/download`: a separate host-approved READ port can return the original PDF/XLSX bytes as an attachment, verifying exact size and SHA-256.
- `GET /api/claw/conversations/{conversation_id}/artifacts/{artifact_id}/preview`: the same separate READ authority supports PDF inline with byte checks; XLSX remains download-only.
- No file bytes, provider location ID, folder ID, OAuth token or storage URL is returned in a metadata response. Unknown or revoked authorization must fail closed in the injected host.
- No Drive WRITE, cloud model call, production deployment, Secrets modification, D1 migration or user file mutation was performed. Existing migration 026 is not reapplied.

## Local validation (mock connector, actual SQLite D1 schema)

Run the two targeted suites from the repository with local `packages/padiem-ai-core`, `packages/padiem-control-plane`, `apps/padiem-chat`, `apps/korean-ai-code-agent/src`, `apps/padiem-chat/tests` in `PYTHONPATH`:

```text
python -m unittest -q test_3929_claw_drive_read_delivery test_3929_claw_drive_output_registration
Ran 15 tests
OK
```

Checks include valid download/preview, owner/conversation isolation, absent READ grant, corrupt bytes, invalid artifact ID, provider WRITE receipts and D1 registration. These are **hermetic local tests**; CI and Production status must be recorded separately.

## Mandatory remaining integration, not claimed complete

1. **P01 artifact producer:** `ClawOrchestrationOutcome` currently has answer, projection, P01 run ID and event evidence but no trusted canonical XLSX/PDF output payload. A model's text claiming a file exists is not a file. Establish a real authorized Office/local-runner artifact producer and handoff before calling Drive upload.
2. **WRITE host:** Worker does not inject `claw_drive_artifact_uploader`. The Control Plane must attest a current owner/workspace connector binding, Drive file scope, approved target folder, one-shot user WRITE approval, and a durable cross-isolate idempotency lease. Browser Google login proves none of these.
3. **READ host:** Worker does not inject `claw_drive_artifact_reader` (new port). Implement a current-grant, owner/workspace-scoped Drive READ adapter that obtains exact original bytes, not a browser URL; never treat upload receipts as READ authorization.
4. **UI and multitur​​n:** Claw file-card rendering and retrieval in subsequent conversations must be wired to the authenticated metadata and byte endpoints. XLSX edits must produce a new version and new SHA, not silently overwrite the source.
5. **Production E2E:** After distinct authorization, verify actual Office file output, a consented Drive WRITE receipt, D1 readback, authenticated PDF preview/download, unauthorized denial, and multi-turn retrieval. Do not declare Hark ready based on 15 local tests.

## Gate

`DRIVE_BROWSER_LOGIN=CONFIRMED` (manual Tabbit), `PRODUCTION_DRIVE_READ_GRANT=UNVERIFIED`, `PRODUCTION_DRIVE_WRITE_GRANT=UNVERIFIED`, `P01_FILE_PRODUCER=NOT_COMPOSED`, `AUTHORIZED_READ_ENDPOINT_SOURCE=IMPLEMENTED`, `END_TO_END_PRODUCTION=NOT_PROVEN`.

Source changes do not activate Google Drive operations in production. Approval required for actual user Drive WRITE, OAuth permission enlargement, Secrets changes and Production deployment.
