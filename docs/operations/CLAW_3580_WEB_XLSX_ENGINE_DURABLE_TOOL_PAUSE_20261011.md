# #3580 WEB-FIRST — Engine XLSX ToolRuntime pending invocation durability

**2026-10-11 KST. Source implementation only; no Production deployment or user-file access.**

## Added and changed

- `0009_web_xlsx_tool_continuations.sql` adds a **separate Engine D1 table** for canonical `padiem-web-xlsx-p01` continuations. A single D1 insert durably records the real Core `ApprovalPause` and its exact bounded ToolInvocation arguments (owner/workspace/original run/selection/doc/SHA256 and fixed intent flags). No workbook bytes, Drive credentials, local filesystem paths, provider prompts, model output, user text or secrets are stored. The generic Engine continuation D1 contract is unchanged.
- `D1WebXlsxToolPendingStore` exclusively accepts the fixed XLSX canonical app/agent/tool. It refuses generic `issue`. On record rehydration it recomputes the original Core ToolInvocation SHA-256, checks canonical identities and the closed XLSX intent schema; any changed stored identity fails closed. D1 `UPDATE ... WHERE state='active' AND expires_at>? RETURNING` provides a single claimer across independent Workers, with CAS commit/release and consumed-replay rejection. Claim/commit failures never pretend a user action succeeded.
- Existing `ToolExecutionEngineService` uses optional `issue_tool` and `load_tool_pending` methods only for an explicitly injected private durable store; it no longer needs isolate memory for that lane. All existing general ToolRuntime callers retain their previous memory-only behavior. Importantly, a verified decision alone is not a new Core grant: the resumed invocation still passes Core's original gates and independently checks active original D1 authority (from #4251).
- Engine Worker composition has a third, **independent operator-owned flag** `PADIEM_WEB_XLSX_P01_DURABLE_TOOL_ENABLED=true`, plus `PADIEM_WEB_XLSX_P01_ENGINE_SCOPE_ENABLED=true`, plus actual `WEB_XLSX_PRIVATE_B62_D1` and `ENGINE_CONTINUATION` bindings. This is OFF by default. Missing any binding leaves ToolExecutionService without continuation store; it cannot mint a fake pause.
- Tool cancel is NOT yet enabled for this adapter (503 fail-closed). Explicit owner decision/resume REST route, first-party verified per-tool grant and cross-service replay/decision binding are still future work.

## Verified locally

Actual SQLite migration 0009 (no mocks for atomic D1 transitions), Core real ToolRuntime pause, fresh independent `ToolExecutionEngineService` instance rehydrates identical owner/source/tool invocation from D1. One-shot DENIED consumes, APPROVED without separate server-owned Core grant fails closed and releases claim; only an explicitly test-injected server-owned grant permits deterministic approval-confirmation handler completion, with replay consumed. Cross-app resolution, concurrent claimant conflict, wrong token, corrupted DB hash/JSON/canonical tool, missing migration all fail closed. Existing Engine ToolRuntime and pre-pause owner-SHA D1 tests remain unchanged.

## Before Production

1. Apply migration 0009 to specifically authorized Engine D1 under separate operational approval. Provision the independently verified B62 private metadata D1 read-only binding. Check Worker flag/default posture and owner/tenant audit.
2. Build B62-specific owner approval/denial and Engine continuation transport with genuine first-party decision verifier and per-tool server-side Core grant. The current Engine's `AuthenticatedFirstPartyApprovalDecisionVerifier` alone **does not mint** the ToolAuthorizationContext confirmation flag. Never simulate grant from browser input.
3. Tie durable Engine continuation to the exact B62 owner-run `waiting_p01` handoff and SHA-verified original before non-destructive XLSX workcopy creation. Neither this step nor previous steps have completed that E2E.
4. Do not claim exactly-once completion: CAS prevents **duplicate claims** and replay, but a Worker crash while claimed requires explicit operational recovery (no automatic retries). No Production, Secrets, paid model, customer R2 read, Drive WRITE or Windows Resident mutation performed.

**Labels:** `ENGINE_TOOL_PAUSE_AND_INVOCATION_DURABLE_IN_TEST=YES` ; `OWNER_WEB_APPROVE_DENY_LIVE=NO` ; `PRODUCTION=OFF`. Keep #3580 OPEN.
