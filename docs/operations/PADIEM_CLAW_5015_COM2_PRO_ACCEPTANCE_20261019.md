# PADIEM Claw #5015 — COM2/Pro PC drive E2E acceptance and Oracle→COM2 handoff (2026-10-19)

**Classification:** public technical evidence record. No private Governance text,
credentials, tokens or customer data are included. This file is not a business
decision, a model-selection approval or a Production release approval.

**Status (2026-10-19):**

~~~text
CLAW_PRO_PC_DRIVE_E2E=PASS        (one Claw conversation, one connected PC)
GENERAL_CHAT=NOT_VERIFIED
NEW_CONVERSATION_PC_RECOGNITION=NOT_VERIFIED
MULTI_DEVICE_SELECTION=NOT_VERIFIED
ANDROID_REMOTE=NOT_VERIFIED
OFFLINE_DENIED_NO_TOOL_USER_SWITCH=NOT_VERIFIED
COMMON_INSTRUCTION_CONTEXT_INJECTION=NOT_INDEPENDENTLY_PROVEN
FREE_EXECUTABLE_ROUTE_OMISSION=SEPARATE_FOLLOW_UP
UPSTREAM_MODEL_TELEMETRY=NOT_VERIFIED
#5015=OPEN
~~~

**Canonical entry for the 2026-10-19 acceptance:** this file. Historical
#4139/Oracle-era handover material remains in
[PADIEM_CONNECTOR_CENTRAL_HANDOVER_20261015.md](PADIEM_CONNECTOR_CENTRAL_HANDOVER_20261015.md)
and is superseded for the executor host/state by the note at its top.

## 1. Verified success (exact evidence)

| Item | Observed value |
| --- | --- |
| Producer fix | PR [#5106](https://github.com/skerishKang/ai-revenue-lab/pull/5106), merged `8095b871f6606ea82bd0eb814ddc75b04bd3a71f` (2026-10-19T08:47:41Z) |
| Engine deployment | B54 Engine Production Deploy Gate run [39225322645](https://github.com/skerishKang/ai-revenue-lab/actions/runs/39225322645) SUCCESS, target `8095b871`; active Engine version `bc31a4ec-d2f6-49b7-be51-e5122876271a` (no git tag on that automatic deployment; the run target is `8095b871`) |
| Chat deployment | active `536d1ea2-b377-48db-8be6-950f9a738e3e`, tag `git-0c9334ae9f4447c0051e900ab1959b457a2a0b37` (consumer parser chain #5102/#5103; final #5106 is Engine-only) |
| Run | `run_08578c3d8f4746a88732a8f3`, action `txt_read`, status `completed` (created 2026-10-19T08:50:37Z, updated 08:50:49Z) |
| Dispatch | `dsp_841b9458d3e445438a32d8fd6e5610e8`, state `done`, kind `command` |
| Command | `Get-PSDrive -PSProvider FileSystem \| Select-Object Name,Root,Used,Free \| ConvertTo-Json` |
| Result | `516` bytes, SHA-256 `724e02d71864f03159b9bd90adda98e00c99ae0355cf6c9f20f85881f6545cb0` |
| Termination | `no_exit_code` (cmdlet-only pipeline; recorded as-is, not converted to exit 0) |
| Model scope | requested **Padiem Pro**; effective route `opencode-go/muse-spark-1.3-contributor`. The upstream provider's actual model ID was **not independently observed** (no bounded upstream-model telemetry). |
| Conversation display | The PC drive result (C:, D:, E:, G: with used/free values) appeared in the **same original Claw conversation message** without a reload and without a follow-up message. |
| Executor path | COM2 WSL executor received the dispatch, MeshCentral ran the command on the COM1 PC `Padiem-Command-Center`, and the verified result returned to the Engine/Chat run. |

The previous failures in the same conversation are historical attempts from
before the fixes below. They are not evidence that the current path is failing.

## 2. Oracle era vs current COM2

| Surface | Oracle era (historical evidence) | COM2 era (current) |
| --- | --- | --- |
| Relay/executor host | Oracle `168.138.200.12`: MeshCentral and executor | COM2 WSL Ubuntu on `K_lipvoice` (`192.168.0.101`): MeshCentral and executor |
| Actual work target | COM1 `Padiem-Command-Center` | Same COM1 PC |
| MeshCentral | Oracle-hosted; COM1 tunnel `127.0.0.1:4443` target `oracle` | COM2 WSL `127.0.0.1:4443`; COM1 tunnel target `comp2` |
| Executor | Oracle process polling the Chat channel | COM2 systemd executor, sole live poller; Oracle executor stopped |
| COM1 tunnel | `PADIEM-Mesh-Tunnel` target `oracle` | `PADIEM-Mesh-Tunnel` target `comp2` (Git ssh; Windows OpenSSH not used) |
| Web/Engine | Cloudflare Chat (B62) and Engine (P01) | Same Cloudflare products; Engine result producer changed by #5106 |
| Explicit command | Proven in the Oracle-era handoff (#4139 §9) | Re-proven on COM2 on 2026-10-18 |
| TXT read | Proven in the Oracle-era handoff (#4139 §10–§11) | Re-proven on COM2 on 2026-10-18 |
| Natural-language tool selection | **No record found in the Oracle-era evidence. UNCONFIRMED — do not infer from the explicit command/TXT lanes.** | **PASS on 2026-10-19** with Padiem Pro (this record) |
| Claw product identity/path | Explicit lanes used the Chat routes/staged dispatch; natural-language identity path not evidenced | Claw app `b54-padiem-claw`, plan agent `agent:padiem:claw-pc-query@1`, Claw internal endpoint `/internal/claw/engine-pc-drive`, shared B54 canonical session bridge |
| Result delivery | Same conversation for explicit/TXT | Same conversation for the natural-language run; pending-result/original-conversation display |
| Executor state | Stopped (kept as recovery) | Active; COM2 MeshCentral, executor and health timer active; Mesh mode `mesh` |

The Oracle→COM2 cutover itself (tunnel/agent reachability, path handling,
zero-byte result handling, ownership-map account, duplicate-executor prevention)
is separate from the later contract defects in §3. None of the 2026-10-19
failures was caused by "COM2", a PC being offline, a token/credential problem or
model performance; the confirmed causes are the parser/producer and identity
contract defects listed below.

## 3. Failure and fix chain (symptom → cause → fix → verification → service)

| PR / merge | Symptom | Cause | Fix location | Verification | Deployed service |
| --- | --- | --- | --- | --- | --- |
| [#5074](https://github.com/skerishKang/ai-revenue-lab/pull/5074) `8508bbe5` | A completed Mesh result stayed invisible; the owner pending-result read returned 503 and the browser stopped polling. | D1 rejects a `LIKE` pattern longer than 50 characters; the split-part pattern `msg_ltr_…_p%` is 51 characters. | `apps/padiem-chat/app/history.py` `get_claw_run_result_message` (substr prefix equality). | Live D1 reproduction; focused tests; mutation proof; live hostname/TXT display. | Chat |
| [#5081](https://github.com/skerishKang/ai-revenue-lab/pull/5081) `fbc4f7aa` | The model-selected drive query failed before dispatch with `invalid_tool_arguments`. | The Engine streaming lane (`prepare_stream`) did not compose the PC-query step driver; the Core plan-backed driver injected a `query` argument the drive tool schema rejects. | `apps/padiem-ai-engine/app/orchestration_service.py` `prepare_stream` step-driver composition. | Focused Engine tests; mutation proof; live stage logs. | Engine |
| [#5088](https://github.com/skerishKang/ai-revenue-lab/pull/5088) `e7baa2c4` | `pc_query_denied` (HTTP 401) before dispatch. | The Claw-originated request used the Claw internal route, which required a separately active b54 product session; the owner's active session is the Chat product. The Chat-identity detour was removed. | `apps/padiem-chat/app/oracle_mesh_read_return_routes.py` reuses the shared B54 canonical-session bridge; Claw identity/path restored. | Engine tail (`pc_query_chat_call` status); route tests; the Chat identity revert. | Chat |
| [#5100](https://github.com/skerishKang/ai-revenue-lab/pull/5100) `3c388273` | `control_plane_rpc_invalid` at the `product_user` bridge stage. | The Control Plane reverse lookup returns the scalar `{"ok":true,"product_user_id":"usr_…"}`; the Chat client expected a nested `product_user` object and rejected every valid reply. | `apps/padiem-chat/app/control_plane_identity_worker.py` (RPC envelope + scalar reverse lookup). | Scalar/nested-shape contract tests; bounded stage log. | Chat |
| [#5102](https://github.com/skerishKang/ai-revenue-lab/pull/5102) `1cf0326b` | `p01_stream_invalid_result` after a successful PC run. | `ToolEvent.to_public_dict()` includes `error_code`, but the closed result parser's allowed-key set omitted it (`unsupported_result_field`). | `packages/padiem-ai-core/padiem_ai_core/orchestration.py` tool-event parser. | Round-trip test + mutation proof. | Chat (shared Core parser bundled in Chat) |
| [#5103](https://github.com/skerishKang/ai-revenue-lab/pull/5103) `0c9334ae` | Same generic stream failure after the previous parser fix. | A successful PC result carries an `AgentPlan`; the parser rejected every plan as `unsupported_result_plan`. | `orchestration.py` reconstructs a validated `AgentPlan` through the existing `AgentPlan`/`AgentPlanStep` rules. | PC plan + synthetic tool event round-trip; invalid-plan negative tests; mutation proof. | Chat (shared Core parser bundled in Chat) |
| [#5106](https://github.com/skerishKang/ai-revenue-lab/pull/5106) `8095b871` | `p01_result_correlation_mismatch` after the parser accepted the result. | The plan success/resume/approval-pause result builders omitted `RunMetadata.session_id`; the Chat P01 correlation rejected the otherwise valid run. | `orchestration.py` carries `request.execution_request.session_id` into all three result builders. | Plan + synthetic tool runner test; public parser round-trip; Chat correlation mismatch test; mutation proof. | **Engine** (Core result producer) |

## 4. Why individual tests passed while the screen kept failing

- The early tests added one field to a **generic completed-result fixture**. They
  did not exercise the actual PC-plan producer path, so `plan`, the tool event
  `error_code` and the producer's `session_id` were never all present in one
  terminal payload.
- Each parser fix therefore exposed the next missing field: `error_code` →
  `plan` → `session_id`. The adapter collapses the inner parser/correlation
  error into `p01_stream_invalid_result` (failure detail `p01_contract_failure`),
  so the screen showed one generic connection error regardless of the specific
  cause.
- The live screen also requires the full chain: model tool selection → P01 →
  Mesh dispatch → COM2 executor → COM1 execution → result → Core parser →
  P01 request/result correlation → Claw event/result projection. A test that
  stops before the producer path cannot certify that chain.
- Bounded stage diagnostics (#5092/#5098 and the Chat failure log) were required
  to expose `product_user`, the parser fields and the correlation stage; the
  production run itself did not repeat blindly.

## 5. Recurrence-prevention verification contract

The full contract must be verified offline with the **real PC-plan execution
code and a synthetic tool**, not only with a hand-built generic result:

~~~text
real PC plan execution code + synthetic tool
  -> Engine terminal result serialization
       (plan, tool event error_code, run session_id)
  -> Core result parser (orchestration_result_from_public)
  -> P01 request/result correlation
  -> Claw event/result projection
~~~

Required positive/negative checks:

- The request's `execution_request.session_id` (the run id) is preserved in the
  result and passes the P01 correlation.
- A different run id is refused (`p01_result_correlation_mismatch`).
- The plan is reconstructed through the existing `AgentPlan`/`AgentPlanStep`
  validation; invalid, cyclic, reordered or over-budget plans remain refused.
- `error_code` is accepted only as a bounded tool-stage identifier.
- The Claw result projection exposes the drive text and keeps the original
  conversation correlation.

Do not weaken these checks. Do not let a consumer overwrite `plan` or
`session_id` to make a test pass.

**Deployment split:** a consumer-parser change (the shared Core parser bundled in
the Chat worker) requires a **Chat** deployment; a result-producer change in the
Engine's Core requires an **Engine** deployment. #5102/#5103 were Chat-side
consumer changes; #5106 was an Engine-side producer change.

## 6. Remaining and unverified scope

| Scope | Status | Existing tracker |
| --- | --- | --- |
| Claw natural-language drive query, existing conversation, one connected PC, Padiem Pro | **PASS** (this record) | #5015 |
| General Chat natural-language PC query | NOT VERIFIED | [#4317](https://github.com/skerishKang/ai-revenue-lab/issues/4317) |
| New conversation / new session PC recognition | NOT VERIFIED | #5015 "PC device dashboard" section |
| Multiple device list and selection | NOT VERIFIED | #5015 "PC device dashboard" section; [#1651](https://github.com/skerishKang/ai-revenue-lab/issues/1651) is CLOSED and is not multi-PC evidence |
| Android remote connector | NOT VERIFIED | [#5080](https://github.com/skerishKang/ai-revenue-lab/issues/5080) |
| Offline / permission denied / no tool / user-switch behavior | NOT VERIFIED in this live pass | #5015 completion condition; focused tests required |
| Common instruction + dynamic PC context injection proof | NOT INDEPENDENTLY PROVEN | #5015 / #4465 |
| Free executable-route omission (`beam-free` not in the P01 executable pin set) | SEPARATE CONSUMER-CONTRACT DEFECT; not a prerequisite of the Pro path | [#5002](https://github.com/skerishKang/ai-revenue-lab/issues/5002), [B14 Free rollout status](B14_FREE_ROLLOUT_REPO_WIDE_STATUS_2026-10-18.md) |
| Upstream actual model ID telemetry | NOT VERIFIED; only the Pro route is recorded | [#4318](https://github.com/skerishKang/ai-revenue-lab/issues/4318) model/Engine E2E lane |
| Windows Alpha/real pairing acceptance | Separate acceptance | [#3099](https://github.com/skerishKang/ai-revenue-lab/issues/3099) |
| Claw full E2E (other features) | Separate acceptance | [#3936](https://github.com/skerishKang/ai-revenue-lab/issues/3936) |

**#5015 closure judgment:** the Claw/Pro representative-request completion
condition is now satisfied, but the issue's Chat, new-conversation,
multi-device, offline/denied and instruction/context conditions are not. #5015
therefore remains **OPEN**; this record does not promote the Claw Pro success to
whole-product completion.

## 7. Canonical entry points

- This acceptance record (2026-10-19 Claw/COM2/Pro): this file.
- Live product tracker: [#5015](https://github.com/skerishKang/ai-revenue-lab/issues/5015).
- Closed connector history and Oracle-era evidence:
  [#4139](https://github.com/skerishKang/ai-revenue-lab/issues/4139) and
  [PADIEM_CONNECTOR_CENTRAL_HANDOVER_20261015.md](PADIEM_CONNECTOR_CENTRAL_HANDOVER_20261015.md).
- Model/provider authority and route evidence: [models index](../models/README.md).
- Test/evidence scope: [TEST_SCOPE_AND_DELIVERY_POLICY.md](TEST_SCOPE_AND_DELIVERY_POLICY.md).
- Repository operating rules: [AGENTS.md](../../AGENTS.md).
