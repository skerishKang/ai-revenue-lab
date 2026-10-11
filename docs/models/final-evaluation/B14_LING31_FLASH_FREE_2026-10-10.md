<!-- B14_OFFICIAL_PARAMETER_AUDIT_20261010 -->
> **2026-10-10 최신 해석:** [B14 공식 파라미터·재시험 판단 감사](B14_OFFICIAL_PARAMETER_REVALIDATION_2026-10-10.md)를 먼저 확인하세요. 아래 과거 실측·우열·추천은 **기록 당시 파라미터에서의 결과**로만 유지합니다. 기존 평가에서 사용한 temperature=0 및 공통 max_tokens는 공식 권장 설정으로 간주하지 않습니다. 공식 공급사 기본값/추론/출력 예산을 검증하는 별도 재시험과 B14 전달 검증 전에는 최종 성능 우열로 사용하지 않습니다. 모델 자동 선택, 대체 라우팅 또는 운영 배포를 승인하는 문서가 아닙니다.
<!-- /B14_OFFICIAL_PARAMETER_AUDIT_20261010 -->

# inclusionAI Ling 3.1 Flash — free Gateway admission preflight (2026-10-10)

**Status: RATE_LIMITED / QUALITY_NOT_ASSESSABLE / NOT_B14_REGISTERED / NOT_CUSTOMER_READY.**

## Exact current discovery and experiment

- Read-only Kilo public `GET https://api.kilo.ai/api/gateway/models`: HTTP **200**, exact free model ID `inclusionai/ling-3.1-flash` listed with prompt/completion price 0 and 262,144 advertised context tokens.
- Actual **anonymous direct Kilo Gateway**, not B14 Worker, `POST /api/gateway/chat/completions` with explicit `model=inclusionai/ling-3.1-flash`, fixed existing synthetic QKR001 Korean quote test, `temperature=0`, `max_tokens=3500`. No Authorization/API key, no customer data, no alternate provider and no paid route.
- **One real provider request** returned **HTTP429** in **938ms**. Gateway error was classified `rate_limited`; `Retry-After` was **not present**. Provider vs shared-IP vs Gateway admission source **cannot be proven** from this bounded response. No raw error body or API secret committed.
- Stop-on-first-429 contract **honored**: no automatic retry, no manual second POST, no use of fallback. QKR002..010 were **NOT RUN**, not failed quality checks.

## Valid outcome

| Outcome | Observation |
|---|---|
| Public free catalog and exact identity | PASS |
| Total attempted QKR cases | **1 of planned 10** |
| HTTP200 / model answer | **0 / 0** |
| HTTP429 | **1** |
| Response time | **938ms** (429 only, **not model latency**) |
| Quote accuracy | **UNASSESSABLE**, **not 0/10** |
| Automatically retried, re-routed or paid | **NO** |

## Model owner and historical routing boundary

- Ling 3.1 Flash appears in older routing history as an Agnes reserve or Space Bunny successor. That historical single-primary/bounded fallback policy was superseded by owner-controlled per-run manual model selection under #3554. This direct free-route trial does not reactivate a primary/fallback chain.
- StepFun Step 3.7 Flash remains **OWNER RETIRED** by merged #3949. Ling is not part of that 3.7 exclusion; it is merely **temporarily unavailable for direct free quote benchmarking** in this observed sample.
- Compared with StepFun Step 5 Free (previous direct Gateway QKR10 **10/10 PASS, 4.05s median**) and Dots3-Note Free (previous direct Gateway QKR10 **9/10 PASS, 21.66s median**), **Ling cannot yet be ranked on model accuracy or latency**. Those were separate prior samples and this experiment has no completed Ling response.
- **CTO queue:** mark Ling `HTTP429 / RETEST_WHEN_FREE_ADMISSION_VERIFIED`, do not add to current nine-model B14 registry, do not deploy, do not mark customer ready. Resume only after external rate-limit window/policy is demonstrably open, with one authorized exact-model canary and no silent retries/fallback. Meanwhile keep other owner-approved model candidates moving.

## Evidence

Sanitized `evidence/B14_LING31_FLASH_FREE_2026-10-10_METADATA.json` includes only one synthetic case status, route and aggregate safe fields; no prompt text, model answer, customer document, request headers, credentials or private user data. Source experiment script resides locally at `E:\b14-ling31-free-20261010-runner.py` on Padiem-Command-Center.

**No registered-model JSON, actual Worker, default/fallback policy, B66 product source or Production deployment changed.**
