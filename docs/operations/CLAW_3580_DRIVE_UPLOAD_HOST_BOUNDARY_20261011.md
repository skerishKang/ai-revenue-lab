# #3580 — Claw Drive WRITE host injection boundary (2026-10-11)

## What was missing

`create_app` has always accepted `claw_drive_artifact_uploader` and defaulted it to `None`, and the
deployed Worker (`worker.py`) never passed anything else. The fail-closed state was correct but
implicit: no single place stated **which** trusted inputs a host must supply, so a future host could
inject a look-alike port or a READ-only grant by accident.

## This slice

New `apps/padiem-chat/app/claw_drive_upload_host_composition.py` — a boundary, not an authority:

- `drive_write_grant_present(binding, *, now)` states the rule once: a **live** binding whose
  `connector_id` is `google-drive`, whose scopes intersect `DRIVE_WRITE_SCOPES` and whose
  capabilities include `DRIVE_UPLOAD_CAPABILITY`. **A `drive.readonly` grant is not a WRITE grant**
  (#2010), and neither is a revoked or expired one.
- `build_claw_drive_upload_host_state(...)` assembles the canonical uploader from the composed Drive
  WRITE port plus the host's trusted binding, scope, artifact-material, folder-proof and approval
  ports — or returns `uploader=None` with one explicit reason per missing input.
- `ClawDriveUploadHostState` refuses to hold a non-canonical uploader, or an uploader alongside a
  blocking reason. `safe_dict()` carries no token, folder id, binding ref or workspace ref.
- `worker.py` now calls the boundary and passes the result to
  `create_app(claw_drive_artifact_uploader=...)`.

Every authority decision still belongs to `GoogleDriveArtifactUploadAdapter`, which re-checks the
binding, scope, folder proof, exact artifact bytes, WRITE approval and replay on every call. This
module adds no grant, no approval schema, no Drive transport and no second upload adapter.

## Evidence (hermetic: local fakes only)

- `python -m pytest tests/test_3580_claw_drive_upload_host_composition.py -q` → **10 passed**.
- Focused regression: `test_3929_claw_drive_output_registration`,
  `test_3933_office_drive_completion`, `test_3929_claw_conversation_artifact_d1` → **33 passed**;
  worker-related `test_b62_production_deploy_config`, `test_b62_3094_worker_local_access_composition`,
  `test_3930_live_canary_subject_admission`, `test_3989_ci_tests_only_scope_contract` → **80 passed**.
- Covered: no trusted input → `None` with a reason per input; READ-only grant → refused and
  `drive_write_grant_present` False; expired/revoked/naive-clock → False; all trusted inputs →
  canonical adapter bound to the composed port; scope/binding mismatch refused; missing approval port
  refused; contradictory state refused; projection leaks nothing; `worker.py` actually imports and
  passes the boundary result; `create_app(claw_drive_artifact_uploader=None)` leaves the Drive
  pipeline unbound.

## Deployed shape (unchanged, truthful)

```text
HOST_INJECTION_BOUNDARY_IMPLEMENTED=True
PRODUCTION_DRIVE_UPLOADER_INJECTED=False
DRIVE_WRITE_GRANT_AUTHORIZED=False          # #2010 READ-only
REAL_DRIVE_UPLOAD=NOT_PROVEN
PRODUCTION_ACTIVATION=BLOCKED
PRODUCTION_MUTATION=0
BLOCKED_ON_OWNER_AUTHORIZATION=True
```

Enabling the Drive leg is now a single, reviewable change: supply a CP Drive WRITE grant, a
run/workspace-scoped artifact material resolver, the authorized folder-proof port
(`AuthorizedDriveFolderProofPort`) and the existing approval authority to the boundary.

## Still open in #3580

1. `DriveWriteApprovalPort` host implementation on the **existing** approval authority — no new
   approval schema. The only existing WRITE approval today is the Engine's Hark-quote P01 tool,
   which belongs to #3933 and is deliberately untouched.
2. The Telegram equivalents: an outbound `TelegramTrustedBindingPort`
   (`resolve_bot_token` / `provider_chat_id`), a scoped `TelegramArtifactMaterialResolver`, a
   `channel_context` and a `TelegramDeliveryApprovalPort` — plus the delivery consumer route.
3. Real operational verification in #3936 once an owner-authorized WRITE/SEND grant exists.
