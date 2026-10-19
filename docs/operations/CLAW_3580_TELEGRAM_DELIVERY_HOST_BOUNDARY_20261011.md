# #3580 — Claw Telegram SEND host injection boundary (2026-10-11)

## What was missing

`TelegramArtifactDeliveryAdapter` (#3666) and `StdlibTelegramDocumentSendPort` (#3901) both existed
and were tested, and #4327 added the composition root that binds them. But no host stated **which**
trusted authorities a deployment must supply, and `create_app` had no seam for the adapter at all.

## This slice

New `apps/padiem-chat/app/claw_telegram_delivery_host_composition.py` — the outbound counterpart of
`claw_drive_upload_host_composition.py` (merged as #4331):

- `telegram_send_grant_present(binding, *, now)` states the SEND-grant rule once: a **live** binding
  whose `connector_id` is `telegram` and whose capabilities include the existing
  `telegram.send_document`. **A `telegram.read` grant is not a SEND grant** (#2010), and neither is
  a revoked or expired one.
- `build_claw_telegram_delivery_host_state(...)` binds the canonical delivery adapter from the host's
  trusted binding, bot scope, trusted binding authority (`resolve_bot_token` / `provider_chat_id`),
  artifact-material resolver, current-channel context provider, approval authority and account/actor
  refs — or returns `delivery=None` with one explicit reason per missing input.
- If the existing adapter rejects the supplied authorities on its own deeper structural rules (for
  example a material lookup that does not require `workspace_ref`/`run_ref`), the boundary fails
  closed and does not forward the adapter's message.
- `create_app(claw_telegram_artifact_delivery=...)` → `app.state.claw_telegram_artifact_delivery`,
  and `worker.py` passes the boundary result. Default `None` keeps it fail-closed.

The token, the chat id and the destination are **never** parameters of this module. They stay inside
the trusted binding and the source-owned transport, so neither a model nor a browser can supply them.
No grant, no token store, no channel authority and no second delivery adapter is created.

## Evidence (hermetic: local fakes only)

- `python -m pytest tests/test_3580_claw_telegram_delivery_host_composition.py -q` → **11 passed**.
- Focused regression: `test_claw_telegram`, `test_3580_claw_drive_upload_host_composition`,
  `test_b62_production_deploy_config`, `test_b62_3094_worker_local_access_composition`,
  `test_3989_ci_tests_only_scope_contract` → **93 passed**.
- Covered: no trusted input → `None` with a reason per input; READ-only grant refused and
  `telegram_send_grant_present` False; expired/revoked/naive-clock/None → False; all trusted inputs →
  canonical adapter bound to the composed transport; wrong connector and foreign scope refused;
  missing authority refused; scope-blind material lookup refused fail-closed; contradictory state
  refused; projection leaks no token/chat id/binding/workspace/chat ref; `worker.py` imports and
  passes the boundary result; `create_app` default keeps the seam `None`.

## Deployed shape (unchanged, truthful)

```text
HOST_INJECTION_BOUNDARY_IMPLEMENTED=True
PRODUCTION_TELEGRAM_DELIVERY_INJECTED=False
TELEGRAM_SEND_GRANT_AUTHORIZED=False        # #2010; seed allows TelegramCapability.READ only
REAL_TELEGRAM_DELIVERY=NOT_PROVEN
PRODUCTION_ACTIVATION=BLOCKED
PRODUCTION_MUTATION=0
BLOCKED_ON_OWNER_AUTHORIZATION=True
```

## Still open in #3580

1. `DriveWriteApprovalPort` host implementation on the **existing** approval authority — the only
   existing WRITE approval today is the Engine's Hark-quote P01 tool, which belongs to #3933 and is
   deliberately untouched.
2. A delivery consumer route that reads `app.state.claw_telegram_artifact_delivery` and executes a
   `ArtifactDeliveryExecutionRequest`. Without an owner-authorized SEND grant it would refuse anyway.
3. Real operational verification in #3936 once an owner-authorized WRITE/SEND grant exists.
