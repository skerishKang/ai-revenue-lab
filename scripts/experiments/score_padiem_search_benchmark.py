#!/usr/bin/env python3
"""Score normalized Padiem search-provider benchmark JSONL.

This scorer intentionally separates mechanically observable retrieval metrics from
human quality judgments. It never infers relevance, authority, freshness correctness,
or Korean quality from URL/domain heuristics.

Live provider result inputs and scored outputs must stay outside the repository.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
import json
import math
from pathlib import Path
import statistics
import sys
from typing import Any, Iterable
from urllib.parse import urlsplit


BENCHMARK_VERSION = "padiem-search-provider-benchmark-v1"
REPO_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_CORPUS_SIZE = 60

RECORD_REQUIRED = {
    "benchmark_version",
    "provider",
    "query_id",
    "language",
    "category",
    "freshness",
    "query",
    "http_status",
    "latency_ms",
    "result_count",
    "error",
    "distribution_gate",
    "results",
}

ANNOTATION_COLUMNS = [
    "provider",
    "query_id",
    "relevant_at_1",
    "relevant_at_5",
    "answer_source_present_at_5",
    "authority_at_5",
    "primary_source_count_at_5",
    "freshness_correct",
    "korean_relevance",
    "korean_local_source_quality",
    "citation_metadata_quality",
    "unsafe_url_rejected",
    "fetch_success",
    "rendered_page_success",
    "signal_boilerplate_ratio",
    "tokens_per_selected_source",
    "estimated_search_cost_usd",
    "estimated_fetch_cost_usd",
    "notes",
]

BINARY_FIELDS = {
    "relevant_at_1",
    "answer_source_present_at_5",
    "freshness_correct",
    "unsafe_url_rejected",
    "fetch_success",
    "rendered_page_success",
}
FIVE_SCALE_FIELDS = {
    "relevant_at_5",
    "authority_at_5",
    "primary_source_count_at_5",
    "korean_relevance",
    "korean_local_source_quality",
    "citation_metadata_quality",
    "signal_boilerplate_ratio",
}
NONNEGATIVE_FLOAT_FIELDS = {
    "tokens_per_selected_source",
    "estimated_search_cost_usd",
    "estimated_fetch_cost_usd",
}


class ScoreInputError(ValueError):
    pass


def _outside_repo(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(REPO_ROOT)
    except ValueError:
        return resolved
    raise ScoreInputError(f"{label} must stay outside the repository")


def _as_nonempty_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ScoreInputError(f"{field} must be a non-empty string")
    return value.strip()


def _as_optional_number(value: Any, field: str, *, nonnegative: bool = False) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScoreInputError(f"{field} must be numeric or null")
    number = float(value)
    if not math.isfinite(number):
        raise ScoreInputError(f"{field} must be finite")
    if nonnegative and number < 0:
        raise ScoreInputError(f"{field} must be nonnegative")
    return number


def _validate_result(item: Any, rank_expected: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ScoreInputError("result item must be an object")
    required = {"rank", "title", "url", "snippet", "published_at", "score"}
    if not required.issubset(item):
        raise ScoreInputError("normalized result item is missing required fields")
    if item["rank"] != rank_expected:
        raise ScoreInputError("result ranks must be contiguous from 1")
    title = _as_nonempty_str(item["title"], "result.title")
    url = _as_nonempty_str(item["url"], "result.url")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ScoreInputError("result.url must be an absolute http(s) URL")
    snippet = item["snippet"]
    if not isinstance(snippet, str):
        raise ScoreInputError("result.snippet must be a string")
    published = item["published_at"]
    if published is not None and not isinstance(published, str):
        raise ScoreInputError("result.published_at must be string or null")
    score = _as_optional_number(item["score"], "result.score")
    return {
        "rank": rank_expected,
        "title": title,
        "url": url,
        "snippet": snippet,
        "published_at": published.strip() if isinstance(published, str) else None,
        "score": score,
    }


def validate_record(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ScoreInputError("JSONL record must be an object")
    missing = RECORD_REQUIRED - set(raw)
    if missing:
        raise ScoreInputError(f"benchmark record missing fields: {', '.join(sorted(missing))}")
    if raw["benchmark_version"] != BENCHMARK_VERSION:
        raise ScoreInputError("benchmark_version mismatch")

    provider = _as_nonempty_str(raw["provider"], "provider")
    query_id = _as_nonempty_str(raw["query_id"], "query_id")
    language = _as_nonempty_str(raw["language"], "language")
    category = _as_nonempty_str(raw["category"], "category")
    freshness = _as_nonempty_str(raw["freshness"], "freshness")
    _as_nonempty_str(raw["query"], "query")  # validated but deliberately not retained by summaries
    distribution_gate = _as_nonempty_str(raw["distribution_gate"], "distribution_gate")

    status = raw["http_status"]
    if status is not None and (isinstance(status, bool) or not isinstance(status, int)):
        raise ScoreInputError("http_status must be integer or null")
    latency = _as_optional_number(raw["latency_ms"], "latency_ms", nonnegative=True)
    result_count = raw["result_count"]
    if isinstance(result_count, bool) or not isinstance(result_count, int) or result_count < 0 or result_count > 5:
        raise ScoreInputError("result_count must be an integer from 0 to 5")
    error = raw["error"]
    if error is not None and not isinstance(error, str):
        raise ScoreInputError("error must be string or null")
    results_raw = raw["results"]
    if not isinstance(results_raw, list) or len(results_raw) > 5:
        raise ScoreInputError("results must be a list of at most 5 items")
    results = [_validate_result(item, index) for index, item in enumerate(results_raw, start=1)]
    if len(results) != result_count:
        raise ScoreInputError("result_count does not match normalized results")

    success = error is None and isinstance(status, int) and 200 <= status < 300
    if success and latency is None:
        raise ScoreInputError("successful record requires latency_ms")
    if not success and results:
        raise ScoreInputError("failed record must not carry results")

    return {
        "provider": provider,
        "query_id": query_id,
        "language": language,
        "category": category,
        "freshness": freshness,
        "http_status": status,
        "latency_ms": latency,
        "result_count": result_count,
        "error": error,
        "distribution_gate": distribution_gate,
        "results": results,
        "success": success,
    }


def load_jsonl(paths: Iterable[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for source in paths:
        source = _outside_repo(source, "benchmark input")
        with source.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ScoreInputError(f"{source}:{line_number}: malformed JSON") from exc
                try:
                    record = validate_record(raw)
                except ScoreInputError as exc:
                    raise ScoreInputError(f"{source}:{line_number}: {exc}") from exc
                key = (record["provider"], record["query_id"])
                if key in seen:
                    raise ScoreInputError(f"duplicate provider/query_id: {key[0]} / {key[1]}")
                seen.add(key)
                records.append(record)
    if not records:
        raise ScoreInputError("no benchmark records found")
    return records


def _nearest_rank_percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return round(ordered[rank - 1], 3)


def _mean(values: Iterable[float]) -> float | None:
    data = list(values)
    return round(statistics.fmean(data), 6) if data else None


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def mechanical_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    successes = [record for record in records if record["success"]]
    failures = [record for record in records if not record["success"]]
    latencies = [record["latency_ms"] for record in successes if record["latency_ms"] is not None]
    result_items = [item for record in successes for item in record["results"]]
    domains = {
        urlsplit(item["url"]).hostname.lower()
        for item in result_items
        if urlsplit(item["url"]).hostname
    }
    http_429 = sum(record["error"] == "HTTP_429" or record["http_status"] == 429 for record in records)
    timeouts = sum(record["error"] == "TIMEOUT" for record in records)
    empty_success = sum(record["success"] and record["result_count"] == 0 for record in records)
    gate_values = sorted({record["distribution_gate"] for record in records})

    result_total = len(result_items)
    return {
        "queries_observed": total,
        "complete_60_query_run": total == EXPECTED_CORPUS_SIZE and len({record["query_id"] for record in records}) == EXPECTED_CORPUS_SIZE,
        "successful_queries": len(successes),
        "failed_queries": len(failures),
        "success_rate": _rate(len(successes), total),
        "provider_error_rate": _rate(len(failures), total),
        "http_429_count": http_429,
        "http_429_rate": _rate(http_429, total),
        "timeout_count": timeouts,
        "empty_success_count": empty_success,
        "empty_success_rate": _rate(empty_success, len(successes)),
        "latency_ms_p50": round(statistics.median(latencies), 3) if latencies else None,
        "latency_ms_p95": _nearest_rank_percentile(latencies, 0.95),
        "mean_results_per_success": _mean(float(record["result_count"]) for record in successes),
        "top5_fill_rate": _rate(result_total, len(successes) * 5),
        "normalized_result_count": result_total,
        "title_present_rate": _rate(sum(bool(item["title"]) for item in result_items), result_total),
        "snippet_present_rate": _rate(sum(bool(item["snippet"].strip()) for item in result_items), result_total),
        "published_at_present_rate": _rate(sum(bool(item["published_at"]) for item in result_items), result_total),
        "provider_score_present_rate": _rate(sum(item["score"] is not None for item in result_items), result_total),
        "unique_result_domains": len(domains),
        "distribution_gates": gate_values,
    }


def _parse_annotation_cell(row: dict[str, str], field: str) -> float | None:
    text = (row.get(field) or "").strip()
    if not text or text.upper() == "NA":
        return None
    try:
        value = float(text)
    except ValueError as exc:
        raise ScoreInputError(f"annotation {field} must be numeric or NA") from exc
    if field in BINARY_FIELDS and value not in {0.0, 1.0}:
        raise ScoreInputError(f"annotation {field} must be 0, 1, or NA")
    if field in FIVE_SCALE_FIELDS and not 0 <= value <= 5:
        raise ScoreInputError(f"annotation {field} must be 0..5 or NA")
    if field in NONNEGATIVE_FLOAT_FIELDS and value < 0:
        raise ScoreInputError(f"annotation {field} must be nonnegative or NA")
    return value


def load_annotations(path: Path, record_keys: set[tuple[str, str]]) -> dict[tuple[str, str], dict[str, Any]]:
    path = _outside_repo(path, "annotation input")
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames != ANNOTATION_COLUMNS:
            raise ScoreInputError("annotation TSV schema mismatch")
        output: dict[tuple[str, str], dict[str, Any]] = {}
        for line_number, row in enumerate(reader, start=2):
            provider = (row.get("provider") or "").strip()
            query_id = (row.get("query_id") or "").strip()
            key = (provider, query_id)
            if not provider or not query_id:
                raise ScoreInputError(f"annotation line {line_number}: provider/query_id required")
            if key not in record_keys:
                raise ScoreInputError(f"annotation line {line_number}: unknown provider/query_id")
            if key in output:
                raise ScoreInputError(f"annotation line {line_number}: duplicate provider/query_id")
            parsed = {field: _parse_annotation_cell(row, field) for field in BINARY_FIELDS | FIVE_SCALE_FIELDS | NONNEGATIVE_FLOAT_FIELDS}
            parsed["notes_present"] = bool((row.get("notes") or "").strip())
            output[key] = parsed
    return output


def annotation_summary(records: list[dict[str, Any]], annotations: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    rows = [annotations[(record["provider"], record["query_id"])] for record in records if (record["provider"], record["query_id"]) in annotations]

    def values(field: str) -> list[float]:
        return [row[field] for row in rows if row.get(field) is not None]

    search_costs = values("estimated_search_cost_usd")
    fetch_costs = values("estimated_fetch_cost_usd")
    return {
        "annotated_queries": len(rows),
        "annotation_coverage": _rate(len(rows), len(records)),
        "relevant_at_1_rate": _mean(values("relevant_at_1")),
        "relevant_at_5_mean": _mean(values("relevant_at_5")),
        "answer_source_present_at_5_rate": _mean(values("answer_source_present_at_5")),
        "authority_at_5_mean": _mean(values("authority_at_5")),
        "primary_source_count_at_5_mean": _mean(values("primary_source_count_at_5")),
        "primary_source_rate_at_5": _mean(value / 5.0 for value in values("primary_source_count_at_5")),
        "freshness_correct_rate": _mean(values("freshness_correct")),
        "korean_relevance_mean": _mean(values("korean_relevance")),
        "korean_local_source_quality_mean": _mean(values("korean_local_source_quality")),
        "citation_metadata_quality_mean": _mean(values("citation_metadata_quality")),
        "unsafe_url_rejected_rate": _mean(values("unsafe_url_rejected")),
        "fetch_success_rate": _mean(values("fetch_success")),
        "rendered_page_success_rate": _mean(values("rendered_page_success")),
        "signal_boilerplate_ratio_mean": _mean(values("signal_boilerplate_ratio")),
        "tokens_per_selected_source_mean": _mean(values("tokens_per_selected_source")),
        "estimated_search_cost_usd_total": round(sum(search_costs), 8) if search_costs else None,
        "estimated_search_cost_usd_per_annotated_query": _mean(search_costs),
        "estimated_fetch_cost_usd_total": round(sum(fetch_costs), 8) if fetch_costs else None,
        "estimated_fetch_cost_usd_per_annotated_query": _mean(fetch_costs),
        "estimated_total_retrieval_cost_usd_per_annotated_query": _mean(
            (row.get("estimated_search_cost_usd") or 0.0) + (row.get("estimated_fetch_cost_usd") or 0.0)
            for row in rows
            if row.get("estimated_search_cost_usd") is not None or row.get("estimated_fetch_cost_usd") is not None
        ),
        "notes_present_count": sum(row["notes_present"] for row in rows),
    }


def build_summary(records: list[dict[str, Any]], annotations: dict[tuple[str, str], dict[str, Any]] | None = None) -> dict[str, Any]:
    by_provider: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_provider[record["provider"]].append(record)

    providers: dict[str, Any] = {}
    for provider in sorted(by_provider):
        provider_records = by_provider[provider]
        entry: dict[str, Any] = {
            "mechanical": mechanical_summary(provider_records),
            "by_language": {
                language: mechanical_summary([record for record in provider_records if record["language"] == language])
                for language in sorted({record["language"] for record in provider_records})
            },
            "by_category": {
                category: mechanical_summary([record for record in provider_records if record["category"] == category])
                for category in sorted({record["category"] for record in provider_records})
            },
        }
        if annotations is not None:
            entry["human_quality"] = annotation_summary(provider_records, annotations)
        providers[provider] = entry

    return {
        "benchmark_version": BENCHMARK_VERSION,
        "summary_type": "AGGREGATE_ONLY_NO_RAW_PROVIDER_RESULTS",
        "providers": providers,
        "human_quality_inference": "NEVER_AUTOMATIC",
        "production_mutation": 0,
    }


def write_annotation_template(records: list[dict[str, Any]], destination: Path) -> None:
    destination = _outside_repo(destination, "annotation template output")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ANNOTATION_COLUMNS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for record in sorted(records, key=lambda item: (item["provider"], item["query_id"])):
            row = {column: "" for column in ANNOTATION_COLUMNS}
            row["provider"] = record["provider"]
            row["query_id"] = record["query_id"]
            writer.writerow(row)


def _write_json(summary: dict[str, Any], output: Path | None) -> None:
    text = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output is None:
        sys.stdout.write(text)
        return
    destination = _outside_repo(output, "score output")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", type=Path, required=True, help="runner JSONL outside repository; repeatable")
    parser.add_argument("--annotations", type=Path, help="optional human annotation TSV outside repository")
    parser.add_argument("--write-annotation-template", type=Path, help="write blank annotation TSV outside repository and exit")
    parser.add_argument("--output", type=Path, help="aggregate JSON output outside repository; defaults to stdout")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    records = load_jsonl(args.input)
    if args.write_annotation_template:
        write_annotation_template(records, args.write_annotation_template)
        return 0
    annotations = None
    if args.annotations:
        annotations = load_annotations(args.annotations, {(record["provider"], record["query_id"]) for record in records})
    _write_json(build_summary(records, annotations), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
