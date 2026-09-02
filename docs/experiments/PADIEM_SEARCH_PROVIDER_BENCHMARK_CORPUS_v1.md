# Padiem Search Provider Benchmark Corpus v1

Issue: #1355
Frozen: 2026-09-03
Scope: synthetic/public web-search provider evaluation only

## Purpose

Freeze one reusable, provider-neutral query corpus for comparing search/retrieval providers before any Production provider/default/secret mutation.

This corpus contains exactly:

```text
Korean = 40
  latest news / current affairs = 10
  government / public policy = 10
  general Korean factual knowledge = 5
  Korean local / daily-life information = 5
  developer / API documentation = 5
  fact-check / conflicting sources = 5
English = 20
  current tech / news = 5
  official documentation = 5
  coding / troubleshooting = 5
  general research = 5
TOTAL = 60
```

No query contains real user data, account identifiers, secrets, private documents, or personal correspondence.

## Execution rules

1. Run the same query text against every eligible provider unless the provider lacks the required search capability.
2. Use provider search/retrieval APIs only; do not let an answer-generation layer hide weak retrieval.
3. Capture the first provider response without retries for the primary quality/latency comparison. Record 429/5xx separately.
4. Use the same requested result count where provider capability permits; target top 5 for common scoring and allow up to 10 for diagnostic review.
5. Do not use provider-specific query rewrites unless that is a separately scored strategy.
6. Current/freshness queries are scored against authoritative sources retrieved at run time, not against a frozen answer key.
7. Stable queries are scored for factual support and source authority, not merely lexical match.
8. Community/blog sources are not automatically penalized when the query explicitly benefits from experiential/community evidence.
9. Do not publish or provide provider-specific Parallel benchmark/evaluation results to third parties unless the applicable Parallel contract permits it or written consent is retained. Internal evaluation may proceed subject to the exact account terms.
10. Daum live LLM-grounding remains gated by #1324; this corpus does not authorize Production activation.
11. No real user query or sensitive prompt may be substituted into this benchmark.

## Common scoring

Per query/provider record:

```text
Relevant@1                 0 | 1
Relevant@5                 0..5
AnswerSourcePresent@5      0 | 1
Authority@5                0..5
PrimarySourceCount@5       0..5
FreshnessCorrect           0 | 1 | NA
KoreanRelevance            0..5 | NA
KoreanLocalSourceQuality   0..5 | NA
CitationMetadataQuality    0..5
UnsafeUrlRejected          0 | 1 | NA
FetchSuccess               0 | 1 | NA
RenderedPageSuccess        0 | 1 | NA
SignalBoilerplateRatio     0..5 | NA
LatencyMs
ProviderError              NONE | 429 | 4XX | 5XX | TIMEOUT | OTHER
EstimatedSearchCostUsd
EstimatedFetchCostUsd
Notes
```

Aggregate metrics required by #1355:

```text
Relevant@1
Relevant@5
Answer-source-present@5
Authority@5
Primary-source rate
Freshness correctness
Korean relevance quality
Korean local-source quality
Fetch success rate
Rendered-page success
Signal / boilerplate ratio
unsafe URL rejection behavior
citation-ready metadata quality
p50 latency
p95 latency
provider error rate
rate-limit behavior
tokens per selected source
estimated search cost per answer
estimated fetch cost per answer
estimated total retrieval cost per grounded answer
```

## Source-preference labels

```text
PRIMARY_OFFICIAL     government / standards body / vendor official docs / primary data owner
AUTHORITATIVE        recognized institution, regulator, university, major reference source
CURRENT_PRIMARY      official source whose current timestamp/version matters
LOCAL_PRIMARY        local government, transit operator, airport, museum, public operator
MIXED_EVIDENCE       primary + reputable secondary sources useful for fact-checking
COMMUNITY_ALLOWED    community evidence may be relevant but must not replace required primary facts
```

---

# Korean 40

## A. Latest news / current affairs — 10

| ID | Query | Freshness | Preferred evidence |
|---|---|---|---|
| KR-NEWS-01 | 오늘 기준 한국은행의 가장 최근 기준금리 결정은 무엇이며, 한국은행이 제시한 핵심 근거는 무엇인가? | CURRENT | 한국은행 공식 발표 |
| KR-NEWS-02 | 가장 최근 발표된 한국의 월간 반도체 수출액과 전년 동월 대비 증감률은 얼마인가? | CURRENT | 산업통상자원부·관세청 등 공식 통계 |
| KR-NEWS-03 | 오늘 장 마감 기준 코스피 종가와 전일 대비 변동은 얼마인가? | CURRENT | 한국거래소 또는 신뢰 가능한 시장 데이터 |
| KR-NEWS-04 | 현재 기상청 기상특보에서 광주·전남에 발효 중인 특보가 있는가? 있다면 무엇인가? | CURRENT | 기상청 |
| KR-NEWS-05 | 가장 최근 통계청 고용동향에서 한국 실업률은 얼마인가? | CURRENT | 통계청 |
| KR-NEWS-06 | 최근 한 달 안에 대한민국 정부가 발표한 인공지능 정책 중 가장 중요한 공식 발표 하나를 찾아 핵심 내용을 요약하라. | CURRENT | 정부 부처·대통령실·공식 정책자료 |
| KR-NEWS-07 | 최근 한 달 안에 국회 본회의를 통과한 법률안 가운데 디지털·AI·개인정보와 관련된 법안이 있는가? | CURRENT | 국회 의안정보·공식 보도자료 |
| KR-NEWS-08 | 현재 질병관리청이 국민에게 알리고 있는 주요 감염병 주의·유행 정보가 있는가? | CURRENT | 질병관리청 |
| KR-NEWS-09 | 오늘 기준 전국 보통휘발유 평균 판매가격은 리터당 얼마인가? | CURRENT | 오피넷/한국석유공사 |
| KR-NEWS-10 | 오늘 기준 원/달러 환율의 최근 공시값은 얼마인가? | CURRENT | 한국은행·공식 외환시장 자료 우선 |

## B. Government / public policy — 10

| ID | Query | Freshness | Preferred evidence |
|---|---|---|---|
| KR-GOV-01 | 2026년 대한민국 최저임금 시급은 얼마이며 공식 적용 기간은 언제부터 언제까지인가? | CURRENT_YEAR | 최저임금위원회·고용노동부 |
| KR-GOV-02 | 2026년 전기승용차 구매 보조금 산정 방식에서 차량 가격에 따른 국비 지원 차등 기준은 어떻게 되는가? | CURRENT_YEAR | 환경부·무공해차 통합누리집 |
| KR-GOV-03 | 주민등록 전입신고를 온라인으로 할 수 있는 공식 정부 서비스와 기본 절차는 무엇인가? | SLOW | 정부24·행정안전부 |
| KR-GOV-04 | 대한민국 일반 복수여권을 재발급할 때 현재 기본 수수료와 신청 가능한 공식 경로는 무엇인가? | SLOW | 외교부·정부24 |
| KR-GOV-05 | 현재 육아휴직 급여의 주요 지급 기준과 상한은 어떻게 되는가? | CURRENT | 고용노동부·고용24 |
| KR-GOV-06 | 현재 국민연금 보험료율은 얼마이며 직장가입자의 사용자와 근로자 부담 비율은 어떻게 되는가? | CURRENT | 국민연금공단 |
| KR-GOV-07 | 대한민국에서 개인정보 유출 사고가 발생한 사업자가 따라야 할 신고·통지의 기본 의무는 무엇인가? | CURRENT | 개인정보보호위원회·법령정보 |
| KR-GOV-08 | 현재 청년 창업기업이 확인할 수 있는 대표적인 중앙정부 창업지원 사업 검색 포털은 무엇이며 어떤 정보를 제공하는가? | CURRENT | K-Startup·중소벤처기업부 |
| KR-GOV-09 | 재난문자에는 어떤 유형이 있고 긴급재난문자와 안전안내문자는 어떻게 구분되는가? | SLOW | 행정안전부 |
| KR-GOV-10 | 대한민국 법정공휴일 제도에서 대체공휴일이 적용되는 주요 공휴일 범위는 현재 어떻게 되는가? | CURRENT | 법제처 국가법령정보센터·인사혁신처 |

## C. General Korean factual knowledge — 5

| ID | Query | Freshness | Preferred evidence |
|---|---|---|---|
| KR-FACT-01 | 직지심체요절이 현존하는 세계 최고(最古)의 금속활자본으로 평가되는 근거와 현재 소장처는 어디인가? | STABLE | UNESCO·국립기관·프랑스국립도서관 |
| KR-FACT-02 | 훈민정음이 창제된 해와 반포된 해는 각각 언제인가? | STABLE | 국립국어원·문화유산 관련 공식 자료 |
| KR-FACT-03 | 제주 화산섬과 용암동굴이 유네스코 세계자연유산에 등재된 해와 핵심 구성 지역은 무엇인가? | STABLE | UNESCO·국가유산청 |
| KR-FACT-04 | 조선이 한양을 수도로 정하고 천도한 시기는 언제이며 당시 한양이 선택된 배경은 무엇인가? | STABLE | 국사편찬위원회·서울역사 자료 |
| KR-FACT-05 | 5·18 민주화운동 기념일은 언제이며 국가기념일로 지정된 법적·역사적 의미는 무엇인가? | STABLE | 국가보훈부·5·18 공식 기록 |

## D. Korean local / daily-life — 5

| ID | Query | Freshness | Preferred evidence |
|---|---|---|---|
| KR-LOCAL-01 | 광주 도시철도 1호선 평동역에서 소태역 방향 첫차와 막차 시간은 현재 어떻게 되는가? | CURRENT | 광주교통공사 |
| KR-LOCAL-02 | 광주광역시 남구에서 일반 종량제 생활폐기물을 배출할 수 있는 기본 요일·시간 규칙은 무엇인가? | CURRENT | 광주 남구청 |
| KR-LOCAL-03 | 국립광주박물관의 오늘 기준 관람시간, 휴관일, 관람료는 어떻게 되는가? | CURRENT | 국립광주박물관 |
| KR-LOCAL-04 | 광주공항 국내선 주차장의 현재 기본 주차요금과 1일 최대요금은 얼마인가? | CURRENT | 한국공항공사 광주공항 |
| KR-LOCAL-05 | 광주광역시 시내버스 일반 성인 교통카드 요금은 현재 얼마인가? | CURRENT | 광주광역시·광주버스운송 관련 공식 자료 |

## E. Developer / API documentation — 5

| ID | Query | Freshness | Preferred evidence |
|---|---|---|---|
| KR-DEV-01 | 현재 Python의 최신 안정 버전은 무엇이며 공식 릴리스 날짜는 언제인가? | CURRENT | python.org |
| KR-DEV-02 | Cloudflare Workers에서 Python Worker가 현재 지원하는 런타임·호환성 모델의 핵심 제약은 무엇인가? | CURRENT | Cloudflare Developers |
| KR-DEV-03 | GitHub REST API의 인증된 일반 요청에 적용되는 현재 primary rate limit의 기본값은 얼마인가? | CURRENT | GitHub Docs |
| KR-DEV-04 | Neon Postgres에서 현재 공식적으로 지원한다고 문서화한 주요 PostgreSQL 확장 기능을 확인할 수 있는 문서는 어디인가? | CURRENT | Neon Docs |
| KR-DEV-05 | Kakao Daum 웹문서 검색 API의 엔드포인트, 정렬 옵션, 현재 일일 쿼터는 무엇인가? | CURRENT | Kakao Developers |

## F. Fact-check / conflicting sources — 5

| ID | Query | Freshness | Preferred evidence |
|---|---|---|---|
| KR-CHECK-01 | “한국의 전기차 구매 보조금은 차종과 차량 가격에 관계없이 모두 같은 금액이다”라는 주장은 사실인가? | CURRENT | 환경부 공식 기준 + 필요시 보조 설명 |
| KR-CHECK-02 | “모바일 주민등록증”과 “주민등록증 모바일 확인서비스”는 완전히 같은 제도라는 주장은 사실인가? | CURRENT | 행정안전부·정부24 |
| KR-CHECK-03 | “대한민국 최저임금은 서울·부산·광주처럼 지역마다 다르다”라는 주장은 사실인가? | CURRENT_YEAR | 최저임금위원회·고용노동부 |
| KR-CHECK-04 | “Daum Search API는 모든 검색 유형을 합쳐 하루 5만 건이고 웹문서 검색도 별도 제한 없이 5만 건이다”라는 주장은 현재 공식 쿼터와 일치하는가? | CURRENT | Kakao Developers quota 문서 |
| KR-CHECK-05 | “대한민국 여권은 만료일 6개월 전이 되어야만 재발급 신청이 가능하다”라는 주장은 현재 공식 안내와 일치하는가? | CURRENT | 외교부·정부24 |

---

# English 20

## G. Current tech / news — 5

| ID | Query | Freshness | Preferred evidence |
|---|---|---|---|
| EN-NEWS-01 | What is the current Node.js LTS release line and its latest maintenance version? | CURRENT | nodejs.org |
| EN-NEWS-02 | What is the latest stable Kubernetes release currently listed by the Kubernetes project, and when was it released? | CURRENT | kubernetes.io / GitHub Kubernetes |
| EN-NEWS-03 | What is the latest stable Google Chrome desktop version currently published for the Stable channel? | CURRENT | Chrome Releases / Google |
| EN-NEWS-04 | What is the most recent major PostgreSQL release and its latest minor release currently available? | CURRENT | postgresql.org |
| EN-NEWS-05 | What is the latest announced major change to GitHub Actions hosted runners within the past 90 days? | CURRENT | GitHub Changelog / GitHub Docs |

## H. Official documentation — 5

| ID | Query | Freshness | Preferred evidence |
|---|---|---|---|
| EN-DOC-01 | According to GitHub's official documentation, how does workflow-level `concurrency` with `cancel-in-progress` behave? | SLOW | docs.github.com |
| EN-DOC-02 | According to Cloudflare's current D1 documentation, what transaction or batch guarantees are provided for grouped SQL statements? | CURRENT | developers.cloudflare.com |
| EN-DOC-03 | According to PostgreSQL's current documentation, what is the purpose of logical replication publications and subscriptions? | SLOW | postgresql.org/docs |
| EN-DOC-04 | According to MDN, how should `AbortController` be used to cancel a `fetch()` request? | SLOW | developer.mozilla.org |
| EN-DOC-05 | According to OpenAI's current API documentation, what are the supported patterns for receiving streamed Responses API events? | CURRENT | platform.openai.com / developers.openai.com |

## I. Coding / troubleshooting — 5

| ID | Query | Freshness | Preferred evidence |
|---|---|---|---|
| EN-CODE-01 | A Python HTTPS request fails with `CERTIFICATE_VERIFY_FAILED`. What are the safe troubleshooting steps that preserve TLS verification? | SLOW | Python / Requests / certifi official docs |
| EN-CODE-02 | A Node.js ESM project throws `ERR_MODULE_NOT_FOUND` for a local import. What path and file-extension rules should be checked first? | CURRENT | nodejs.org docs |
| EN-CODE-03 | How can a PostgreSQL administrator identify sessions involved in blocking or deadlock-related waits using current system views? | CURRENT | postgresql.org docs |
| EN-CODE-04 | A Cloudflare Worker Service Binding is `undefined` at runtime. Which binding configuration and environment mismatch checks should be performed first? | CURRENT | Cloudflare Developers |
| EN-CODE-05 | In GitHub Actions, what does `permissions: contents: read` grant to the workflow token, and what common operation will still require additional permission? | CURRENT | GitHub Docs |

## J. General research — 5

| ID | Query | Freshness | Preferred evidence |
|---|---|---|---|
| EN-RES-01 | What amount of moderate-intensity physical activity does the WHO recommend per week for adults aged 18–64? | STABLE | WHO |
| EN-RES-02 | What does the IPCC conclude about human influence on observed global warming since the pre-industrial period? | STABLE | IPCC |
| EN-RES-03 | What are the latest OECD projections or measurements showing about population ageing in South Korea? | CURRENT | OECD primary data/report |
| EN-RES-04 | What is the diameter of the James Webb Space Telescope's primary mirror and how is it segmented? | STABLE | NASA / ESA |
| EN-RES-05 | Why are `example.com`, `example.net`, and `example.org` reserved, and which standards or IANA resources define their intended use? | STABLE | IANA / RFC |

---

## Run metadata schema

Each benchmark run should record at minimum:

```json
{
  "corpus_version": "padiem-search-provider-benchmark-v1",
  "run_date": "YYYY-MM-DD",
  "provider": "provider-id",
  "provider_mode": "mode-or-null",
  "query_id": "KR-NEWS-01",
  "requested_results": 5,
  "effective_results": 5,
  "latency_ms": 0,
  "provider_error": "NONE",
  "relevant_at_1": 0,
  "relevant_at_5": 0,
  "answer_source_present_at_5": 0,
  "authority_at_5": 0,
  "primary_source_count_at_5": 0,
  "freshness_correct": null,
  "korean_relevance": null,
  "korean_local_source_quality": null,
  "citation_metadata_quality": 0,
  "unsafe_url_rejected": null,
  "estimated_search_cost_usd": 0.0,
  "notes": ""
}
```

## Decision discipline

The corpus does **not** preselect a winner. Final #1355 output must be role-based and may select different providers for different jobs:

```text
GENERAL_DEFAULT_CANDIDATE
KOREAN_SPECIALIST
FETCH_DEFAULT_CANDIDATE
DEEP_RESEARCH_PROVIDER
PRIVACY_SENSITIVE_PROVIDER
FREE_HIGH_VOLUME_PROVIDER
FALLBACK_ORDER
PARALLEL_SEARCH_POLICY
```

Vendor self-reported benchmark claims are context only. Padiem provider selection must be based on this fixed corpus, current official terms/privacy constraints, and reproducible Padiem measurements.

## Safety / mutation lock

```text
REAL_USER_QUERY_BENCHMARK = NO
REAL_USER_DATA_TO_EXPERIMENTAL_PROVIDER = NO
PROVIDER_DEFAULT_CHANGE = NO
PRODUCTION_PROVIDER_ENABLE = NO
PRODUCTION_SECRET_INSTALL = NO
B62_PUBLIC_BEHAVIOR_CHANGE = NO
PRODUCTION_MUTATION = 0
```
