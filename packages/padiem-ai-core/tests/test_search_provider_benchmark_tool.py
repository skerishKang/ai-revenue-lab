from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/experiments/benchmark_padiem_search_providers.py"
spec = importlib.util.spec_from_file_location("search_benchmark", SCRIPT)
benchmark = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = benchmark
spec.loader.exec_module(benchmark)


def test_frozen_corpus_shape():
    cases = benchmark.load_corpus(ROOT / "docs/experiments/PADIEM_SEARCH_PROVIDER_BENCHMARK_CORPUS_v1.tsv")
    assert len(cases) == 60
    assert sum(case.language == "ko" for case in cases) == 40
    assert sum(case.language == "en" for case in cases) == 20
    assert len({case.id for case in cases}) == 60


def test_provider_inventory_is_fixed_and_non_secret(monkeypatch):
    monkeypatch.setenv("PARALLEL_API_KEY", "secret-that-must-not-leak")
    assert set(benchmark.PROVIDERS) == {
        "tinyfish", "parallel", "brave", "tavily", "exa", "firecrawl", "daum"
    }
    public = benchmark.provider_public_metadata(benchmark.PROVIDERS["parallel"])
    assert public["credential_env"] == "PARALLEL_API_KEY"
    assert public["credential_configured"] is True
    assert "secret-that-must-not-leak" not in json.dumps(public)


@pytest.mark.parametrize(
    ("provider", "payload", "expected_url", "expected_snippet"),
    [
        (
            "tinyfish",
            {"results": [{"title": "Tiny", "url": "https://example.com/t", "snippet": "tiny snippet", "date": "2026-09-03"}]},
            "https://example.com/t",
            "tiny snippet",
        ),
        (
            "brave",
            {"web": {"results": [{"title": "Brave", "url": "https://example.com/b", "description": "brave snippet"}]}},
            "https://example.com/b",
            "brave snippet",
        ),
        (
            "parallel",
            {"results": [{"title": "Parallel", "url": "https://example.com/p", "excerpts": ["one", "two"], "publish_date": "2026-09-03"}]},
            "https://example.com/p",
            "one two",
        ),
        (
            "tavily",
            {"results": [{"title": "Tavily", "url": "https://example.com/v", "content": "tavily content", "score": 0.9}]},
            "https://example.com/v",
            "tavily content",
        ),
        (
            "exa",
            {"results": [{"title": "Exa", "url": "https://example.com/e", "highlights": ["exa highlight"], "publishedDate": "2026-09-03"}]},
            "https://example.com/e",
            "exa highlight",
        ),
        (
            "firecrawl",
            {"data": {"web": [{"title": "Firecrawl", "url": "https://example.com/f", "description": "firecrawl text"}]}},
            "https://example.com/f",
            "firecrawl text",
        ),
        (
            "daum",
            {"documents": [{"title": "<b>Daum</b>", "url": "https://example.com/d", "contents": "<b>daum</b> text", "datetime": "2026-09-03T00:00:00Z"}]},
            "https://example.com/d",
            "daum text",
        ),
    ],
)
def test_provider_parsers_normalize_without_raw_payload(provider, payload, expected_url, expected_snippet):
    result = benchmark._normalize_items(provider, payload, limit=5)
    assert len(result) == 1
    assert result[0].rank == 1
    assert result[0].url == expected_url
    assert result[0].snippet == expected_snippet


def test_unsafe_result_urls_are_dropped():
    payload = {
        "results": [
            {"title": "bad", "url": "file:///etc/passwd", "snippet": "x"},
            {"title": "credentials", "url": "https://user:pass@example.com/x", "snippet": "x"},
            {"title": "good", "url": "https://example.com/good", "snippet": "ok"},
        ]
    }
    results = benchmark._normalize_items("tinyfish", payload)
    assert [item.url for item in results] == ["https://example.com/good"]


def test_missing_credential_fails_before_transport(monkeypatch):
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    calls = []

    def transport(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("transport must not be called")

    case = benchmark.QueryCase("Q", "en", "test", "CURRENT", "test query")
    with pytest.raises(benchmark.MissingCredential):
        benchmark.run_case(benchmark.PROVIDERS["brave"], case, transport=transport)
    assert calls == []


def test_http_429_is_distinct(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "not-logged")

    def transport(*args, **kwargs):
        raise benchmark.BenchmarkHttpError(429)

    case = benchmark.QueryCase("Q", "en", "test", "CURRENT", "test query")
    with pytest.raises(benchmark.BenchmarkHttpError) as exc:
        benchmark.run_case(benchmark.PROVIDERS["tavily"], case, transport=transport)
    assert exc.value.code == "HTTP_429"


def test_dry_run_never_calls_network(monkeypatch, capsys):
    monkeypatch.setenv("EXA_API_KEY", "secret")
    monkeypatch.setattr(benchmark, "_perform_request", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network")))
    rc = benchmark.main(["--provider", "exa", "--max-queries", "2"])
    assert rc == 0
    output = capsys.readouterr().out
    assert "DRY_RUN_NETWORK_DENIED" in output
    assert "secret" not in output
    assert '"request_count": 2' in output


def test_live_output_cannot_be_written_inside_repository():
    repo_output = ROOT / "docs/experiments/provider-live-results.jsonl"
    with pytest.raises(ValueError, match="outside the repository"):
        benchmark._output_handle(str(repo_output))


def test_parallel_distribution_gate_is_fail_closed():
    assert benchmark.PROVIDERS["parallel"].distribution_gate == "internal_only_without_written_benchmark_consent"
