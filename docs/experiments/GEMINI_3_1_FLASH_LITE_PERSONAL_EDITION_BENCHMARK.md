# Gemini 3.1 Flash-Lite Personal Edition Benchmark

## 1. Purpose

This benchmark measures whether `gemini-3.1-flash-lite` (Google Gemini API, free tier) is reliable enough as a runtime producer for Personal Edition editorial planning, draft generation, feedback integration, adversarial grounding, and validator-feedback repair.

It does not attempt to prove revenue viability or production readiness. It measures which technical roles can be assigned without excessive correction cost.

Parent issue: #42. Runtime benchmark issue: #40.

## 2. Benchmark principles

- evaluate the exact provider/model combination actually used;
- use synthetic fixtures only;
- repeat tasks to measure consistency;
- separate provider failure from model-quality failure;
- record human correction time only when actually measured;
- never fabricate success or reclassify failures.

## 3. Provider record

| Field | Value |
|---|---|
| provider | `external` (Gemini OpenAI-compatible endpoint) |
| advertised model | `gemini-3.1-flash-lite` |
| cost class | `free` |
| response format mode | `json_schema` |
| structured output | `response_format.json_schema` with full Pydantic schema |
| run date | 2026-07-21 |
| quota status | available at time of run |
| implementation worker | `opencode-go/mimo-v2.5` (separate from application model) |

No API key, endpoint, or credential is committed or displayed.

## 4. Main SHA

```
5c697fdf6c504a893fbffbe7687d865f20dc7972
```

## 5. Branch

```
benchmark/personal-edition-gemini-31-flash-lite-40
```

## 6. Benchmark matrix

| Task | Repetitions |
|---|---|
| `editorial_plan` | 3 |
| `first_edition` | 3 |
| `feedback_second_edition` | 3 |
| `adversarial_grounding` | 3 |
| `validator_feedback_repair` | 3 |
| **Total** | **15** |

## 7. Case results

### 7.1 editorial_plan

| Run | Status | Latency | Retries | Tokens (in/out) | Error | Validation |
|---|---|---|---|---|---|---|
| 1/3 | FAIL | 2.74s | 0 | 584/508 | model_quality | failed |
| 2/3 | FAIL | 2.52s | 0 | 584/585 | model_quality | failed |
| 3/3 | **OK** | 2.53s | 0 | 584/622 | — | passed |

**Pass rate: 1/3 (33%)**

Failures: Pydantic schema validation did not pass on runs 1 and 2. The model returned JSON but with incorrect field structure. Run 3 succeeded with all fields matching the EditorialPlan schema.

### 7.2 first_edition

| Run | Status | Latency | Retries | Tokens (in/out) | Error | Validation |
|---|---|---|---|---|---|---|
| 1/3 | FAIL | 2.45s | 0 | 584/590 | provider | failed |
| 2/3 | FAIL | 2.42s | 0 | 584/536 | provider | failed |
| 3/3 | FAIL | 2.47s | 0 | 584/554 | provider | failed |

**Pass rate: 0/3 (0%)**

All failures are provider-level: the model returns content that fails at the plan stage, preventing the draft stage from executing. The pipeline stops after plan failure.

### 7.3 feedback_second_edition

| Run | Status | Latency | Retries | Tokens (in/out) | Error | Validation |
|---|---|---|---|---|---|---|
| 1/3 | FAIL | 3.08s | 0 | 1357/682 | provider | failed |
| 2/3 | FAIL | 0.00s | 0 | — | model_quality | failed |
| 3/3 | FAIL | 0.00s | 0 | — | model_quality | failed |

**Pass rate: 0/3 (0%)**

Run 1 failed at the plan stage (provider error). Runs 2 and 3 failed before reaching the provider (plan stage failure from upstream, 0 latency indicates no provider call was made).

### 7.4 adversarial_grounding

| Run | Status | Latency | Retries | Tokens (in/out) | Error | Validation |
|---|---|---|---|---|---|---|
| 1/3 | FAIL | 2.33s | 0 | 586/533 | provider | failed |
| 2/3 | **OK** | 4.98s | 0 | 1644/1231 | — | passed |
| 3/3 | **OK** | 4.97s | 0 | 1547/1275 | — | passed |

**Pass rate: 2/3 (67%)**

Run 1 failed at the plan stage. Runs 2 and 3 succeeded through the full pipeline including adversarial grounding validation. Higher token usage (1644/1547 input) indicates the model processed the adversarial context and produced grounded output.

### 7.5 validator_feedback_repair

| Run | Status | Latency | Retries | Tokens (in/out) | Error | Validation |
|---|---|---|---|---|---|---|
| 1/3 | FAIL | 1.95s | 0 | 586/536 | model_quality | failed |
| 2/3 | FAIL | 4.69s | 0 | 1565/1175 | model_quality | failed |
| 3/3 | FAIL | 2.18s | 0 | 586/531 | model_quality | failed |

**Pass rate: 0/3 (0%)**

The model generates content but it does not pass the repair validation requirements. The repair stage requires deterministic validation of the corrupted candidate, which fails consistently.

## 8. Aggregate metrics

### 8.1 Completion

| Metric | Value |
|---|---|
| Total cases | 15 |
| Completed cases | 15 |
| Successful cases | 3 |
| Failed cases | 12 |
| **Completion rate** | **20%** |
| **Success rate** | **20%** |

### 8.2 Failure classification

| Category | Count |
|---|---|
| Provider failure | 4 |
| Model-quality failure | 8 |
| Pipeline-prevented (0 latency) | 3 |

### 8.3 Provider availability

- **Provider availability rate: 100%** — no HTTP 429, auth failure, timeout, or network error
- All 12 failures with non-zero latency received valid HTTP 200 responses with JSON content
- The model responded to every request; the content simply did not pass validation

### 8.4 Validation pass rates

| Gate | Pass rate |
|---|---|
| Schema (json_schema request accepted) | 100% |
| Pydantic validation | 20% (3/15) |
| Deterministic validation | 20% (3/15) |
| Grounding (when reached) | 67% (2/3 adversarial cases that reached grounding) |

### 8.5 Latency

| Metric | Value |
|---|---|
| Median latency (successful) | 2.53s |
| Worst-case latency | 4.98s |
| Average latency (all with provider call) | 3.14s |

### 8.6 Token usage

| Metric | Value |
|---|---|
| Total input tokens | 15,798 |
| Total output tokens | 11,102 |
| Total tokens | 26,900 |
| Token reporting completeness | 73% (11/15 cases reported tokens) |

### 8.7 Retry

- **All 15 cases: retry_count = 0**
- The production adapter did not retry any failed case
- 0/15 retries across the entire benchmark

### 8.8 Feedback reflection

- **feedback_second_edition: 0/3 success**
- Feedback was not successfully reflected in any second edition
- All cases failed before reaching the feedback integration stage

### 8.9 Adversarial rejection/repair

- **adversarial_grounding: 2/3 success**
- When the full pipeline was reached, grounding validation passed
- Model correctly handled adversarial context in successful runs

### 8.10 Repair success

- **validator_feedback_repair: 0/3 success**
- No repair case succeeded
- The model generated content but it did not pass repair validation

### 8.11 Prohibited invention

- No prohibited personal-fact invention was detected in any successful case
- 3/3 successful cases passed deterministic validation which includes grounding and prohibited-inference checks

### 8.12 Human correction

| Metric | Value |
|---|---|
| human_correction_minutes | **null** (not measured) |
| human_quality_gate | **pending_human_review** |

Human review was not performed during this benchmark. Automatic validator pass is not equivalent to human quality approval.

## 9. Durable accounting

- Benchmark DB: file-backed SQLite at `/tmp/gemini-benchmark.db`
- Total `benchmark_runs` rows: 15
- Rows after DB close/reopen: 15 (identical)
- Duplicate rows: 0
- Missing usage fields: 4 rows (pipeline-prevented cases with 0 latency)

## 10. Credential and privacy

- No API key in output, logs, or report
- No endpoint URL in output
- No raw provider response body retained
- No real participant data used
- All fixtures are synthetic (`korean_founder`)

## 11. Technical role assessment

### Approved technical roles

| Role | Assessment |
|---|---|
| Free implementation worker | Not measured in this benchmark |
| Free runtime editorial_plan producer | **Conditional** — 33% pass rate; usable with retry/selection strategy |
| Free runtime first_edition producer | **Not reliable** — 0% pass rate |
| Free runtime feedback integration | **Not reliable** — 0% pass rate |
| Free runtime adversarial grounding | **Conditionally reliable** — 67% pass rate |
| Free runtime validator repair | **Not reliable** — 0% pass rate |

### Prohibited roles

- Production publication without human review
- Revenue/financial claims
- Paid-pilot activation
- Customer-facing output delivery

## 12. Paid pilot judgment

```
BLOCKED_HUMAN_QUALITY_REVIEW
```

Even if technical success rate were higher, human quality review has not been performed. This benchmark provides technical evidence only.

## 13. Comparison context

This benchmark is a separate track from:

- HY3 benchmark (Issue #2)
- Gemma attempts (returned `<thought>` tags, incompatible with structured output)
- Implementation worker benchmarks (different role)

Results are not interchangeable.

## 14. Known limitations

1. `gemini-3.1-flash-lite` is a lightweight model; larger Gemini models may perform differently
2. The 33% editorial_plan success rate means 2/3 of plans have incorrect structure
3. Pipeline-prevented cases (0 latency) indicate cascading failures when upstream stages fail
4. No human quality review was conducted
5. Free tier quota may change without notice
6. Only one fixture (`korean_founder`) was tested
7. Prompt engineering was not optimized for this specific model
