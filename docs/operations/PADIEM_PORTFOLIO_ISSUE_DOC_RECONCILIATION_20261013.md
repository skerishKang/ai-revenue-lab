# PADIEM AI — GitHub issue/document operational reconciliation (2026-10-13 KST)

> **STATUS INDEX, not a new execution authority.** This is a dated, **source- and issue-evidence** snapshot from `skerishKang/ai-revenue-lab` at `main a525f21f36198317edde5d76c332c97095edef49`. Update the status against the actual PR HEAD, CI, deployed Worker version and authenticated production evidence before claiming anything is live. Historical files/issue bodies remain historical even when they contain old, conflicting model names.
>
> **User decision priority:** current owner choices > old dated model/tier examples. **Source enabled ≠ credentials valid ≠ live response ≠ customer entitlement ≠ site deployment.** Source-only CI/PR merge never authorizes cross-product rollout.

## 1. Current exact-source evidence

| Domain | Verified source/PR state on this audit | Still NOT proven / owner |
| --- | --- | --- |
| B14 | [Registry](../../apps/korean-ai-platform/app/pilot/b14_models.json) **20 models: 14 `enabled:true`, 6 `enabled:false`**; `groups.plus/pro/max` are all empty; precise providers distinguish Google, ExLab, OpenCode Go and ZansLab | No 2026-10-13 live-response claim based merely on registry/binding names |
| Gemini | #4504 source gate merged; #4514 Cloudflare 100%-served GET-only version workflow merged. **Gemini 3.1 real PASS** [run 38288787901](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38288787901), 11,039ms, exact model. **Gemini 3.5 preflight BLOCKED** [run 38291355344](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38291355344) by concurrent B66 main SHA change before POST | #4499 OPEN; 3.5 real response **NOT RUN**, zero provider POST, zero retry/fallback; 3.1 no retest. Serving version is time-scoped and must be freshly checked for any later distinct run |
| Central model assignment | #4454 (S1), #4479 (signed D1 gate), #4494 (independent site groups), #4498 (max one fallback/site/tier) MERGED | #4453 OPEN; #4480 signer validity **not verified**, do not claim repaired; #4483 exact pre-dispatch product enforcement OPEN/HOLD; #4482 advice Draft, not execution |
| Customer sites | **Chat / Claw / B66** can recommend different grades for the *same exact B14 model*. S0 independent group contract merged #4494; one explicit fallback allowed per site/tier and **OFF by default** #4498 | No current evidence of independent per-site UI saved groups, runtime entitlement enforcement, real site model assignments or full production rollout |
| B62 Chat Library | #4496 merged `9c418857` with owner-scoped project file listing, Files/Images navigation (Images = truthful no persistent store), same-state owner-switch and incomplete-list fixes | #4489 OPEN: only first 20 projects read, no complete historical pagination, **no B62 image persistence**. Real logged-in production E2E unverified |
| B62 calendar | CLO2 #4501 OPEN; Calendar glass overlay issue isolated from Library patch | No verified fix/merged PR/operational QA yet |
| Claw | LOCAL1 #4493 remains Draft; #3936 owns actual user/sse+HOLD E2E | Draft CI is not a customer-visible fix, do not merge blindly with stale main |
| PADIEM Connector | #4139 OPEN; shared internal broker/Windows runtime may be reused. #4503 docs reconciliation merged `c2262bec`; server #4476 and Windows #4490 remain Draft | **#4476 GitHub Actions 13/13 SUCCESS but GitGuardian separate check-run FAILURE** on HEAD `74875c35` — security block; source and Windows E2E NOT authorized |
| B66 quote | #4466 canonical general dialogue, #4412 quote-building handoff, #4316 single product E2E, #4465 Core instructions, #4468 time contract, #4469 actual web-search adapter. B66 #4481 general-model chat remains Draft | No inference that general provider dialogue, time injection or real TinyFish/Daum search is deployed merely from design/Mock/PR |
| Owner-selected OpenCode Go | Five Go models and one ZansLab `enabled:false` in registry; #4416 owns activation prerequisites. LongCat and Step 5 Free suitability #4505 OPEN | Go provider OFF. Do NOT import **different Kilo path**'s #3830/#3835 429/concurrency measurements as Go live evidence |
| Cross-product pre-instructions | #4465 shared Core owner; #4468 KST per-call contract; #4469 B66 actual retrieval adapter | **HOLD** until actual dispatch path inspection, fact-search authorization, prompt trust boundaries and tests; current date context does not itself perform web search |

## 2. Owner's model/tier decision — single current lookup

Read **[2026-10-13 1차 모델 등급·혜택·시험 원장](../models/PADIEM_OWNER_TIER_EVALUATION_20261013.md)** before proposing any grade/fallback. It distinguishes **confirmed draft preference**, **uncertain/exact-ID pending**, **owner-observed quality concern**, **registered state**, and **live test evidence**. The older [2026-10-08 Owner Decision Ledger](B14_OWNER_MODEL_DECISION_LEDGER_2026-10-08.md) and [2026-10-12 Go intake](B14_OWNER_SELECTED_OPENCODE_FIVE_ZANSLAB_LUNA_20261012.md) are versioned historical/registration documents, not current grade authority.

Current owner draft is **Free** 3.1 Flash Lite (1st), Laguna, SenseNova, with LongCat and Step 5 conditional; **Plus** 3.5 Flash Lite (2nd), Gemma 4 variant pending, ExLab identity pending; **Pro** Muse Spark 1.2 **not registered / exact identity unresolved**, ExLab Qwen; **Max** Muse Spark 1.3 (source OFF). Model availability and promotional economics are not interchangeable with member-tier rights. User has **not finalized per-site assignments or exact fallback candidates**.

## 3. Single issue owners / consolidation map

| Owner and lane | Canonical open issue | Incorporated / historical / separate acceptance |
| --- | --- | --- |
| Central brand/account/site separation | [#4428](https://github.com/skerishKang/ai-revenue-lab/issues/4428) | B66 **customer identity, PC, grades and navigation distinct** from PADIEM. Same admin email does not grant cross-product access |
| Model/admin policy source → durable write → runtime | [#4453](https://github.com/skerishKang/ai-revenue-lab/issues/4453), [#4480](https://github.com/skerishKang/ai-revenue-lab/issues/4480), [#4483](https://github.com/skerishKang/ai-revenue-lab/issues/4483) | Phase-specific blockers, NOT duplicates. B14 long-term BYOK/auto-routing design belongs to #2107; historical #2085/#2099/#2100 **already CLOSED** |
| Gemini live QA | [#4499](https://github.com/skerishKang/ai-revenue-lab/issues/4499) (LOCAL3 + CENTRAL) | #4502 closed unmerged; #4504 source gate, #4514 version GET gate merged; 3.1 real PASS once; 3.5 **NOT RUN** due pre-dispatch main race |
| LongCat/StepFun Free trial | [#4505](https://github.com/skerishKang/ai-revenue-lab/issues/4505) (LOCAL3) | #3830/#3835 are **old Kilo-provider Drafts**, not fresh OpenCode Go activation authority. #4416 owns provider API/account prerequisites |
| B62 Library | [#4489](https://github.com/skerishKang/ai-revenue-lab/issues/4489) (LOCAL2) | #4496 merged bounded UI; remaining all-history and independent image storage, production QA |
| Calendar glass issue | [#4501](https://github.com/skerishKang/ai-revenue-lab/issues/4501) (CLO2) | Separate visual fix. Do not conflate with Library source #4496 |
| Claw model HOLD / E2E | [#3936](https://github.com/skerishKang/ai-revenue-lab/issues/3936) (LOCAL1) | #4493 Draft and #3933 implementation; #3099 Windows E2E is distinct |
| Connector secure enrollment | [#4139](https://github.com/skerishKang/ai-revenue-lab/issues/4139) | [Connector status source index](PADIEM_CONNECTOR_4139_CENTRAL_STATUS_20261013.md), #4434 XLSX-PC result E2E, #3099 Windows acceptance, #4428 branded home; do not close dependent tickets as shipped |
| Shared freshness / B66 actual use | [#4465](https://github.com/skerishKang/ai-revenue-lab/issues/4465), #4466, #4412 | #4468 time verification is **subtask**, #4469 B66 retrieval is **adapter**, #4316 single B66 E2E. Old #4467 **already CLOSED and folded into #4466** |

### Explicit non-goals of this reconciliation
- No issue closure merely because its Draft PR exists; no destructive rewriting of past acceptance reports.
- No central-to-product automatic tier fanout, no silently enabled fallback, no B14 auto-route or substituted provider.
- No production secret inspection/rotation, D1 write, domain change, actual model POST, deployment, PC pairing or customer data access.
- No B66/PADIEM customer identity consolidation. Shared **internal platform** != linked customer account.

## 4. Immediate priority / safe gating

1. **CENTRAL / LOCAL3 #4499:** Gemini 3.1 has already real-PASSED one bounded synthetic POST — do **not** rerun. Gemini 3.5 has **no provider call** yet; B66 #4481 main advancement triggered an exact-SHA guard on the attempted workflow. Preserve this safety; coordinate a future distinct current-main/version-pinned one-shot, not an automatic replay.
2. **LOCAL3 #4505:** source-only LongCat input boundary / Step 5 Go error-class evidence; separate Kilo historical tests; output draft/HOLD status pending authentic Go evidence.
3. **LOCAL1 #3936:** revise #4493 against current main, preserve SSE/HTTP HOLD distinction and product permission; report exact-head CI; no B14 tier writes.
4. **LOCAL2 #4489:** actual production version check + logged-in Library UX and owner-isolation; then cursor pagination independently. Image storage is separate review.
5. **CLO2 #4501:** demonstrate Calendar glass obscuration with visual evidence, then small Calendar-only CSS/test fix.
6. **CENTRAL:** #4480 signer valid/served proof (currently unknown), #4453/#4483 member/site binding and per-dispatch enforcement; #4139 security findings; #4428 brand separation, #4465 shared contract only after product conflicts clear.

**ExLab follow-up (LOCAL3):** [#4516](https://github.com/skerishKang/ai-revenue-lab/issues/4516) owns an ExLab-only Qwen 3.8 one-shot source gate; previous [#4220](https://github.com/skerishKang/ai-revenue-lab/issues/4220) direct 200 versus Worker 429/504 and [#4252](https://github.com/skerishKang/ai-revenue-lab/issues/4252) capacity/429 are historical provider-specific evidence, **not** new successful gateway proof. Do not reuse the Google gate; no ExLab real call in source phase.

**Status semantics:** `MERGED_SOURCE` / `CI_GREEN` / `DEPLOYED_SERVED_VERSION` / `RUNTIME_CREDENTIAL_READY` / `OWNER_AUTHENTICATED_E2E` / `CUSTOMER_ENABLED` are **separate assertions**. Mark only with an exact dated evidence link.
