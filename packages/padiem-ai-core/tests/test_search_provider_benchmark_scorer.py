from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/experiments/score_padiem_search_benchmark.py"
spec = importlib.util.spec_from_file_location("search_benchmark_scorer", SCRIPT)
scorer = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = scorer
spec.loader.exec_module(scorer)


def raw_record(
    *,
    provider="brave",
    query_id="Q1",
    language="en",
    category="current_tech_news",
    freshness="CURRENT",
    status=200,
    latency=100.0,
    error=None,
    result_count=1,
    distribution_gate="internal_results_only",
):
    results = []
    if error is None and status is not None and 200 <= status < 300:
        results = [
            {
                "rank": index,
                "title": f"Title {index}",
                "url": f"https://example{index}.com/{query_id}",
                "snippet": f"Snippet {index}",
                "published_at": "2026-09-03" if index == 1 else None,
                "score": 0.9 if index == 1 else None,
            }
            for index in range(1, result_count + 1)
        ]
    return {
        "benchmark_version": scorer.BENCHMARK_VERSION,
        "provider": provider,
        "query_id": query_id,
        "language": language,
        "category": category,
        "freshness": freshness,
        "query": "raw query text must not enter aggregate summary",
        "http_status": status,
        "latency_ms": latency,
        "result_count": result_count if results else 0,
        "error": error,
        "distribution_gate": distribution_gate,
        "results": results,
    }


def write_jsonl(path: Path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_validate_record_drops_raw_query_from_normalized_record():
    record = scorer.validate_record(raw_record())
    assert record["provider"] == "brave"
    assert "query" not in record
    assert record["success"] is True


def test_load_jsonl_rejects_inputs_inside_repository(tmp_path):
    repo_path = ROOT / "docs/experiments/should-not-exist-live.jsonl"
    with pytest.raises(scorer.ScoreInputError, match="outside the repository"):
        scorer.load_jsonl([repo_path])


def test_load_jsonl_rejects_duplicate_provider_query_ids(tmp_path):
    path = tmp_path / "dup.jsonl"
    row = raw_record()
    write_jsonl(path, [row, row])
    with pytest.raises(scorer.ScoreInputError, match="duplicate provider/query_id"):
        scorer.load_jsonl([path])


def test_failed_record_cannot_carry_results():
    row = raw_record(status=429, latency=None, error="HTTP_429", result_count=0)
    row["results"] = [{"rank": 1, "title": "x", "url": "https://example.com", "snippet": "x", "published_at": None, "score": None}]
    row["result_count"] = 1
    with pytest.raises(scorer.ScoreInputError, match="failed record must not carry results"):
        scorer.validate_record(row)


def test_mechanical_summary_computes_latency_errors_and_fill_rate():
    rows = [
        scorer.validate_record(raw_record(query_id="Q1", latency=100, result_count=5)),
        scorer.validate_record(raw_record(query_id="Q2", latency=200, result_count=3)),
        scorer.validate_record(raw_record(query_id="Q3", latency=300, result_count=0)),
        scorer.validate_record(raw_record(query_id="Q4", status=429, latency=None, error="HTTP_429", result_count=0)),
    ]
    summary = scorer.mechanical_summary(rows)
    assert summary["queries_observed"] == 4
    assert summary["successful_queries"] == 3
    assert summary["failed_queries"] == 1
    assert summary["success_rate"] == 0.75
    assert summary["http_429_count"] == 1
    assert summary["latency_ms_p50"] == 200
    assert summary["latency_ms_p95"] == 300
    assert summary["empty_success_count"] == 1
    assert summary["top5_fill_rate"] == pytest.approx(8 / 15)


def test_build_summary_has_provider_category_language_breakdown_and_no_raw_text():
    records = [
        scorer.validate_record(raw_record(query_id="Q1", language="ko", category="korean_local_daily_life")),
        scorer.validate_record(raw_record(query_id="Q2", language="en", category="official_documentation")),
    ]
    summary = scorer.build_summary(records)
    brave = summary["providers"]["brave"]
    assert set(brave["by_language"]) == {"en", "ko"}
    assert set(brave["by_category"]) == {"korean_local_daily_life", "official_documentation"}
    encoded = json.dumps(summary)
    assert "raw query text" not in encoded
    assert summary["human_quality_inference"] == "NEVER_AUTOMATIC"


def annotation_row(provider="brave", query_id="Q1", **overrides):
    row = {column: "" for column in scorer.ANNOTATION_COLUMNS}
    row.update(
        {
            "provider": provider,
            "query_id": query_id,
            "relevant_at_1": "1",
            "relevant_at_5": "4",
            "answer_source_present_at_5": "1",
            "authority_at_5": "5",
            "primary_source_count_at_5": "3",
            "freshness_correct": "1",
            "korean_relevance": "NA",
            "korean_local_source_quality": "NA",
            "citation_metadata_quality": "4",
            "unsafe_url_rejected": "1",
            "fetch_success": "NA",
            "rendered_page_success": "NA",
            "signal_boilerplate_ratio": "4",
            "tokens_per_selected_source": "120",
            "estimated_search_cost_usd": "0.002",
            "estimated_fetch_cost_usd": "0",
            "notes": "reviewed",
        }
    )
    row.update(overrides)
    return row


def write_annotations(path: Path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=scorer.ANNOTATION_COLUMNS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def test_annotation_schema_and_aggregation_are_explicit(tmp_path):
    record = scorer.validate_record(raw_record())
    path = tmp_path / "annotations.tsv"
    write_annotations(path, [annotation_row()])
    annotations = scorer.load_annotations(path, {("brave", "Q1")})
    quality = scorer.annotation_summary([record], annotations)
    assert quality["annotation_coverage"] == 1.0
    assert quality["relevant_at_1_rate"] == 1.0
    assert quality["relevant_at_5_mean"] == 4.0
    assert quality["authority_at_5_mean"] == 5.0
    assert quality["primary_source_rate_at_5"] == 0.6
    assert quality["estimated_search_cost_usd_total"] == 0.002
    assert quality["estimated_total_retrieval_cost_usd_per_annotated_query"] == 0.002


def test_annotation_rejects_invalid_human_score(tmp_path):
    path = tmp_path / "annotations.tsv"
    write_annotations(path, [annotation_row(relevant_at_1="2")])
    with pytest.raises(scorer.ScoreInputError, match="must be 0, 1, or NA"):
        scorer.load_annotations(path, {("brave", "Q1")})


def test_annotation_template_contains_ids_only_not_queries(tmp_path):
    records = [scorer.validate_record(raw_record(query_id="Q1")), scorer.validate_record(raw_record(query_id="Q2"))]
    destination = tmp_path / "template.tsv"
    scorer.write_annotation_template(records, destination)
    text = destination.read_text(encoding="utf-8")
    assert "provider\tquery_id" in text
    assert "brave\tQ1" in text
    assert "raw query text" not in text


def test_annotation_and_score_outputs_must_stay_outside_repository(tmp_path):
    records = [scorer.validate_record(raw_record())]
    with pytest.raises(scorer.ScoreInputError, match="outside the repository"):
        scorer.write_annotation_template(records, ROOT / "docs/experiments/annotations.tsv")
    with pytest.raises(scorer.ScoreInputError, match="outside the repository"):
        scorer._write_json(scorer.build_summary(records), ROOT / "docs/experiments/score.json")


def test_cli_aggregate_output_is_redacted(tmp_path, capsys):
    input_path = tmp_path / "results.jsonl"
    write_jsonl(input_path, [raw_record()])
    rc = scorer.main(["--input", str(input_path)])
    assert rc == 0
    output = capsys.readouterr().out
    assert "AGGREGATE_ONLY_NO_RAW_PROVIDER_RESULTS" in output
    assert "raw query text" not in output
    assert '"successful_queries": 1' in output
