# PADIEM browser.control execution boundary and reuse decision (#3782)

```text
DOC_ROLE=BROWSER_CONTROL_ENGINEERING_DECISION
OWNER=PADIEM CENTRAL / Claw browser-control integration
DECISION_DATE=2026-10-09
EXECUTION_PRIMARY=RETAIN_EXISTING_ELECTRON_CDP
EXTERNAL_BROWSER_BACKEND=EVALUATION_ONLY_NOT_SELECTED
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
| [Microsoft Playwright MCP](https://github.com/microsoft/playwright-mcp) | Optional external Chrome/Edge automation adapter | **CANDIDATE / NOT_SELECTED** | Audit exact tag/SHA, license/transitives, Windows install/browser ownership, P01/egress enforcement, tool allowlist, launch/teardown and rollback |
| [Browser Use](https://github.com/browser-use/browser-use) | Possible agent/browser backend reference or Python sidecar | **CANDIDATE / NOT_SELECTED** | Audit exact code/license/deps/model calls, Python process, profile/credential/session ownership and no second agent policy |
| [Qwen Code Browser Use](https://qwenlm.github.io/qwen-code-docs/en/users/features/browser-use/) | Chrome extension architecture reference | **REFERENCE_ONLY** | Official docs describe macOS/Linux support; Windows feasibility unverified; do not install as part of #3782 |

An external repository, its UI, a GitHub license badge, or a working demo does **not** mean PADIEM can safely embed its entire runtime. Per #2996, upstream candidates need exact source/version, transitive redistribution license, data egress, model-provider billing, installation, runtime/Windows fit, and rollback review. Playwright MCP explicitly states it is **not a security boundary**; PADIEM retains all approval and safety checks. External implementation and current embedded browser need not both be shipped.

## Next implementation / verification gates (in order)

- **G0: source + documentation baseline.** Inventory and keep current trusted-main Electron/CDP; register this decision and link #3782/#3775/#3669/#2996. No source/runtime behavior changes required for this documentation gate.
- **G1: real first-party P01 owner boundary.** Verify the live authenticated Engine original continuation, signed-in B54 user/workspace and actual human APPROVE; reject missing/denied/expired/revoked or mismatch. A pending ticket or test fixture is NEVER approval. Connect Broker's `QUEUED -> ADMITTED` exclusively to that verified source. No promotion through `process.execute`.
- **G2: closed transport.** After canonical P01 admission, deliver one bounded `browser.control` command through existing supervised Windows Resident to trusted-main Desktop ingress; take exactly once, authenticate each hop, and keep `sourceConfigured=false` until release gate.
- **G3: hermetic Windows E2E.** Exercise one legitimate non-committing tab/treeitem interaction in an isolated test web view, with actual supervised process boundaries but no real external website/user account. Prove denial on owner/binding/view/origin/approval drift, duplicate/restart, TTL, budget, step-up, crash and zero input on denial; provide terminal evidence without secrets.
- **G4: conformance-first adapter pilot (separate approval).** Compare primary Electron/CDP against at most one shortlisted external backend for the *same* bounded tasks. Record action correctness, denial parity, Windows compatibility, latency, install/runtime cost, threat surface, cleanup and rollback. Do not build a general interface until an actual second backend needs it.
- **G5: owner-governed release.** Only after #3523 sequencing, exact-head CI, independent review, real approval flow and owner authorization may anyone propose limited Product/Production activation; separately confirm deployment, secrets and external egress.

```text
G1_G3_IMPLEMENTATION_ALLOWED=SOURCE_ONLY_UNDER_EXISTING_ISSUE_GATES
G4_EXTERNAL_ADAPTER_APPROVED=NO
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
