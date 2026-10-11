# #3580 — Google Drive WRITE trusted port composition root (2026-10-11)

## Scope of this implementation slice

Two existing, previously tested components had no place that assembled them:

1. `kagent/google_drive_multipart_transport.py` — `StdlibGoogleDriveMultipartCreatePort`, the
   concrete Drive `files.create` multipart/related port that performs one TLS POST against the
   pinned `https://www.googleapis.com` origin.
2. `kagent/google_drive_artifact_upload.py` — `GoogleDriveArtifactUploadAdapter`, the canonical
   upload executor that independently enforces binding, scope, folder proof, exact artifact bytes,
   WRITE approval and one-shot replay.

Before this change the only callers of the real port were its own hermetic tests, and
`PRODUCTION_DRIVE_WRITE_PORT_COMPOSED` read `False`. The Control Plane host never supplied a
`claw_drive_artifact_uploader` either (`app_factory` default `None`).

New `kagent/google_drive_upload_composition.py` is the single composition root, mirroring the
existing `e2b_live_composition.py` precedent:

- wires `DriveAuthorizedWriteTokenPort` (injected; defaults to
  `UnconfiguredDriveAuthorizedWriteTokenPort`, which refuses) + `StdlibGoogleProviderNetwork`
  into `StdlibGoogleDriveMultipartCreatePort`;
- `uploader(...)` assembles the canonical `GoogleDriveArtifactUploadAdapter` around that composed
  port only, so a caller cannot substitute a look-alike transport;
- construction performs no provider request and resolves no token;
- `safe_dict()` projects the origin and class names, never a token, folder id or artifact byte;
- `blocked_reasons` names the authority gaps that remain closed.

## Evidence (hermetic: fake token authority, fake HTTPS transport)

- `python -m unittest tests.test_google_drive_upload_composition_3580` → **10 PASS**.
- Focused regression re-run: `test_google_drive_artifact_upload`,
  `test_google_drive_multipart_transport_3580`, `test_google_drive_scope`,
  `test_google_workspace_working_copy`, `test_local_xlsx_artifact_handoff_3580`,
  `test_artifact_full_chain_3580`, `test_artifact_delivery_execution_receipt`,
  `test_telegram_artifact_delivery`, `test_telegram_document_transport` → **197 PASS**.
- Covered: composition root wired while `armed` stays `False`; zero provider requests and zero
  token resolutions at construction; unconfigured token authority fails closed before any socket;
  one physical POST to the pinned upload origin drives the existing adapter to a DURABLE artifact;
  look-alike ports refused; projection leaks no token/folder/bytes; parameter surface pinned.

## Not implemented or activated

```text
GOOGLE_DRIVE_UPLOAD_COMPOSITION_ROOT_WIRED=True
PRODUCTION_DRIVE_WRITE_PORT_COMPOSED=False      # no production host composes it yet
DRIVE_WRITE_GRANT_AUTHORIZED=False              # #2010 keeps Drive at READ-only
LIVE_DRIVE_UPLOAD_CANARY=False
PRODUCTION_ACTIVATION=BLOCKED
NEW_DRIVE_AUTHORITY=False
NEW_TOKEN_STORE=False
```

- No CP Drive WRITE token authority, OAuth grant, lease or secret store is created here.
  `padiem-ai-engine/app/drive_port_cp_lease.py` still reports `DRIVE_WRITE = False`.
- No Worker/chat host injection, no Production rollout, no live Google call, no customer file.
- No second connector/approval/idempotency authority.

## Next acceptance

1. Telegram SEND composition root wiring `StdlibTelegramDocumentSendPort` into the existing
   `TelegramArtifactDeliveryAdapter` (separate PR).
2. Drive implementation of `ArtifactDeliveryAdapterPort` so a Drive hand-off produces the existing
   `ArtifactDeliveryReceipt` (Telegram already has one; Drive does not).
3. After an explicit owner-authorized Drive WRITE grant, a bounded live canary recorded in #3936.
