# Padiem Search Provider — W4 Terms / Benchmark Consent Outreach Pack

Issue: #1355  
Date: **2026-09-03 (Asia/Seoul)**  
Baseline main: `442369a14ac7a1712c288e98865d78abc0e87ab6`  
Scope: provider-specific written clarification requests and acceptance fields

## 0. Non-action boundary

This is a **draft outreach pack only**. Creating/merging this document does not send a message, create a vendor account, install an API key, approve spend, change a provider default, or activate Production.

```text
EXTERNAL_MESSAGE_SENT = NO
PROVIDER_ACCOUNT_CREATED = NO
EVALUATION_CREDENTIAL_INSTALLED = NO
PRODUCTION_SECRET_REUSE = NO
LIVE_PROVIDER_CALLS = 0
REAL_USER_QUERY = NO
PROVIDER_DEFAULT_CHANGE = NO
PRODUCTION_PROVIDER_ENABLE = NO
PRODUCTION_MUTATION = 0
```

External outreach requires a separate owner-authorized action.

## 1. Common Padiem use case to describe to every provider

Use the same core description so provider answers are comparable.

> Padiem Chat is a public/commercial AI chat service. For a user question that requires current web information, our server may send the search query to a search API, receive a small set of URLs/snippets/metadata, and temporarily pass selected returned content to an external LLM as grounding context. The LLM generates a user-facing answer with source links/attribution. We do not use search results to train or fine-tune our models and do not resell the search API. We may keep a bounded, short-lived cache or normalized evidence record only for reliability, citation continuity, cost control, and freshness-aware reuse. We also need to run a synthetic/public 60-query internal evaluation to compare retrieval quality, latency, metadata quality, Korean-language performance, and cost.

For every provider, distinguish these three activities:

```text
A. INTERNAL_SYNTHETIC_BENCHMARK
B. PUBLIC_CUSTOMER_FACING_GROUNDING
C. TRANSIENT_OR_SHORT_LIVED_RESULT_RETENTION
```

Never treat permission for A as permission for B or C.

## 2. Required answer fields

For each provider, retain the written response and classify only what the provider actually confirms.

```text
PROVIDER =
CHANNEL = email | support | sales | official forum | contract/order form
RESPONSE_URL_OR_THREAD =
RESPONSE_DATE =
RESPONDER_IDENTITY_OR_TEAM =
APPLICABLE_PLAN_OR_CONTRACT =

SYNTHETIC_INTERNAL_BENCHMARK = ALLOWED | NOT_ALLOWED | NEEDS_CLARIFICATION
PUBLIC_CUSTOMER_FACING_SEARCH = ALLOWED | NOT_ALLOWED | NEEDS_CLARIFICATION
TRANSIENT_LLM_GROUNDING = ALLOWED | NOT_ALLOWED | NEEDS_CLARIFICATION
EXTERNAL_LLM_TRANSMISSION = ALLOWED | NOT_ALLOWED | NEEDS_CLARIFICATION
SHORT_LIVED_CACHE = ALLOWED | NOT_ALLOWED | NEEDS_CLARIFICATION
NORMALIZED_EVIDENCE_RETENTION = ALLOWED | NOT_ALLOWED | NEEDS_CLARIFICATION
CROSS_END_USER_CACHE_REUSE = ALLOWED | NOT_ALLOWED | NEEDS_CLARIFICATION
QUERY_RETENTION_BY_PROVIDER =
TRAINING_USE_BY_PROVIDER =
TRAINING_OPT_OUT =
ZDR = AVAILABLE | UNAVAILABLE | NEEDS_CLARIFICATION
DPA = AVAILABLE | UNAVAILABLE | NEEDS_CLARIFICATION
SENSITIVE_QUERY_PATH = ALLOWED | NOT_ALLOWED | NEEDS_CLARIFICATION
ATTRIBUTION_REQUIREMENT =
OUTPUT_STORAGE_LIMIT =

PROVIDER_SPECIFIC_BENCHMARK_PUBLICATION = ALLOWED | NOT_ALLOWED | NEEDS_CLARIFICATION
WRITTEN_BENCHMARK_PUBLICATION_CONSENT_URL =

PRODUCTION_ELIGIBLE = YES | NO
PRODUCTION_ELIGIBILITY_REASON =
```

Default rule:

```text
AMBIGUOUS_OR_SILENT = NEEDS_CLARIFICATION
NEEDS_CLARIFICATION => PRODUCTION_ELIGIBLE = NO
```

## 3. Parallel — highest-priority clarification

Current official evidence:
- https://parallel.ai/customer-terms
- https://parallel.ai/pricing
- https://parallel.ai/privacy-policy

Current Customer Terms allow API integration into Customer Applications and delivery of derivative Customer Output to End Customers, but state that output generated from one query is primarily for one End Customer and must not be copied/cached/stored for other End Customers. They also prohibit providing benchmark/evaluation results to a third party without Parallel's prior written consent.

### Ready-to-send request

**Subject:** Clarification and written consent request — Padiem Search API grounding and benchmark

> Hello Parallel team,
>
> We are evaluating Parallel Search for Padiem Chat, a public/commercial AI chat service. For current-information questions, our server would send an end-user search query to Parallel Search, select a small number of returned URLs/excerpts, and pass those selected fields transiently to an external LLM as grounding context. The LLM would generate a user-facing answer with source links. We do not use Parallel output to train/fine-tune a model, do not resell the Search API, and do not build a general Parallel-output database.
>
> Could you please confirm in writing:
>
> 1. Is this public customer-facing Search → external LLM grounding → attributed answer flow permitted under the applicable self-serve/customer terms?
> 2. May we retain a bounded short-lived copy of the selected URL/excerpt/metadata for the same end user's citation continuity, retry/recovery, and freshness-aware cache?
> 3. Is any reuse of an identical selected result across different end users prohibited even if the original public source URL is the same?
> 4. What storage duration or storage volume would be considered acceptable for temporary normalized evidence?
> 5. Is Enterprise ZDR required or recommended for end-user queries, and is a DPA available?
> 6. We have a fixed synthetic/public 60-query retrieval benchmark. May we run it internally?
> 7. Your current terms restrict providing benchmark/evaluation results to third parties. Please confirm whether we may publish or share provider-specific aggregate benchmark results such as Relevant@5, latency, error rate, Korean-language retrieval quality, and cost. If allowed, please provide written consent and any required conditions or attribution.
>
> We can keep raw provider responses private and publish only aggregate measurements if that is required.
>
> Thank you.

### Parallel acceptance gate

```text
INTERNAL_BENCHMARK_RUN = requires authorized evaluation key + applicable account terms
PUBLIC_PROVIDER_SPECIFIC_BENCHMARK_RESULTS = HOLD until explicit written consent
PUBLIC_GROUNDING = HOLD until exact customer-facing + external-LLM use is confirmed for the intended plan
CROSS_USER_OUTPUT_CACHE = NO by default under current Customer Terms
PRODUCTION_DEFAULT = HOLD
```

## 4. Brave Search API — retention/ZDR clarification

Current official evidence:
- https://api-dashboard.search.brave.com/privacy-policy
- https://api-dashboard.search.brave.com/documentation/pricing
- https://api-dashboard.search.brave.com/documentation/resources/help-feedback

The current Brave Search API privacy notice says standard Search API query records are retained for up to 90 days for billing/troubleshooting. Current help material requires an appropriate arrangement if a customer needs to retain Search API data. Enterprise ZDR is a separate path.

### Ready-to-send request

**Subject:** Brave Search API — grounded AI answer and short-lived result-retention clarification

> Hello Brave Search API team,
>
> We are evaluating Brave Search for Padiem Chat, a public/commercial AI chat service. Our server would submit an end-user web query, select up to five returned URLs/snippets/metadata items, pass those selected fields transiently to an external LLM for grounded synthesis, and show the user an answer with source links. We do not train on Brave output or resell the API.
>
> Could you please confirm:
>
> 1. Is this customer-facing Search → external LLM grounding → user-facing attributed answer flow permitted on a standard Search API plan?
> 2. Your current documentation says retaining Search API data requires an appropriate arrangement. Does a short-lived cache of selected URL/title/snippet/metadata for citation continuity, failover, or freshness-aware reuse count as prohibited retention?
> 3. If short-lived retention requires a special plan or contract, which plan/contract should we use and what retention period is permitted?
> 4. Does Enterprise ZDR cover the full Search API request path and all relevant subprocessors?
> 5. Is a DPA available for this service?
> 6. Are sensitive or personal-data-bearing search queries permitted on Enterprise ZDR, and what restrictions apply?
> 7. May we run a fixed synthetic/public 60-query internal benchmark and publish aggregate provider-specific quality/latency/cost results? Are there any publication or attribution conditions?
>
> Raw responses can remain private; the intended benchmark publication, if permitted, would be aggregate metrics only.

### Brave acceptance gate

```text
SYNTHETIC_INTERNAL_BENCHMARK = eligible with authorized evaluation key
STANDARD_QUERY_PATH = not ZDR; up-to-90-day query logging remains material
SHORT_LIVED_RESULT_CACHE = HOLD until Brave confirms allowed arrangement
PRIVACY_SENSITIVE_PRODUCTION = Enterprise ZDR/contract path only
PRODUCTION_DEFAULT = HOLD until benchmark + storage/privacy fit
```

## 5. Exa — standard training path vs Enterprise ZDR

Current official evidence:
- https://exa.ai/privacy-policy
- https://exa.ai/enterprise
- https://exa.ai/pricing

Exa's current public privacy policy says open-text Query Data is not intended for personal information and Query Data is used to improve products, including training/fine-tuning models. Exa separately advertises Enterprise ZDR.

### Ready-to-send request

**Subject:** Exa Enterprise ZDR/DPA and public AI-grounding clarification for Padiem

> Hello Exa team,
>
> We are evaluating Exa Search/Contents for Padiem Chat, a public/commercial AI chat service. We would send end-user search queries, use returned URLs/highlights/content as transient grounding for an external LLM, and show an attributed user-facing answer. We do not train our model on Exa outputs and do not resell Exa.
>
> Your public Privacy Policy states that standard Query Data may be used to improve products, including model training/fine-tuning, and asks users not to submit personal information as Query Data. We therefore do not consider the standard path suitable for private or sensitive Padiem queries.
>
> Please confirm:
>
> 1. Under Enterprise ZDR, are end-user query strings and returned results excluded from storage and model training/fine-tuning across Exa and relevant subprocessors?
> 2. Is a DPA available and does it cover Search, Contents, Deep Search, and any subprocessors used by those endpoints?
> 3. Is the Search/Contents → external LLM grounding → attributed answer workflow permitted for a public customer-facing service?
> 4. May Padiem retain bounded short-lived normalized evidence (URL/title/highlight/date) for citations, recovery, freshness-aware caching, and cost control? What duration/limits apply?
> 5. Are personal-data-bearing or sensitive queries permitted under the Enterprise ZDR/DPA path?
> 6. May we run a fixed synthetic/public 60-query internal benchmark and publish aggregate provider-specific quality/latency/cost results? Are there conditions on benchmark publication?

### Exa acceptance gate

```text
STANDARD_REAL_USER_PERSONAL_OR_SENSITIVE_QUERY = NO
SYNTHETIC_PUBLIC_BENCHMARK = eligible with authorized evaluation key
PRIVACY_SENSITIVE_PRODUCTION = requires Enterprise ZDR/DPA confirmation
PRODUCTION_ROLE = HOLD until benchmark + enterprise contract fit
```

## 6. Tavily — no-training / third-party AI provider clarification

Current official evidence:
- https://www.tavily.com/terms
- https://www.tavily.com/privacy
- https://www.tavily.com/pricing

Current Tavily Terms define Customer Input to include end-user Customer Application queries and state that Tavily and third-party AI providers may use/process/analyze/retain Customer Input and AI Functionality Outputs for training/improving AI models.

### Ready-to-send request

**Subject:** Request for no-training/ZDR terms for public customer search queries — Padiem Chat

> Hello Tavily team,
>
> We are evaluating Tavily for Padiem Chat, a public/commercial AI chat service. Our server would send end-user search queries to Tavily, select returned URLs/content/metadata, pass selected evidence transiently to an external LLM, and generate a user-facing answer with sources.
>
> We reviewed the current Tavily Terms, including the provisions allowing Tavily and third-party AI service providers to use/process/retain Customer Input and certain Outputs for training/improving AI systems. That standard data-use position is not acceptable for Padiem end-user queries.
>
> Please confirm whether Tavily offers a written contractual path that provides all of the following:
>
> 1. no training/fine-tuning/evaluation use of Padiem queries, inputs, or outputs;
> 2. zero-data-retention or a clearly bounded retention period;
> 3. equivalent restrictions for relevant subprocessors/third-party AI providers;
> 4. a DPA suitable for a public customer-facing SaaS application;
> 5. permission for Search/Extract output to be passed transiently to an external LLM for grounded synthesis;
> 6. permission for a bounded short-lived normalized evidence cache for citations/recovery/freshness;
> 7. a permitted path for private/sensitive end-user queries, if available;
> 8. permission to run and, if allowed, publish aggregate results from a fixed synthetic/public 60-query provider benchmark.
>
> If these protections are Enterprise-only, please identify the applicable plan/order-form terms.

### Tavily acceptance gate

```text
STANDARD_REAL_USER_QUERY_PATH = HOLD
SYNTHETIC_PUBLIC_INTERNAL_BENCHMARK = conditional with authorized evaluation key
PRODUCTION_ELIGIBLE = NO until written no-training/retention/subprocessor terms are acceptable
```

## 7. TinyFish — public SaaS license and training-use override

Current official evidence:
- https://www.tinyfish.ai/terms
- https://www.tinyfish.ai/pricing

Current standard Terms grant a license to use the Services solely for internal business purposes and grant TinyFish rights to use Customer Data to analyze/improve services and train/fine-tune/evaluate its AI/ML models. Search and Fetch are currently free, but cost does not override these license/privacy gates.

### Ready-to-send request

**Subject:** Separate public-SaaS / no-training agreement inquiry — TinyFish Search and Fetch

> Hello TinyFish team,
>
> We are evaluating TinyFish Search/Fetch for Padiem Chat, a public/commercial AI chat service. We have reviewed your current standard Terms, including the internal-business-purpose license and Customer Data rights for training/fine-tuning/evaluation.
>
> Could TinyFish offer a separate written agreement for this public customer-facing use case that confirms:
>
> 1. Padiem may use Search and/or Fetch behind a public commercial SaaS experience for end users;
> 2. Padiem end-user queries, fetched content, prompts, outputs, logs, and usage data are not used for model training/fine-tuning/evaluation;
> 3. zero-data-retention or a bounded retention schedule is available;
> 4. a DPA and subprocessor commitments are available;
> 5. selected Search/Fetch output may be sent transiently to an external LLM for grounded synthesis and source attribution;
> 6. a bounded short-lived normalized evidence cache is allowed;
> 7. the agreement covers any sensitive-query path that TinyFish permits;
> 8. Padiem may run a fixed synthetic/public 60-query internal benchmark and publish aggregate provider-specific benchmark results, subject to any agreed conditions.
>
> If these protections require Enterprise or a custom Order Form, please identify the applicable route.

### TinyFish acceptance gate

```text
CURRENT_SEARCH_FETCH_PRICE = $0
STANDARD_PUBLIC_PADIEM_DEFAULT = NO / HOLD
STANDARD_SENSITIVE_QUERY = NO
INTERNAL_SYNTHETIC_PUBLIC_EVALUATION = candidate with authorized key
PRODUCTION_ELIGIBLE = requires separate acceptable public-SaaS + no-training/privacy agreement
```

## 8. Firecrawl — Search/Fetch retention and Enterprise privacy boundary

Current official evidence:
- https://www.firecrawl.dev/pricing
- https://www.firecrawl.dev/enterprise
- https://docs.firecrawl.dev/

Firecrawl is primarily a Padiem fetch/extraction candidate. Enterprise currently advertises Zero Data Retention. W4 needs the exact Search/Scrape/Crawl data-use and retention boundary rather than inferring Enterprise protections onto standard plans.

### Ready-to-send request

**Subject:** Firecrawl Search/Scrape grounding, retention, ZDR and DPA clarification — Padiem Chat

> Hello Firecrawl team,
>
> We are evaluating Firecrawl primarily for search discovery and browser/content acquisition behind Padiem Chat, a public/commercial AI chat service. Returned search results or scraped page content would be selected by our server, passed transiently to an external LLM as grounding context, and used to generate an attributed user-facing answer. We do not train on Firecrawl output or resell Firecrawl.
>
> Please confirm:
>
> 1. Is public customer-facing Search/Scrape/Crawl → external LLM grounding → attributed answer use permitted?
> 2. What are the retention and model-training/data-use rules for standard/self-serve Search, Scrape, and Crawl requests and responses?
> 3. For Enterprise Zero Data Retention, does ZDR cover Search, Scrape, Crawl, browser/interact surfaces, logs, and relevant subprocessors?
> 4. Is a DPA available?
> 5. May we store a bounded short-lived normalized evidence record or extracted page content for citation continuity, retry/recovery, freshness-aware caching, and cost control? What limits apply?
> 6. Are personal-data-bearing or sensitive retrieval requests permitted on the Enterprise ZDR path?
> 7. May we run a fixed synthetic/public 60-query Search benchmark and a separate fetch/extraction benchmark, and publish aggregate provider-specific results?

### Firecrawl acceptance gate

```text
FETCH_ROLE = high-priority benchmark candidate
SEARCH_DEFAULT = not implied by existing integration
PRIVACY_SENSITIVE_ROLE = Enterprise ZDR/DPA path only after written scope confirmation
PRODUCTION_ROLE = HOLD until benchmark + exact data-use/retention terms
```

## 9. Daum Search / Kakao — do not duplicate #1324

The exact Daum → external LLM grounding question is already tracked in #1324. W4 must not create a second divergent Kakao question.

Fresh #1324 state on 2026-09-03:

```text
ISSUE_1324 = OPEN
COMMERCIAL_USE_GENERAL = public official DevTalk evidence exists
API_RESULT_DB_STORAGE_PROCESSING_GENERAL = public official DevTalk evidence exists
EXTERNAL_LLM_GROUNDING_EXACT_PERMISSION = NOT FOUND
KAKAO_LLM_GROUNDING_TERMS_CONFIRMATION = NEEDS_CLARIFICATION
```

Use the Korean/English wording already retained in #1324 and obtain a written official Kakao response addressing:

1. transient transmission of `title`, `contents`, `url`, `datetime` to an external LLM;
2. public/commercial synthesized user-facing answer with source attribution;
3. no model training/fine-tuning and no API resale;
4. bounded short-lived cache;
5. required attribution/retention limits;
6. whether the response is the approval required by current Kakao operating policy.

```text
DAUM_PRODUCTION_KEY_INSTALL = NO
DAUM_LLM_GROUNDING_LIVE = NO
DAUM_W4_DUPLICATE_OUTREACH = NO
```

## 10. Outreach priority

Recommended order is driven by how much each response unlocks #1355.

```text
P0 = Parallel
     reason: general-default shortlist + explicit benchmark-publication prohibition

P0 = Brave
     reason: general-default shortlist + storage/retention ambiguity

P1 = Exa
     reason: deep-research shortlist + standard training path vs Enterprise ZDR

P1 = Firecrawl
     reason: fetch-default shortlist + exact Enterprise ZDR scope needed

P1 = Tavily
     reason: potentially useful retrieval, but standard training terms block real-user Production

P1 = TinyFish
     reason: exceptional $0 Search/Fetch economics, but standard license/training clauses block public default

P0_SEPARATE_EXISTING_GATE = Daum / #1324
     reason: Korean-specialist role cannot proceed without explicit Kakao LLM-grounding approval
```

## 11. Benchmark execution readiness after W4

W4 does not itself unlock live calls. A provider can enter the W1 60-query live run only when all benchmark-level gates are satisfied.

```text
W1_CORPUS = MERGED
W2_RUNNER = MERGED
W2_SCORER = MERGED
W3_PORTFOLIO = MERGED
W4_OUTREACH_PACK = THIS DOCUMENT

AUTHORIZED_EVALUATION_CREDENTIAL = REQUIRED
EVALUATION_ACCOUNT_TERMS_ACCEPTABLE_FOR_SYNTHETIC_PUBLIC_QUERIES = REQUIRED
RAW_RESULT_STORAGE_INSIDE_REPO = NO
REAL_USER_QUERY = NO
PRODUCTION_SECRET_REUSE = NO BY DEFAULT
```

Additional provider-specific benchmark gates:

```text
PARALLEL_PUBLIC_SCORE_PUBLICATION = requires written consent
DAUM_LLM_GROUNDING_BENCHMARK_PATH = remains behind #1324; do not use benchmark to bypass legal gate
TINYFISH_BENCHMARK = internal synthetic/public evaluation only under reviewed standard terms
TAVILY_BENCHMARK = synthetic/public only unless written terms improve
```

## 12. Production gate

No written provider reply automatically changes Production.

After a satisfactory provider response and live benchmark evidence, a separate activation decision must still assess:

```text
QUALITY
KOREAN_QUALITY
FRESHNESS
LATENCY
ERROR_RATE
COST
PRIVACY
RETENTION
TRAINING_USE
ZDR_DPA
CACHE_RIGHTS
ATTRIBUTION
FALLBACK_POLICY
```

Then, and only under a separate explicit activation authorization:

```text
PROVIDER_DEFAULT_CHANGE = MAY_BE_PROPOSED
PRODUCTION_SECRET_INSTALL = MAY_BE_PROPOSED
PRODUCTION_DEPLOY = MAY_BE_PROPOSED
```

Nothing in #1355 W4 performs those actions.
