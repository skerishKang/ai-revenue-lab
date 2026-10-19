# #3580 — Drive destination folder proof host port (2026-10-11)

## What was missing

`kagent/google_drive_artifact_upload.py` refuses to create a Drive file until it holds a trusted
`DriveResourceProof` of the **destination folder** and has re-authorized it against the Drive scope
(`resolve_folder_proof` → `authorize_drive_resource(...) is DriveScopeDecision.ALLOW`). No host
implementation of that port existed anywhere in the repository — only test fakes. The Drive WRITE
path therefore could not be composed even after a WRITE grant is issued.

## This slice

New `kagent/google_drive_folder_proof.py`: `AuthorizedDriveFolderProofPort`, implemented on the
**existing** authorized Drive READ seam
(`kagent.google_drive_connector.AuthorizedGoogleDriveHttpPort` — the same seam
`GoogleDriveReadTransport` already uses). It performs exactly one bounded `files.get` per call.

- No new authority: no OAuth, no token store, no scope authority, no WRITE path, no cache.
- `READ_ONLY_PORT=True`, `NEW_DRIVE_AUTHORITY=False`, `NEW_OAUTH_AUTHORITY=False`,
  `NEW_SCOPE_AUTHORITY=False`, `AUTO_RETRY=False`, `PRODUCTION_FOLDER_PROOF_COMPOSED=False`.
- Pinned origin/path/fields/timeout; folder ids are quoted and never treated as paths.
- Fail-closed `None` (the answer the upload adapter already treats as "trusted Drive folder proof
  required") for: untrusted refs, provider/transport failure, non-object response, invalid metadata,
  id mismatch, non-folder MIME, shortcut, trashed.
- Provider exception text, headers and body never surface.

**It cannot authorize anything.** The upload adapter keeps the scope decision, which the tests prove
by driving a truthful proof through an out-of-scope adapter and observing refusal with zero upload
calls.

## Evidence (hermetic: fake authorized READ seam, existing hermetic upload double)

- `python -m unittest tests.test_google_drive_folder_proof_3580` → **12 PASS**.
- Covered: truthful proof for an exact live folder with the pinned query/fields/timeout; non-folder
  MIME, shortcut, trashed, id-mismatch all refused; provider failure returns `None` without leaking
  provider text; untrusted refs refused before any provider call; the real port drives the existing
  `GoogleDriveArtifactUploadAdapter` to a DURABLE artifact + canonical receipt; an out-of-scope
  folder is still refused by the adapter.

## Not implemented or activated

```text
DRIVE_FOLDER_PROOF_PORT_IMPLEMENTED=True
PRODUCTION_FOLDER_PROOF_COMPOSED=False       # no host wires it yet
DRIVE_WRITE_GRANT_AUTHORIZED=False           # #2010 READ-only
REAL_DRIVE_UPLOAD=NOT_PROVEN
PRODUCTION_ACTIVATION=BLOCKED
PRODUCTION_MUTATION=0
```

## Remaining Drive host ports

1. `DriveWriteApprovalPort` — must consume the existing approval authority; no new approval schema.
2. `DriveArtifactMaterialPort` — for the Office path `LocalRevisedXlsxPdf.resolve_artifact_material`
   already exists; a host composition must bind it (or an equivalent scoped resolver).
3. Worker/`app_factory` injection boundary for `claw_drive_artifact_uploader`.
