#!/usr/bin/env python3
"""Provider-neutral search benchmark runner for Issue #1355.

This is experiment tooling, not a Production provider runtime. It makes at most one
network request per selected corpus case, never retries, never logs credentials,
and refuses to write live provider results inside the repository.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
import json
import ipaddress
import os
from pathlib import Path
import re
import socket
import sys
import time
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

MAX_RESULTS = 5
MAX_RESPONSE_BYTES = 1_048_576
MAX_TEXT_CHARS = 2_000
DEFAULT_TIMEOUT_SECONDS = 20.0
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS = REPO_ROOT / "docs/experiments/PADIEM_SEARCH_PROVIDER_BENCHMARK_CORPUS_v1.tsv"


@dataclass(frozen=True)
class QueryCase:
    id: str
    language: str
    category: str
    freshness: str
    query: str


@dataclass(frozen=True)
class ProviderSpec:
    provider: str
    endpoint: str
    credential_env: str
    distribution_gate: str
    production_gate: str
    notes: str


@dataclass(frozen=True)
class NormalizedResult:
    rank: int
    title: str
    url: str
    snippet: str
    published_at: str | None = None
    score: float | None = None


class BenchmarkError(RuntimeError):
    code = "BENCHMARK_ERROR"


class MissingCredential(BenchmarkError):
    code = "MISSING_CREDENTIAL"


class ResponseTooLarge(BenchmarkError):
    code = "RESPONSE_TOO_LARGE"


class MalformedResponse(BenchmarkError):
    code = "MALFORMED_RESPONSE"


class TransportError(BenchmarkError):
    code = "TRANSPORT_ERROR"


class BenchmarkHttpError(BenchmarkError):
    def __init__(self, status: int):
        super().__init__(f"provider returned HTTP {status}")
        self.status = status
        if status == 429:
            self.code = "HTTP_429"
        elif 400 <= status < 500:
            self.code = "HTTP_4XX"
        elif status >= 500:
            self.code = "HTTP_5XX"
        else:
            self.code = "HTTP_ERROR"


PROVIDERS: dict[str, ProviderSpec] = {
    "tinyfish": ProviderSpec(
        "tinyfish",
        "https://api.search.tinyfish.ai",
        "TINYFISH_API_KEY",
        "internal_results_only",
        "standard_terms_internal_business_use_and_training; public_customer_app_not_eligible_without_separate_agreement",
        "Search API; 5 normalized results retained; no raw provider payload stored.",
    ),
    "parallel": ProviderSpec(
        "parallel",
        "https://api.parallel.ai/v1/search",
        "PARALLEL_API_KEY",
        "internal_only_without_written_benchmark_consent",
        "terms_and_account_tier_review_required_before_production",
        "Uses Search fast mode for ordinary-search comparison.",
    ),
    "brave": ProviderSpec(
        "brave",
        "https://api.search.brave.com/res/v1/web/search",
        "BRAVE_SEARCH_API_KEY",
        "internal_results_only",
        "privacy_retention_and_zdr_tier_review_required_before_production",
        "Raw Web Search only; no Answers/LLM Context endpoint.",
    ),
    "tavily": ProviderSpec(
        "tavily",
        "https://api.tavily.com/search",
        "TAVILY_API_KEY",
        "internal_results_only",
        "privacy_and_data_use_review_required_before_production",
        "basic search, no generated answer, no raw-content expansion.",
    ),
    "exa": ProviderSpec(
        "exa",
        "https://api.exa.ai/search",
        "EXA_API_KEY",
        "internal_results_only",
        "zdr_or_dpa_tier_review_required_before_sensitive_production",
        "auto search with highlights for citation-ready snippets.",
    ),
    "firecrawl": ProviderSpec(
        "firecrawl",
        "https://api.firecrawl.dev/v2/search",
        "FIRECRAWL_API_KEY",
        "internal_results_only",
        "existing_core_provider; default_search_not_preferred_by_owner",
        "Mirrors the existing Core search endpoint without mutating Core.",
    ),
    "daum": ProviderSpec(
        "daum",
        "https://dapi.kakao.com/v2/search/web",
        "DAUM_REST_API_KEY",
        "internal_results_only",
        "hold_for_kakao_llm_grounding_terms_issue_1324",
        "Evaluation-only request; never installs or reads a Production secret.",
    ),
}


def _clean_text(value: Any, limit: int = MAX_TEXT_CHARS) -> str:
    if not isinstance(value, str):
        return ""
    value = re.sub(r"<[^>]*>", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value if len(value) <= limit else value[:limit].rstrip() + "…"


def _safe_url(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if len(value) > 2048:
        return ""
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    if parsed.username is not None or parsed.password is not None:
        return ""
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan", ".home")):
        return ""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if re.fullmatch(r"[0-9.]+", host):
            return ""
    else:
        candidate = getattr(address, "ipv4_mapped", None) or address
        if not candidate.is_global:
            return ""
    return value


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def load_corpus(path: Path = DEFAULT_CORPUS) -> list[QueryCase]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    required = {"id", "language", "category", "freshness", "query"}
    if not rows or set(rows[0]) != required:
        raise ValueError("corpus TSV schema mismatch")
    cases = [
        QueryCase(
            id=row["id"].strip(),
            language=row["language"].strip(),
            category=row["category"].strip(),
            freshness=row["freshness"].strip(),
            query=row["query"].strip(),
        )
        for row in rows
    ]
    if len(cases) != 60 or len({case.id for case in cases}) != 60:
        raise ValueError("benchmark corpus must contain exactly 60 unique cases")
    if sum(case.language == "ko" for case in cases) != 40:
        raise ValueError("benchmark corpus must contain exactly 40 Korean cases")
    if sum(case.language == "en" for case in cases) != 20:
        raise ValueError("benchmark corpus must contain exactly 20 English cases")
    if any(not case.query for case in cases):
        raise ValueError("benchmark query must not be empty")
    return cases


def provider_public_metadata(spec: ProviderSpec) -> dict[str, Any]:
    return {
        "provider": spec.provider,
        "endpoint": spec.endpoint,
        "credential_env": spec.credential_env,
        "credential_configured": bool(os.environ.get(spec.credential_env)),
        "distribution_gate": spec.distribution_gate,
        "production_gate": spec.production_gate,
        "notes": spec.notes,
    }


def _request_for(spec: ProviderSpec, case: QueryCase, credential: str, limit: int) -> tuple[str, str, dict[str, str], bytes | None]:
    limit = max(1, min(MAX_RESULTS, int(limit)))
    headers = {"Accept": "application/json", "User-Agent": "PadiemSearchBenchmark/1.0"}

    if spec.provider == "tinyfish":
        params = {
            "query": case.query,
            "location": "KR" if case.language == "ko" else "US",
            "language": case.language,
        }
        headers["X-API-Key"] = credential
        return "GET", spec.endpoint + "?" + urlencode(params), headers, None

    if spec.provider == "brave":
        params = {
            "q": case.query,
            "count": str(limit),
            "country": "KR" if case.language == "ko" else "US",
            "search_lang": case.language,
        }
        headers["X-Subscription-Token"] = credential
        return "GET", spec.endpoint + "?" + urlencode(params), headers, None

    if spec.provider == "daum":
        params = {"query": case.query, "size": str(limit), "sort": "accuracy"}
        headers["Authorization"] = f"KakaoAK {credential}"
        return "GET", spec.endpoint + "?" + urlencode(params), headers, None

    headers["Content-Type"] = "application/json"
    if spec.provider == "parallel":
        headers["x-api-key"] = credential
        payload = {
            "mode": "fast",
            "objective": case.query,
            "search_queries": [case.query],
            "advanced_settings": {
                "max_results": limit,
                "excerpt_settings": {"max_chars_per_result": MAX_TEXT_CHARS},
            },
        }
    elif spec.provider == "tavily":
        headers["Authorization"] = f"Bearer {credential}"
        payload = {
            "query": case.query,
            "topic": "general",
            "search_depth": "basic",
            "max_results": limit,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
        }
    elif spec.provider == "exa":
        headers["x-api-key"] = credential
        payload = {
            "query": case.query,
            "type": "auto",
            "numResults": limit,
            "contents": {"highlights": True},
        }
    elif spec.provider == "firecrawl":
        headers["Authorization"] = f"Bearer {credential}"
        payload = {"query": case.query, "limit": limit, "sources": ["web"]}
    else:
        raise ValueError(f"unsupported provider: {spec.provider}")
    return "POST", spec.endpoint, headers, json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _decode_json(raw: bytes) -> dict[str, Any]:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MalformedResponse("provider returned malformed JSON") from exc
    if not isinstance(data, dict):
        raise MalformedResponse("provider response must be a JSON object")
    return data


def _normalize_items(provider: str, data: dict[str, Any], limit: int = MAX_RESULTS) -> list[NormalizedResult]:
    if provider == "tinyfish":
        items = data.get("results", [])
    elif provider == "brave":
        web = data.get("web")
        items = web.get("results", []) if isinstance(web, dict) else []
    elif provider in {"parallel", "tavily", "exa"}:
        items = data.get("results", [])
    elif provider == "firecrawl":
        payload = data.get("data")
        if isinstance(payload, dict):
            items = payload.get("web", [])
        elif isinstance(payload, list):
            items = payload
        else:
            items = []
    elif provider == "daum":
        items = data.get("documents", [])
    else:
        raise ValueError(provider)

    if not isinstance(items, list):
        raise MalformedResponse("provider result collection is not a list")

    normalized: list[NormalizedResult] = []
    for item in items:
        if len(normalized) >= limit:
            break
        if not isinstance(item, dict):
            continue
        url = _safe_url(item.get("url"))
        if not url:
            continue

        if provider == "parallel":
            excerpts = item.get("excerpts", [])
            snippet = " ".join(part for part in excerpts if isinstance(part, str)) if isinstance(excerpts, list) else item.get("excerpt", "")
            published = item.get("publish_date") or item.get("published_date")
            score = item.get("score")
        elif provider == "tavily":
            snippet = item.get("content")
            published = item.get("published_date")
            score = item.get("score")
        elif provider == "exa":
            highlights = item.get("highlights", [])
            snippet = " ".join(part for part in highlights if isinstance(part, str)) if isinstance(highlights, list) else item.get("text", "")
            snippet = snippet or item.get("text", "")
            published = item.get("publishedDate")
            score = item.get("score")
        elif provider == "firecrawl":
            snippet = item.get("description") or item.get("markdown") or item.get("snippet")
            published = item.get("publishedDate") or item.get("date")
            score = item.get("score")
        elif provider == "daum":
            snippet = item.get("contents")
            published = item.get("datetime")
            score = None
        else:
            snippet = item.get("snippet") or item.get("description")
            published = item.get("date") or item.get("published_date")
            score = item.get("score")

        normalized.append(
            NormalizedResult(
                rank=len(normalized) + 1,
                title=_clean_text(item.get("title")) or url,
                url=url,
                snippet=_clean_text(snippet),
                published_at=_clean_text(published, 120) or None,
                score=_num(score),
            )
        )
    return normalized


def _perform_request(method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float) -> tuple[int, bytes]:
    request = Request(url=url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200))
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        raise BenchmarkHttpError(exc.code) from exc
    except (URLError, socket.timeout, TimeoutError) as exc:
        if isinstance(getattr(exc, "reason", None), socket.timeout) or isinstance(exc, (socket.timeout, TimeoutError)):
            error = TransportError("provider request timed out")
            error.code = "TIMEOUT"
            raise error from exc
        raise TransportError("provider transport failed") from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ResponseTooLarge("provider response exceeded safe benchmark limit")
    if status < 200 or status >= 300:
        raise BenchmarkHttpError(status)
    return status, raw


def run_case(
    spec: ProviderSpec,
    case: QueryCase,
    *,
    limit: int = MAX_RESULTS,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    transport=_perform_request,
) -> dict[str, Any]:
    credential = os.environ.get(spec.credential_env, "").strip()
    if not credential:
        raise MissingCredential(f"{spec.credential_env} is not configured")
    method, url, headers, body = _request_for(spec, case, credential, limit)
    started = time.perf_counter()
    status, raw = transport(method, url, headers, body, timeout)
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    data = _decode_json(raw)
    results = _normalize_items(spec.provider, data, limit)
    return {
        "benchmark_version": "padiem-search-provider-benchmark-v1",
        "provider": spec.provider,
        "query_id": case.id,
        "language": case.language,
        "category": case.category,
        "freshness": case.freshness,
        "query": case.query,
        "http_status": status,
        "latency_ms": latency_ms,
        "result_count": len(results),
        "error": None,
        "distribution_gate": spec.distribution_gate,
        "results": [asdict(result) for result in results],
    }


def select_cases(
    cases: Iterable[QueryCase],
    query_ids: set[str] | None,
    categories: set[str] | None,
    max_queries: int | None,
) -> list[QueryCase]:
    selected = [
        case
        for case in cases
        if (not query_ids or case.id in query_ids)
        and (not categories or case.category in categories)
    ]
    if query_ids:
        missing = sorted(query_ids - {case.id for case in selected})
        if missing:
            raise ValueError(f"unknown query ids: {', '.join(missing)}")
    if max_queries is not None:
        if max_queries < 1:
            raise ValueError("--max-queries must be >= 1")
        selected = selected[:max_queries]
    return selected


def _output_handle(output: str | None):
    if not output:
        return sys.stdout, False
    destination = Path(output).expanduser().resolve()
    try:
        destination.relative_to(REPO_ROOT)
    except ValueError:
        pass
    else:
        raise ValueError("live benchmark output must stay outside the repository")
    destination.parent.mkdir(parents=True, exist_ok=True)
    return destination.open("a", encoding="utf-8"), True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=sorted(PROVIDERS))
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--query-id", action="append", default=[])
    parser.add_argument("--category", action="append", default=[])
    parser.add_argument("--max-queries", type=int)
    parser.add_argument("--limit", type=int, default=MAX_RESULTS, choices=range(1, MAX_RESULTS + 1))
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--output", help="JSONL destination outside the repository")
    parser.add_argument("--allow-network", action="store_true", help="required for live provider requests")
    parser.add_argument("--list-providers", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.list_providers:
        for name in sorted(PROVIDERS):
            print(json.dumps(provider_public_metadata(PROVIDERS[name]), ensure_ascii=False, sort_keys=True))
        return 0
    if not args.provider:
        raise SystemExit("--provider is required unless --list-providers is used")

    cases = select_cases(load_corpus(args.corpus), set(args.query_id), set(args.category), args.max_queries)
    spec = PROVIDERS[args.provider]

    if not args.allow_network:
        print(
            json.dumps(
                {
                    "mode": "DRY_RUN_NETWORK_DENIED",
                    "provider": spec.provider,
                    "credential_env": spec.credential_env,
                    "credential_configured": bool(os.environ.get(spec.credential_env)),
                    "selected_queries": [case.id for case in cases],
                    "request_count": len(cases),
                    "retries": 0,
                    "production_mutation": 0,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0

    handle, should_close = _output_handle(args.output)
    try:
        for case in cases:
            try:
                record = run_case(spec, case, limit=args.limit, timeout=args.timeout)
            except BenchmarkError as exc:
                record = {
                    "benchmark_version": "padiem-search-provider-benchmark-v1",
                    "provider": spec.provider,
                    "query_id": case.id,
                    "language": case.language,
                    "category": case.category,
                    "freshness": case.freshness,
                    "query": case.query,
                    "http_status": getattr(exc, "status", None),
                    "latency_ms": None,
                    "result_count": 0,
                    "error": exc.code,
                    "distribution_gate": spec.distribution_gate,
                    "results": [],
                }
                print(json.dumps(record, ensure_ascii=False, sort_keys=True), file=handle, flush=True)
                if exc.code in {"MISSING_CREDENTIAL", "HTTP_429"}:
                    return 2
                continue
            print(json.dumps(record, ensure_ascii=False, sort_keys=True), file=handle, flush=True)
    finally:
        if should_close:
            handle.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
