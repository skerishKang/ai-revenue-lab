# StepFun Step 5 Preview Free — 2026-10-09 preliminary P1 evaluation

**Owner priority:** Step 5 Preview Free is the first model to **test**, not a verified highest-quality model. Authority: [B14 owner ledger](../operations/B14_OWNER_MODEL_DECISION_LEDGER_2026-10-08.md) and GitHub issue #3554. This is an isolated Kilo Code free-route evaluation, NOT customer B14 routing.

## Exact models and method

- Step 5: kilo/stepfun/step-5-preview-free
- Comparator: kilo/dots-studio/dots-3-note-preview:free. Previous Kilo global default was listed as kilo/z-ai/glm-5:free but that exact ID was not present in the current Kilo model discovery list, so it was NOT invoked.
- Mode: kilo run --pure --agent plan --model [exact ID] --format json. Isolated empty directories, no auto-approval, no repo mutation.
- Two objective tasks: (A) Python interval normalization and merging, 8 deterministic cases including input immutability, (B) Korean quotation math, exact four-key integer JSON. Both models initially got the same task prompts. After Step 5 concurrency rejects it was retried sequentially; the retry quote prompt was semantically equivalent but not byte-identical.
- Correct quote: item subtotal 98,500 KRW, discount 9,850, VAT 8,865, total 102,515 including nontaxable 5,000 delivery.

## Observed evidence — one valid model answer per task

| Measurement | Step 5 Preview Free | Dots 3 Note Preview Free |
| --- | --- | --- |
| Initial concurrent attempts | Two API errors: request limited concurrency reached, current: 141, limit: 140 | Both requests answered |
| Bounded sequential retry | Two requests answered, recorded $0 cost | Not needed |
| Python unit tests | 8/8 PASS | 8/8 PASS |
| Plain-Python output formatting | PASS | FAIL: Markdown fenced code |
| Korean quote numeric result | FAIL | PASS |
| Returned VAT | 9,865 (wrong) | 8,865 (right) |
| Returned total | 113,515 (wrong) | 102,515 (right) |
| Cost reported | $0 for completed retries | $0 for completed requests |

The initial Step 5 failures were provider concurrency errors **before model responses**, not reasoning answers. The sequential Step 5 quote contained real arithmetic errors. These are two tiny tasks, one valid completion per model per task. Neither an overall quality winner nor long-term free availability is proven. Cold-start and concurrency differences also make latency comparisons invalid.

## Current decision and next evaluation

- OWNER_STEP5_EVALUATION_PRIORITY=1 RETAINED; BEST_MODEL_VERIFIED=NO
- QUALITY_WINNER=UNDETERMINED, since Step 5 complied with plain code-only formatting while Dots 3 solved the quote calculation correctly.
- FREE_ROUTE_AVAILABILITY_RISK=OBSERVED. Require repeatability and rate-limit tests; never silently switch model or top up/pay without separate owner permission.
- Next: agent-level repository bug-fix with executable tests, Korean long-instruction document task, and repeated calls with bounded costs and precise route IDs.
- No B14 JSON registry change, no Step 5 customer onboarding, no Kilo default change, no Plus/Pro/Max assignment, no Auto Router activation, no Production deployment.
