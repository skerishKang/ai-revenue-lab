# Padiem Search Provider Benchmark — W2 Runner Contract

Issue: #1355  
Baseline corpus: `PADIEM_SEARCH_PROVIDER_BENCHMARK_CORPUS_v1`  
Frozen runner date: 2026-09-03  
Scope: synthetic/public retrieval benchmark only

## Purpose

W2 adds a provider-neutral experiment runner without promoting any new search provider into
`padiem_ai_core.web_runtime`.

The Production/shared Core provider allow-list remains unchanged. Candidate providers are
benchmarked outside that runtime first; only an accepted winner/role should receive a later,
separately reviewed Core adapter.

## Fixed providers

| Provider | Search endpoint | Credential env | W2 mode | Production / distribution gate |
|---|---|---|---|---|
| TinyFish | `GET https://api.search.tinyfish.ai` | `TINYFISH_API_KEY` | direct Search | standard terms permit training/evaluation on Customer Data; sensitive default is not eligible without separate acceptable terms |
| Parallel | `POST https://api.parallel.ai/v1/search` | `PARALLEL_API_KEY` | `mode=fast` | results stay internal unless benchmark publication is permitted by the applicable agreement; Production terms/account tier require review |
| Brave | `GET https://api.search.brave.com/res/v1/web/search` | `BRAVE_SEARCH_API_KEY` | raw Web Search | retention/ZDR tier review required before privacy-sensitive Production use |
| Tavily | `POST https://api.tavily.com/search` | `TAVILY_API_KEY` | basic search, no answer/raw content | privacy/data-use review required before Production |
| Exa | `POST https://api.exa.ai/search` | `EXA_API_KEY` | `type=auto`, highlights enabled | ZDR/DPA tier review required before privacy-sensitive Production use |
| Firecrawl | `POST https://api.firecrawl.dev/v2/search` | `FIRECRAWL_API_KEY` | web search | already supported by Core; owner direction still says it is not the intended default public search path |
| Daum | `GET https://dapi.kakao.com/v2/search/web` | `DAUM_REST_API_KEY` | accuracy search | #1324 Kakao LLM-grounding written confirmation remains mandatory before Production activation |

## Primary official references used for the runner

- TinyFish Search API: `https://docs.tinyfish.ai/search-api/reference`
- TinyFish Terms: `https://www.tinyfish.ai/terms`
- Parallel Search API: `https://docs.parallel.ai/search/search-quickstart`
- Brave Web Search API: `https://api-dashboard.search.brave.com/api-reference/web/search/get`
- Tavily API introduction: `https://docs.tavily.com/documentation/api-reference/introduction`
- Exa Search API: `https://exa.ai/docs/reference/search`
- Firecrawl Search API: `https://docs.firecrawl.dev/api-reference/endpoint/search`
- Kakao Daum Search: tracked by #1302 / #1324 and the existing Core provider contract

These URLs are evidence pointers, not permission to activate a Production provider.

## Fail-closed execution contract

```text
CORPUS = exactly 60 committed synthetic/public queries
MAX_RESULTS_PER_QUERY = 5
NETWORK_DEFAULT = DENY
NETWORK_ENABLE = explicit --allow-network
RETRIES = 0
HTTP_429 = distinct stop signal
CREDENTIAL_VALUE_OUTPUT = NO
RAW_PROVIDER_PAYLOAD_PERSISTENCE = NO
RAW_RESPONSE_HEADERS_PERSISTENCE = NO
MAX_PROVIDER_RESPONSE_BYTES = 1 MiB
LIVE_RESULT_OUTPUT_INSIDE_REPOSITORY = REJECT
PRODUCTION_PROVIDER_CHANGE = NO
PRODUCTION_SECRET_INSTALL = NO
B62_PUBLIC_BEHAVIOR_CHANGE = NO
```

The runner reads credentials only from environment variables. `--list-providers` exposes the
environment-variable name and a boolean `credential_configured`; it never prints the value.

Without `--allow-network`, the runner only prints a dry-run plan and performs zero provider calls.

## Example dry run

```bash
python scripts/experiments/benchmark_padiem_search_providers.py \
  --provider brave \
  --max-queries 5
```

Expected mode:

```text
DRY_RUN_NETWORK_DENIED
```

## Example bounded live run

Only use an evaluation credential already authorized for this benchmark. Do not copy a
Production secret into source, command history, GitHub, or result files.

```bash
BRAVE_SEARCH_API_KEY=<process-environment-only> \
python scripts/experiments/benchmark_padiem_search_providers.py \
  --provider brave \
  --max-queries 5 \
  --allow-network \
  --output /outside/repository/brave-search.jsonl
```

The first 429 is represented as `HTTP_429` and the process stops with no retry.

## Normalized result surface

Only these retrieval fields are retained:

```text
rank
title
url
snippet
published_at
score
```

The benchmark record also keeps:

```text
benchmark_version
provider
query_id
language
category
freshness
query
http_status
latency_ms
result_count
error
distribution_gate
```

Provider-specific raw JSON, request headers and credentials are deliberately absent.

## W2 acceptance boundary

W2 runner readiness does not equal Provider acceptance.

```text
RUNNER_NETWORK_FREE_TESTS = REQUIRED
SAME_CORPUS = REQUIRED
SAME_TOP_K = 5
PROVIDER_CALL_RETRY = 0
LIVE_PROVIDER_CALL = HOLD UNTIL EVALUATION CREDENTIAL IS AVAILABLE/AUTHORIZED
PARALLEL_PUBLIC_RESULT_COMMIT = NO WITHOUT APPLICABLE PERMISSION
DAUM_PRODUCTION_ACTIVATION = HOLD #1324
CORE_PROVIDER_ALLOWLIST_CHANGE = NO
PRODUCTION_MUTATION = 0
```

After credentials are available, run the same corpus against eligible providers and score the
results using `PADIEM_SEARCH_PROVIDER_BENCHMARK_CORPUS_v1.md`. Provider role selection remains a
later #1355 acceptance decision.
