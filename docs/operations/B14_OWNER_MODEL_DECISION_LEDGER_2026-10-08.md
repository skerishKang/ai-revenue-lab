<!-- B14_OWNER_ROLE_SOURCE_OF_TRUTH_20261010 -->
> **B14 역할 최신 원칙(2026-10-10):** [원제작사 모델·서빙 제공업체·변형 모델의 공식 사양 및 B14 실행 권한](../architecture/B14_MODEL_PROVIDER_EXECUTION_AUTHORITY_2026-10-10.md)을 우선 확인합니다. **B14는 정확히 사용자가 선택한 모델을 해당 업체의 공식 API로 실행**하며, temperature/토큰/리즈닝을 임의 지정하거나 옵션을 조용히 바꾸지 않습니다. 원본 모델의 공식 사양과 실제 API 제공업체의 계약은 별도 증빙합니다. 과거 코드·평가 수치는 이 원칙의 구현 증명이 아닙니다.
<!-- /B14_OWNER_ROLE_SOURCE_OF_TRUTH_20261010 -->

> 2026-10-08 모델 등록 구조: apps/korean-ai-platform/app/pilot/b14_models.json이 단일 실제 등록 원본입니다. 5개 제거/9개 유지 및 설정 절차는 B14_MODEL_REGISTRY_SINGLE_SOURCE.md를 참조하세요. 아래 기존 Owner 승인/배포 안전 정책은 유효하며 과거 모델 예시는 역사적 기록입니다.

# B14 owner model decisions and implementation reconciliation (2026-10-08)

**Authority status:** owner decision record and current snapshot; documentation only. This ledger takes precedence over older historical examples in issues #1933, #2107, #2698, #3143, #3209, #3570, and #3589 for reporting current owner choices. It does NOT replace B14 catalog execution permission, activate a model, authorize Production, or override MODEL_CHANGE_OWNER_APPROVAL_POLICY.md. The owner controls new selection and activation.

**Snapshot reconciliation (2026-10-08):** B14 Google four manual-pin model registrations were merged by PR #3788 at SHA bcb05bb7fea9a31b72d805e7237441e045883b1b. Separate LOCAL product naming/tier drafts are not thereby merged. Source registration is not a Plus product route or proof of Production readiness; recheck exact-main B14 catalog, Control Plane declaration and credential-backed live evidence.

## 0D. Owner-selected ExLab Qwen3.8 Flash Next Uncensored (2026-10-10)

- Owner explicitly requested `experiential/qwen3.8-flash-next-uncensored`, the ExLab gateway upstream `qwen3.8-flash-next-uncensored`. Canonical B14 source now has **10 registered models / 7 platform providers**; the prior nine-model discussions are historical snapshots. This is separate from retired B.AI Qwen (`b-ai/qwen3.8-flash`) and retired ExLab GPT-5.6 Luna.
- The existing Cloudflare Secrets Store binding name `PADIEM_EXLAB_API_KEY` is reused, without reading or changing its value. No automatic fallback, tier assignment or Production deployment.
- **Owner correction 2026-10-10:** The Owner expressly accepts ExLab data-retention concerns for the current free-promotion live evaluation and did not request a special release hold. Remove `model_data_policy_pending` and matching last-egress refusal from PR #3961. Preserve manual-only selection, normal credential and network error controls, no automatic model selection, silent fallback or default/tier mutation. Live Worker success is not established by mocked tests.

## 0C. Owner final retirement — Thinking Machines Inkling Small (2026-10-10, newest)

- **REMOVE / DO NOT EVALUATE / DO NOT REGISTER / DO NOT RECOMMEND:** Thinking Machines **Inkling Small**, exact public Kilo free ID `thinkingmachines/inkling-small:free`, direct upstream and Kilo aliases. The Owner explicitly rejected this small-capacity candidate; do not propose it again as the next model or place it in B14/Claw/B62/B66 candidate, manual selection, Auto, fallback or recurring benchmark queues.
- **Narrow exclusion, no blanket ban:** Other vendors' Small/Mini and other Thinking Machines models are not excluded by this decision. StepFun **Step 5 Preview Free** and all nine currently registered B14 models remain unchanged.
- The latest canonical B14 registry (nine models) and read-only served model roster **never included Inkling Small**, so no provider entry, credential or Production endpoint was deleted. The owner exclusion guard, last pre-network gate and evaluation registration tests prevent accidental future admission.
- Vendor-managed Kilo public catalog visibility is unrelated to PADIEM approval; historical records remain for audit.

## 0B. Owner final retirement — StepFun Step 3.7 Flash (2026-10-09)

- **RETIRE / DO NOT EVALUATE / DO NOT REGISTER / DO NOT RECOMMEND:** StepFun **Step 3.7 Flash**. This covers public direct `stepfun/step-3.7-flash`, any draft `kilo/stepfun/step-3.7-flash`, catalog/discovery aliases and model presets that point to this upstream. Do not put it in B14/Claw/B62/B66 candidate or manual model lists, Auto, fallback, or future benchmark schedule.
- **Current B14 nine-model canonical JSON:** Step 3.7 Flash was **never present**, so no actual registered-model deletion, deployment or credential mutation was necessary. Exact model exclusion is enforced in live pre-egress and read-only evaluation registry gates so later drafts cannot silently re-introduce it. Vendor's public Kilo /models listing is external discovery and cannot be deleted by PADIEM.
- **StepFun Step 5 Preview Free is NOT Step 3.7** and remains an approved *evaluation candidate*, not automatically a customer default. The independent source-only Step 5 10/10 QKR report (PR #3947) remains evidence; do not alter it or reuse the disallowed 3.7 route.
- Prior issue/PR/test references to Step 3.7 are **historical only**, not a current proposal. This owner decision supersedes the 2026-10-09 statement that Step 3.7 would be next.

## 0. Owner reconciliation — 2026-10-09 (current over 2026-10-08 snapshot)

- **Model/evaluation single source:** apps/korean-ai-platform/app/pilot/b14_models.json on exact main. As of this decision, it registers **9 enabled models across 6 providers**, with Plus/Pro/Max groups all empty. Neither a Kilo provider listing nor an old issue, fixture or Draft PR creates an approved evaluation candidate.
- **Poolside direct provider:** poolside/laguna-s-2.1 uses https://inference.poolside.ai/v1, credential binding NAME PADIEM_POOLSIDE_API_KEY. The Owner explicitly reconfirmed DIRECT Poolside for evaluation and rejected using Kilo for this model. This is source registration/evaluation permission, not proof of a real key, live readiness or customer tier assignment.
- **Retire the Kilo Laguna route:** kilo/poolside-laguna-s-2.1-free and alternate discovered Kilo/poolside/laguna aliases MUST NOT be evaluated. The other four deleted model identities (B.AI Qwen, Motif 3, GPT-5.6 Luna, NVIDIA Nemotron) stay excluded. No silent replacement route or fallback.
- **PR #3819 is MERGED**, superseding former Draft references. The StepFun #3835 experiment is still a separate Draft: NOT one of the nine current-main models, even if another provider advertises its availability.
- **Current evaluation protocol:** docs/operations/B14_B66_QUOTE_MODEL_EVALUATION_PROTOCOL.md documents the B66 input-extraction rubric, no per-quote template regeneration, and strict live availability evidence.
- **Operational evaluation gate:** .github/scripts/b14_owner_evaluation_registry.py selects only canonical enabled model IDs and validates exact provider/upstream identity. The old five-model fixture is historical; old live all-five/Motif/Luna candidates are rejected before provider calls. No live provider access is inferred from a successful synthetic test.
- **B66 assessment:** initial quote source analysis and certification (Sol 6.1 prior implementation) is separate from evaluating repeat-request extraction of recipient, items, quantities and unit prices. B66 QuoteCore computes all money. A certified template renderer converts the normalized data to PDF without a repeated model call.
- Owner-only controls for tier membership, Auto routing, cost/price rules, credential provisioning and Production stay unchanged.

## 1. Customer-visible names (owner decision)

Exact owner wording: 파디엠플러스모델명, meaning 파디엠플러스 plus the INDIVIDUAL MODEL NAME. Historical unmerged LOCAL English naming proposals are not current merged UI behavior or owner-approved Korean naming. Do not invent separator, spacing, Pro/Max branding, tier-wide default or a single primary.

## 2. Explicitly chosen Google AI Studio four-model set

The owner chose the four exact Google AI Studio IDs below. PR #3788 merged their B14 manual-pin registration in apps/korean-ai-platform/app/pilot/google_provider.py, wired by platform.py. Its source uses Google's OpenAI-compatible origin /v1beta/openai, the existing B14 Bearer /chat/completions contract and PADIEM_GEMINI_API_KEY as a credential binding NAME only. This is SOURCE MERGED, not evidence of a Plus product route, live credential or Production call. The tests cover TEXT and IMAGE INPUT/UNDERSTANDING, NOT IMAGE GENERATION or EDITING.

| Provider | Upstream ID | B14 manual-pin model ID (merged source) | Text / image input evidence from LOCAL | Customer model part |
| --- | --- | --- | --- | --- |
| Google AI Studio | gemini-3.1-flash-lite | google/gemini-3.1-flash-lite | text 7/7; image 5/5 | Gemini 3.1 Flash Lite |
| Google AI Studio | gemini-3.5-flash-lite | google/gemini-3.5-flash-lite | text 7/7; image 5/5 | Gemini 3.5 Flash Lite |
| Google AI Studio | gemma-4-26b-a4b-it | google/gemma-4-26b-a4b-it | text 7/7; image 5/5 | Gemma 4 26B |
| Google AI Studio | gemma-4-31b-it | google/gemma-4-31b-it | text 7/7; image NOT VERIFIED (provider capacity); text 49.0s vs B14 20.0s budget | Gemma 4 31B |

All 7/7 and 5/5 claims are prior synthetic-fixture measurements, not independently repeated Production/live results. Preview ID gemini-3.1-flash-lite-preview is not selected. PR #3788 corrected the LOCAL native x-goog-api-key vs B14 Bearer protocol mismatch by using the compatible Google /v1beta/openai origin. Source+network-free tests prove registration wiring, NOT Production availability. Gemma 4 31B remains text-only in merged source because image input was unverified and the earlier 49.0s text result exceeded the 20.0s B14 default budget.

## 3. Other model history versus current approval

- Agnes 3.0 Flash (agnes-ai/agnes-3.0-flash): 2026-10-07 owner text experiment selected it, with Ling 3.1 Flash (inclusionai/ling-3.1-flash) as reserve and auto fallback OFF. The later owner multi-model decision does not imply an Agnes single global primary.
- The unmerged LOCAL selectable-set draft also declares SenseNova 6.8 Flash Lite (sensenova/sensenova-6.8-flash-lite), Mercury 2.5 (inception/mercury-2.5), Atria Dawn Preview (atria/Atria-Dawn-Preview), and Dots 3 Note Preview (kilo/dots-3-note-preview-free). Their presence in a local draft is not independent proof of final operator activation or Production access. Preserve provenance and verify the original exact owner choices before promoting their status.
- GLM 5.3 Flash Abliterated model work is in unmerged Draft PR #3597; not an accepted live model merely because a PR exists.
- The old Space Bunny Alpha product route is retired: #3593 MERGED. Historical references remain evidence only.
- B14 multiple-model per-run user selection is explicitly permitted under #3554 and merged PR #3750. PR #3743 merged Claw choice wiring. Neither is proof that a newly registered provider is live/ready.
- Legacy #3209 Space Bunny, #3570 Ling/Step/Agnes chain, #3589 Ling-to-Agnes fallback, #2698 old routing assumptions, and #1933 NVIDIA single-route prose are NOT the current model-selection authority.

## 4. Five OWNER-EXCLUDED models: final exclusion overrides old entries

1. Kilo Poolside Laguna route: **OWNER EXCLUDED**, including discovery aliases. Separate direct Poolside Laguna registration is **OWNER RECONFIRMED for B14 evaluation** (2026-10-09). Customer Plus/Pro/Max activation remains separate.
2. B.AI Qwen.
3. Motif 3.
4. GPT-5.6 Luna.
5. NVIDIA Nemotron, including Nemotron 3 Ultra.

These five retired routes must not enter B14 current registered evaluation, B66, Auto or fallback. Historic catalog.py and old benchmark fixtures are NOT selection authorities; consult section 0 and central JSON. Direct Poolside is currently registered/reconfirmed for evaluation but does NOT imply a paid tier or a live credential. Legacy 2026-10-08 unresolved language is superseded by the 2026-10-09 Owner decision.

## 5. B14 registration truth table (as of this snapshot)

| Scope | Owner intent | Current B14 source | Other evidence / limitation | State |
| --- | --- | --- | --- | --- |
| Google four exact IDs | chosen | PR #3788 merged four exact CATALOG_BY_ID manual-pin registrations | Not appended to CATALOG_MODELS or generic b14/auto; Plus tier remains HOLD | SOURCE MERGED / LIVE NOT PROVEN |
| Google capability | text and image-input tests | Three with image input tags; Gemma 4 31B text-only | Prior synthetic fixture only; no image generation proof | SOURCE CAPABILITIES DECLARED / LIVE NOT PROVEN |
| Google provider live | governed B14 execution only | OpenAI-compatible Google origin and Bearer adapter wired | Credential-backed live/Production E2E NOT VERIFIED | NOT PROVEN |
| Individual customer names | 파디엠플러스 + model name | old generic tier branding | English 'Padiem Plus - ' generator | DISPLAY MISMATCH |
| Five excluded | no customer approval | historic NVIDIA catalog entry | Kilo Poolside excluded; direct Poolside registered for evaluation; no tier assignment | OWNER RECONFIRMED / LIVE UNVERIFIED |
| Claw explicit registered model | permitted | PR #3743 merged | n/a | SOURCE MERGED, LIVE NOT PROVEN |
| B66 quote selector | Owner rejects free/paid eligibility filter; one attempt and no silent retry/fallback | Legacy free-first source remains merged from PR #3762 | Draft policy PR #3796 is separate; runtime policy/source mismatch and E2E issue #3751 remain unresolved | POLICY/SOURCE MISMATCH OPEN |
| B14 admin Control Center | later design | #2107 open DESIGN ONLY | n/a | NOT BUILT |

## 6. B66 CGI Production evidence and distinct incident

Login PASS; Guided CGI quote + browser PDF PASS; complete freeform HTTP 502 / upstream_timeout; exactly one model interpreter POST and no retry/fallback; partial follow-up UNTESTED; CUSTOMER_READY=NO. Actual invoked MODEL ID is absent from the protected E2E evidence. DO NOT infer NVIDIA was called from the catalog. Distinguish registry/selection consistency from true upstream timeout and prove an exact selected model ID via bounded safe telemetry before assigning root cause. #3751 stays open.

## 7. Safe work order; no source or Production change authorized by this ledger

(1) Preserve existing local drafts/worktrees. (2) Keep owner exclusions authoritative. (3) Reconcile Korean per-model display in a separate product UI slice. (4) Preserve the merged Google OpenAI-compatible adapter; independently prove credential-backed live readiness before release. (5) Verify B14 source registration separately from Chat/Claw/B66 route activation. (6) Diagnose B66 timeout using exact model evidence, with no silent retry/fallback. (7) Review, merge and deploy only at explicit owner gates.

## 8. Evidence and authority links

- Issue #3554: current owner model-selection authority (multi-model, per-execution choice).
- Issue #2107: future centralized admin; design-only.
- Issue #2698: future Auto Router V2; deferred.
- Issue #3751 and #3760; PR #3762: B66 runtime and Production gate.
- PR #3593: Space Bunny retirement; PR #3597: GLM changes still Draft.
- PR #3743 / #3750: merged Claw choice and owner policy.
- PR #3788 MERGED: Google B14 source registration in google_provider.py and platform.py. Product naming/tier proposals in E:/padiem-wt-plus-model-select are separate, unmerged LOCAL work; neither proves Production. Draft PR #3796 addresses B66 no-price-filter policy text only, not runtime.
- Historic snapshot only: issues #1933, #3143, #3209, #3570, #3589.
