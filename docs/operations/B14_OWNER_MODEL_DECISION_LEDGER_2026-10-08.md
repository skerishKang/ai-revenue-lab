# B14 owner model decisions and implementation reconciliation (2026-10-08)

**Authority status:** owner decision record and current snapshot; documentation only. This ledger takes precedence over older historical examples in issues #1933, #2107, #2698, #3143, #3209, #3570, and #3589 for reporting current owner choices. It does NOT replace B14 catalog execution permission, activate a model, authorize Production, or override MODEL_CHANGE_OWNER_APPROVAL_POLICY.md. The owner controls new selection and activation.

**Snapshot:** remote main was fresh-read on 2026-10-08; local unmerged work found at E:/padiem-wt-plus-model-select. Source and production may diverge. Recheck exact-main, exact model ID and live readiness before declaring any model executable.

## 1. Customer-visible names (owner decision)

Exact owner wording: 파디엠플러스모델명, meaning 파디엠플러스 plus the INDIVIDUAL MODEL NAME. Never replace model identity with bare Padiem Plus / Pro / Max product tiers. Current unmerged local product_tier_routes.py instead builds English 'Padiem Plus - {model display name}'; this is not yet reconciled to the owner's Korean instruction. Do NOT infer that a separator, spacing, Pro/Max branding, or a tier-wide default is approved by this wording; fix literal product display contract against the recorded owner instruction.

## 2. Explicitly chosen Google AI Studio four-model set

Owner conversation record (2026-10-07 18:46 KST) names the four actual model IDs below. The local 2026-10-08 google_provider.py names the same four, with Google AI Studio origin generativelanguage.googleapis.com/v1beta and the binding NAME PADIEM_GEMINI_API_KEY. The local Google module is untracked; it is absent from current merged main. These models were tested for TEXT and IMAGE INPUT / UNDERSTANDING. This evidence does not establish IMAGE GENERATION or EDITING support.

| Provider | Upstream ID | Intended product model ID in unmerged local code | Text / image input evidence from LOCAL | Customer model part |
| --- | --- | --- | --- | --- |
| Google AI Studio | gemini-3.1-flash-lite | google/gemini-3.1-flash-lite | text 7/7; image 5/5 | Gemini 3.1 Flash Lite |
| Google AI Studio | gemini-3.5-flash-lite | google/gemini-3.5-flash-lite | text 7/7; image 5/5 | Gemini 3.5 Flash Lite |
| Google AI Studio | gemma-4-26b-a4b-it | google/gemma-4-26b-a4b-it | text 7/7; image 5/5 | Gemma 4 26B |
| Google AI Studio | gemma-4-31b-it | google/gemma-4-31b-it | text 7/7; image NOT VERIFIED (provider capacity); text 49.0s vs B14 20.0s budget | Gemma 4 31B |

All 7/7 and 5/5 claims are prior LOCAL synthetic fixture measurements, not a current Production or independently repeated live result. Preview ID gemini-3.1-flash-lite-preview is not in the selected four. Local provider wiring should be reviewed before any activation: the local google_provider.py specifies Google native origin/x-goog-api-key while generic app/pilot/platform.py currently constructs /chat/completions with Bearer semantics; registry declaration is not executable integration proof.

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

| Scope | Owner intent | Current main evidence | Local unmerged evidence | State |
| --- | --- | --- | --- | --- |
| Google four exact IDs | chosen | google_provider.py absent | module declaring four CATALOG_BY_ID exact IDs | LOCAL ONLY / NOT MERGED |
| Google capability | text and image-input tests | no integrated four-model source proved | 3 image proven on local fixture, one inconclusive | PARTIAL |
| Google provider live | execute via governed B14 only | NOT VERIFIED | protocol/credential binding mismatch to inspect | NOT PROVEN |
| Individual customer names | 파디엠플러스 + model name | old generic tier branding | English 'Padiem Plus - ' generator | DISPLAY MISMATCH |
| Five excluded | no customer approval | historic NVIDIA catalog entry | Kilo Poolside excluded; separate direct Poolside draft authorization unverified | EXCLUSION + UNVERIFIED AUTHORITY |
| Claw explicit registered model | permitted | PR #3743 merged | n/a | SOURCE MERGED, LIVE NOT PROVEN |
| B66 automatic quote selection | narrow B66-only free-first, unique qualified ID, attempts <=1, retry/fallback 0 | PR #3762 merged | n/a | SOURCE MERGED, E2E NOT READY |
| B14 admin Control Center | later design | #2107 open DESIGN ONLY | n/a | NOT BUILT |

## 6. B66 CGI Production evidence and distinct incident

Login PASS; Guided CGI quote + browser PDF PASS; complete freeform HTTP 502 / upstream_timeout; exactly one model interpreter POST and no retry/fallback; partial follow-up UNTESTED; CUSTOMER_READY=NO. Actual invoked MODEL ID is absent from the protected E2E evidence. DO NOT infer NVIDIA was called from the catalog. Distinguish registry/selection consistency from true upstream timeout and prove an exact selected model ID via bounded safe telemetry before assigning root cause. #3751 stays open.

## 7. Safe work order; no source or Production change authorized by this ledger

(1) Preserve existing local drafts/worktrees. (2) Complete provenance/classification for remaining models; remove five excluded from customer execution proposals. (3) Reconcile customer-visible per-model naming without inventing global primary. (4) Correct native Google protocol adapter and validate catalog/provider/auth/capabilities with network-free tests, then owner-authorized live canary. (5) Verify B14 registration and Chat/Claw/B66 authorization separately. (6) Diagnose B66 timeout using exact selected model evidence; no silent retry/fallback or billing expansion. (7) Independently review, merge and deploy only at explicit owner gates.

## 8. Evidence and authority links

- Issue #3554: current owner model-selection authority (multi-model, per-execution choice).
- Issue #2107: future centralized admin; design-only.
- Issue #2698: future Auto Router V2; deferred.
- Issue #3751 and #3760; PR #3762: B66 runtime and Production gate.
- PR #3593: Space Bunny retirement; PR #3597: GLM changes still Draft.
- PR #3743 / #3750: merged Claw choice and owner policy.
- LOCAL unmerged: E:/padiem-wt-plus-model-select/apps/korean-ai-platform/app/pilot/google_provider.py; .../app/pilot/platform.py; packages/padiem-control-plane/padiem_control_plane/product_tier_routes.py.
- Historic snapshot only: issues #1933, #3143, #3209, #3570, #3589.
