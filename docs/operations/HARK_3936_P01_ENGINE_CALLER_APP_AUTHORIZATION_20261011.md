# #3936 Hark WEB-FIRST P01 READ — Engine caller app authorization

**2026-10-11 KST. Source fix only; no Production deployment, no owner E2E, no user file access.**

## Live failure being fixed

One-shot `POST /api/claw/office/web-selections/{sel}/start-p01` on
`https://chat.padiem.net` returned **HTTP 409 `web_xlsx_p01_pause_refused`** with
the B62 private D1 reservation left at `dispatching` (browser status
`request_unknown`) and **zero** rows in the Engine
`padiem_web_xlsx_tool_continuations` table. Evidence:
[#3936 issuecomment-6107720471](https://github.com/skerishKang/ai-revenue-lab/issues/3936#issuecomment-6107720471).

## Actual root cause (proven at source)

The Engine authorizes the **requested app** of every authenticated internal call
*before* any service runs:

- `apps/padiem-ai-engine/worker.py` → `_authenticate_non_health_request` reads
  `app_id` from the request body and calls `authenticate_request(...)`.
- `apps/padiem-ai-engine/app/identity_enforcement.py` → `authenticate_request`
  resolves the overlay caller and calls `authenticate_engine_caller`.
- `apps/padiem-ai-engine/app/service_identity.py` → `authenticate_engine_caller`:

  ```python
  if requested_app_id not in caller.allowed_app_ids:
      raise ServiceIdentityError("service_app_not_authorized", ...)
  ```

The Chat P01 engine client
(`apps/padiem-chat/app/web_xlsx_p01_engine_client.py`) addresses
`/internal/v1/tools/execute` with `app_id = "padiem-web-xlsx-p01"`, but the
dedicated overlay caller `b54-p01-overlay-20260914-a1` (bound on the Chat side to
`P01_ENGINE_CALLER_ID`) was authorized for **only** the four connector apps
(`b54-padiem-claw`, `-drive`, `-telegram`, `-calendar`).

Therefore the Engine answered **403 `service_app_not_authorized`** before
`ToolExecutionEngineService` ran. No Core approval pause was issued, no Engine D1
continuation was written, and B62's transport collapsed the non-202 response into
its generic `WebXlsxP01RequestError` → public **409 `web_xlsx_p01_pause_refused`**.

Every other layer was verified healthy and is unchanged: the Engine Worker code
served in Production (`41b99c04`) contains the full #3580 P01 wiring; the three
READ flags and the `WEB_XLSX_PRIVATE_B62_D1` / `ENGINE_CONTINUATION` bindings are
present; the B62 D1 source/run/selection/SHA/object-key metadata satisfies every
`D1WebXlsxTrustedScopeResolver` predicate.

## Fix (minimal, additive)

`.github/scripts/b54_engine_caller_registry_overlay_rotation.py` — the canonical
overlay caller authority now registers the Hark WEB-FIRST XLSX **READ** Engine
tool app:

```python
ALLOWED_APP_IDS = (
    "b54-padiem-claw", "b54-padiem-claw-drive",
    "b54-padiem-claw-telegram", "b54-padiem-claw-calendar",
    "padiem-web-xlsx-p01",
)
```

Parity/gate tests updated to the new canonical set, plus a new cross-component
regression test that pins the app id the Chat client actually sends against the
caller registry entry, proves the Engine's own authenticator accepts it over the
exact overlay payload the rotation gate PUTs, and proves the pre-fix shape still
fails closed.

## Explicitly NOT changed

- **Approval verification is not relaxed.** The Engine still independently
  re-reads the private B62 D1 source, still enforces the Core
  `USER_CONFIRMATION` gate, and still requires the durable continuation. This is
  an app-authorization entry only.
- **WRITE is not registered *by this change*.** `padiem-web-xlsx-write-p01` was
  left out of the caller registry here, and WRITE/PDF flags, composition and
  migration 0010 were untouched. *Superseded for the registry entry only:* the
  #3933 follow-up
  (`HARK_3933_WEB_XLSX_WRITE_ENGINE_APP_AUTHORIZATION_20261011.md`) later adds
  the WRITE app as an app-authorization entry; the WRITE flags, composition and
  approval gates remain OFF there too.
- No B62 public contract change: the public failure stays a generic 409 with the
  one-shot reservation rule preserved.
- No #3580 Drive WRITE / Telegram SEND behaviour change.
- No base V1 registry mutation; no credential value or semantics change.

## Before Production (operator)

1. Run the **B54 Engine Caller Registry Overlay Rotation Gate**
   (`workflow_dispatch`, `ROTATE_B54_KAGENT_ENGINE_OVERLAY_FROM_EXACT_MAIN`) from
   the merged exact main SHA so the served Engine overlay carries the new app id.
2. Then re-run the one-shot live READ E2E with a **fresh** synthetic XLSX and a
   **fresh** selection reference. Never retry the consumed selection.
3. Migration `0009_web_xlsx_tool_continuations.sql` still has **no applier** in
   this repository and is an operator step; the `engine_read` activation gate
   verifies bindings but not this table. Confirm the table exists on the
   `padiem-engine` D1 before the live E2E.

**Labels:** `P01_READ_CALLER_APP_AUTHORIZATION_FIXED_IN_SOURCE=YES` ;
`APPROVAL_VERIFICATION_RELAXED=NO` ; `WRITE_PDF_TOUCHED=NO` ;
`PRODUCTION_DEPLOY_REQUIRED=YES` ; Keep #3936 OPEN.
