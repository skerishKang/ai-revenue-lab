# #4379: Model-native capacity — implementation work order (2026-10-20)

Status: **DESIGN/OWNER DIRECTIVE CAPTURED; NOT IMPLEMENTED BY THIS DOCUMENT**.
Scope: B14, Core, Engine/P01, B62 Chat, Claw, B66, Tool/Skill. Track source implementation in existing issue [#4379](https://github.com/skerishKang/ai-revenue-lab/issues/4379). Runtime Claw admin-tier 422 / shared 500–503 are separately tracked in [#5108](https://github.com/skerishKang/ai-revenue-lab/issues/5108).

## Latest owner implementation target

PADIEM must not impose its own arbitrary *total* model input/output/context/token/byte/wait/execution-step/tool-result budgets. Respect real provider/model capacities and hard infrastructure ceilings. Solve capacity via scalable execution, streaming/chunking/backpressure, durable storage references, async continuation, and additional runtime resources where needed. A larger invented number is not removal. Do not falsely describe a platform-imposed bound as removed.

Preserve real authorization, Free/Plus/Pro/Max eligibility, admin model authorization, tenant data isolation, prevention of duplicate side-effect execution, and effective security controls. Protocol **per-frame** limits and finite-resource protections must not silently become total answer/file/task caps. If a bounded resource cannot support the user's total output, redesign the path rather than unboundedly buffer in a Worker.

## Confirmed historical limits — inspect active callers and latest main

| Layer | Source / example | Historical bound |
| --- | --- | --- |
| Claw HTTP | `apps/padiem-chat/app/claw_general_routes.py` | `MAX_CLAW_GENERAL_BODY_BYTES=6_000_000` |
| Claw → Engine context | same file | `P01_ENGINE_REQUEST_ENVELOPE_BYTES=5_500_000` |
| B14 completed response | `packages/padiem-ai-core/padiem_ai_core/b14_execution.py` | `MAX_B14_RESPONSE_BYTES=1_048_576` |
| B14 configured completed maximum | same file | `MAX_CONFIGURED_B14_RESPONSE_BYTES=8_388_608` |
| Core tool request | `packages/padiem-ai-core/padiem_ai_core/tool_runtime.py` | `MAX_TOOL_ARGUMENT_BYTES=65_536` |
| Core tool result | same file | `MAX_TOOL_OUTPUT_BYTES=262_144` |
| B14/P01 time | B14 execution config / `apps/korean-ai-code-agent/src/kagent/p01_adapter.py` | defaults 600s / 900s |

The global 4,096 `max_tokens` ceiling was previously removed (commit `b67119315`). These entries identify source locations, not evidence that every value blocks a real active model call.

## Acceptance

1. Enumerate *current* source and production paths, owners and overlapping PRs; reuse prior #4379 merges. Distinguish model response budget from wire framing, file storage, session/security TTL, endpoint-specific limits and true provider errors.
2. Remove remaining PADIEM-owned arbitrary **cumulative** content and execution limits, using streaming/chunks/durable references for workloads larger than any given transport frame. Do not set a new fixed cumulative threshold under another name.
3. Preserve source-level policy and authorization guarantees; fail with the true reason and request ID when an actual provider/platform constraint is reached.
4. Focused tests: previously rejected long input, cumulative model output, large tool result, long-running asynchronous continuation, and model/tier/security regressions. Run only mandatory CI; one representative authenticated product path per affected lane.
5. Report `SOURCE_FIXED`, `MERGED`, `DEPLOYED`, `LIVE_VERIFIED` independently, with exact SHA, affected files, API response, and tests.
6. Do not label short-message Claw `tier=admin` 422 or unrelated service-wide 500/503 as byte/timeout failures absent server evidence.

Latest private governance resides only on authorized COM1. This public engineering work order does not reproduce private business-policy text.
