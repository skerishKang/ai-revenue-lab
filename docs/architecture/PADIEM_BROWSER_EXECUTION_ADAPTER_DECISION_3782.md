# PADIEM browser.control execution boundary and reuse decision (#3782)

```text
DOC_ROLE=BROWSER_CONTROL_ENGINEERING_DECISION
OWNER=PADIEM CENTRAL / Claw browser-control integration
DECISION_DATE=2026-10-09
EXECUTION_PRIMARY=RETAIN_EXISTING_ELECTRON_CDP
EXTERNAL_BROWSER_BACKEND=PLAYWRIGHT_MCP_SELECTED_OPTIONAL_PILOT_ONLY_NOT_WIRED
STAGEHAND_V4=DEFER_NO_PRODUCT_INTEGRATION
BROWSER_USE_OSS=REFERENCE_ONLY_NO_PRODUCT_INTEGRATION
WINDOWS_COMPARISON=LOCAL_LOOPBACK_3_OF_3_PASS_BOTH_NOT_AI_BENCHMARK
BROWSER_USE_PRODUCT_RELEASE=OFF
CANONICAL_LEASE_ADMISSION_WIRED=false
COMPUTER_USE_OS_GUI=OUT_OF_SCOPE
NEXT_PRIORITY=TRUSTED_P01_TO_BROKER_TO_WINDOWS_E2E
```

## Authority and non-duplication

This is the **browser-specific engineering decision**, not a new repository-wide technology adoption policy, P01 authority, provider catalog, model selection, or launch approval.

- **Technology selection policy:** [TECHNOLOGY_ADOPTION_POLICY.md](../operations/TECHNOLOGY_ADOPTION_POLICY.md).
- **Technology inventory / replaceable components:** [PADIEM_TECHNOLOGY_COMPONENT_REGISTRY_v1.md](PADIEM_TECHNOLOGY_COMPONENT_REGISTRY_v1.md).
- **Stable capability ownership:** [PADIEM_AI_CAPABILITY_OWNERSHIP_REGISTRY_v1.md](PADIEM_AI_CAPABILITY_OWNERSHIP_REGISTRY_v1.md).
- **OSS/commercial reuse intake, upstream SHA/license review:** [#2996](https://github.com/skerishKang/ai-revenue-lab/issues/2996). The LOCAL1 audit already requested there is the required upstream selection evidence. Do not create another adoption radar.
- **Product implementation and acceptance:** [#3782](https://github.com/skerishKang/ai-revenue-lab/issues/3782) and parent [#3775](https://github.com/skerishKang/ai-revenue-lab/issues/3775) / [#3669](https://github.com/skerishKang/ai-revenue-lab/issues/3669), with source-only [Draft PR #3783](https://github.com/skerishKang/ai-revenue-lab/pull/3783).
- **Release sequencing:** [#3523](https://github.com/skerishKang/ai-revenue-lab/issues/3523) and separate owner authorization. This document does **not** authorize activation.

Existing approved in-flight slices continue under the technology adoption policy unless a material security/license hazard is independently established. This decision governs the **next substantial execution-engine expansion or swap**, not an automatic halt or rollback of accepted source work.

## Decision: own authority; reuse execution mechanisms

**RETAIN** the current bounded Electron/CDP execution binding as the PADIEM Desktop embedded-browser primary. **RETAIN** existing IP-CORE/Engine, B14, P01/Control Plane, canonical Broker, one supervised Windows Resident, durable approval/one-shot state, and trusted-main view ownership.

**DO NOT BUILD** a second general-purpose browser automation engine, general CDP/DevTools endpoint, browser-native agent framework, arbitrary script execution, public renderer IPC, or duplicate user-approval authority. Do not continue expanding our custom low-level browser mechanism just for feature parity with Tabbit, Kimi, Qwen, or Browser Use.

**COMPARE** upstream execution alternatives only when a concrete unmet product task, external Chrome/Edge requirement, or measured reliability/maintenance problem justifies a bounded pilot. The external adapter, if later approved, consumes the *same* PADIEM-approved action and may not claim independent approval or session authority.

This is **Browser Use** for web pages/tabs, **not OS Computer Use** (native arbitrary desktop GUI is explicitly deferred by #3583). Browser Use feature activation remains OFF.

## Verified existing internal code — do not reimplement

| Slot | Current source | Status / ownership |
|---|---|---|
| Bounded action + P01 resolve/consume | `apps/padiem-desktop-shell/src/browser/browser-action-host.ts` | Product trusted-main enforcement; remain PADIEM-owned |
| Embedded Electron Chromium input | `apps/padiem-desktop-shell/src/browser/browser-action-electron-binding.ts` | Existing `Input.*` allowlist; retain |
| Accessibility projection | `apps/padiem-desktop-shell/src/browser/browser-observation-electron-source.ts` | Existing `Accessibility.getFullAXTree` restricted projection; retain |
| Trusted live browser.open view | `apps/padiem-desktop-shell/src/browser/browser-action-trusted-main.ts` | Existing view/run/workspace/owner/origin checks; retain |
| Broker-approved command ingress | `apps/padiem-desktop-shell/src/browser/browser-control-canonical-command-ingress.ts` | Source-only; canonical command port required |
| Resident one-shot transport | `apps/padiem-desktop-shell/src/conversation/resident-browser-control-command-take.ts` | `sourceConfigured=false` in trusted main |
| Broker command/ticket ledger | `packages/padiem-control-plane/local_agent_broker_pending_browser_issue.py`, `local_agent_broker_browser_control_take.py` | Draft #3783 code, not Production release |
| Actual product wiring | `apps/padiem-desktop-shell/src/main/main.ts` | `sourceConfigured: false`; keep off |

Source existence or hermetic tests do **not** establish real authenticated human approval, cross-process E2E, external-browser support, or Production enablement. Review actual latest source before making implementation claims; Draft #3783 can change independently of main.

## Replaceable backend versus non-replaceable authority

```text
User task / product UX
  -> IP-CORE / Engine tool semantics; B14 remains the only model router
  -> CURRENT Engine owner + signed-in workspace + real browser.control P01
  -> Canonical Broker admission / durable one-shot take / origin-budget-time policy
  -> One supervised Windows Resident / trusted desktop view owner
  -> Browser execution adapter (backend does NOT grant access)
       A. Electron CDP input + AX source: CURRENT PRIMARY
       B. Playwright MCP or other backend: RESEARCH/PILOT ONLY
  -> Sanitized receipt / failure / audit and terminal result
```

Adapter work is permitted only as a **small, contract-first extraction** from current `BrowserActionDispatchPort` / `BrowserObservationSourcePort` and approved-command ingress when genuinely required. Do not preemptively replace the working implementation or fork P01/business logic into a plugin.

A backend implementation must:
1. Accept only the existing typed, bounded action vocabulary from the trusted host; never arbitrary URLs, selectors, code, MCP tool names, scripts, file paths, or new capabilities supplied by the model.
2. Check current canonical owner/workspace/run/device/session, live host view, exact origin, current approval scope, TTL/idle, remaining action budget and any local DENY **before** each dispatch. Canonical P01 PHASE A/B and the durable Broker take remain authoritative, including under backend crashes.
3. Preserve `CONSUME_ONCE`, `NO_REFUND`, `NO_AUTO_RETRY`, `NO_SECOND_APPROVAL_AUTHORITY` and reject token reuse after restart. A backend may not independently replay a failed command.
4. Return only a bounded evidence/receipt; sanitize error and diagnostic surfaces. Never export cookies, password values, credentials, arbitrary raw DOM, or developer tools to the model.
5. Remain within the current lease-eligible action scope. Submit, login/credential interaction, download/upload, payments, account changes, destructive acts and cross-origin transitions stay blocked or require an existing separately authorized step-up policy; **do not expand them as part of an adapter pilot**.
6. Be disabled by default until conformance, Windows E2E, lifecycle cleanup, version pinning, and a rollback to the current backend are independently verified.

## External candidates — evaluation, not integration authorization

| Slot candidate | Potential use | Current decision | Prerequisite |
|---|---|---|---|
| Existing Electron/CDP | Embedded PADIEM Desktop ephemeral view | **RETAIN_CURRENT primary** | Finish #3782 live P01 delivery + Windows E2E |
| [Microsoft Playwright MCP](https://github.com/microsoft/playwright-mcp) | Optional existing external Chrome/Edge automation only | **SELECTED FOR FUTURE BOUNDED OPTIONAL PILOT; NOT INTEGRATED/ENABLED** | Pin tested npm `@playwright/mcp@0.0.83` (Apache-2.0); require tool allowlist, real P01/egress/ownership conformance, audit dependency/license, teardown and rollback |
| [Browserbase Stagehand v4](https://github.com/browserbase/stagehand) | AI-driven action/observe/extract framework / local Chrome SDK | **DEFER: NO #3782 PRODUCT INTEGRATION** | Windows deterministic locator smoke passed for npm `@browserbasehq/stagehand@4.2.0` (MIT), but installed Node 22.17.1 is below package requirement `>=22.18.0`; AI model behavior/cost and PADIEM contract unverified |
| [Browser Use](https://github.com/browser-use/browser-use) | Separate agent/browser backend reference | **REFERENCE_ONLY / NOT SELECTED** | A second autonomous agent/model loop adds unmeasured B14/Engine governance duplication; no provider calls or new Python sidecar for #3782 |
| [Qwen Code Browser Use](https://qwenlm.github.io/qwen-code-docs/en/users/features/browser-use/) | Chrome extension architecture reference | **REFERENCE_ONLY** | Official docs describe macOS/Linux support; Windows feasibility unverified; do not install as part of #3782 |

An external repository, its UI, a GitHub license badge, or a working demo does **not** mean PADIEM can safely embed its entire runtime. Per #2996, upstream candidates need exact source/version, transitive redistribution license, data egress, model-provider billing, installation, runtime/Windows fit, and rollback review. Playwright MCP explicitly states it is **not a security boundary**; PADIEM retains all approval and safety checks. External implementation and current embedded browser need not both be shipped.

## 2026-10-09 Windows candidate comparison — FINAL technology disposition

This section **finalizes backend selection, NOT product approval** under #2996. Do not turn this evidence into permission for remote Worker/D1 modification, browser access to existing user accounts, generic MCP tool execution or Production activation.

**Measured environment:** Windows PADIEM development machine (OS edition not pinned), Node.js `v22.17.1`, installed Chrome and Edge; packages installed in an **isolated temporary folder outside the repo** via npm (`@playwright/mcp@0.0.83`, Apache-2.0; `@browserbasehq/stagehand@4.2.0`, MIT). Only a locally served, isolated loopback HTML fixture was used; no customer session, provider/model API call, external website action, browser cookie capture or paid inference. Three cold process starts per candidate, using a static 2-row table, preview-form input, click and in-page tab switch.

| Observation | Microsoft Playwright MCP | Stagehand v4 browser SDK |
|---|---|---|
| Windows fixture outcomes | **3/3 PASS**: table, type, click, tab | **3/3 PASS**: table, locator fill, click, tab |
| Elapsed cold-start and three-action sequence | 2,610 ms median; 2,581–2,743 ms | 1,187 ms median; 1,162–1,648 ms |
| Protocol measured | MCP stdio `browser_navigate` / `browser_snapshot` / `browser_type` / `browser_click` to **isolated Edge** | Direct local Chrome `Stagehand.create` + browser/locator SDK; **no `act/observe/extract` model action** |
| Node requirement | `>=18`; current Windows host satisfies | `>=22.18.0`; current Windows host `22.17.1` **below supported engine**, despite smoke pass |
| Exact npm package | `@playwright/mcp@0.0.83` | `@browserbasehq/stagehand@4.2.0` |
| B14 / real P01 / Broker / external-login compatibility | **NOT TESTED** | **NOT TESTED** |

**Interpretation limits:** These are fundamentally different invocation layers (MCP stdio versus direct SDK), **not equivalent agent benchmarks**. Do not claim Stagehand is categorically 2x faster, cheaper or more reliable; no repeated same-model natural-language `act/observe/extract` workload, prompt-injection/red-team assessment or real PADIEM P01/Broker invocation was run. The package installation/runtime warning is a release integration constraint, not proof Stagehand is broken. These local elapsed times are exploratory, not an SLA or production performance figure.

**Internal baseline checked in parallel:** current Windows PADIEM Desktop TypeScript build succeeded; **44/44 browser trusted-main/action/CDP observation/transport contract tests PASS**. This supports *retention* of the embedded bounded executor; it does **not** prove live owner-approved external-user/browser E2E, which remains #3782 G1–G3.

**Security/capability constraint:** The Playwright MCP server exposes high-capability tools including `browser_evaluate` and `browser_run_code_unsafe`; upstream's origin allow/block lists are **not** a security boundary. If an optional external-browser adapter is later justified, the host MUST **not forward the general MCP catalog to the model**. It must privately map only PADIEM's existing approved bounded action enum to an explicit allowlist (e.g., snapshot/click/type), enforce P01/Broker and exact origin before each invocation, own the process/browser/profile lifecycle, and permit a clean fallback to Electron/CDP. Reusing logged-in external Chrome/Edge sessions is a *separate* access decision: the smoke deliberately did **not** attach to such a session.

### Selection and no-go decision

```text
FINAL_PRIMARY_EMBEDDED_BROWSER=RETAIN_EXISTING_ELECTRON_CDP
EXTERNAL_BROWSER_FEATURE_FUTURE_PILOT_BACKEND=MICROSOFT_PLAYWRIGHT_MCP_0_0_83
STAGEHAND_V4_FOR_3782=DEFER_NOT_INTEGRATE
BROWSER_USE_AGENT_FOR_3782=REFERENCE_ONLY_NOT_INTEGRATE
GENERAL_BROWSER_AUTOMATION_ENGINE_BUILD=NO
NEW_BROWSER_AGENT_OR_MODEL_ROUTER=NO
G1_TO_G3_EXISTING_APPROVED_SOURCE_WORK=CONTINUE
OWNER_P01_AND_BROKER_AUTHORITY=RETAIN_PADIEM
PILOT_OR_RUNTIME_BACKEND_SWAP_AUTHORIZED=NO
REMOTE_CLOUDFLARE_D1_CREATE_OR_DEPLOY_AUTHORIZED=NO
PRODUCTION_BROWSER_USE_ENABLED=NO
```

**Reason:** Existing Electron/CDP already meets the restricted embedded Desktop contract with test coverage; a wholesale external engine replacement would add licensing/packaging and security-risk work without proven incremental product value. For an **unmet requirement to act in the user's existing Chrome/Edge tabs**, prefer a separately approved, narrowly scoped Playwright MCP adapter pilot; it has an observed Windows MCP protocol path and model-agnostic executor. Stagehand's full agent capabilities are unbenchmarked with B14 and would add a second model/tool planning layer; Browser Use similarly is not justified as a second agent under Engine governance. The final decision does not pause approved work or delay G1–G3 solely for another technology scan.

Upstream references: [Microsoft Playwright MCP](https://github.com/microsoft/playwright-mcp), [Playwright connecting to browsers](https://playwright.dev/mcp/configuration/browser-extension), [Stagehand](https://github.com/browserbase/stagehand), and [Browser Use](https://github.com/browser-use/browser-use). Exact npm versions are smoke-pinned, **not** a full transitive license/security admission; before any pilot, #2996 must record pinned source/integrity, dependencies, extension permissions, egress policy and rollback evidence.

## Next implementation / verification gates (in order)

- **G0: source + documentation baseline.** Inventory and keep current trusted-main Electron/CDP; register this decision and link #3782/#3775/#3669/#2996. No source/runtime behavior changes required for this documentation gate.
- **G1: real first-party P01 owner boundary.** Verify the live authenticated Engine original continuation, signed-in B54 user/workspace and actual human APPROVE; reject missing/denied/expired/revoked or mismatch. A pending ticket or test fixture is NEVER approval. Connect Broker's `QUEUED -> ADMITTED` exclusively to that verified source. No promotion through `process.execute`.
- **G2: closed transport.** After canonical P01 admission, deliver one bounded `browser.control` command through existing supervised Windows Resident to trusted-main Desktop ingress; take exactly once, authenticate each hop, and keep `sourceConfigured=false` until release gate.
- **G3: hermetic Windows E2E.** Exercise one legitimate non-committing tab/treeitem interaction in an isolated test web view, with actual supervised process boundaries but no real external website/user account. Prove denial on owner/binding/view/origin/approval drift, duplicate/restart, TTL, budget, step-up, crash and zero input on denial; provide terminal evidence without secrets.
- **G4: conformance-first adapter pilot (separate approval).** Compare primary Electron/CDP against at most one shortlisted external backend for the *same* bounded tasks. Record action correctness, denial parity, Windows compatibility, latency, install/runtime cost, threat surface, cleanup and rollback. Do not build a general interface until an actual second backend needs it.
- **G5: owner-governed release.** Only after #3523 sequencing, exact-head CI, independent review, real approval flow and owner authorization may anyone propose limited Product/Production activation; separately confirm deployment, secrets and external egress.

```text
G1_G3_IMPLEMENTATION_ALLOWED=SOURCE_ONLY_UNDER_EXISTING_ISSUE_GATES
G4_OPTIONAL_EXTERNAL_BROWSER_BACKEND_SELECTED=PLAYWRIGHT_MCP_0_0_83
G4_EXTERNAL_ADAPTER_PRODUCT_INTEGRATION_AUTHORIZED=NO
MODEL_CHANGE=NO
PRODUCTION_DEPLOYMENT=NO
LIVE_BROWSER_OPERATION=NO
PR_3783_DRAFT_AND_UNMERGED=YES
CLOSE_3782_3775_3669=NO_UNTIL_ACCEPTANCE
```

## Comparison evidence to record at #2996

For each backend that survives screening, provide: current PADIEM source slot; upstream **exact tag/SHA** and license/dependencies; integration topology and browser/session ownership; P01/budget/origin/mismatch failure equivalence; capabilities intentionally withheld; Windows packaging/exit behavior; cost/performance; tests and observed failures; reverse-swap procedure; disposition `RETAIN / ADAPT / REPLACE_LATER / REJECT`. Without source-pinned evidence use `UNVERIFIED`. Review here as a design input, not as a second technology-selection authority.

## Scope protection / rollback

Do not rebase/merge the large #3783 source PR merely to publish this design. Keep this decision in its own docs-only Draft PR; merge only after review. If a pilot fails, leave external integration OFF and retain the original Electron/CDP binding unchanged. The reusable canonical authority and durable data remain PADIEM-owned in every scenario.
