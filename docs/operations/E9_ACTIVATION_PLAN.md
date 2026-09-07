# E9 Engine Capability Activation Plan and Infrastructure Audit

- Issue: #1753
- Parent program: #1743
- Repository: skerishKang/ai-revenue-lab
- Authority: Issue #1753 — creation of this plan does NOT authorize any Production mutation.
- Evidence model: `docs/operations/EVIDENCE_REQUIREMENTS.md`; deployment policy `docs/operations/DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md`

## 1. Purpose

Turn each accepted Engine source capability (`SOURCE_ACCEPTED`) into a bounded,
individually reversible Production activation (`ACTIVATED`), and migrate reference
products from product-local generic paths only after shared Engine parity is proven.

Each activation is tracked separately and never bundles unrelated capabilities
into one cutover.

```text
SOURCE_ACCEPTED
 -> exact deployment/config authority audit
 -> rollback anchor
 -> Preview/controlled environment activation
 -> synthetic/non-sensitive structural probe
 -> reference Product parity probe
 -> failure/rollback proof
 -> explicit Production authorization
 -> bounded Production activation
 -> post-activation evidence
 -> manifest AVAILABLE review
```

## 2. Manifest audit result (current main)

Source of truth: `apps/padiem-ai-engine/app/capability_manifest.py` at
origin/main `e7453cfd` (family `padiem-ai-engine`, major 1, version 1.0).

| Unit | Capability id | Manifest state | Routes | Notes |
|---|---|---|---|---|
| A0 | `multi_caller_identity` | `AVAILABLE` | () | caller identity bounded; no dedicated route |
| A1 | `web_search` | `DEFERRED` | `RESEARCH_PATH` | REVERTED_TO_DEFERRED per §12 amendment (WO-7, owner decision D2) |
| A1 | `web_fetch` | `DEFERRED` | `RESEARCH_PATH` | REVERTED_TO_DEFERRED per §12 amendment (WO-7, owner decision D2) |
| A1 | `deep_research` | `DEFERRED` | `RESEARCH_PATH` | REVERTED_TO_DEFERRED per §12 amendment (WO-7, owner decision D2) |
| A2 | `evidence_citations` | `AVAILABLE` | EXECUTE, STREAM, RESEARCH | already on bounded B14 authority |
| A3 | `tool_runtime` | `AVAILABLE` | TOOL_EXECUTE/RESUME/CANCEL | Production-activated (bounded dispatch, see §13) |
| A4 | `memory_rag` | `DEFERRED` | MEMORY, MEMORY_WRITE | tenant-bounded, not Production activated |
| A5 | `agent_skill_runtime` | `DEFERRED` | AGENT_SKILL_RUN/RESUME/CANCEL | not Production activated |
| A6 | `file_document_multimodal` | `DEFERRED` | MULTIMODAL_EXECUTE, DOCUMENT_CONTEXT | tenant-bounded |
| A7 | `tenant_entitlement_usage_admission` | `DEFERRED` | () | E7 adapter source exists (`tenant_auth.py`); trusted authority not wired |
| A8 | cross-product manifest/conformance | `COMPLETED` (ledger) | n/a | manifest + conformance suite merged via #1944; conformance gate in CI |
| A9 | `idempotency` | `DEFERRED` | ORCHESTRATE_PATH | existing #1621 durable idempotency activation |
| — | `continuation/approval` | `DEFERRED` | ORCHESTRATE_RESUME_PATH | DEFERRED — BLOCKER_C1, see P01_ENGINE_APPROVAL_CONTINUATION_ACTIVATION_v1.md |
| — | `public_browser_api`, `provider_selection` | `UNAVAILABLE` | () | not offered by this contract version |

Notes:

- `require_capability` fails closed: a `DEFERRED`/`UNAVAILABLE`/unknown
  capability or an incompatible major never silently degrades.
- The conformance suite (`apps/padiem-ai-engine/tests/test_capability_conformance.py`)
  cross-checks manifest state against routed service truth and runs in CI.

## 3. Activation unit disposition

| Unit | Issue | Disposition now |
|---|---|---|
| A0 multi-caller identity | #1698 | already `AVAILABLE` in manifest — no activation needed; record as verified |
| A1 Web / Research | #1744 | **REVERTED_TO_DEFERRED** — §12 amendment (WO-7, owner decision D2, 2026-09-06) |
| A2 Evidence / Citation | #1745 | already `AVAILABLE` — record as verified |
| A3 Tool Runtime | #1746 | **ACTIVATED** — owner-authorized bounded Production dispatch (§13) |
| A4 Memory / RAG | #1748 | `DEFERRED` — pending |
| A5 Agent / Skill | #1749 | `DEFERRED` — pending |
| A6 File / Multimodal | #1750 | `DEFERRED` — pending |
| A7 Tenant / Entitlement / Usage | #1751 | `DEFERRED` — E7 source accepted; activation pending |
| A8 Cross-product manifest/conformance | #1752 | `COMPLETED` — ledger + conformance gate on main |
| A9 durable idempotency | #1621 | `DEFERRED` — existing durable idempotency activation applies |

## 4. First activation selection: A1 Web / Research (#1744)

Chosen by Web CTO for the first capability-by-capability activation.

Rationale:

- `web_search`, `web_fetch`, `deep_research` are the reference Web/Research
  capability family with real `RESEARCH_PATH` routes already present
  (`apps/padiem-ai-engine/app/web_research_service.py`).
- Stateless per-request research work: no durable object, queue, or storage
  migration is required for the first activation, so the rollback surface is
  minimal.
- Reference consumers: LoveBud Scout (first completed-execution consumer) and
  B30 400 AI Finder (strong Web/Research/Evidence reference) provide concrete
  parity probes.
- It establishes the repeatable activation pattern (rollback anchor → controlled
  activation → synthetic probe → parity → rollback proof) before harder,
  stateful capabilities (A3/A4/A6/A9) are attempted.

## 5. A3 Tool Runtime activation prep (#1746)

Second activation target (preparation complete, owner authorization pending).

Rationale:

- `tool_runtime` (`TOOL_EXECUTE_PATH`/`TOOL_RESUME_PATH`/`TOOL_CANCEL_PATH`) is
  already implemented in `apps/padiem-ai-engine/app/tool_execution_service.py`
  and reuses the real Core `ToolRuntime`; only Production activation is missing.
- Rollback surface is bounded: no durable object/queue migration is required and
  the approval/continuation path is already server-authority gated by Core.
- Reference consumers: **B62 Padiem Chat** and **B54 Padiem Claw** share this
  Engine capability; the parity probe is structural and imports no product code.

Readiness record (no Production mutation authorized):

```text
ACTIVATION_GATE_MODULE = apps/padiem-ai-engine/app/tool_runtime_activation.py
ACTIVATION_GATE_TESTS  = apps/padiem-ai-engine/tests/test_tool_runtime_activation.py
CONFIRMATION_TOKEN     = ACTIVATE_ENGINE_A3_TOOL_RUNTIME
CURRENT_DEPLOYED_VERSION = 26288341 (deploy run 33980178544)
ROLLBACK_VERSION       = 8d4db98c (previous successful deploy run 33970133859)
CONFIG_BINDING_DIFF    = none
SECRET_NAME_DIFF       = none (names only)
SYNTHETIC_PROBES       = tool_execute / tool_resume / tool_cancel
REFERENCE_CONSUMERS    = b62-padiem-chat, b54-padiem-claw
REAL_PROVIDER_CALLS    = 0
REAL_USER_DATA         = 0
FINAL_DISPOSITION      = PENDING_PRODUCTION_AUTHORIZATION
```

The manifest entry for `tool_runtime` remains `DEFERRED` (comment records
`PENDING_PRODUCTION_AUTHORIZATION`) until a separate owner-authorized dispatch
runs the gate, proves parity, and completes the bounded cutover.

## 6. Rollback anchors (audit at plan creation)

Audited from the B54 Engine Production Deploy Gate workflow and its run history.

| Item | Value |
|---|---|
| Worker name | `padiem-ai-engine` (Python Worker, `python_workers` flag) |
| Deploy mechanism | `b54-engine-production-deploy-gate.yml` — exact-main SHA `workflow_dispatch` |
| CURRENT_DEPLOYED_VERSION | SHA `26288341` (last successful deploy run 33980178544) |
| ROLLBACK_VERSION | `wrangler rollback` restores the previous deployment, corresponding to SHA `8d4db98c` (previous successful deploy run 33970133859) |
| CONFIG_BINDING_DIFF | none — `wrangler.toml` identical between deployed SHA and current main (`B14_SERVICE` → `ai-revenue-korean-ai-platform` service binding only; `workers_dev=false`) |
| SECRET_NAME_DIFF | none — no `[vars]`/`[secrets]` in `wrangler.toml`; engine is service-binding only; deploy gate uses GitHub environment secrets `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` (values never published) |
| Deployment policy | Git-connected automatic path only; Preview/staging disabled unless a new explicit owner decision authorizes the exact exception |
| Failure recovery | expected-head-reviewed fix/revert PR merged to `main`, then automatic deployment; or `wrangler rollback` via the gate's `ROLLBACK_B54_ENGINE_TO_PREVIOUS_VERSION` path |

Re-deploy/rollback gate reference: re-pin of expected pre-fix state is tracked in
`b54-local-agent-ingress-remediation-redeploy.yml` (#1942) and is engine-adjacent;
it does not authorize engine Production mutation by itself.

## 7. Required evidence per activation (A1 first)

```text
CURRENT_MAIN
ACCEPTED_SOURCE_HEAD
DEPLOYMENT_TARGET
CURRENT_DEPLOYED_VERSION
CONFIG_BINDING_DIFF
SECRET_NAME_DIFF (names only)
ROLLBACK_VERSION
ROLLBACK_CONFIG
REFERENCE_CONSUMER
SYNTHETIC_CASES
REAL_PROVIDER_CALL_COUNT
REAL_USER_DATA = 0 unless separately approved
MUTATION_SCOPE
POST_DEPLOY_HEALTH
FUNCTIONAL_PARITY
ROLLBACK_TEST/READINESS
FINAL_DISPOSITION
```

Secret values are never published. `REAL_USER_DATA` stays 0 until separately
approved.

## 8. Product migration rule

Product-local generic AI paths may be removed only after the shared Engine
capability is proven for that product:

```text
shared Engine route enabled
 -> parallel/shadow or bounded Preview comparison where practical
 -> output/error/latency/safety parity
 -> rollback path proven
 -> Product direct/local generic path disabled behind reversible gate
 -> observation
 -> later source retirement
```

Priority reference migrations:

```text
LoveBud Scout   first completed-execution consumer; Web/Research follows #1744
B53 Sidecar     primary commercial embedded distribution consumer
B30 400 AI Finder  strong Web/Research/Evidence reference
B61 StoryMemory strong Context/Memory/Evidence reference
B62 Padiem Chat broad standalone regression/reference consumer
B54 Padiem Claw included where shared Engine capabilities apply (no Claw-specific sandbox/computer authority moves)
```

## 9. Global safety invariants

```text
BIG_BANG_CUTOVER = NO
SECRET_VALUE_OUTPUT = NO
UNRELATED_BINDING_MUTATION = NO
UNRELATED_PROVIDER_MUTATION = NO
DIRECT_PRODUCT_PROVIDER_RETIREMENT_BEFORE_PARITY = NO
ROLLBACK_ANCHOR_REQUIRED = YES
EXACT_HEAD_REQUIRED = YES
MANIFEST_AVAILABLE_BEFORE_EVIDENCE = NO
```

## 10. Program completion criteria

```text
ALL_ACCEPTED_ENGINE_CAPABILITIES_HAVE_ACTIVATION_DISPOSITION = YES
REFERENCE_PRODUCTS_USE_SHARED_ENGINE_WHERE_ARCHITECTURALLY_REQUIRED = YES
LEGACY_GENERIC_DUPLICATION_RETIRED_AFTER_PARITY = YES
ROLLBACK_EVIDENCE = COMPLETE
FALSE_AVAILABLE_MANIFEST_ENTRIES = 0
CROSS_PRODUCT_AUTHORITY_BOUNDARIES = PRESERVED
```

## 11. Status

- [x] A0 disposition recorded (AVAILABLE per manifest, no activation needed)
- [x] A1 activation gate merged (#1949) — owner-authorized dispatch pending
- [x] A1 bounded Production activation dispatched and manifest flipped to `AVAILABLE` (§12)
- [x] A1 REVERTED_TO_DEFERRED — §12 amendment (WO-7, owner decision D2, 2026-09-06): no live provider var possible; composition fails closed 503 web_tools_off
- [x] A2 disposition recorded (AVAILABLE per manifest, no activation needed)
- [x] A3 activation prep merged — gate + tests + rollback anchor; owner-authorized dispatch pending
- [x] A3 bounded Production activation dispatched and manifest flipped to `AVAILABLE` (§13)
- [ ] A4-A6, A7, A9 activation dispositions
- [ ] `E9_ACTIVATION_PLAN.md` reviewed and merged

Refs #1743 #1698 #1744 #1745 #1746 #1748 #1749 #1750 #1751 #1752 #1621

## 12. A1 bounded Production activation dispatch (owner-authorized)

Owner authorized A1 Web/Research Production (`#1744`). The bounded dispatch
ran the activation gate on the exact current main, proved synthetic and parity
probes, flipped the manifest entries `DEFERRED -> AVAILABLE` atomically with
the conformance/contract updates, and records the secret-free evidence below.

```text
ACTIVATION_GATE_MODULE = apps/padiem-ai-engine/app/web_research_activation.py
CONFIRMATION_TOKEN     = ACTIVATE_ENGINE_A1_WEB_RESEARCH
CURRENT_MAIN           = ed18a2a8766b9ae595a82bbe184569c87c2685ec
ACCEPTED_SOURCE_HEAD   = 1457f201c27b21efdc86c38110048de825f53d82
DEPLOYMENT_TARGET      = Cloudflare Workers (padiem-ai-engine)
CURRENT_DEPLOYED_VERSION = 26288341021f9b2ceaa45b9f587d571af63a07bf
ROLLBACK_VERSION       = 8d4db98c13b2b23378536d3b2e5270bb3b457f06
CONFIG_BINDING_DIFF    = none
SECRET_NAME_DIFF       = none (names only)
SYNTHETIC_PROBES       = search / fetch / deep_research — all ok
REFERENCE_CONSUMERS    = lovebud-scout, 400-ai-finder — parity ok
REAL_PROVIDER_CALLS    = 0
REAL_USER_DATA         = 0
MUTATION_SCOPE         = A1 Web/Research activation only
FINAL_DISPOSITION      = ACTIVATED (manifest AVAILABLE on current main)
```

Manifest/contract state after the dispatch:

```text
capability_manifest: web_search AVAILABLE, web_fetch AVAILABLE, deep_research AVAILABLE
contract_manifest:   web_search_projection AVAILABLE, web_fetch_projection AVAILABLE, deep_research_projection AVAILABLE
conformance:         test_capability_states_match_routed_truth updated; 101/101 pass in affected files
```

Rollback: `wrangler rollback` restores the previous Engine deployment (SHA
`8d4db98c13b2b23378536d3b2e5270bb3b457f06`); a source revert PR is the normal
recovery path per `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md`.

### §12 amendment — FINAL_DISPOSITION superseded: REVERTED_TO_DEFERRED (WO-7, 2026-09-06)

The `FINAL_DISPOSITION = ACTIVATED` recorded above is superseded by owner
decision D2 (CTO decision ledger 2026-09-06, work order WO-7). The §12
dispatch's own evidence already showed `CONFIG_BINDING_DIFF = none` and
`SECRET_NAME_DIFF = none` — no provider configuration was ever added — and
`wrangler.toml` carries no `[vars]` and no `keep_vars`, so every deploy drops
dashboard-level vars and `PADIEM_ENGINE_WEB_PROVIDER` cannot be live. The
Production composition therefore fails closed (`503 web_tools_off`), and the
manifest AVAILABLE claim was not production truth. The A1 production probe
(WO-3) is waived by the same decision. No product caller invokes `/research`
(0 consumers), so the revert has no product impact. The entries return to
`DEFERRED` (capability + contract projections); the original §12 record above
is preserved for audit. Re-activation requires a real provider var/secret in a
separate activation PR passing the E9 gate and the WO-2 production composition
conformance test.

## 13. A3 bounded Production activation dispatch (owner-authorized)

Owner authorized A3 Tool Runtime Production (`#1746`). The bounded dispatch
ran the activation gate on the exact current main, proved synthetic and parity
probes through the real Core ``ToolRuntime``, flipped the manifest entries
`DEFERRED -> AVAILABLE` atomically with the conformance/contract updates, and
records the secret-free evidence below.

```text
ACTIVATION_GATE_MODULE = apps/padiem-ai-engine/app/tool_runtime_activation.py
CONFIRMATION_TOKEN     = ACTIVATE_ENGINE_A3_TOOL_RUNTIME
CURRENT_MAIN           = 1f6220d59adc73518e13a8bfddecc9380d8354d9
ACCEPTED_SOURCE_HEAD   = 1457f201c27b21efdc86c38110048de825f53d82
DEPLOYMENT_TARGET      = Cloudflare Workers (padiem-ai-engine)
CURRENT_DEPLOYED_VERSION = 26288341021f9b2ceaa45b9f587d571af63a07bf
ROLLBACK_VERSION       = 8d4db98c13b2b23378536d3b2e5270bb3b457f06
CONFIG_BINDING_DIFF    = none
SECRET_NAME_DIFF       = none (names only)
SYNTHETIC_PROBES       = execute / resume / cancel — all ok (real Core ToolRuntime)
REFERENCE_CONSUMERS    = b62-padiem-chat, b54-padiem-claw — parity ok, wire authority rejected
REAL_PROVIDER_CALLS    = 0
REAL_USER_DATA         = 0
MUTATION_SCOPE         = A3 Tool Runtime activation only
FINAL_DISPOSITION      = ACTIVATED (manifest AVAILABLE on current main)
```

Manifest/contract state after the dispatch:

```text
capability_manifest: tool_runtime AVAILABLE
contract_manifest:   tool_runtime_projection AVAILABLE
conformance:         test_capability_states_match_routed_truth updated; 86/86 pass in affected files
```

Rollback: `wrangler rollback` restores the previous Engine deployment (SHA
`8d4db98c13b2b23378536d3b2e5270bb3b457f06`); a source revert PR is the normal
recovery path per `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md`.

### §13 amendment — truthful disposition correction (CTO audit 2026-09-06)

Post-activation audit (CTO independent verification, 2026-09-06) proved the
Production composition (`worker_identity.py`) composes
`ToolExecutionEngineService(tool_binding_resolver=None)` on both composition
paths, so every Production tool request fails closed with 503
`tool_runtime_unavailable`. The §13 probe evidence was produced against a
test-constructed service with a fake resolver, not the Production composition.
The manifest AVAILABLE claim was therefore not production truth and violated
`SOURCE_PRESENT != AVAILABLE` / `FALSE_AVAILABLE_MANIFEST_ENTRIES = 0`.

```text
FINAL_DISPOSITION = REVERTED_TO_DEFERRED (reason: production composition fail-closed, CTO audit 2026-09-06)
MANIFEST_STATE_AFTER_CORRECTION = tool_runtime DEFERRED / tool_runtime_projection DEFERRED
REACTIVATION_PRECONDITIONS = real tool binding resolver wired in the Production
  composition + WO-2 production composition conformance gate passing + separately
  authorized activation PR with exact-SHA dispatch evidence
PRIOR_RECORD = preserved above unmodified; this amendment supersedes FINAL_DISPOSITION only
```

