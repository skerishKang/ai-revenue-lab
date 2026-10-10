# #3580 Hark WEB FIRST — genuine Engine/Core P01 XLSX original confirmation tool

**2026-10-11 KST** · Backend **source contract** milestone (not connected production/browser E2E).

## Implemented

- New `app/web_xlsx_p01_tool_binding.py` uses the **existing Core ToolRuntime** and canonical `ToolSpec(approval_policy=USER_CONFIRMATION)` to create a real Engine P01 `ApprovalPause`, not a fabricated "waiting" JSON state.
- `TrustedWebXlsxSelectionScope` binds authenticated owner, workspace, original Hark run, opaque selection ref, original document ID, SHA-256 and explicit source-active/immutable flags. `web_xlsx_p01_arguments` accepts only that typed trusted scope.
- Canonical approved handler rechecks the exact trusted scope via an injected **server-owned resolver**, including all six identifiers and source state. It reports **intent confirmation only**: no R2 content read, working copy, output PDF, Drive write, model invocation or Windows access.
- Deployment remains explicitly **OFF**: registration requires *both* `enabled=True` and a server-authenticated selection resolver. Merely setting a public browser flag or constructing the core tool is insufficient.
- Actual Engine orchestration test proves Core `tool_user_confirmation_required` before handler invocation, original SHA-bound `ApprovalPause.invocation_sha256`, first-party Engine-verified APPROVED resume, once-only consume and DENIED not invoking handler. Invalid source identifiers, browser authority widening and other-source fingerprints fail closed.

## Missing connection (do not claim web P01 live)

The B62 `padiem_ai_engine_client.client._run_payload` currently rejects/deferred `tool_arguments` for `orchestrate`. The production B62 `/api/claw/approvals/decision` only resumes already issued canonical Engine orchestration handoffs, not a new source-selection request. Therefore **this Engine binding must NOT be enabled in production** until a reviewed, authenticated B62-to-Engine request adapter carries the server-owned original run/selection/fingerprint and writes the real Engine-issued pause to the owner/workspace `claw_approval_handoff` history. No browser-provided approval evidence or runtime selection-resolver substitute is acceptable.

Remaining WEB stages: authenticated Engine invocation transport/admission -> real owner-run pause and existing decision route -> after verified approved and one-shot consumed, verify R2 original SHA again and create an immutable-original-preserving working copy -> safe XLSX editor -> fidelity-checked PDF -> browser cards/preview. This milestone is `P01_CORE_ENGINE_SOURCE_TEST_PASS`, NOT `P01_B62_BROWSER_E2E_PASS` or `PRODUCTION_READY`.

No production env/settings, deployment, Secrets, customer files, model calls, Drive WRITE or Windows Resident mutation performed. #3580 remains OPEN.
