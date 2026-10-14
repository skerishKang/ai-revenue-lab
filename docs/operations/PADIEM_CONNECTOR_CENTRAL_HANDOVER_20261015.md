# PADIEM Connector / Claw first PC TXT — CENTRAL technical handover (2026-10-15)

**Classification:** public engineering facts, not private business policy. **Status:** handover only; no live release/E2E implied. Existing issue [#4139](https://github.com/skerishKang/ai-revenue-lab/issues/4139) remains open; Windows release acceptance is [#3099](https://github.com/skerishKang/ai-revenue-lab/issues/3099).

## 1. Definition of done — still unproven

Claw original conversation -> existing account/canonical Broker -> installed Windows Connector/Resident -> **real authorized bounded TXT READ on that PC** -> Broker-verified UTF-8 body/SHA-256 -> **same Claw conversation**.

Do not confuse fixture tests, an independent remote MCP probe, a green CI, a tray icon, or a synthetic Browser stub with real PADIEM Claw/Broker/Resident E2E. The working approach is to **reuse suitable open-source implementation source now** where it makes real connection, execution and result handling quicker. Do not require a new MCP service, Broker, external login, or complete full-desktop app. Existing file Reader is a candidate, not an obligatory rewrite milestone.

## 2. Observed GitHub refs (2026-10-15)

| Surface | Observed exact ref | Status |
| --- | --- | --- |
| main | `68b056a8d81980fa03725a84c188d889b70ccc15` | main at final inventory, may advance |
| CENTRAL integrated | [#4719](https://github.com/skerishKang/ai-revenue-lab/pull/4719) `72170803aa54c60a87ec0a547c7992e693cebfb5` | **OPEN DRAFT; unmerged; undeployed** |
| LOCAL2 Windows/Resident | [#4572](https://github.com/skerishKang/ai-revenue-lab/pull/4572) `e86ac6a581c67beb7a96eadc43527ad8b75e15b5` | latest GitHub-confirmed HEAD |
| LOCAL1 Broker TXT | [#4705](https://github.com/skerishKang/ai-revenue-lab/pull/4705) `a6c489897f94ef13cf9c851e991cc6f5a9818b09` | latest GitHub-confirmed HEAD |
| Production Request Port | `6c778923ad17b83286959fe20dc1ab7c6f6cfc3f` | cherry-picked into #4719 |
| Separate TXT implementation | [#4704](https://github.com/skerishKang/ai-revenue-lab/pull/4704) | **exclude from this integration** |
| Installer/R2 guidance | [merged #4710](https://github.com/skerishKang/ai-revenue-lab/pull/4710) | documents only, not a binary |

**#4719 lineage:** LOCAL2 `e86ac6a5` -> Request Port `1f06e472` -> LOCAL1 TXT result `9e41ecee` -> LOCAL1 pre-ACK race fix `71e70a13` -> **existing main** Claw TXT consumer `38dc4125` -> CI Core setup `c47a8abc` -> historical default-OFF CI assertion correction `72170803`. No #4704 TXT implementation was included.

**Later LOCAL2 report is not commit-proven:** LOCAL2 reported updates to `apps/claw-connect/claw_connect/agent_preflight.py`, `resident_launch.py`, `apps/claw-connect/install.ps1`, `apps/korean-ai-code-agent/src/kagent/local_agent_broker_production_entry.py`, and synthetic-agent packaging lists. Report says `make_production_request_port`, production-module preflight and `PADIEM_AGENT_VERIFIED_TEXT_PLAN_SOURCE` propagation were added, with 530 PASS / one unrelated dependency-environment FAIL / four skips. **The reported change came without a new SHA**. Do not assert it was pushed to #4572 or merged into #4719 until latest source blobs are checked.

## 3. What already works in source

- Existing Broker Durable Object / SQLite, authenticated device `POST /text-result`, private `read_verified_file_text_rpc`, bounded `content_utf8` + lowercase SHA-256; first TXT content bound is **768 UTF-8 bytes**. Source: `packages/padiem-control-plane/local_agent_broker_text_results.py` and canonical Broker HTTP/worker modules.
- LOCAL2 preserved **pending acknowledged by Broker -> actual authorized READ -> successful command ACK -> upload preserved text body**. Do not create body from stdout or from ACK; do not re-read after ACK.
- Existing main Claw `apps/padiem-chat/app/claw_local_task_result_projection.py` and `claw_local_task_result_composition.py` hold a pending file-read result instead of consuming the conversation's exactly-once message ID.
- Existing supervised `kagent.local_agent_resident_process` and production Request Port use the same canonical Broker. `kagent` is an internal package alias, not another product.

## 4. Earliest genuine blockers

**P01 pre-ACK verified TXT plan material is missing:**
- `apps/korean-ai-code-agent/src/kagent/local_agent_resident_process.py::verified_text_plan_source_from_environment()` requires `PADIEM_AGENT_VERIFIED_TEXT_PLAN_SOURCE=module:factory`, where the created source implements `approved_plan_for_admitted_command(binding, command, admitted)`. **No actual shipping TXT source backed by authenticated first-party approval was found.**
- Existing Engine `apps/padiem-ai-engine/app/hark_office_p01_receipt.py::ApprovedOfficeReadReceipt`, `hark_office_p01_durable_ledger.py::PrivateDurableOfficeReadLedger` and Resident `kagent/verified_engine_office_read_plan_source.py::VerifiedEngineOfficeReadPlanSource` are for **Hark Office XLSX** and **post-success-ACK** plans. They are NOT direct pre-ACK TXT authorization.
- Need smallest production **Engine TXT verified receipt sink/host binding resolver, private redeem, production admission reference wiring, and admitted-stage TXT factory**. Correlate owner/workspace/session/device/command, selected root, evidence and exact file path. Broker `evidence_ref/admitted_at` alone is admission evidence, not permission to fabricate a file READ grant. No fixture-based or automatic forged approval.

**Actual PC not enrolled:**
- Last read-only inspection of the representative Windows PC found installed Connector files but its enrollment status was `device_lifecycle=unpaired`, enrollment time unset and active credential generation absent. The installed pinned Agent root then lacked the production Request Port module.
- `apps/claw-connect/claw_connect/resident_launch.py::plan_resident_launch()` refuses non-live enrollment. Actual Resident installed runtime must receive `PADIEM_AGENT_DEVICE_ID`, `PADIEM_AGENT_AUTHORITY_REF`, `PADIEM_AGENT_CREDENTIAL_DIR`, `PADIEM_AGENT_REQUEST_PORT`, `PADIEM_AGENT_BROKER_URL`, `PADIEM_AGENT_VERIFIED_TEXT_PLAN_SOURCE`. `credential_install.py` had `CREDENTIAL_HANDOFF_WIRED=False` at inspection. Do not claim an installer or environment shim proves a successful real registration.
- Existing Broker/Worker/Claw production deployment and same-conversation real TXT read are **not verified**.

## 5. Focused proof already done; do not restart a test campaign

- At #4719 intermediate `38dc4125`: integrated Broker/Resident **89 PASS** and Claw **30 PASS**. Earlier deterministic cross-component regression failed because the old Claw consumer said `completed` instead of `pending`; the **existing main** consumer corrected it.
- On exact #4719 `72170803`, observed GitHub CI: **Control Plane CI PASS**, P01 Boundary, Operations Guard and B54 ingress/activation PASS, other related gates PASS; **B62 Padiem Chat CI FAIL, Validate B54 KAgent FAIL**, Browser QA in progress at last check. CI green is not claimed. No new tests performed by this handover.
- Do not bypass required security/authorization gates; do not let general full-suite/repeated mutation investigation replace the first real PC operation.

## 6. Minimal next-owner execution path (only under a new assignment)

1. Check the latest #4719/#4572/#4705/main refs and obtain the unreported LOCAL2 correction SHA; preserve already integrated material, keep #4704 out.
2. Complete the real existing-account/session/command authorization path and **admitted-stage verified TXT plan factory** before any success ACK. Reuse existing safe local file READ, Broker and OSS source where that shortens the critical path.
3. Update the **existing** installed Connector/Agent with production Port and all six actual settings; enroll this PC through the authorized existing system, honor visible tray OFF.
4. Deploy to the **existing** Broker/Cloudflare only with a working canonical source and enrollment. Do not create another server, account, or external MCP installation.
5. Request **one** safe bounded synthetic TXT from Claw; inspect the **original Claw conversation** for real PC body and checksum. If it fails, name the **first failing API/function**, rather than expanding tests.

**Eventual concise report only:** integration SHA; plan factory + real material origin; server/PC deployed Y/N; Claw returned real text Y/N; first failing API/function if N.

## 7. Adjacent release considerations

The standalone customer EXE/MSI has **not been built**, download size **not measured** (~30 MB is an optimization target), R2 bucket/download route **not deployed**. Cloudflare R2 Standard Internet egress is free, but storage/API operations can be charged. See [public installer/download runbook](PADIEM_CONNECTOR_INSTALLER_DISTRIBUTION_20261015.md). This packaging work is not a prerequisite for preserving the first genuine TXT connection workflow.

```text
PR_4719=OPEN_DRAFT_NOT_MERGED
LOCAL2_LATER_PATCH_SHA=UNAVAILABLE
REAL_P01_TXT_PLAN_FACTORY=NOT_PROVEN
REPRESENTATIVE_PC_ENROLLMENT=UNPAIRED_AS_LAST_OBSERVED
PRODUCTION_STACK_DEPLOYED=NO
SAME_CONVERSATION_REAL_TXT=NOT_PROVEN
```
