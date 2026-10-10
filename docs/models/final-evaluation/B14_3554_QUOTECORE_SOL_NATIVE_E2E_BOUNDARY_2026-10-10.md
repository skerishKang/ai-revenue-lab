# B14 #3554 — SenseNova/Kira quotation → QuoteCore → Sol 6.1 E2E evidence boundaries

**Checked:** 2026-10-10 KST. **Current result: OFFLINE BOUNDARY CONTRACT PASS; CUSTOMER NATIVE SOL PDF E2E NOT VERIFIED.** These are different gates; do not infer an operating PDF generator from a client-side cache.

## 1. Evidence matrix and division of ownership

| Boundary | Existing evidence | Current conclusion |
|---|---|---|
| B14 Production exact selected model → provider → short nonempty answer | [SenseNova 1 authorized POST](B14_3554_OWNER_QUOTA_AND_LIVE_PROBE_GATE_2026-10-10.md) HTTP200 / 8,328 ms / `OK`, 385 tokens; [Kira 1 authorized POST](B14_KIRA_LIVE_ONCE_AND_PROMO_SCOPE_2026-10-10.md) HTTP200 / 7,781 ms / `OK`, 2,037 tokens; both attempt=1, fallback=false | **LIVE CONNECTIVITY PASS** for *two exact models*, not quality |
| Actual model response for QKR-008 12 Korean items | Historical 2026-10-09 SenseNova B14 quote cases **10/10 PASS**, direct vendor 10/10 plus four reasoning cases, but **different code, prior settings**. **Kira QKR prompt has not been run** as part of this update | SenseNova **HISTORIC LIMITED**; Kira **NOT TESTED**; no new provider requests |
| Synthetic model-shaped `choices[0].message.content` JSON + `business14` route metadata → actual B66 `QuoteExtraction.buildDraftCandidate` → actual `QuoteCore.computeDraftTotals` | [Offline Node test](tests/b14_3554_quote_to_sol_boundary.test.cjs) using exact current `b14_models.json` IDs plus committed QKR-008 synthetic fixture, **for SenseNova and Kira separately** | **OFFLINE CONTRACT PASS**: 12/12 item names and quantities preserved; supply **6,500,000 KRW**, VAT **650,000**, total **7,150,000**. This verifies the transform/math, not an actual model's factual extraction |
| Trusted saved CGI quote skill / approved template / tax review / Sol native renderer | Offline test supplies **explicit synthetic approved model/scope** to exercise verifier. [#4117](https://github.com/skerishKang/ai-revenue-lab/issues/4117) B66 team owns the real trusted release and Sol native renderer endpoint | **STUBBED**: synthetic approval does not prove an authenticated Saved Quote Skill exists or has passed release. Never promote fake PDF bytes |
| `quote-sol-pdf-snapshot.js` native PDF cache and preview/download/Drive byte identity | The actual client snapshot code checks renderer marker, certificate/profile/skill hashes, real SHA-256 bytes and stale-snapshot revocation. Offline test mocks the trusted response with a distinct *mock-only* PDF byte sequence and checks the same computed SHA-256 for all three target copies, for both B14 IDs | **OFFLINE CONTRACT PASS**: confirms *byte-consistency when valid signed response is supplied*; no renderer deployed/invoked, no real browser preview/Google Drive save performed |
| Current Production Sol 6.1 native PDF → customer preview/download/Drive/Claw/Engine workflow | **No end-to-end release/production proof** in this B14 slice. Live served commit SHA for latest B14 changes remains unattested | **OPEN**; do not misstate an offline model mock or Chromium/browser PDF as Sol-native |

## 2. How to reproduce — no paid tokens, no secret access

From current exact source worktree:

```powershell
node --test docs/models/final-evaluation/tests/b14_3554_quote_to_sol_boundary.test.cjs
```

Four tests cover exact SenseNova and Kira model IDs, synthetic Korean QKR-008 12-row QuoteCore arithmetic and receipt-to-Sol-snapshot byte identity, fail-closed local identity checks (wrong selected/actual model, extra attempt, fallback, blank/truncated response) and no-network/mock-only marking. These additional **test-side identity guards are not evidence of newly changed Production Gateways**. If Gateway/UI does not enforce identical acceptance, the separate product team must verify it.

The test explicitly executes **no HTTP request**, **no actual native Sol renderer**, **no Provider/LLM POST**, **no Drive API**, and **no Production deployment**. The fixture byte header may begin `%PDF-` but contains obvious `OFFLINE ... MOCK ONLY` text. Its digest equality is *not* proof of customer-readable PDF pages, font/layout parity, authenticated PDF release, or complete Sol 6.1 generation.

## 3. Next owner gates — avoid redundant paid greeting tests

1. **B66/Sol owner #4117:** certify an *authenticated and released* Saved Quote Skill and a **real** Sol-native PDF endpoint; verify that preview/download/Drive share the same actual PDF SHA-256 from the same approved snapshot, that tax/profile/skill certificate matches, and stale/account-changed downloads fail.
2. **B14 #3554 + evaluation #2676:** when separately approved for further possibly billed model calls, test **one selected canonical model and one QKR case first**, compare nonempty returned content, exact provider identity, 12 row facts and quote totals through *customer's actual B66 ingestion*. **Kira has no real QKR response in the present evidence**. Model performance scores require representative standardized cases, not one greetings request.
3. **Engine/Claw team:** separately attest authenticated user-selected model → Engine → B14 → extracted facts → B66/QuoteCore → Sol native PDF customer download. A passing mocked HTTP body does **not** certify this integration.
4. **ExLab:** retain owner restriction HOLD; this report does not grant a new API POST or model fallback.
5. Preserve ownership boundaries: B14 adds **offline tests and documentation only**; no B66 Sol route changes, no request default changes, no local private customer file operations.

**Status:** `SENSENOVA_LIVE_GREETING=PASS`, `KIRA_LIVE_GREETING=PASS`, `QKR008_B14_SYNTHETIC_TO_QUOTECORE=PASS`, `SOL_SNAPSHOT_BYTES_OFFLINE=PASS`, `REAL_SOL_NATIVE_PDF=NOT_TESTED`, `GOOGLE_DRIVE_UPLOAD=NOT_TESTED`, `REAL_KIRA_QKR=NOT_TESTED`, `EXLAB_RETRY=NO`.
