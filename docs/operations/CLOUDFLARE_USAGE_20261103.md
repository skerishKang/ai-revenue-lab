# Cloudflare 계정 자원과 최근 7일 사용량 — 2026-11-03

## 범위와 계산 방법

- 읽기 전용 조사. Wrangler `whoami`로 계정 목록을 확인했고, 계정 식별자는 끝 4자리만 기록했다.
- 사용량 창은 완료된 UTC 날짜 7일인 2026-10-27 00:00부터 2026-11-02 23:59까지다. 날짜별 사용량은 UTC 기준이다.
- Workers는 GraphQL `workersInvocationsAdaptive`를 날짜별·Worker별로 조회하고, 같은 7일 창의 Worker별 통합 질의와 교차 확인했다. Worker별 요청·오류 합계가 두 조회에서 일치했다. CPU p50/p99는 7일 Worker별 quantile이며, GraphQL CPU 단위(µs)를 ms로 환산했다.
- 복합 쿼리는 Cloudflare 적응형 샘플링이 쿼리 복잡도에 따라 다른 값을 반환해 Workers 수치 계산에서 제외했다. Cloudflare는 짧은 창과 단순 집계를 권한다. D1/R2도 별도 질의로 재조회해 첫 합계와 일치함을 확인했다. Analytics 값은 적응형 집계의 추정치로 볼 수 있다.
- Pages 정적 파일 요청은 제외하고 Functions 실행 요청만 Workers 요청 합계에 포함했다. Pages Functions는 Workers 요청 한도를 공유한다.
- 실제 플랜은 Cloudflare `GET /accounts/{account_id}/subscriptions`로 읽으려 했으나 두 계정 모두 HTTP 403, code 10000이었다. Cloudflare API 문서상 이 조회에는 Billing Read 또는 Billing Write 권한이 필요하므로 Free/Paid를 추정하지 않았다.
- 아래 사용률은 계정 플랜을 Free로 가정한 비교값이다. 실제 플랜은 확인되지 않았다. Workers Free 기준은 100,000 요청/일과 요청당 CPU 10ms, D1 Free 기준은 5,000,000 rows read/일·100,000 rows written/일·5GB 총 저장량이다. 2026-09-01부터 Free 한도 초과 시 일일 한도 초기화(UTC 자정)까지 쿼리가 실패한다.
- R2 저장은 관측한 일별 최대 스냅샷을 10GB-month 포함량과 비교한 참고 비율이며, 실제 GB-month는 청구 기간의 일별 최대 저장량 평균으로 계산된다. R2 Class A/B는 7일 합계를 월 포함량(각 1M/10M 요청)과 비교했다.

## 계정 및 자원 소속

| 계정 이름 | ID 끝 4자리 | Workers | D1 | R2 | Pages |
|---|---:|---:|---:|---:|---:|
| Charliekant Gmail account | 6932 | 53 | 10 | 6 | 10 |
| Padiem | a41d | 6 | 0 | 2 | 6 |

| 대상 | 확인된 자원 위치 |
|---|---|
| Padiem Chat·front·Auth·Control Plane Identity | 계정 …6932. 확인된 Worker 예: `padiem-chat`, `padiem-chat-front`, `padiem-auth`, `padiem-control-plane-identity`. |
| CGI 견적 API·D1 | `cgi-quote-api` Worker와 `cgi_quotes` D1 모두 계정 …6932. |
| CGI Pages | 이름이 정확히 `cgishop`인 Pages 프로젝트는 두 계정 목록에서 찾지 못했다. `cgi` 프로젝트는 계정 …a41d에 있다. 둘이 같은 서비스인지는 확인되지 않았다. |
| 튜토리얼 R2 | `padiem-tutorial-media` 버킷은 계정 …6932에 등록돼 있다. 해당 버킷은 7일 저장량 GraphQL 행이 반환되지 않았다. |
| Workers 요금제 | 두 계정 모두 확인 불가(Subscriptions API 403). Billing Read 권한이 있는 기존 조회 자격으로 재확인해야 한다. |

## 계정별 일일 사용량

| UTC 날짜 | 계정 | Workers 요청 | Pages Functions | 합계 / 100k | Invocation errors (Worker+Functions) | D1 read rows | D1 written rows | D1 저장 GB |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 10-27 | …6932 | 12,638 | 429 | 13,067 | 61 | 197,494 | 5,984 | 0.006148 |
| 10-28 | …6932 | 22,146 | 132 | 22,278 | 763 | 214,224 | 10,542 | 0.007557 |
| 10-29 | …6932 | 26,565 | 874 | 27,439 | 2,029 | 251,120 | 10,930 | 0.007868 |
| 10-30 | …6932 | 9,815 | 369 | 10,184 | 669 | 120,729 | 4,203 | 0.009273 |
| 10-31 | …6932 | 4,159 | 1,196 | 5,355 | 158 | 57,893 | 169 | 0.009282 |
| 11-01 | …6932 | 6,406 | 2,596 | 9,002 | 3 | 66,032 | 110 | 0.009282 |
| 11-02 | …6932 | 5,541 | 3,523 | 9,064 | 3 | 15,592 | 0 | 0.009282 |
| 10-27 | …a41d | 118 | 282 | 400 | 0 | 0 | 0 | 0 |
| 10-28 | …a41d | 102 | 194 | 296 | 0 | 0 | 0 | 0 |
| 10-29 | …a41d | 107 | 79 | 186 | 0 | 0 | 0 | 0 |
| 10-30 | …a41d | 114 | 1,069 | 1,183 | 0 | 0 | 0 | 0 |
| 10-31 | …a41d | 107 | 2,820 | 2,927 | 0 | 0 | 0 | 0 |
| 11-01 | …a41d | 107 | 1,047 | 1,154 | 0 | 0 | 0 | 0 |
| 11-02 | …a41d | 110 | 256 | 366 | 0 | 0 | 0 | 0 |

| 자원(Free 비교 기준) | …6932 관측 최대 | 사용률 | …a41d 관측 최대 | 사용률 |
|---|---:|---:|---:|---:|
| Workers + Pages Functions 요청/일 (100,000) | 27,439 / 10-29 | 27.44% | 2,927 / 10-31 | 2.93% |
| D1 rows read/일 (5,000,000) | 251,120 / 10-29 | 5.02% | 0 | 0% |
| D1 rows written/일 (100,000) | 10,930 / 10-29 | 10.93% | 0 | 0% |
| D1 저장 (5GB 총량) | 9,281,536 bytes / 11-02 | 0.186% | 0 | 0% |
| R2 저장 포함량 (10GB-month) | 2.087147GB 관측 최대 / 11-02 | 20.87%* | 0.000002255GB 관측 최대 | 0.000023%* |
| R2 Class A 요청 (1M/month) | 219건 / 7일 | 0.022%** | 0건 | 0% |
| R2 Class B 요청 (10M/month) | 1,976건 / 7일 | 0.020%** | 0건 | 0% |

* 저장 비율은 7일 중 관측한 최대 저장 스냅샷 대 10GB-month 포함량이다. 청구 기간 사용량과 같지 않다.
** 7일 관측 요청 합계를 월 포함량에 비교한 참고 비율이다.
일일 요청 최댓값은 …6932 계정에서 27.44%, …a41d에서 2.93%다. 50%를 넘은 요청·D1·R2 항목은 없다. 따라서 특정 Worker나 SQL 패턴을 초과 원인으로 분류할 항목은 없다.

## Workers별 일일 요청·오류·CPU

CPU p50/p99는 해당 Worker의 7일 분포다. 요청·오류는 날짜별 `scriptName` 기준이며, 날짜별 요청 수를 더한 값과 7일 통합 조회가 일치했다.

### 계정 …6932

REST 인벤토리 53개 중 29개 이름은 invocation 행과 연결되고 24개는 조회 행이 없었다. 별도 `__unknown__` 1행은 Worker 이름이 없어 53개 인벤토리에 연결되지 않는다.

| Worker | 10-27 | 10-28 | 10-29 | 10-30 | 10-31 | 11-01 | 11-02 | 7일 요청 | 오류 | CPU p50 ms | CPU p99 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| padiem-chat | 5,733 | 10,147 | 14,880 | 5,078 | 678 | 483 | 87 | 37,086 | 3,662 | 35.417 | 583.710 |
| padiem-local-agent-broker-state | 3,880 | 5,434 | 8,866 | 1,255 | 52 | 0 | 0 | 19,487 | 2 | 6.144 | 25.958 |
| padiem-control-plane-identity | 1,829 | 4,717 | 1,682 | 2,009 | 354 | 1,383 | 169 | 12,143 | 1 | 5.095 | 301.327 |
| padiem-chat-front | 0 | 0 | 0 | 0 | 749 | 2,917 | 2,695 | 6,361 | 0 | 1.240 | 4.376 |
| ai-revenue-korean-ai-platform | 352 | 585 | 672 | 534 | 303 | 709 | 158 | 3,313 | 0 | 63.765 | 317.799 |
| padiem-auth | 0 | 0 | 201 | 438 | 404 | 166 | 732 | 1,941 | 0 | 0.713 | 10.134 |
| padiem-cutover-trial-a | 0 | 0 | 0 | 0 | 407 | 188 | 675 | 1,270 | 0 | 0.227 | 0.747 |
| cgi-quote-api | 125 | 552 | 13 | 210 | 92 | 131 | 2 | 1,125 | 0 | 1.236 | 26.895 |
| padiem-com2-backup | 11 | 7 | 10 | 61 | 226 | 7 | 665 | 987 | 20 | 2.453 | 2,020.000 |
| b64-ai-reward-router | 407 | 417 | 61 | 17 | 1 | 43 | 2 | 948 | 0 | 2.551 | 16.225 |
| padiem-google-oauth-edge | 2 | 3 | 18 | 1 | 293 | 280 | 304 | 901 | 0 | 4.338 | 27.520 |
| padiem-chat-staging | 0 | 0 | 0 | 26 | 397 | 0 | 0 | 423 | 0 | 16.085 | 336.274 |
| padiem-control-plane-engine-admission | 41 | 140 | 72 | 94 | 25 | 11 | 26 | 409 | 0 | 11.928 | 713.634 |
| padiem-ai-engine | 55 | 95 | 33 | 33 | 20 | 10 | 0 | 246 | 1 | 212.711 | 638.574 |
| cgi-nicepay-sandbox | 164 | 5 | 1 | 0 | 0 | 0 | 0 | 170 | 0 | 2.506 | 9.348 |
| padiem-local-agent-broker-edge | 9 | 5 | 14 | 40 | 31 | 9 | 5 | 113 | 0 | 13.153 | 31.655 |
| __unknown__ | 8 | 10 | 10 | 10 | 26 | 8 | 8 | 80 | 0 | 1.940 | 6.601 |
| padiem-cutover-trial-b | 0 | 0 | 0 | 0 | 74 | 0 | 0 | 74 | 0 | 0.272 | 0.499 |
| padiem-b66-cgi-qa | 0 | 0 | 0 | 0 | 0 | 42 | 0 | 42 | 0 | 5.538 | 147.452 |
| padiem-google-oauth-state | 6 | 9 | 18 | 0 | 0 | 0 | 0 | 33 | 0 | 5.405 | 35.596 |
| padiem-ai-engine-ingress | 0 | 0 | 0 | 0 | 13 | 10 | 1 | 24 | 0 | 1.527 | 3.522 |
| lovetree-limone | 5 | 1 | 2 | 2 | 3 | 2 | 2 | 17 | 0 | 5.029 | 17.451 |
| lovetree-limone-pr35-cinematic-preview | 2 | 1 | 2 | 1 | 2 | 1 | 2 | 11 | 0 | 6.411 | 10.306 |
| lovetree-limone-staging | 2 | 1 | 2 | 1 | 2 | 1 | 2 | 11 | 0 | 5.023 | 12.731 |
| lovetree-limone-issue-26-final-review-preview | 2 | 1 | 2 | 1 | 2 | 1 | 2 | 11 | 0 | 6.368 | 15.923 |
| lovetree-limone-cache-pr12-preview | 2 | 0 | 2 | 1 | 2 | 1 | 2 | 10 | 0 | 5.340 | 12.622 |
| lovetree-limone-pr-38-preview | 2 | 1 | 2 | 1 | 2 | 1 | 1 | 10 | 0 | 5.379 | 13.667 |
| lovetree-limone-v3-integrated-preview | 1 | 2 | 1 | 2 | 1 | 2 | 1 | 10 | 0 | 4.963 | 10.071 |
| lovetree-authority-caller | 0 | 9 | 0 | 0 | 0 | 0 | 0 | 9 | 0 | 1.117 | 3.066 |
| lovetree-auth-caller | 0 | 4 | 1 | 0 | 0 | 0 | 0 | 5 | 0 | 0.751 | 1.896 |

### 계정 …a41d

| Worker | 10-27 | 10-28 | 10-29 | 10-30 | 10-31 | 11-01 | 11-02 | 7일 요청 | 오류 | CPU p50 ms | CPU p99 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| padiem-danjion-api-production | 113 | 98 | 102 | 110 | 101 | 102 | 107 | 733 | 0 | 0.287 | 37.677 |
| padiem-danjion-api-qa | 5 | 4 | 5 | 4 | 6 | 5 | 3 | 32 | 0 | 23.374 | 63.978 |

### 조회 기간에 invocation 행이 없던 Worker

아래 Worker는 Cloudflare REST 인벤토리에는 있으나 7일 GraphQL invocation 행이 없었다. 요청 0, 오류 0, CPU quantile 없음으로 표기한다.

- 계정 …6932 (24개): `living-fiction-cloudflare-container-m0`, `lovebud-reliability-preview`, `lovetree-limone-five-source-preview`, `lovetree-limone-pr37-memory-sources-preview`, `lovetree-limone-pr39-preview`, `lovetree-limone-pr40-preview`, `lovetree-limone-release-rehearsal-new`, `lovetree-limone-release-rehearsal-old`, `lovetree-limone-ui-preview`, `lovetree-limone-v2`, `lovetree-limone-v4-preview-entry-preview`, `padiem-ai-engine-preview`, `padiem-ai-engine-preview-caller-preview`, `padiem-b66-cgi-qa-identity`, `padiem-b66-pdf-renderer`, `padiem-chat-connector-acceptance-4139`, `padiem-com2-identity-bridge`, `padiem-control-plane-identity-acceptance-4139`, `padiem-document-parser`, `padiem-local-agent-broker-state-acceptance-4139`, `padiem-voice-stt`, `test-secret-store-js`, `test-secret-store-js2`, `test-secret-store-js3`.
- 계정 …a41d (4개): `padiem-contact-verification`, `padiem-danjion-api-owner-preview-762`, `padiem-danjion-api-preview`, `padiem-danjion-api-preview-auth-write`.

## D1 데이터베이스별 사용량

`rowsRead`·`rowsWritten`는 7일 합계이며 각 데이터베이스의 관측 일일 최댓값·날짜를 함께 적었다. 저장량은 7일 중 일별 최대 DB 크기다.

| 계정 | 데이터베이스 | 7일 read rows | 7일 written rows | 일일 read 최댓값 / 날짜 | 일일 write 최댓값 / 날짜 | 저장량 GB |
|---|---|---:|---:|---|---|---:|
| …6932 | padiem-chat-db | 885,272 | 26,468 | 250,113 / 10-29 | 10,296 / 10-29 | 0.005337 |
| …6932 | padiem-chat-staging-db | 24,914 | 1,567 | 24,748 / 10-30 | 1,524 / 10-30 | 0.001225 |
| …6932 | padiem-engine | 5,097 | 28 | 2,225 / 10-30 | 28 / 10-30 | 0.000291 |
| …6932 | padiem-b14-call-ledger | 3,939 | 3,267 | 1,550 / 10-31 | 1,268 / 10-28 | 0.000532 |
| …6932 | cgi_quotes | 3,134 | 359 | 1,377 / 11-01 | 207 / 10-30 | 0.000340 |
| …6932 | cgi_quotes_sandbox | 152 | 156 | 152 / 10-27 | 156 / 10-27 | 0.000209 |
| …6932 | padiem-b64 | 576 | 93 | 336 / 10-27 | 56 / 10-28 | 0.000074 |
| …6932 | padiem-connector-acceptance-4139 | 0 | 0 | 0 | 0 | 0.000733 |
| …6932 | padiem-browser-owner-p01 | 0 | 0 | 0 | 0 | 0.000037 |
| …6932 | padiem-b66-cgi-qa-261011 | 0 | 0 | 0 | 0 | 0.000512 |
| …a41d | D1 데이터베이스 없음 | 0 | 0 | 0 | 0 | 0 |

## R2 버킷별 저장량과 요청

저장량은 각 버킷에서 7일 중 관측된 최대 `payloadSize + metadataSize`다. Class A/B는 7일 전체 요청 합계다.

| 계정 | 버킷 | 최대 저장 GB | 객체 수 | Class A / 7일 | Class B / 7일 |
|---|---|---:|---:|---:|---:|
| …6932 | padiem-b14-private-config | 0 | 0 | 0 | 0 |
| …6932 | padiem-b66-cgi-qa-261011 | 0.000196 | 3 | 9 | 9 |
| …6932 | padiem-com2-offsite | 0.048233 | 40 | 108 | 70 |
| …6932 | padiem-media | 1.995814 | 108 | 9 | 1,577 |
| …6932 | padiem-tutorial-media | analytics 행 없음 | — | 0 | 0 |
| …6932 | padiem-workspace-files | 0.042904 | 191 | 79 | 320 |
| …6932 | (bucketName dimension 없음: ListBuckets) | — | — | 14 | 0 |
| …a41d | danjion-storage | 0.000002 | 7 | 0 | 0 |
| …a41d | danjion-storage-qa | 0.000000286 | 1 | 0 | 0 |

R2 계정 …6932의 7일 전체는 Class A 219건, Class B 1,976건, 무료 분류 작업 18건이다. …a41d에서는 7일 GraphQL 작업 행이 없었다.

## 판정

- 계정별 일일 Workers+Pages Functions 요청 최댓값은 …6932 27.44%, …a41d 2.93%로 Free 요청 참고 한도 50% 이하이다.
- D1은 …6932에서 일일 read 최댓값 5.02%, write 최댓값 10.93%, 저장량 0.186%다. …a41d에는 D1이 없다.
- R2는 …6932 저장 스냅샷이 10GB-month 포함량의 20.87% 수준이며, 7일 요청 합계는 Class A 0.022%, Class B 0.020%다. …a41d의 저장량은 2.255KB이며 요청 행이 없다.
- 50%를 초과한 자원은 없다. 따라서 특정 Worker·쿼리 패턴의 초과 원인 분석 대상은 없다. 이 집계는 URL/SQL 패턴별 분해를 제공하지 않는다.
- Free 요청당 CPU 10ms에 자주 닿는 후보는 7일 p50이 10ms 이상인 여섯 Worker다: `padiem-chat` (35.417ms), `ai-revenue-korean-ai-platform` (63.765ms), `padiem-chat-staging` (16.085ms), `padiem-control-plane-engine-admission` (11.928ms), `padiem-ai-engine` (212.711ms), `padiem-local-agent-broker-edge` (13.153ms). 실제 요금제는 확인 불가하므로 초과 판정이 아니라 Free 한도와의 비교다.
- `padiem-com2-backup`은 p50 2.453ms이나 p99 2,020ms로 꼬리 구간이 길다(7일 요청 987, 오류 20). `padiem-auth`도 p99 10.134ms, p50 0.713ms다. 이는 per-request CPU quantile이며 계정 일일 quota 사용률이 아니다.
- Worker invocation 오류는 …6932 3,686건(대부분 `padiem-chat` 3,662건), …a41d 0건이다. 이 집계만으로 오류 원인이나 HTTP 5xx를 단정하지 않는다.

## 공식 기준 및 데이터 문서

- [Workers limits](https://developers.cloudflare.com/workers/platform/limits/)
- [Pages Functions pricing](https://developers.cloudflare.com/pages/functions/pricing/)
- [D1 pricing](https://developers.cloudflare.com/d1/platform/pricing/)
- [D1 Free 한도 초과 동작(2026-09-01)](https://developers.cloudflare.com/changelog/post/2026-09-01-d1-free-tier-limit-enforcement/)
- [R2 pricing](https://developers.cloudflare.com/r2/pricing/)
- [Workers GraphQL 조회 예시](https://developers.cloudflare.com/analytics/graphql-api/tutorials/querying-workers-metrics/)
- [GraphQL 적응형 샘플링 결과 설명](https://developers.cloudflare.com/analytics/faq/graphql-api-inconsistent-results/)
- [Subscriptions API 권한](https://developers.cloudflare.com/api/resources/accounts/subresources/subscriptions/methods/get/) — Billing Read/Write 필요
- [Billing Read 권한 설명](https://developers.cloudflare.com/fundamentals/api/reference/permissions/)
- [Cloudflare GraphQL CPU 필드 참조](https://github.com/cloudflare/skills/blob/main/skills/cloudflare/references/graphql-api/api.md) — `cpuTimeUs` 합계 필드와 CPU quantile 필드
