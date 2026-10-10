<!-- B14_OFFICIAL_PARAMETER_AUDIT_20261010 -->
> **2026-10-10 최신 해석:** [B14 공식 파라미터·재시험 판단 감사](B14_OFFICIAL_PARAMETER_REVALIDATION_2026-10-10.md)를 먼저 확인하세요. 아래 과거 실측·우열·추천은 **기록 당시 파라미터에서의 결과**로만 유지합니다. 기존 평가에서 사용한 temperature=0 및 공통 max_tokens는 공식 권장 설정으로 간주하지 않습니다. 공식 공급사 기본값/추론/출력 예산을 검증하는 별도 재시험과 B14 전달 검증 전에는 최종 성능 우열로 사용하지 않습니다. 모델 자동 선택, 대체 라우팅 또는 운영 배포를 승인하는 문서가 아닙니다.
<!-- /B14_OFFICIAL_PARAMETER_AUDIT_20261010 -->

# Dots Studio Dots3-Note Preview (free) — actual QKR quote extraction benchmark

**Status: BOUNDED_DIRECT_GATEWAY_MEASUREMENT / NOT_B14_REGISTERED / NOT_CUSTOMER_READY.**

## Route and scope

- Public Kilo catalog GET HTTP200 contained **`dots-studio/dots-3-note-preview:free`** with reported input/output price **0** and context window **512,000**. Exact model ID was explicitly requested.
- Direct anonymous Kilo Gateway `/api/gateway/chat/completions`, not PADIEM B14 Worker. No API key, customer input, paid model request or automatic fallback.
- Fixed B66 synthetic QKR-001..010 corpus and `.github/scripts/b66_quote_model_benchmark.py::PROMPT_HEADER` with actual newline separator, strict `grade_case` and B66 QuoteExtraction normalization; `temperature=0`, `max_tokens=3500`, one attempt/case, no retries/fallback.
- Both request and returned model IDs were checked against the expected exact free route or its explicit underlying base name; per-case response identity and strict accuracy are preserved below. All content was processed in memory; no raw user prompts or model responses committed.

## Actual one-shot results

| Metric | Direct free route |
|---|---:|
| Synthetic QKR cases | 10 |
| HTTP200 | **10/10** |
| Strict quote PASS | **9/10** |
| HTTP429 | **0** |
| HTTP504 | **0** |
| HTTP200 median | **21.66s** |
| Min / max HTTP200 | **11.88s / 46.78s** |

| Case | HTTP | Strict | Elapsed |
|---|---:|---|---:|
| QKR-001 | 200 | PASS | 21.27s |
| QKR-002 | 200 | PASS | 22.81s |
| QKR-003 | 200 | PASS | 13.94s |
| QKR-004 | 200 | PASS | 11.88s |
| QKR-005 | 200 | PASS | 18.97s |
| QKR-006 | 200 | PASS | 15.31s |
| QKR-007 | 200 | OUTPUT_LIMIT_EMPTY | 46.78s |
| QKR-008 | 200 | PASS | 29.45s |
| QKR-009 | 200 | PASS | 27.89s |
| QKR-010 | 200 | PASS | 22.05s |

**QKR-007 failure analysis:** the Gateway returned HTTP200 and the expected model identity but `finish_reason=length`, total-token usage 3,862, and an **empty visible answer** at the experiment's `max_tokens=3500`. This is **not** a correct quotation, and it is **not** HTTP429/504 availability failure. It indicates output-budget exhaustion under this request, not a proven provider outage. No re-request of QKR-007 was made. The run was continued with only QKR-008..010, each exactly once, preserving 10 unique-case one-shot grading.

**Latency caveat:** the 21.66s median includes the incomplete QKR-007 HTTP200; the medians are transport-level timings, not a guarantee of completed useful output. Dots3's 9 completed correct replies were substantially slower than the earlier Step 5 free 10/10 round. Sample size is 10; pricing, throughput and reliability can change by provider demand.

## Separate historical/comparator evidence — interpret with route differences

- [StepFun Step 5 Preview Free](B14_STEPFUN_STEP5_PREVIEW_FREE_2026-10-09.md) on the SAME synthetic QKR corpus (direct Kilo free route) returned **10/10 PASS, HTTP200 10/10, median 4.05s** in its separate sampling round. These are not contemporaneous calls, and free gateway quotas can vary.
- [Mercury 2.5, Gemini 3.5 Flash Lite and SenseNova](B14_SAME_CASE_MODEL_COMPARISON_2026-10-09.md) were measured through **Production B14 Worker**, not direct Kilo. Prior Mercury strict 9/10 with HTTP200 10/10, median 3.87s; route and output variance prevent a direct production winner declaration.
- Earlier Draft [#3830](https://github.com/skerishKang/ai-revenue-lab/pull/3830) contained a much smaller nonidentical Dots3 coding/VAT smoke, **not** the full strict 10-case QKR extraction test. B66 QuoteCore, not any model, owns arithmetic and PDF rendering.
- StepFun **3.7 Flash is owner-retired** (merged PR #3949) and **not** a candidate or fallback.

## CTO bounded recommendation

- This is **evaluation evidence**, not permission to add the model to the B14 canonical list, auto-select it, make it default, or replace manually chosen models.
- **Current CTO priority: keep Step 5 Preview Free ahead of Dots3 for quotation extraction** because both had high case-level accuracy, but Step 5's previous median was about five times faster and did not exhaust output on this test set. Dots3 remains a **secondary/manual research candidate**, not a proposed default.
- Any later Dots3 onboarding would require separately approved **B14 manual-only model registration**, current-main policy tests, gated production deployment, exact-model Worker parity, and output-budget tests. Do not merge unrelated old branches.
- Paid fallback, automatic substitutions, long-term rate-limit guarantees, customer Saved Quote Skill/PDF and per-model reasoning controls are **not** verified.

**Safe evidence:** `docs/models/final-evaluation/evidence/B14_DOTS3_NOTE_FREE_2026-10-10_METADATA.json` contains metadata only (10 synthetic cases), no credentials, full prompts or model replies. The source script and original metadata remain local on Padiem-Command-Center.
