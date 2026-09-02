# Padiem Search Provider Portfolio — W3 Fresh Inventory

Issue: #1355  
Snapshot date: **2026-09-03 (Asia/Seoul)**  
Baseline main: `0fbb2c30c6bb1f5775c69423b3bd912daf56f571`  
Scope: current public provider documentation / terms / pricing reconciliation; **no live provider calls**

## 1. Purpose

This document freezes the W3 provider inventory needed before the 60-query live benchmark can be interpreted or any Production role can be selected.

It does **not** select a Production default. It separates:

1. technical benchmark eligibility;
2. public/customer-facing SaaS eligibility;
3. privacy / retention / training eligibility;
4. result-storage / benchmark-publication restrictions;
5. search vs fetch roles;
6. expected benchmark economics.

The existing W1 corpus and W2 runner/scorer remain authoritative for actual measurements.

```text
LIVE_PROVIDER_CALLS = 0
REAL_USER_QUERY_BENCHMARK = NO
PROVIDER_DEFAULT_CHANGE = NO
PRODUCTION_PROVIDER_ENABLE = NO
PRODUCTION_SECRET_INSTALL = NO
B62_PUBLIC_BEHAVIOR_CHANGE = NO
PRODUCTION_MUTATION = 0
```

## 2. Current role matrix — pre-benchmark only

| Padiem role | Current W3 classification | Why |
|---|---|---|
| General default shortlist | **Parallel Search Turbo/Basic; Brave Search** | low/known per-query cost, broad web search, high self-serve capacity; different legal/privacy constraints must be respected |
| Korean specialist | **Daum Search — HOLD** | Korean ecosystem value remains plausible, but #1324 written Kakao LLM-grounding confirmation is still OPEN |
| Deep/premium research | **Exa; Parallel higher-compute surfaces; Tavily after terms resolution** | Exa/Parallel expose deep/research-oriented retrieval; Tavily standard terms create a data-use gate |
| Fetch/extract shortlist | **Firecrawl; Parallel Extract; TinyFish Fetch for synthetic/public internal evaluation** | search and fetch should remain independently selectable |
| Privacy-sensitive self-serve default | **HOLD** | reviewed self-serve terms do not establish a clean universal ZDR/no-training path |
| Privacy-sensitive enterprise shortlist | **Parallel / Brave / Exa / Firecrawl** | official materials expose Enterprise ZDR and/or enterprise privacy controls; exact contract/DPA still required before sensitive Production use |
| Free/high-volume internal experiment | **TinyFish Search/Fetch** | $0 Search/Fetch, but standard terms restrict use to internal business purposes and permit training/evaluation on Customer Data |
| Ordinary-chat fan-out | **NO by default** | multi-provider parallel search remains an experiment for high-value/deep tasks only |

This matrix is an architecture hypothesis, not an acceptance result.

## 3. 60-query benchmark economics

The W1 corpus is 60 queries and W2 retains at most 5 normalized results per query. Pricing below uses the provider's current public pricing model and one search call per corpus row.

| Provider / mode | Public price basis | 60-query nominal search cost | Notes |
|---|---:|---:|---|
| Parallel Search Turbo | $1 / 1,000 requests, 10 results | **$0.06** | current published latency ~200 ms |
| Parallel Search Basic / Advanced | $5 / 1,000 requests, 10 results | **$0.30** | current published latency ~1 s / ~3 s |
| Brave Search | $5 / 1,000 requests | **$0.30** | $5 monthly credit may cover the run, but billing account/plan is still required |
| Exa Search | $7 / 1,000 requests, up to 10 results | **$0.42** | Deep Search is separately $12–15 / 1,000 |
| Tavily Basic | 1 credit/search × $0.008/credit | **$0.48** | 1,000 free credits/month may cover a run if available |
| Tavily Advanced | 2 credits/search × $0.008/credit | **$0.96** | use only if benchmark explicitly compares advanced mode |
| TinyFish Search | $0 / request | **$0.00** | benchmark use remains synthetic/public/internal-only under standard terms |
| Firecrawl Search | 2 credits / 10 results | **120 credits** | $0 marginal if unused Free 1,000-credit monthly allocation is available; otherwise subscription-allocation dependent; no PAYG plan |
| Daum Web Search | included quota | **$0 incremental within quota** | web-document quota currently 30,000/day; legal gate #1324 still blocks Production grounding |

These figures exclude downstream LLM synthesis, fetch/extract calls, retry multiplication, and human review cost. The W2 runner uses zero retries for the primary benchmark.

## 4. Provider inventory

### 4.1 Parallel

```text
PROVIDER = Parallel
SEARCH_SUPPORTED = YES
FETCH_SUPPORTED = YES (Extract API)
BROWSER_RENDERING = NOT ESTABLISHED AS A SEARCH/EXTRACT CONTRACT IN THIS W3 SNAPSHOT
INDEX / LIVE_WEB_MODEL = live web search/retrieval product
FRESHNESS_CONTROLS = provider search modes / live search available; exact per-query control set validated at execution time
DOMAIN_FILTERS = validate exact current API surface at execution time
DATE_FILTERS = validate exact current API surface at execution time
NEWS / RESEARCH_SPECIALIZATION = YES; Search + Responses + Task surfaces
KOREAN_LOCALIZATION = UNKNOWN UNTIL PADIEM BENCHMARK
RESULT_METADATA = ranked URLs + compressed excerpts
RANK / SCORE_SIGNAL = ranked order; detailed scoring signal must be measured from response shape
MAX_RESULTS = W2 common top-k 5; pricing basis published for 10 results
RATE_LIMITS = Search 600 req/min; Extract 600 req/min
FREE_TIER = up to 5,000 requests/month stated on current pricing page; $5 monthly credits also advertised
PAYG_COST = Search $0.001–$0.005/request for 10 results; Turbo $1/1K, Basic/Advanced $5/1K
AUTH_MODEL = API key / server-side credential
CUSTOMER_FACING_SAAS_TERMS = CONDITIONAL YES
QUERY_RETENTION = Enterprise ZDR available; exact self-serve retention contract must be reviewed for account used
TRAINING_USE = enterprise materials state no-training/ZDR path; exact applicable account terms control
ZDR_AVAILABLE = YES, Enterprise
DPA_AVAILABLE = YES, Enterprise
ENTERPRISE_ONLY_BOUNDARIES = ZDR, DPA, custom rate limits and support listed as enterprise features
OUTAGE / FALLBACK_CONSIDERATIONS = benchmark independently; do not make single-provider dependency before evidence
```

**Material legal constraints:** Current Customer Terms permit incorporation of Customer Output into material provided to End Customers, but one-query output is primarily for one End Customer and may not be copied/cached/stored for other End Customers. The terms also prohibit providing benchmark/evaluation results to third parties without Parallel's prior written consent.

Therefore:

```text
PARALLEL_INTERNAL_BENCHMARK = ELIGIBLE SUBJECT TO ACCOUNT TERMS
PARALLEL_PUBLIC_PROVIDER_SCORE_PUBLICATION = HOLD WITHOUT WRITTEN CONSENT
PARALLEL_SHARED_CROSS_USER_RESULT_CACHE = DO NOT ASSUME PERMITTED
PARALLEL_PRODUCTION_DEFAULT = HOLD UNTIL BENCHMARK + CONTRACT FIT
```

Official evidence:
- https://parallel.ai/pricing
- https://parallel.ai/customer-terms
- https://parallel.ai/privacy-policy
- https://docs.parallel.ai/

### 4.2 Brave Search API

```text
PROVIDER = Brave Search API
SEARCH_SUPPORTED = YES
FETCH_SUPPORTED = NO GENERAL PAGE-FETCH CONTRACT IN REVIEWED SEARCH API SURFACE
BROWSER_RENDERING = NO
INDEX / LIVE_WEB_MODEL = Brave independent web index
FRESHNESS_CONTROLS = YES; API supports freshness/date ranges
DOMAIN_FILTERS = not a primary W3 selection differentiator; validate exact needs at execution
DATE_FILTERS = YES; documented freshness presets/custom date range
NEWS / RESEARCH_SPECIALIZATION = web/news/video/image result surfaces; separate Answers product exists but W2 tests raw Search only
KOREAN_LOCALIZATION = UNKNOWN UNTIL PADIEM BENCHMARK
RESULT_METADATA = URLs, text snippets and typed result surfaces
RANK / SCORE_SIGNAL = ranked result order; no provider score assumed by W2
MAX_RESULTS = API-specific count; W2 normalizes top 5
RATE_LIMITS = Search 50 requests/sec
FREE_TIER = $5 monthly credits
PAYG_COST = Search $5/1K requests
AUTH_MODEL = X-Subscription-Token API key
CUSTOMER_FACING_SAAS_TERMS = YES FOR SEARCH APPLICATION USE, SUBJECT TO DATA/RESULT RESTRICTIONS
QUERY_RETENTION = standard Search query logs up to 90 days for billing/troubleshooting/abuse
TRAINING_USE = not classified as a training-right path from the reviewed privacy notice; retention remains material
ZDR_AVAILABLE = YES, Enterprise
DPA_AVAILABLE = YES; public privacy notice links DPA
ENTERPRISE_ONLY_BOUNDARIES = full-funnel ZDR/custom agreements/capacity
OUTAGE / FALLBACK_CONSIDERATIONS = independent index is useful for provider diversity
```

**Material storage constraint:** Brave's current help material states that retaining data received through the Search API is prohibited unless the customer contacts Brave for an appropriate arrangement.

Therefore:

```text
BRAVE_SYNTHETIC_INTERNAL_BENCHMARK = ELIGIBLE WITH AUTHORIZED KEY
BRAVE_STANDARD_QUERY_PRIVACY = NOT ZDR; UP TO 90-DAY QUERY LOG RETENTION
BRAVE_RESULT_STORAGE = HOLD / CONTRACTUAL ARRANGEMENT REQUIRED
BRAVE_PRIVACY_SENSITIVE_DEFAULT = ENTERPRISE ZDR PATH ONLY
```

Official evidence:
- https://api-dashboard.search.brave.com/documentation/pricing
- https://api-dashboard.search.brave.com/api-reference/web/search/get
- https://api-dashboard.search.brave.com/privacy-policy
- https://api-dashboard.search.brave.com/documentation/resources/help-feedback

### 4.3 Exa

```text
PROVIDER = Exa
SEARCH_SUPPORTED = YES
FETCH_SUPPORTED = YES (Contents / crawler-oriented retrieval)
BROWSER_RENDERING = NOT ESTABLISHED AS A BROWSER CONTRACT IN THIS W3 SNAPSHOT
INDEX / LIVE_WEB_MODEL = Exa web index / real-time search
FRESHNESS_CONTROLS = YES
DOMAIN_FILTERS = YES
DATE_FILTERS = YES
NEWS / RESEARCH_SPECIALIZATION = YES; Search, Deep Search, Agent/research surfaces
KOREAN_LOCALIZATION = UNKNOWN UNTIL PADIEM BENCHMARK
RESULT_METADATA = URLs, page text/highlights, dates where available
RANK / SCORE_SIGNAL = provider search signal available depending mode; W2 records optional score only if returned
MAX_RESULTS = pricing base includes up to 10 results; W2 normalizes top 5
RATE_LIMITS = account/tier dependent; benchmark must record observed 429s
FREE_TIER = trial/free entry advertised; do not assume sustained architecture economics
PAYG_COST = Search $7/1K; Deep Search $12/1K; Deep-Reasoning Search $15/1K; Contents $1/1K pages
AUTH_MODEL = API key
CUSTOMER_FACING_SAAS_TERMS = CONDITIONAL
QUERY_RETENTION = standard public privacy policy says Query Data is used to improve products; Enterprise ZDR available
TRAINING_USE = YES under standard public privacy policy: Query Data may be used for training/fine-tuning
ZDR_AVAILABLE = YES, Enterprise
DPA_AVAILABLE = YES / enterprise agreements advertised
ENTERPRISE_ONLY_BOUNDARIES = ZDR and custom data-security arrangements
OUTAGE / FALLBACK_CONSIDERATIONS = strong candidate for deep/coding/doc retrieval role rather than automatic universal default
```

The public privacy policy explicitly says open-text Query Data is not intended for personal information and that Query Data is used to improve products, including training/fine-tuning models. Enterprise materials separately advertise ZDR where queries/results are not stored or trained on.

```text
EXA_SYNTHETIC_PUBLIC_BENCHMARK = ELIGIBLE WITH AUTHORIZED KEY
EXA_REAL_USER_PERSONAL_OR_SENSITIVE_QUERY_ON_STANDARD_PATH = NO
EXA_PRIVACY_SENSITIVE_PRODUCTION = ENTERPRISE ZDR/CONTRACT PATH
```

Official evidence:
- https://exa.ai/pricing
- https://exa.ai/privacy-policy
- https://exa.ai/enterprise
- https://exa.ai/products/search

### 4.4 Tavily

```text
PROVIDER = Tavily
SEARCH_SUPPORTED = YES
FETCH_SUPPORTED = YES (Extract / crawl surfaces)
BROWSER_RENDERING = advanced extraction handles complex/dynamic pages, but do not equate this with a guaranteed browser-rendering contract without benchmark evidence
INDEX / LIVE_WEB_MODEL = search/retrieval service using public web indexes and third-party providers as applicable
FRESHNESS_CONTROLS = YES
DOMAIN_FILTERS = YES
DATE_FILTERS = YES / current API supports time/date-oriented controls
NEWS / RESEARCH_SPECIALIZATION = YES; basic/advanced search and research-oriented retrieval
KOREAN_LOCALIZATION = UNKNOWN UNTIL PADIEM BENCHMARK
RESULT_METADATA = URLs, snippets/content and scores depending mode
RANK / SCORE_SIGNAL = result score available
MAX_RESULTS = configurable; W2 normalizes top 5
RATE_LIMITS = Development 100 RPM; Production 1,000 RPM; Crawl 100 RPM
FREE_TIER = 1,000 API credits/month
PAYG_COST = $0.008/credit; Basic Search 1 credit; Advanced Search 2 credits
AUTH_MODEL = API key
CUSTOMER_FACING_SAAS_TERMS = CUSTOMER APPLICATIONS CONTEMPLATED, BUT DATA-USE TERMS ARE A HARD PADIEM GATE
QUERY_RETENTION = current Terms authorize retain/process Customer Input and Output for AI functionality
TRAINING_USE = YES under current standard Terms for AI Functionality, including Tavily and third-party AI providers
ZDR_AVAILABLE = NOT ESTABLISHED BY THE CURRENT PUBLIC STANDARD TERMS REVIEWED HERE
DPA_AVAILABLE = VERIFY BEFORE PRODUCTION
ENTERPRISE_ONLY_BOUNDARIES = enterprise-grade security/privacy and custom limits are advertised; exact ZDR/no-training override requires written contract review
OUTAGE / FALLBACK_CONSIDERATIONS = do not use standard path for private/sensitive Padiem queries
```

Current Tavily Terms state that Customer Input and Outputs associated with AI Functionality may be used/processsed/retained for training and improving AI models, including by third-party providers. They also prohibit submitting specified categories of sensitive information.

```text
TAVILY_SYNTHETIC_PUBLIC_BENCHMARK = CONDITIONAL YES WITH AUTHORIZED EVAL KEY
TAVILY_REAL_USER_QUERY_DEFAULT = HOLD
TAVILY_TERMS = NEEDS_CLARIFICATION / CONTRACT OVERRIDE BEFORE PRODUCTION
```

Official evidence:
- https://www.tavily.com/pricing
- https://www.tavily.com/terms
- https://www.tavily.com/privacy
- https://help.tavily.com/articles/3240802908-rate-limits
- https://help.tavily.com/articles/6938147944-basic-vs-advanced-search-what-s-the-difference

### 4.5 TinyFish

```text
PROVIDER = TinyFish
SEARCH_SUPPORTED = YES
FETCH_SUPPORTED = YES
BROWSER_RENDERING = YES via Browser / web-native Agent surfaces; exact Fetch rendering behavior must be benchmarked separately
INDEX / LIVE_WEB_MODEL = web-native search/fetch service
FRESHNESS_CONTROLS = exact Search filter set to be validated at execution
DOMAIN_FILTERS = exact Search filter set to be validated at execution
DATE_FILTERS = exact Search filter set to be validated at execution
NEWS / RESEARCH_SPECIALIZATION = general agent/search/fetch rather than a Padiem-proven specialist
KOREAN_LOCALIZATION = UNKNOWN UNTIL PADIEM BENCHMARK
RESULT_METADATA = normalized only after W2 parser; provider shape measured in live run
RANK / SCORE_SIGNAL = do not assume a stable score until live response is measured
MAX_RESULTS = W2 normalizes top 5
RATE_LIMITS = PAYG Search 30 req/min, Fetch 150 URL/min; Starter 60/300; Pro 120/600; Enterprise custom
FREE_TIER = Search and Fetch are $0 on every current plan; Agent/Browser consume credits
PAYG_COST = Search $0; Fetch $0; Agent/Browser $0.015/credit PAYG
AUTH_MODEL = API key
CUSTOMER_FACING_SAAS_TERMS = NO UNDER STANDARD TERMS AS A PUBLIC PADIEM DEFAULT WITHOUT A SEPARATE ACCEPTABLE AGREEMENT
QUERY_RETENTION = Customer Data may be reviewed/processed to improve services
TRAINING_USE = YES; standard Terms grant training/fine-tuning/evaluation rights over Customer Data
ZDR_AVAILABLE = NOT ESTABLISHED FOR STANDARD SELF-SERVE PATH
DPA_AVAILABLE = VERIFY / SEPARATE ENTERPRISE CONTRACT
ENTERPRISE_ONLY_BOUNDARIES = custom SLA/on-prem advertised; exact privacy override must be confirmed
OUTAGE / FALLBACK_CONSIDERATIONS = free economics are attractive but must not override license/privacy constraints
```

Current TinyFish Terms grant access/use **solely for internal business purposes**, and grant TinyFish rights to review runs/prompts/inputs/outputs and train/fine-tune/evaluate models using Customer Data.

```text
TINYFISH_SYNTHETIC_PUBLIC_INTERNAL_EVALUATION = ELIGIBLE WITH AUTHORIZED KEY
TINYFISH_PUBLIC_CUSTOMER_FACING_PADIEM_DEFAULT = HOLD / NO UNDER STANDARD TERMS
TINYFISH_SENSITIVE_QUERY = NO UNDER STANDARD TERMS
```

Official evidence:
- https://www.tinyfish.ai/pricing
- https://www.tinyfish.ai/terms
- https://docs.tinyfish.ai/

### 4.6 Firecrawl

```text
PROVIDER = Firecrawl
SEARCH_SUPPORTED = YES
FETCH_SUPPORTED = YES (Scrape/Crawl)
BROWSER_RENDERING = YES; Interact / browser features exist
INDEX / LIVE_WEB_MODEL = search plus live content acquisition/extraction
FRESHNESS_CONTROLS = search-specific controls must be validated at execution
DOMAIN_FILTERS = available workflows, exact benchmark contract validated at execution
DATE_FILTERS = validate exact Search surface at execution
NEWS / RESEARCH_SPECIALIZATION = best treated primarily as fetch/extract/content-acquisition infrastructure for #1355
KOREAN_LOCALIZATION = UNKNOWN UNTIL PADIEM BENCHMARK
RESULT_METADATA = Search + page extraction metadata depending endpoint
RANK / SCORE_SIGNAL = benchmark live response rather than assume a portable score
MAX_RESULTS = pricing: 2 credits per 10 Search results; W2 normalizes top 5
RATE_LIMITS = plan/concurrency dependent; Free currently 2 concurrent requests
FREE_TIER = 1,000 credits/month
PAYG_COST = no pay-per-use plan; Hobby $16/month annual billing; Standard $83/month annual billing for 100,000 credits; Growth/Scale higher
AUTH_MODEL = API key
CUSTOMER_FACING_SAAS_TERMS = CONDITIONAL; exact account/privacy terms still govern
QUERY_RETENTION = Enterprise ZDR available
TRAINING_USE = do not infer standard no-training from Enterprise ZDR marketing alone
ZDR_AVAILABLE = YES, Enterprise
DPA_AVAILABLE = VERIFY EXACT ENTERPRISE CONTRACT
ENTERPRISE_ONLY_BOUNDARIES = ZDR, SLA, advanced security
OUTAGE / FALLBACK_CONSIDERATIONS = search and fetch should be scored separately; do not promote Firecrawl to search default merely because it is already integrated
```

Current pricing states Search costs 2 credits per 10 results; Scrape/Crawl cost 1 credit/page. Enterprise advertises zero-data retention. Firecrawl remains especially relevant for `search provider != fetch provider` experiments.

Official evidence:
- https://www.firecrawl.dev/pricing
- https://www.firecrawl.dev/enterprise
- https://docs.firecrawl.dev/

### 4.7 Daum Search / Kakao

```text
PROVIDER = Daum Search
SEARCH_SUPPORTED = YES
FETCH_SUPPORTED = NO GENERAL PAGE FETCH
BROWSER_RENDERING = NO
INDEX / LIVE_WEB_MODEL = Daum portal search index/services
FRESHNESS_CONTROLS = YES; sort=accuracy|recency
DOMAIN_FILTERS = NOT A PRIMARY API FEATURE IN REVIEWED WEB-DOCUMENT ENDPOINT
DATE_FILTERS = no general arbitrary date-range filter established in reviewed endpoint; recency sorting exists
NEWS / RESEARCH_SPECIALIZATION = Korean web/blog/cafe ecosystem specialist potential
KOREAN_LOCALIZATION = HIGH-PRIORITY TO MEASURE; DO NOT ASSUME QUALITY WITHOUT BENCHMARK
RESULT_METADATA = title, contents, url, datetime
RANK / SCORE_SIGNAL = ordered results; no portable numerical score assumed
MAX_RESULTS = size 1..50 per page; W2 normalizes top 5
RATE_LIMITS / QUOTA = Daum Search 50,000/day overall; Web Document Search 30,000/day currently documented
FREE_TIER = included quota; quota subject to change
PAYG_COST = $0 incremental within included quota; additional-quota arrangements subject to Kakao policies
AUTH_MODEL = server REST API key in KakaoAK Authorization header
CUSTOMER_FACING_SAAS_TERMS = **HOLD #1324** for the exact Daum → LLM grounding use case
QUERY_RETENTION = exact grounding/cache guidance pending #1324 official response
TRAINING_USE = Padiem does not intend training use; provider permission for transient LLM grounding is still pending
ZDR_AVAILABLE = NOT ESTABLISHED
DPA_AVAILABLE = NOT ESTABLISHED FOR THIS SEARCH USE IN CURRENT REVIEW
ENTERPRISE_ONLY_BOUNDARIES = partnership/consultation required for quota increases
OUTAGE / FALLBACK_CONSIDERATIONS = cannot be sole Korean path until legal gate and live benchmark both pass
```

Fresh GitHub state on 2026-09-03: #1324 remains OPEN. Generic API availability, quota, or commercial use is **not** accepted as permission for transient LLM grounding.

```text
DAUM_SYNTHETIC_API_BENCHMARK = DO NOT USE TO BYPASS #1324
DAUM_PRODUCTION_KEY_INSTALL = NO
DAUM_LLM_GROUNDING_PRODUCTION = HOLD
```

Official evidence:
- https://developers.kakao.com/docs/en/daum-search/common
- https://developers.kakao.com/docs/en/daum-search/dev-guide
- https://developers.kakao.com/docs/en/getting-started/quota
- GitHub issue #1324

## 5. Privacy / legal eligibility matrix

| Provider | Synthetic/public internal benchmark | Real user standard-tier queries | Sensitive/privacy-critical Production | Result storage/cache | Public provider-specific benchmark publication |
|---|---|---|---|---|---|
| Parallel | **YES, conditional** | **Conditional** | **Enterprise ZDR/DPA path** | cross-user reuse/cache constrained by current Customer Terms | **HOLD without written consent** |
| Brave | **YES, conditional** | **Conditional**; query logs up to 90d | **Enterprise ZDR path** | current help says retention of API data prohibited absent arrangement | no special W3 publication prohibition found; normal contractual/copyright rules still apply |
| Exa | **YES, synthetic/public** | **NO for personal/sensitive on standard path** | **Enterprise ZDR/DPA path** | contract-specific | no special W3 benchmark-publication prohibition identified |
| Tavily | **Conditional synthetic/public only** | **HOLD** | **HOLD until acceptable enterprise/no-training terms** | contract-specific | no special W3 benchmark-publication prohibition identified |
| TinyFish | **YES, internal synthetic/public evaluation** | **NO as public Padiem default under standard terms** | **NO under standard terms** | internal-business license / data-use constraints control | internal evaluation only unless contract permits broader use |
| Firecrawl | **YES, conditional** | **Conditional** | **Enterprise ZDR path** | exact contract/account controls | no special W3 benchmark-publication prohibition identified |
| Daum | **HOLD for LLM-grounding evaluation path pending #1324** | **HOLD** | **HOLD** | pending Kakao guidance | not applicable until legal gate resolves |

`YES` above never means a credential may be installed or Production activated under #1355. It only classifies whether W2's synthetic/public benchmark can proceed when an independently authorized evaluation credential exists.

## 6. Search vs fetch routing hypotheses to test

### Strategy A — general + Korean specialist

```text
general/current -> Parallel vs Brave
Korean/local -> Daum only after #1324; otherwise benchmark general providers' Korean performance
```

### Strategy B — cheap ordinary + premium deep

```text
ordinary search -> Parallel Turbo / Brave / another measured low-cost winner
deep research -> Exa / Parallel higher-compute / Tavily only after terms fit
```

### Strategy C — search/fetch split

```text
search -> best discovery provider
fetch -> Firecrawl / Parallel Extract / another accepted fetcher
```

TinyFish Fetch remains interesting on cost but is not a public customer-facing Padiem path under the reviewed standard terms.

### Strategy D — bounded fallback

```text
primary search
  -> insufficient evidence OR provider error
  -> one bounded fallback provider
  -> stop
```

No silent retry loop and no unlimited paid-provider multiplication.

### Strategy E — selective parallel search

Only test for high-value/deep-research classes. Ordinary chat must not fan out to two providers by default without measured quality gain that justifies cost and latency.

## 7. Current blocker to W4 live measurements

W1 corpus, W2 runner, and W2 scorer are now merged. The remaining live benchmark blocker is not source code.

```text
AUTHORIZED_EVALUATION_CREDENTIAL = REQUIRED PER PROVIDER
CREDENTIAL_VALUE_IN_GITHUB = NO
PRODUCTION_SECRET_REUSE = NO BY DEFAULT
REAL_USER_QUERY = NO
RAW_RESULT_COMMIT = NO
PARALLEL_PUBLIC_RESULT_COMMIT = NO WITHOUT WRITTEN CONSENT
```

The W2 runner already consumes credentials from process environment only and refuses live output inside the repository.

## 8. W3 recommendation before measurements

```text
GENERAL_DEFAULT_CANDIDATE = Parallel Search vs Brave Search benchmark
KOREAN_SPECIALIST = HOLD (Daum #1324)
FETCH_DEFAULT_CANDIDATE = Firecrawl vs Parallel Extract benchmark
DEEP_RESEARCH_PROVIDER = Exa vs Parallel; Tavily only after acceptable terms
PRIVACY_SENSITIVE_PROVIDER = HOLD self-serve; Enterprise ZDR shortlist = Parallel / Brave / Exa / Firecrawl
FREE_HIGH_VOLUME_PROVIDER = TinyFish for synthetic/public internal experiment only
FALLBACK_ORDER = HOLD until measured quality/error/cost data
PARALLEL_SEARCH_POLICY = high-value/deep experiment only until evidence
PRODUCTION_DEFAULT = HOLD
```

No provider should be promoted from this document alone.
