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
| Agent loop / tools / skills / MCP / sessions | B54/P01/Engine/Core contracts plus in-repo kagent implementations | [OpenCode](https://github.com/anomalyco/opencode) (MIT), [OpenClaw](https://github.com/openclaw/openclaw) (MIT), [Kilo Code](https://github.com/Kilo-Org/kilocode) (MIT) | **CANDIDATE / NO IMPORT DECISION**. LOCAL1 to compare exact pinned subsystems and adapter/parity risks; no second account, task, approval, connector or model authority. |
| Browser action execution / computer-use primitive | Existing Padiem Broker + P01 command tickets, #3775/#3782; Chrome/browsers are outside authorization authority | [Browser Use](https://github.com/browser-use/browser-use) (MIT), ZCode (Apache-2.0) | **CANDIDATE / NO IMPORT DECISION**. Native/browser runtime and sandbox/egress constraints require exact audit; retain Padiem per-command approval and fail-closed broker. #3783 ongoing PR ownership unchanged. |
| Provider/model integration implementation | B14 catalog and provider adapters, Engine/Core service contracts | OpenCode/ZCode/Kilo Code upstream provider configurations as possible **reference implementations** | **REFERENCE ONLY unless explicit B14 adapter parity proves safe**. OWNER chooses models; never transplant upstream account/provider/router/telemetry/credential authority. |

License values above are root GitHub repository metadata verified on 2026-10-09, **not** package-by-package redistribution clearance, transitive-asset licensing, hosted-service rights or license conclusions for a fork. For any chosen submodule, pin immutable commit, audit actual dependencies and notices, and record the legal/technical disposition before copy/embedding.

Proof to distinguish `already adopted` from `may be adopted`:
- ZCode code provenance: `apps/padiem-desktop-shell/THIRD_PARTY_NOTICES.md` pins `zai-org/ZCode@29628c9acdb81b703bbd4080c207a0e7ce5e276e` and exact file path; this does **not** imply the local Agent runtime was imported.
- #3436 / #3583 govern ZCode Desktop disposition; do not create a competing Desktop authority or overwrite an already accepted decision.
- #2996 collects reuse matrices; #3523 remains the only currently active user-visible Golden Path target.
- Component swap criteria: stable adapter + shared offline conformance + verified license/security + rollback. A code-level 429/502 transport failure or workspace-isolation defect is not automatically fixed by importing another agent.
