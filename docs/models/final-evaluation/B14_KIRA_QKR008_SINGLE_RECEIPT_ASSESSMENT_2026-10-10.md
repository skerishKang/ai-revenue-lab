# B14 Kira QKR-008 single real-response *receipt* assessment — source ready, no new paid call

**Date:** 2026-10-10 KST. **Owner issues:** [#2676](https://github.com/skerishKang/ai-revenue-lab/issues/2676) evaluation and [#3554](https://github.com/skerishKang/ai-revenue-lab/issues/3554) B14 execution.

## Result and scope

A **new one-response OFFLINE assessor** can process a separately captured B14 response for Kira's *exact manually selected* `kira/qwen3.8-flash-free` and evaluate fixed Korean quotation **QKR-008 (12 items)**. It reuses the existing `.github/scripts/b66_quote_model_benchmark.py::grade_case`, actual B66 `quote-extraction.js` and **`quote-core.js`** (via local Node), not a new AI-based grading oracle.

**No real Kira QKR-008 response was captured in this change.** The one previously approved Kira Production B14 request gave the literal greeting `OK` in 7.781s/2,037 reported tokens; it was **not** a quotation. Test fixtures below are synthetic. The source tool uses **zero HTTP calls** even with `--response-file` and has **no live/execute flags**, API credentials, or retries; **all further provider API POSTs require separate Owner approval** despite a limited-time public free promotion.

## Source and invocation

- Tool: `.github/scripts/b14_kira_qkr_single_receipt.py`
- Tests: `docs/models/final-evaluation/tests/test_b14_kira_qkr_single_receipt.py`
- Previously merged [#4134](https://github.com/skerishKang/ai-revenue-lab/pull/4134) covers **synthetic** QKR-008 B66→QuoteCore→mock Sol PDF snapshot only. This new tool assesses a *separately imported single B14 completion*. Neither proves an actual Sol-native renderer or final customer PDF.

Default dry plan:

```powershell
python .github/scripts/b14_kira_qkr_single_receipt.py
```

After **a separately approved** bounded real QKR call has been independently executed and its private raw response retained outside the repository, the offline assessor accepts **one existing local receipt**:

```powershell
python .github/scripts/b14_kira_qkr_single_receipt.py --response-file E:\private-b14-qkr008-receipt.json
```

Expected private receipt input schema (example is *shape only*, not an actual model answer):

```json
{
  "case_id": "QKR-008",
  "model_id": "kira/qwen3.8-flash-free",
  "http_status": 200,
  "response": {
    "business14": {
      "selected_model": "kira/qwen3.8-flash-free",
      "selected_upstream_model": "qwen3.8-flash-free",
      "actual_response_model": "qwen3.8-flash-free",
      "route_mode": "manual",
      "attempt_count": 1,
      "fallback_used": false
    },
    "choices": [
      {
        "message": { "role": "assistant", "content": "{...actual JSON quotation object...}" },
        "finish_reason": "stop"
      }
    ]
  }
}
```

The result contains **only booleans, mismatched field counts, amounts and safe status**. It never emits raw model answers, customer names, provider headers or credential values; any actual imported receipt and any private evidence stay outside Git. `http_status` and route fields are **read from the external receipt**, not independently attested by this offline grader. The resulting `provenance=IMPORTED_RESPONSE_NOT_ATTESTED_LIVE` is mandatory even for PASS; independent external capture proof must be checked by the evaluation owner. A single-case PASS is **not eligible for a complete model-quality rank**.

## Exact scoring gates

1. Current canonical registry has the exact Kira ID, `provider_id=kira`, upstream `qwen3.8-flash-free`; no aliases or fallback.
2. Receipt's case, model, HTTP200 and its B14 `business14.selected_model`, `selected_upstream_model`, `actual_response_model`, manual route, **attempt_count=1** and `fallback_used=false` must match.
3. Exactly one completed choice with `finish_reason=stop`, nonblank strict JSON object content; `length`, whitespace, code fences, invalid JSON are **not gradeable**, not quietly turned into a quality score.
4. The existing QKR-008 strict answer key checks company/project/date and all **12 item names, quantities, unit prices** by existing B66 extraction contract; raw matches are not printed.
5. QuoteCore independently checks **supply 6,500,000 KRW / VAT 650,000 KRW / grand 7,150,000 KRW** and 12 items, with `EXCLUSIVE` tax mode. A wrong tax mode fails even if all item facts match.
6. One-case results are **not** a 10/10 model benchmark, customer-authenticated B66 ingestion, live Provider-proof on their own, actual Sol-native PDF or Drive proof.

Focused tests:

```powershell
python docs/models/final-evaluation/tests/test_b14_kira_qkr_single_receipt.py -v
```

**7 tests PASS**. They include synthetic correct/incorrect quotations, Korean item/VAT calculation, exact model/attempt/fallback controls, blank/truncated/non-JSON failures, no raw private output, file-size bound and default no-POST CLI. No full local B14 suite, no CI dispatch, no additional provider calls, no Production or Secrets mutations.

## Remaining decision

Actual Kira quotation response **NOT_TESTED** in this step. The next *possibly charged* model request would be a **single exact manual Kira QKR-008** with bounded output budget, no temperature/reasoning defaults, max_attempts=1, max_retries=0, fallback=false, and an account-specific price/quota preflight. That must be **separately approved**. The B66 #4117 team remains owner of real Sol 6.1-native signed PDF bytes, preview/download/Drive SHA equivalence and deployment.
