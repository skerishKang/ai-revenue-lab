# Padiem Search Provider Benchmark — W2 Scoring Contract

Issue: #1355  
Benchmark version: `padiem-search-provider-benchmark-v1`  
Scope: aggregate scoring of normalized synthetic/public benchmark output

## Purpose

The W2 scorer consumes JSONL produced by `benchmark_padiem_search_providers.py` and produces
aggregate comparison metrics without committing or reproducing raw Provider benchmark results.

It deliberately separates two evidence classes:

```text
MECHANICAL / OBJECTIVE OBSERVATION
  latency, HTTP/error state, 429s, result count, metadata presence, domain diversity

HUMAN QUALITY JUDGMENT
  relevance, authority, freshness correctness, Korean/local quality,
  source support, signal/boilerplate, fetch/render quality
```

The scorer must not convert URL/domain heuristics into claims of relevance, authority or
freshness correctness.

## Input boundary

Live benchmark JSONL and human annotation TSV files must remain outside the repository.

```text
RAW_PROVIDER_RESULTS_IN_REPO = NO
RAW_QUERY_TEXT_IN_AGGREGATE_SUMMARY = NO
PROVIDER_HEADERS_IN_SCORE = NO
PROVIDER_CREDENTIALS_IN_SCORE = NO
```

Duplicate `(provider, query_id)` records fail closed. Malformed normalized result shapes fail
closed. A failed Provider call may not carry result items.

## Mechanical metrics

For each Provider, and for language/category breakdowns, calculate:

```text
queries observed
complete 60-query run flag
successful / failed queries
success rate / provider error rate
HTTP 429 count/rate
timeout count
empty-success count/rate
latency p50 / p95
mean results per successful query
top-5 fill rate
normalized result count
title presence rate
snippet presence rate
published-at presence rate
Provider score presence rate
unique result domains
distribution gate values
```

`p95` uses deterministic nearest-rank calculation. These are observational retrieval metrics,
not answer-quality scores.

## Human annotation schema

Generate a blank annotation sheet from an external result JSONL with:

```bash
python scripts/experiments/score_padiem_search_benchmark.py \
  --input /outside/repository/provider-results.jsonl \
  --write-annotation-template /outside/repository/provider-annotations.tsv
```

The template contains Provider + query ID only. It does not reproduce raw query text or result
snippets.

Supported quality columns follow #1355:

```text
Relevant@1                         0|1
Relevant@5                         0..5
Answer-source-present@5            0|1
Authority@5                        0..5
Primary-source-count@5             0..5
Freshness-correct                  0|1|NA
Korean-relevance                   0..5|NA
Korean-local-source-quality        0..5|NA
Citation-metadata-quality          0..5|NA
Unsafe-URL-rejected                0|1|NA
Fetch-success                      0|1|NA
Rendered-page-success              0|1|NA
Signal/boilerplate                 0..5|NA
Tokens-per-selected-source         >=0|NA
Estimated-search-cost-USD          >=0|NA
Estimated-fetch-cost-USD           >=0|NA
Notes                              free text, not copied into aggregate JSON
```

The aggregate scorer reports annotation coverage so a partially scored Provider cannot look like
a fully accepted 60-query run.

## Aggregate quality output

With a human annotation TSV, the scorer may calculate:

```text
Relevant@1 rate
Relevant@5 mean
Answer-source-present@5 rate
Authority@5 mean
Primary-source count/rate
Freshness correctness rate
Korean relevance mean
Korean local-source quality mean
Citation metadata quality mean
Unsafe URL rejection rate
Fetch / rendered-page success rates
Signal/boilerplate mean
Tokens per selected source mean
Search/fetch/total retrieval cost per annotated query
```

These metrics only aggregate explicit human annotations. They are never inferred automatically.

## Output boundary

Aggregate JSON defaults to stdout. If an output file is requested, the scorer rejects a path
inside the repository.

The output is marked:

```text
summary_type = AGGREGATE_ONLY_NO_RAW_PROVIDER_RESULTS
human_quality_inference = NEVER_AUTOMATIC
production_mutation = 0
```

Provider contractual distribution restrictions still apply to aggregate benchmark results. In
particular, the Parallel gate recorded by W2 must be respected before any Provider-specific
benchmark result is published or committed.

## Acceptance boundary

```text
SCORER_ACCEPTS_NORMALIZED_RUNNER_OUTPUT = YES
RAW_PROVIDER_RESULT_REPUBLICATION = NO
RAW_QUERY_REPUBLICATION = NO
HUMAN_QUALITY_AUTOINFERENCE = NO
PARTIAL_ANNOTATION_COVERAGE_VISIBLE = YES
PROVIDER_LANGUAGE_CATEGORY_BREAKDOWN = YES
PRODUCTION_PROVIDER_CHANGE = NO
PRODUCTION_SECRET_INSTALL = NO
PRODUCTION_MUTATION = 0
```

This scoring infrastructure advances #1355 while live 60-query execution remains separately gated
by availability and authorization of evaluation credentials.
