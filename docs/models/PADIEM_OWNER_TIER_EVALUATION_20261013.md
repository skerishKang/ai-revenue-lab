# PADIEM AI owner draft — Free/Plus/Pro/Max model tier, benefits, and test decisions (2026-10-13 KST)

> **CURRENT OWNER DRAFT / NON-EXECUTING RECOMMENDATION, NOT AN ACTIVATION MAP.** The grade suggestions are based on the owner's own picks, provider promotional benefits/cost constraints, and observed usability, **not a model benchmark ranking**. This supersedes only the **grade preferences** written in historical [2026-10-12 OpenCode Go intake](../operations/B14_OWNER_SELECTED_OPENCODE_FIVE_ZANSLAB_LUNA_20261012.md); it does **not** undo provider intake IDs, exclusion decisions, secret boundaries or official API protocols. Confirmed actual model IDs come from the canonical [B14 JSON registry](../../apps/korean-ai-platform/app/pilot/b14_models.json).
>
> **Snapshot:** 2026-10-13 `main a525f21f36198317edde5d76c332c97095edef49`: 20 registered, **14 source enabled / 6 source disabled**, `groups.plus/pro/max=[]`. Source ON does **not** prove a working runtime credential, live provider response, member entitlement or production selection. **Chat, Claw and B66 may each assign different grades to one exact registered model.** Owner has not approved a cross-site fanout.

## 1. Owner's current first-round candidates

| Intended member tier | Model and exact B14 ID | Owner preference / unresolved detail | B14 source state | Live usability evidence |
| --- | --- | --- | --- | --- |
| **Free** | **Gemini 3.1 Flash Lite** — `google/gemini-3.1-flash-lite` | **1st priority** | ON | **LIVE PASS**: [one-shot run 38288787901](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38288787901), HTTP 2xx, exact model match, 11,039ms, 1 POST, retry/fallback 0; no streaming/reliability or Free customer activation proof |
| Free | Laguna S 2.1 — `poolside/laguna-s-2.1` | Included; do not alias to retired **Kilo-routed** Laguna | ON | Real serving/Free membership not inferred |
| Free | SenseNova 6.8 Flash Lite — `sensenova/sensenova-6.8-flash-lite` | Included | ON | Real serving/Free membership not inferred |
| Free conditional | LongCat 2.5 Preview Free — `opencode-go/longcat-2.5-preview-free` | Owner reports input feels small; **test then retain/remove** | **OFF**, Go provider OFF | #4505 input boundary / user experience pending |
| Free conditional | StepFun Step 5 Preview Free — `opencode-go/step-5-preview-free` | Owner reports busy/server overload; **test then retain/remove** | **OFF**, Go provider OFF | #4505 Go evidence pending; do not equate Kilo-route 429 with Go |
| **Plus** | **Gemini 3.5 Flash Lite** — `google/gemini-3.5-flash-lite` | **2nd priority** | ON | **LIVE PASS**: [Gemini 3.5 live run 38292210671](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38292210671), HTTP 2xx, exact provider+model match, **1,861ms**. Earlier [run 38291355344](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38291355344) stopped before POST due main drift. Actual provider POST **1 total**, retries/fallback 0 |
| Plus | Gemma 4 — exact choice **PENDING**: `google/gemma-4-26b-a4b-it` or `google/gemma-4-31b-it` | Owner said “Gemma 4”, did **not** choose between 26B/31B | Both ON | No variant selected or live acceptance |
| Plus | ExLab (exact identity **PENDING**) | Owner said “ExLab” without exact Plus target; do not infer same Qwen as Pro | UNKNOWN until selected | No Plus model assignment |
| **Pro** | OpenCode Go Muse Spark **1.2** — **EXACT ID UNKNOWN / NOT REGISTERED** | **Add only after official catalog/account/model-ID/wire/license proof** | NOT REGISTERED | No real test; do not alias to Muse 1.3 |
| Pro | ExLab Qwen — `experiential/qwen3.8-flash-next-uncensored` | Clearly nominated | ON | Historical direct HTTP 200 vs B14 429/504 [#4220](https://github.com/skerishKang/ai-revenue-lab/issues/4220), intermittent capacity [#4252](https://github.com/skerishKang/ai-revenue-lab/issues/4252). Exact one-shot source gate [#4517](https://github.com/skerishKang/ai-revenue-lab/pull/4517) **MERGED**, but real dispatch **tool-blocked before transmission**: live HTTP NOT_RUN, POST=0, no success/reliability claim [#4516](https://github.com/skerishKang/ai-revenue-lab/issues/4516) |
| **Max** | OpenCode Go Muse Spark **1.3 Contributor** — `opencode-go/muse-spark-1.3-contributor` | Owner moved this from historical Pro to **Max** | **OFF**, Go provider OFF | Response protocol/account & contributor terms review still needed |

### Unassigned, preserved existing intake
- `opencode-go/gpt-6-luna` and `opencode-go/claude-haiku-5-5` were **previously nominated Max** in the 2026-10-12 Go intake, but **not reconfirmed in this first-round shortlist**. Keep registered OFF; do not delete them or silently make them Max active. The owner will decide remaining models later.
- `zanslab/gpt-6-luna` is present in **current B14 JSON as disabled**. This updates the *historical* Go/ZansLab intake document that had said “not yet registered”; registration still does **not** confirm authenticated account availability, official route identity or live dispatch readiness.
- Other enabled B14 candidates remain **unassigned in this owner shortlist**. The 14 source-enabled entries are a registry fact, not 14 approved subscriber tier slots.

## 2. Primary + ONE fallback per site/tier

- The owner approved **at most one explicit fallback** for a selected primary, **default OFF**; #4498 merged source guard. This is a **slot constraint**, not a selection of a particular backup model.
- The assistant's illustrative suggestions (**Free Laguna backup, Plus Gemma backup, Pro Muse backup**) were **not separately owner-confirmed as live fallback picks**. Mark them `SUGGESTION_ONLY`; no B14 fallback routing request or member-visible auto retry.
- A central tier roster offers suggestions; it **never** overwrites Chat, Claw or B66 site's tier groups. The same exact B14 ID can be Free in Chat, Pro in Claw, Plus in B66, subject to product/global/provider policy and each product's separate customer/brand account.
- No alternate model calls on auth/entitlement/HOLD/approval, no paid escalation, and never use temporary provider free benefits as proof of a Free product grant.

## 3. Source and real test gates

| Gate | Now | Evidence owner |
| --- | --- | --- |
| B14 exact registered ID + model/provider enabled | 14 ON / 6 OFF; `groups.plus/pro/max` empty | B14 JSON and registry loader |
| Gemini contract/mock | LOCAL3 73 prior tests; #4504 merged 40+ new guard tests, exact PR CI green | [#4499](https://github.com/skerishKang/ai-revenue-lab/issues/4499), [#4504](https://github.com/skerishKang/ai-revenue-lab/pull/4504) |
| Gemini actual provider response | **3.1 PASS** 11,039ms; **3.5 PASS** 1,861ms, both exact model matched, one actual POST each, no network retry or fallback. Sample size one each; not sustained speed/stability | [#4499](https://github.com/skerishKang/ai-revenue-lab/issues/4499), [3.1 success](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38288787901), [3.5 success](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38292210671) |
| LongCat and Step 5 Go Free acceptance | **HOLD / real provider test pending**; source #4508 tests/report merged, provider/models OFF; `context_window=0` = unknown bound, not zero effective context. #4416 real gateway currently lacks authenticated stable coding session propagation; Draft #4524 test-only | [#4505](https://github.com/skerishKang/ai-revenue-lab/issues/4505), #4416 |
| OpenCode Go paid/contributor and Muse 1.2 | Exact route/terms/account permission unknown; no speculative registration or customer traffic | #4416; official serving provider's dated terms |
| Product-specific primary/fallback persistence and runtime enforcement | **NOT ACTIVE**; S0 groups only, no site write fanout | #4453, #4480, #4483, #4428 |

## 4. Decision and testing order

1. Preserve current first-round membership **as an owner evaluation table only**; do not set B14 `groups` or product tier DB.
2. **Both Gemini 3.1 and 3.5 have PASSED one bounded real API run each**; no extra connection smoke needed. Do not enable member tiers, auto-fallback or customer-wide model selection from a single sample; streaming, sustained latency/uptime and site entitlements require separate acceptance.
3. ExLab #4517 separate gate is **already source-merged**, but actual one-shot dispatch was tool-level blocked before transmission; #4516 stays OPEN (POST=0). No retry, bypass, or false live success claims. Do not change Gemini allowlists.
4. LongCat/StepFun evaluation report source #4508 is merged; #4505 real provider suitability remains HOLD. LOCAL3 #4416 / Draft #4524 investigates missing authenticated stable coding-agent session bridge; no model enabling or untrusted session header shortcut.
5. Request exact **Gemma 4 variant**, exact **Plus ExLab model**, verified **Muse 1.2 upstream ID**, and actual **fallback ID(s)** only when the owner revisits the decisions. Do not silently fill these gaps.

**Historical documents remain evidence of when a decision was made, not current approval.** If historical grade examples conflict with this date's user decision, use this newer provisional decision while retaining official model-exclusion/security gates.
