# #3936 Claw → Engine P01 dispatch — bounded stage attribution for a refused start

**2026-10-11 KST. Source + tests only.** No Production deploy, no Production D1 mutation, no
customer file, no WRITE/PDF, no Drive WRITE, no Telegram SEND, no secret change, no model call.

Ownership: the **Engine caller-registry registration** (overlay rotation payload and
`ALLOWED_APP_IDS`) is **LOCAL1's** remit and is **not** part of this change
(#4350 registered the READ app, #4363 the WRITE app). This record covers only the **B62
diagnostic seam** that makes a refusal attributable after the fact.

## Live failure being explained (CENTRAL CTO Production QA, `https://chat.padiem.net`)

Signup/login 200 → XLSX upload 201 → file selection 201 → original download 200 with matching
SHA-256 → P01 `not_requested`, `owner_request_enabled=true` → **POST
`/api/claw/office/web-selections/{selection_ref}/start-p01` (body `{}`) → 409
`web_xlsx_p01_pause_refused`** → state `request_unknown`, `owner_request_enabled=false`, no
workcopy. The B62 reservation row stayed `dispatching` and
`padiem_web_xlsx_tool_continuations` had **0 rows**, so no pause was ever materialized.

## Failure boundary in the Claw → Engine path

```
B62 start-p01 route
  → D1 reserve (dispatching)
  → B62 private Engine client  POST /internal/v1/tools/execute
  → Engine caller authentication  (identity_enforcement.authenticate_request)
  → Engine app authorization      (service_identity.authenticate_engine_caller)   ← refusal here
  → trusted tool binding → Core ToolRuntime pause → Engine D1 continuation
```

`service_identity.authenticate_engine_caller` requires `requested_app_id in
caller.allowed_app_ids` and otherwise raises `service_app_not_authorized`, which `worker.py`
returns as **HTTP 403**. That is a bounded authorization answer, **not** an outage and **not** the
generic `502 engine_execution_failed` used by the ordinary Claw execute/approval path — the two
must never be conflated. Before this change B62 collapsed every distinct private Engine outcome
into the single generic `409 web_xlsx_p01_pause_refused`, so the live cause was invisible in the
browser and in the reservation row.

## What this change adds

A **bounded, non-secret** attribution seam at the B62 dispatch boundary. It does not change any
public response, any authorization rule, the one-shot D1 reservation, or the no-retry rule.

- `apps/padiem-chat/app/web_xlsx_p01_refusal.py` **(new)** — closed stage vocabulary, an
  allowlisted Engine-error-code → stage map, a closed event shape, and an emitter that can never
  fail the request path.
- `apps/padiem-chat/app/web_xlsx_p01_engine_client.py` — a real Engine refusal (caller auth, app
  authority, source authority, continuation store, tool runtime) is now attributed instead of
  discarded.
- `apps/padiem-chat/app/claw_web_xlsx_p01_request.py` — an optional bounded `stage` on
  `WebXlsxP01RequestError`, separating `reservation_refused`, `pause_commit_failed` and
  `engine_pause_contract_mismatch`.
- `apps/padiem-chat/app/claw_web_xlsx_p01_start_routes.py` — exactly **one** event per attempt;
  the public `409 web_xlsx_p01_pause_refused` / `503 web_xlsx_p01_dispatch_unknown` answers are
  byte-identical to before.

### Diagnostic stages, HTTP status and event

| Stage constant | Boundary that produced it | Public answer |
| --- | --- | --- |
| `engine_pause_issued` | verified Engine pause + durable B62 commit | 202 `waiting_p01` |
| `engine_app_not_authorized` | Engine app authorization (403 `service_app_not_authorized`) | 409 |
| `engine_caller_unauthenticated` | Engine caller credential (401 `service_authentication_failed`) | 409 |
| `engine_identity_unavailable` | Engine identity/overlay unavailable or misconfigured | 409 |
| `engine_source_authority_denied` / `..._unavailable` | trusted source authority lookup | 409 |
| `engine_approval_verification_unavailable` | approval verifier | 409 |
| `engine_continuation_store_unavailable` / `..._capacity_exceeded` / `engine_continuation_unusable` | durable continuation store | 409 |
| `engine_tool_runtime_unavailable` / `engine_tool_binding_resolution_failed` | tool binding / ToolRuntime | 409 |
| `engine_request_rejected` / `engine_tool_not_authorized` / `engine_tool_timeout` / `engine_internal_error` | tool request contract, tool authority, tool terminal outcome | 409 |
| `engine_status_client_error` / `engine_status_server_error` / `engine_status_unexpected` | well-formed but unregistered Engine code, bounded by status class only | 409 |
| `engine_transport_unavailable` / `engine_response_unreadable` | private Engine transport / body | 409 |
| `engine_did_not_pause` / `engine_pause_contract_mismatch` | Engine answered but no closed pause contract | 409 |
| `reservation_refused` | B62 D1 reservation (the only in-principle retryable stage) | 409 / 503 |
| `pause_commit_failed` | Engine paused but B62 could not persist it | 409 |
| `engine_dispatch_unknown` | uncertain dispatch (reservation retained, browser must GET status) | 503 |

Event name: `web_xlsx_p01_dispatch` (service `padiem-chat`), one structured JSON line per attempt.

### Evidence boundary

An emitted event carries **only** fixed constants from the module plus an integer Engine HTTP
status (100–599) and an allowlisted Engine error code. It never contains an owner, workspace, run,
selection, document or conversation identifier, a source hash, a credential, cookie or token, a
continuation/pause reference, workbook bytes, Engine message text, a raw response body or any
caller-supplied string. A code outside the allowlist collapses to `engine_code_unrecognized`, so a
future or hostile Engine reply cannot inject text into the log stream.

### No SSE error event was added

The ordinary Claw execute path's SSE error contract (`error` frames carrying
`engine_execution_failed`, and the `claw_general_approval_required` / `done` terminators in
`claw_live_events.py`) is **untouched** by this change: no frame kind, code, completion or failure
rule was added, removed or reordered. Regression evidence below.

## Verification (local, offline, hermetic — no Production access)

| Check | Result |
| --- | --- |
| `tests/test_3936_p01_engine_refusal_diagnostic.py` + `tests/test_3936_web_xlsx_p01_cross_app.py` | **12 passed** |
| Focused P01 / web-XLSX suite (`test_3580_web_xlsx_*`) | **84 passed** |
| Claw general + SSE / stream regression (answer DOM, recovery truth, history projection, model hold, P01 routing, route ordering, live SSE relay, stream fail taxonomy, upstream error mapping/busy diagnostics) | **125 passed** |

- The cross-application harness runs the **real** B62 `/start-p01` route against the **real**
  Engine identity module, the **real** canonical overlay payload built by the rotation gate script
  and the **real** Engine `ToolExecutionEngineService`: caller authentication PASS, **foreign app
  id refused with `service_app_not_authorized` as the negative control**, owner upload/selection
  PASS, original SHA preserved, Engine pause issued, B62 request committed, Engine continuation
  durable, and no identifier/credential leak.
- The refusal diagnostic reproduces the exact live Production refusal shape
  (403 `service_app_not_authorized`) and proves the public answer stays
  `409 web_xlsx_p01_pause_refused`, the reservation stays retained and single-row, and exactly one
  bounded event is emitted with no request material in it.
- The classifier is proven closed: well-formed-but-unknown codes are bounded by status class, and
  hostile codes (mixed case, embedded newline, 300 chars, non-string, mappings, sequences) never
  reach the event.
- An exploding emitter cannot change the public answer.

## Scope boundary

- **Not touched:** `.github/scripts/b54_engine_caller_registry_overlay_rotation.py`, the overlay
  rotation gate workflow, the P01 caller-id parity / rotation gate tests, and every
  `apps/padiem-ai-engine/**` file. File-level overlap with #4363 is **zero**.
- **Read-only dependency:** the cross-application harness *imports* LOCAL1's canonical overlay
  payload builder (`build_overlay_payload` / `build_overlay_put_body`) so the test authenticates
  against the exact payload the rotation gate PUTs. It reads that module; it does not modify it and
  it duplicates none of it.
- No B14 model restriction or routing policy change; no retry added; no automatic model change on
  error; no Production secret, flag or binding touched.

## Status

`SOURCE=YES` ; `FOCUSED_AND_REGRESSION_TESTS=PASS` ; `CALLER_REGISTRY_TOUCHED=NO` ;
`OVERLAP_WITH_4363=0` ; `SSE_CONTRACT_CHANGED=NO` ; `PRODUCTION_DEPLOY=NOT_EXECUTED` ;
`PRODUCTION_RETEST=NOT_EXECUTED`. Keep #3936 OPEN.
