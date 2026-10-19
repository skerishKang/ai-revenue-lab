# #3580 — B62 WEB-FIRST owner-bound XLSX P01 request boundary

**2026-10-11 KST. Source-only request boundary; not a deployed or clickable P01 approval UI.**

## Actual implementation

- Adds authenticated `POST /api/claw/office/web-selections/{selection_ref}/request-p01` with JSON containing exactly `run_id`. B62 derives owner and workspace from its current signed-in session and source selection metadata from private D1; it also verifies the original XLSX's current private metadata fingerprint without opening R2 bytes.
- Requires an **existing, recent, running, owner/workspace-scoped Claw run** with linked conversation. Rejects foreign owner, stale/closed run, wrong workspace, expired/mismatched original, and caller-invented `decision`, `tool_arguments`, `workspace_id`, `source_sha256`, continuation, etc. The browser cannot choose the Engine app, tool, arguments, model, scope, source fingerprint or decision.
- `TrustedWebXlsxP01Request` is built exclusively from these server-verified facts and sent only to a private injected `start_pause()` Engine port. Its response must be an actual structured `padiem-web-xlsx-p01` Core/Engine paused-tool projection with exact tool id, confirmation requirement, scope, original selection-bound trace and bounded pause expiry. `completed` or fabricated approval projections are rejected.
- New migration `030_claw_web_xlsx_p01_requests.sql` and `D1WebXlsxP01RequestStore` durably **reserve one dispatch per original selection before the Engine call**, so network uncertainty never leads to a second paid/authorized operation. The Engine-returned continuation/pause identity is persisted only after validation; reservation remains unconsumed if the result is invalid or uncertain. No automatic retry, no memory store fallback, no browser-provided Engine authority.
- Successful result returns `status=waiting_p01`, `owner_decision_enabled=false`, `processing_started=false`, `workcopy_created=false`: no user-facing claim of functional approval buttons, file read or PDF output.

## Why production is still off

- `app.state.web_xlsx_p01_pause_client=None` by default; the real authenticated Engine web-XLSX source resolver / Engine Service Binding request adapter is **not yet composed**. The previous #4241 Engine-side confirmation tool also defaults disabled until the Engine can independently authenticate the trusted owner/workspace/run/source selection scope.
- Existing `/api/claw/approvals/decision` accepts **orchestration lane** handoffs only. Web XLSX must not reuse a different run's continuation or treat a merely paused request as authorization. The new D1 reservation is deliberately a separate owner-run P01-pending marker, **not an approval handoff** and **cannot be used to resume**. The next code phase must connect the Engine tool authority to this scope and implement verified user decision/one-shot continuation on this exact request, *then* reread SHA-256 and create a separately stored work copy.
- Migration 030 and any changes to Worker/Engine Production bindings must be applied only under explicit operational approval. Deploy/migration not executed here.

## Focused tests

Synthetic workbook only. Actual existing D1 migrations 029+030 on in-memory SQLite plus web routes with signed-in session: exact owner/file/run SHA, one-shot replay, concurrent requests, foreign identity, fake approval/tool authority fields, expired/wrong file, missing deployment binding or migration, Engine-projection mismatch, uncertain dispatch. No customer files, paid providers, Drive writes or Resident work.

**Gate labels:** `WEB_XLSX_P01_REQUEST_SOURCE_TEST_PASS` vs. `WEB_XLSX_P01_OWNER_DECISION_E2E=NOT_PROVEN` and `PRODUCTION_LIVE=NO`.
