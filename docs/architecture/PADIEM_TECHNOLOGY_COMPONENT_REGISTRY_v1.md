# Padiem Technology Component Registry v1

```text
DOC_STATUS=CANONICAL_TECHNOLOGY_INVENTORY
OWNER=Padiem platform architecture
LAST_RECONCILED=2026-09-25
POLICY=SEARCH / BUY / ADOPT / ADAPT BEFORE BUILD
REPLACEABLE_COMPONENTS=YES
```

This registry tracks **implementation components**, not product capability ownership. Capability ownership remains in `PADIEM_AI_CAPABILITY_OWNERSHIP_REGISTRY_v1.md`.

A component may change while its Padiem contract remains stable.

## Decision vocabulary

```text
OWN_AUTHORITY          Padiem product/security policy; not outsourced.
REPLACEABLE_COMPONENT commodity implementation behind a Padiem contract.
EXTERNAL_SERVICE      external API/provider already used by design.
TECH_SCAN_ACTIVE      current implementation/candidate landscape is under review.
SCAN_DEFERRED         replaceable but not currently a delivery bottleneck.
```

Replacement outcomes:

```text
RETAIN_CURRENT
ADD_ALTERNATIVE
REPLACE_PRIMARY_KEEP_FALLBACK
REPLACE_AND_RETIRE
REJECT_CANDIDATE
```

## Current component inventory

| Capability / slot | Current implementation | Class | External/new-tech posture | Current action |
|---|---|---|---|---|
| File admission / MIME / archive / parser isolation | Padiem in-repo safety boundary | OWN_AUTHORITY | External parsers may sit behind it; admission authority stays Padiem | RETAIN |
| PDF native read / text / metadata | pypdf-backed Core authority | REPLACEABLE_COMPONENT | Keep as fallback; compare broader PDF/document toolkits for remaining render/table/OCR/authoring | TECH_SCAN_ACTIVE #2827 |
| PDF merge/split | pypdf-backed implementation | REPLACEABLE_COMPONENT | Existing path remains valid fallback even if a larger toolkit becomes primary | TECH_SCAN_ACTIVE #2827 |
| PDF image-backed create | Padiem adapter over merged image→PDF emitter | REPLACEABLE_COMPONENT | May coexist with richer authoring engine behind same Skill contract | TECH_SCAN_ACTIVE #2827 |
| PDF full-page rendering / tables / OCR | no accepted complete primary | REPLACEABLE_COMPONENT | OSS/commercial toolkit first | TECH_SCAN_ACTIVE #2827 |
| Raster inspect/normalize/transform | Pillow-based accepted image foundation | REPLACEABLE_COMPONENT | Stable Image contract should permit future engine swap; current implementation remains fallback | SCAN_DEFERRED |
| Image OCR | no accepted primary | REPLACEABLE_COMPONENT | DeepSeek-OCR, PaddleOCR, HunyuanOCR, dots.ocr, olmOCR, Surya, MinerU, GOT-OCR and commercial options | TECH_SCAN_ACTIVE #2828 |
| HWPX read/create/edit/template/table | Padiem in-repo partial/native implementation | REPLACEABLE_COMPONENT | Do not discard; compare Hancom/OSS/commercial HWPX engines and keep current path as fallback if better primary is adopted | TECH_SCAN_ACTIVE #2825 |
| HWP legacy read/conversion | no accepted cloud primary | REPLACEABLE_COMPONENT | Hancom/commercial/OSS/sidecar options before custom parser | TECH_SCAN_ACTIVE #2826 |
| Spreadsheet XLSX handling | openpyxl in Core documents extra | REPLACEABLE_COMPONENT | Mature commodity dependency; scan only when capability gap appears | SCAN_DEFERRED |
| Sandbox policy / lease / run authority | Padiem provider-neutral contract + conformance | OWN_AUTHORITY | Provider implementation is replaceable | RETAIN |
| Sandbox provider implementation | E2B pre-live path exists; real primary not selected | REPLACEABLE_COMPONENT | Compare managed OSS/commercial sandbox providers | TECH_SCAN_ACTIVE #1405 |
| Automation rule / membership / dedup / run history | Padiem Claw/Control Plane authority | OWN_AUTHORITY | Do not replace with a generic scheduler framework | RETAIN #2833 |
| Schedule trigger primitive | Cloudflare Worker scheduled/Cron lane | REPLACEABLE_COMPONENT | Managed trigger primitive; replaceable if platform need changes | SCAN_DEFERRED |
| AI provider/model execution | B14 provider/model routing | OWN_AUTHORITY for routing; providers are replaceable | Provider adapters/models intentionally replaceable | CONTINUOUS |
| Cross-runtime AI transport | IP-ENGINE contracts | OWN_AUTHORITY | Hosting/transport implementation can evolve behind contract | RETAIN |
| HTTP application runtime | Starlette/httpx/uvicorn + Workers runtime where applicable | REPLACEABLE_COMPONENT | Not current bottleneck | SCAN_DEFERRED |
| Browser Control P01/admission/replay and audit authority | Engine/P01/Control Plane/Broker + trusted Desktop owner | OWN_AUTHORITY | Never outsource human approval, binding, origin/budget/time checks or Broker durable one-shot state; see [browser decision](PADIEM_BROWSER_EXECUTION_ADAPTER_DECISION_3782.md) | RETAIN #3782 |
| Browser action observation and input execution | Existing bounded Electron/CDP observation + Input.* binding | REPLACEABLE_COMPONENT | **Retain Electron/CDP as embedded primary** (Windows contract 44/44); **Playwright MCP 0.0.83 selected only as optional future existing-Chrome/Edge pilot**, not integrated or authorized; Stagehand v4 and Browser Use agent deferred. Windows 3/3 per SDK smoke is not AI quality/security conformance; [binding decision/evidence](PADIEM_BROWSER_EXECUTION_ADAPTER_DECISION_3782.md) | RETAIN_CURRENT; OPTIONAL_PLAYWRIGHT_MCP_PILOT_SELECTED_NOT_WIRED #2996 #3782 |
| Browser/E2E verification | Playwright where configured | REPLACEABLE_COMPONENT | Tooling only; switch if materially better | SCAN_DEFERRED |
| Cloud runtime/storage | Cloudflare Workers / D1 / R2 in current products | REPLACEABLE_INFRASTRUCTURE with high migration cost | Evaluate only when cost/capability/reliability justifies migration | SCAN_DEFERRED |
| Drive/Gmail/Telegram/Slack/Calendar integrations | external provider APIs through Padiem connector boundaries | EXTERNAL_SERVICE | Already adopt-first; SDK/API may change while connector contract stays stable | CONTINUOUS |
| External coding-agent execution | provider-neutral ExternalCodingAgentRunner contract | OWN_AUTHORITY contract / replaceable adapters | Hermes/Octop/Grok/Codex/Claude/etc may plug in as adapters | CONTINUOUS #2996 |

## Swap contract

Every replaceable component should converge toward:

```text
stable Padiem interface
+ implementation selector/config
+ shared conformance tests
+ implementation-specific adapter
+ bounded benchmark
+ rollback path
```

Do not fork product code for each technology when an adapter/strategy boundary is sufficient.

## Existing implementation is an asset, not a prison

An already-implemented component may be superseded when a candidate materially improves:

- accuracy/quality;
- Korean/document capability;
- latency;
- resource use;
- operating cost;
- maintenance burden;
- security;
- licensing/commercial support;
- time-to-market.

Previous code should normally remain as one of:

```text
ACTIVE_FALLBACK
DORMANT_ROLLBACK
REFERENCE_IMPLEMENTATION
TEST_ORACLE
```

until the replacement is stable and retirement is justified.

## Technology scan backlog

Priority scan domains:

1. OCR / document understanding — #2828
2. PDF render/table/OCR/authoring — #2827
3. HWPX engines/SDKs/services — #2825
4. HWP parser/conversion engines/services — #2826
5. Managed cloud sandboxes — #1405
6. Agent/coding runtimes and reusable infrastructure — #2996

Secondary domains to inventory continuously:

- browser/computer-use;
- RAG/vector/search;
- speech/audio;
- vision/video;
- schedulers/queues;
- connector SDKs;
- media conversion;
- storage/databases;
- observability/evaluation;
- workflow/agent frameworks.

## Reassessment trigger

A component is re-scanned when:

```text
NEW_CREDIBLE_TECH_FOUND
OR MAJOR_UPSTREAM_RELEASE
OR QUALITY_GAP
OR COST_GAP
OR DELIVERY_BOTTLENECK
OR LICENSE_CHANGE
OR NEW_PRODUCT_REQUIREMENT
```

A scan should normally produce no more than three finalists and one recommended primary.

<!-- AGENT_RUNTIME_CANDIDATE_INVENTORY_20261009 -->
## 2026-10-09 agent runtime / Desktop / browser reusability crosswalk

This is a **candidate/source inventory**, not authorization to replace Padiem runtimes or choose models. For actual engineering ownership see the capability registry; for the live delivery priority see #3523; source-intake findings and LOCAL1's review belong to #2996.

| Replaceable implementation slot | Current Padiem implementation or boundary | Candidate upstream (GitHub root license) | Verified disposition / next proof |
|---|---|---|---|
| Windows Desktop shell / local workspace primitives | `apps/padiem-desktop-shell` + Padiem local broker / agent contracts #1633–#1636 | [ZCode](https://github.com/zai-org/ZCode) (Apache-2.0) | **Partial reuse already landed**: `THIRD_PARTY_NOTICES.md` documents pinned `workspaceFileSearch.ts` adaptation; #3436 CLOSED `ADAPT_PARTIAL`. Whole runtime remains NOT imported/approved; future #3583 gated after #3523. |
| Agent loop / tools / skills / MCP / sessions | B54/P01/Engine/Core contracts plus in-repo kagent implementations | [OpenCode](https://github.com/anomalyco/opencode) (MIT), [OpenClaw](https://github.com/openclaw/openclaw) (MIT), [Kilo Code](https://github.com/Kilo-Org/kilocode) (MIT) | **RETAIN** current Padiem agent-loop/durable authority. LOCAL1 pinned source audit completed under #2996; OpenCode, Kilo and OpenClaw remain pattern/reference candidates only; no whole-runtime import approved. |
| Browser action execution / computer-use primitive | Existing Padiem Broker + P01 command tickets, #3775/#3782; Chrome/browsers are outside authorization authority | [Browser Use](https://github.com/browser-use/browser-use) (MIT), ZCode (Apache-2.0) | **RETAIN CURRENT ELECTRON/CDP** per #3829/#3782. Browser Use remains NOT SELECTED: tagged default telemetry, vendor model fallback unless explicitly injected, and Windows/egress conformance need independent review. Playwright MCP source/runtime pin remains UNVERIFIED. #3783 ownership unchanged. |
| Provider/model integration implementation | B14 catalog and provider adapters, Engine/Core service contracts | OpenCode/ZCode/Kilo Code upstream provider configurations as possible **reference implementations** | **ADAPT PATTERN ONLY** (provider-as-data vs protocol module); #3819 OPEN/DRAFT already owns the B14 JSON registry migration. No imported second registry/router, no model-list/group decision, no production activation. |

**Audit completed; source-of-truth links:** [LOCAL1 pinned-source evidence](https://github.com/skerishKang/ai-revenue-lab/issues/2996#issuecomment-6064222379) and [CENTRAL CTO adjudication](https://github.com/skerishKang/ai-revenue-lab/issues/2996#issuecomment-6064323208). This crosswalk records only the current disposition; those issue records retain the detailed per-file evidence and uncertainty. OPEN/CANDIDATE does not authorize dependency import.

**License and source-pin qualifications:** OpenClaw's optional external Lightpanda browser engine is AGPL-3.0-or-later, despite the MIT adapter/root; the optional component requires topology-specific legal review before inclusion, not a blanket claim about OpenClaw. Browser Use 0.13.11 has default-on telemetry; authenticated artifact upload is separately gated and default secret/data exfiltration is not established. GitHub Release target_commitish is not a verified immutable source commit (OpenCode v1.18.35 differs from its tag); resolve git tag refs and peel annotated tags. A package.json private:true flag blocks npm publishing, not MIT source reuse in itself. Any future selected module still requires transitive license/NOTICE, outbound network, credential, Windows and authority review.

License values above are root GitHub repository metadata verified on 2026-10-09, **not** package-by-package redistribution clearance, transitive-asset licensing, hosted-service rights or license conclusions for a fork. For any chosen submodule, pin immutable commit, audit actual dependencies and notices, and record the legal/technical disposition before copy/embedding.

Proof to distinguish `already adopted` from `may be adopted`:
- ZCode code provenance: `apps/padiem-desktop-shell/THIRD_PARTY_NOTICES.md` pins `zai-org/ZCode@29628c9acdb81b703bbd4080c207a0e7ce5e276e` and exact file path; this does **not** imply the local Agent runtime was imported.
- #3436 / #3583 govern ZCode Desktop disposition; do not create a competing Desktop authority or overwrite an already accepted decision.
- #2996 collects reuse matrices; #3523 remains the only currently active user-visible Golden Path target.
- Component swap criteria: stable adapter + shared offline conformance + verified license/security + rollback. A code-level 429/502 transport failure or workspace-isolation defect is not automatically fixed by importing another agent.
