> 2026-10-08 모델 등록 구조: apps/korean-ai-platform/app/pilot/b14_models.json이 단일 실제 등록 원본입니다. 5개 제거/9개 유지 및 설정 절차는 B14_MODEL_REGISTRY_SINGLE_SOURCE.md를 참조하세요. 아래 기존 Owner 승인/배포 안전 정책은 유효하며 과거 모델 예시는 역사적 기록입니다.

# B14 owner model decisions and implementation reconciliation (2026-10-08)

**Authority status:** owner decision record and current snapshot; documentation only. This ledger takes precedence over older historical examples in issues #1933, #2107, #2698, #3143, #3209, #3570, and #3589 for reporting current owner choices. It does NOT replace B14 catalog execution permission, activate a model, authorize Production, or override MODEL_CHANGE_OWNER_APPROVAL_POLICY.md. The owner controls new selection and activation.

**Snapshot reconciliation (2026-10-08):** B14 Google four manual-pin model registrations were merged by PR #3788 at SHA bcb05bb7fea9a31b72d805e7237441e045883b1b. Separate LOCAL product naming/tier drafts are not thereby merged. Source registration is not a Plus product route or proof of Production readiness; recheck exact-main B14 catalog, Control Plane declaration and credential-backed live evidence.

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

1. Kilo Poolside Laguna (the Kilo route `kilo/poolside-laguna-s-2.1-free`). The owner statement alone does **not** establish an inclusion or exclusion decision for a separately registered direct Poolside provider route `poolside/laguna-s-2.1`; that route's final customer approval remains UNCONFIRMED.
2. B.AI Qwen.
3. Motif 3.
4. GPT-5.6 Luna.
5. NVIDIA Nemotron, including Nemotron 3 Ultra.

These five must not be represented as owner-approved selectable Padiem Plus models. Inspect B14 registry and B66 eligibility before changing runtime; do not delete provider metadata blindly. Specifically, merged main catalog.py still contains a historical NVIDIA Nemotron entry; the unmerged LOCAL Plus selectable set declares direct poolside/laguna-s-2.1 EXECUTABLE but its separate owner authorization has not been recovered. Treat the NVIDIA entry as an exclusion conflict and the separate Poolside draft as an authorization-UNCONFIRMED state, not as owner approval or rejection. Future remediation must verify existing dependencies and prevent excluded routes becoming auto/manual/fallback eligible under customer products, preserving unrelated provider integrations.

## 5. B14 registration truth table (as of this snapshot)

| Scope | Owner intent | Current B14 source | Other evidence / limitation | State |
| --- | --- | --- | --- | --- |
| Google four exact IDs | chosen | PR #3788 merged four exact CATALOG_BY_ID manual-pin registrations | Not appended to CATALOG_MODELS or generic b14/auto; Plus tier remains HOLD | SOURCE MERGED / LIVE NOT PROVEN |
| Google capability | text and image-input tests | Three with image input tags; Gemma 4 31B text-only | Prior synthetic fixture only; no image generation proof | SOURCE CAPABILITIES DECLARED / LIVE NOT PROVEN |
| Google provider live | governed B14 execution only | OpenAI-compatible Google origin and Bearer adapter wired | Credential-backed live/Production E2E NOT VERIFIED | NOT PROVEN |
| Individual customer names | 파디엠플러스 + model name | old generic tier branding | English 'Padiem Plus - ' generator | DISPLAY MISMATCH |
| Five excluded | no customer approval | historic NVIDIA catalog entry | Kilo Poolside excluded; separate direct Poolside draft authorization unverified | EXCLUSION + UNVERIFIED AUTHORITY |
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
