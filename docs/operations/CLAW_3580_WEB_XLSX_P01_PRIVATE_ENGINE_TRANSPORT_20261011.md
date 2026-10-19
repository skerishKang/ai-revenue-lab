# #3580 — WEB-FIRST B62 → Engine private ToolRuntime transport

**Date:** 2026-10-11 KST. **Implemented in source**; not proof of Production LIVE approval.

## Changed from PR #4245

- B62 now has `CloudflareWebXlsxP01EngineClient`, a **dedicated** one-way private pause request client for the actual Engine `/internal/v1/tools/execute` service endpoint. It does not widen the generic P01 orchestration client, provider function-calling or the public browser authority.
- The only body is a server-built `app_id=padiem-web-xlsx-p01`, `agent_id=agent:padiem:web-xlsx-confirm@1`, `tool_id=tool:padiem:web-xlsx-confirm@1` plus the trusted `TrustedWebXlsxP01Request` fields and read-for-workcopy intent flags. Owner/workspace/run/selection/document/SHA256 come from session and server D1 checks, not browser-supplied ToolInvocation arguments.
- The Engine endpoint URL is constant, reached only through the **existing** `P01_ENGINE_SERVICE` Worker Service Binding. Caller ID and credential use `p01_engine_config_from_worker_bindings`, not a new secret or URL. The request is bounded at 2 KiB; Engine response is bounded at 12 KiB via the common Cloudflare streaming response reader. No automatic retry.
- Worker composition requires all of: `runtime_mode=b14`, exact deployment flag `PADIEM_WEB_XLSX_P01_TOOL_DISPATCH_ENABLED=true`, valid preexisting P01 Engine binding/caller/credential. Otherwise the default B62 state stays `web_xlsx_p01_pause_client=None`, so the route returns its existing 503.
- **Protocol correction:** Engine `ToolExecutionEngineService.execute_payload` issues HTTP 202 `{"ok":true,"tool":...}`, not `{"orchestration":...}`. B62's `parse_engine_pause` now accepts only the real tool contract `padiem.engine.tools/1.0` with exact canonical agent/tool, server-issued paused run/continuation, ToolRuntime user-confirmation proof and selection-bounded expiry. Old simulated orchestration responses are rejected.
- The actual Core ToolRuntime pause from the ToolExecution service projects `approval_scope=[]` (its registered ToolSpec/authorization context separately enforces `workspace.xlsx.original.read.intent`). We have added a **live Engine service test** for this source contract; do not invent non-empty `approval_scope` in the wire. The Engine owns its exact ToolInvocation digest, approval verification and continuation.
- Browser receives only the existing request-ref and `waiting_p01` state with `owner_decision_enabled=false`. No Engine caller credential, original bytes, Drive token, local path or grant is exposed.

## Explicit blockers before enabling production

1. The Engine `with_web_xlsx_p01_tool_binding` is still OFF until a **trusted independent owner/workspace/run/selection SHA resolver** is composed on the Engine side. B62's assertion of an identity is not itself that Engine authority. No fake resolver is permitted.
2. Engine `ToolExecutionEngineService` currently retains the original pending invocation in an **in-memory `_pending` map**. Its continuation record alone is not sufficient to resume on a different isolate; a durable trusted invocation record with fingerprint and one-shot claim is needed before production approval/deny can work reliably.
3. B62's general `/api/claw/approvals/decision` consumes a different orchestration continuation contract. An XLSX **tool-specific** owner decision/resume adapter must be created before showing a real approve/deny button or asserting `P01_WEB_E2E=PASS`.
4. Migration 030 + live Worker/Engine registration, Production changes and customer files were **not** executed.

## Verification

- B62 targeted source/selection/request/private Engine adapter tests: 39 PASS.
- Engine ToolRuntime/real ToolExecutionEngineService cross-wire contract + existing Engine tool and P01 approval regression: 48 PASS.
- No paid provider, browser external request, user-file access, R2 read, XLSX workcopy, PDF, Drive WRITE, Windows Resident or Production deploy.

**NEXT WEB-FIRST:** Engine trusted private scope resolver, durable original invocation + verified one-shot ToolRuntime decision, browser owner decision flow, then separately verified workcopy with original SHA recheck. Keep #3580 OPEN.
