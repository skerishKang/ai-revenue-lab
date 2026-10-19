# Hark #3580: P01 registered approval scope and server-only Broker run correlation

Date: 2026-10-10. This is a Core/Engine contract fix, **not** customer-ready P01 file READ authorization or a Resident deployment.

## Confirmed prior failure

The real `OrchestrationEngineService` + Core ToolRuntime issued an approval pause for registered Office LIST/READ ToolInvocations, but the pause had `approval_scope=()` and its run ID was generated as `bridge_run_*`. The Windows file and candidate list permission ports require a matching registered `filesystem.read` scope and the exact Broker-selected-file run ID. An approved Engine continuation was insufficient.

## Code correction

1. `ToolRuntime.registered_approval_scopes(tool_id)` returns only the frozen registered ToolSpec's `auth_scope`. It does not grant any scope. ToolRuntime itself continues to verify authorization scopes and tool ownership/allowlist before emitting a USER_CONFIRMATION or EXTERNAL_AUTHORIZATION policy block.
2. On that exact policy block, Core `BoundedAgentRuntime` annotates the immutable ApprovalPause with the registered tool scopes instead of the previous empty default. Model arguments, browser payloads and tool-call output cannot choose or widen scopes; an ungranted declared scope still causes a terminal authorization denial, not a pause.
3. `OrchestrationRequest.trusted_agent_bridge_run_id` is a bounded optional **internal Python-only server field**. If and only if a trusted first-party orchestrator supplies it, the Plan Bridge executes and pauses under that exact ID; otherwise the existing random `bridge_run_*` remains unchanged.
4. The public Engine orchestration JSON decoder never maps this field. It explicitly returns 400 `invalid_request` if a browser attempts to insert it. Actual B62/Broker owner/run verification MUST happen before an authenticated server composes this internal field. No host authority is manufactured by adding the property.

## Tests

Core Agent runtime verifies preserved ToolSpec scope, ungranted scope denial, no public grant, default empty unchanged. Core OrchestrationRequest verifies trusted ID safe identifier bounds. Engine real `OrchestrationRunner` and existing smoke ToolRuntime verify internal exact ID+scope and public forged ID refusal; existing external verifier/continuation tests remain in scope. Focused regression: 42 PASS.

## Remaining before real Hark file execution

An owner/workspace/device/Broker-command/candidate correlated first-party Office approval producer (not #3140 test fixture) must create a real Engine LIST then selected-file READ pause, obtain user decision from existing first-party verifier and persist exact canonical approved evidence. The authenticated device-bound Broker/Resident handoff must deliver that evidence one-shot, correlate exact command/run/request/fingerprint, then inject the existing `office_p01_plan_source` in shipped Resident. Those layers must be implemented and verified with a real human-approved file; Engine continuation alone is not file READ. Keep #3580/#3933/#3936 open. No Production deploy, Secrets mutation, Drive upload, paid model call or user-file overwrite.