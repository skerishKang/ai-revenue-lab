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


@pytest.fixture(autouse=True)
def _deny_network(monkeypatch):
    """Lowest-level outbound-network deny, installed before every test here.

    Patching a call site whose default argument already captured the network
    function is not enough — one unintended outbound POST slipped through that
    way during development — so the outbound choke points are denied directly.
    ``socket.socket`` itself is left alone because asyncio's event loop builds
    its self-pipe with ``socket.socketpair``.
    """
    import socket

    def _deny(*args, **kwargs):
        raise AssertionError("network access is denied in search benchmark tests")

    monkeypatch.setattr(socket, "create_connection", _deny)
    monkeypatch.setattr(socket, "getaddrinfo", _deny)
    monkeypatch.setattr(benchmark, "urlopen", _deny)
    yield


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
            {"title": "local", "url": "http://127.0.0.1/private", "snippet": "x"},
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


def test_http_402_free_quota_exhaustion_is_distinct(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "not-logged")

    def transport(*args, **kwargs):
        raise benchmark.BenchmarkHttpError(402)

    case = benchmark.QueryCase("Q", "en", "test", "CURRENT", "test query")
    with pytest.raises(benchmark.BenchmarkHttpError) as exc:
        benchmark.run_case(benchmark.PROVIDERS["tavily"], case, transport=transport)
    assert exc.value.code == "HTTP_402"
    assert exc.value.code != "HTTP_4XX"


def test_live_run_aborts_on_free_quota_exhaustion(monkeypatch, tmp_path):
    monkeypatch.setenv("TAVILY_API_KEY", "not-logged")
    calls = []

    def raise_402(method, url, headers, body, timeout):
        calls.append(url)
        raise benchmark.BenchmarkHttpError(402)

    # Transport-injection through the real `run_case` path (not by patching
    # `run_case` itself); the autouse fixture denies sockets/urlopen underneath.
    monkeypatch.setattr(benchmark, "_perform_request", raise_402)
    output = tmp_path / "search-live.jsonl"
    rc = benchmark.main(
        [
            "--provider", "tavily",
            "--query-id", "KR-NEWS-01", "--query-id", "KR-NEWS-02",
            "--allow-network", "--output", str(output),
        ]
    )
    assert rc == 2
    assert len(calls) == 1  # the run stops on the first 402; no second request


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


TINYFISH_SNIPPET_FIELDS = [
    ("snippet", {"snippet": "core snippet field"}),
    ("description", {"description": "core description field"}),
    ("summary", {"summary": "core summary field"}),
    ("content", {"content": "core content field"}),
]


@pytest.mark.parametrize(("key", "fields"), TINYFISH_SNIPPET_FIELDS)
def test_tinyfish_benchmark_reads_every_key_the_core_provider_accepts(key, fields):
    payload = {"results": [{"title": "Tiny", "url": "https://example.com/t", **fields}]}
    result = benchmark._normalize_items("tinyfish", payload, limit=5)
    assert [item.snippet for item in result] == [fields[key]]


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"snippet": "s", "description": "d", "summary": "u", "content": "c"}, "s"),
        ({"description": "d", "summary": "u", "content": "c"}, "d"),
        ({"summary": "u", "content": "c"}, "u"),
        ({"content": "c"}, "c"),
        ({"snippet": "", "description": "", "summary": "u"}, "u"),
        ({"snippet": None, "description": 0, "content": "c"}, "c"),
    ],
)
def test_tinyfish_benchmark_snippet_precedence_matches_the_core_provider(fields, expected):
    payload = {"results": [{"title": "Tiny", "url": "https://example.com/t", **fields}]}
    result = benchmark._normalize_items("tinyfish", payload, limit=5)
    assert [item.snippet for item in result] == [expected]


def test_tinyfish_benchmark_declares_the_expected_snippet_key_order():
    assert benchmark.TINYFISH_SNIPPET_KEYS == ("snippet", "description", "summary", "content")


def test_tinyfish_benchmark_precedence_matches_the_core_provider_behaviourally():
    import asyncio

    import httpx

    from padiem_ai_core.web_runtime import TinyFishWebProvider, WebRuntimeConfig

    payload = {"results": [
        {"title": "A", "url": "https://example.com/a", "summary": "only summary"},
        {"title": "B", "url": "https://example.com/b", "content": "only content"},
        {"title": "C", "url": "https://example.com/c", "snippet": "s", "description": "d",
         "summary": "u", "content": "c"},
        {"title": "D", "url": "https://example.com/d", "text": "unsupported key only"},
    ]}

    served = []

    class _StubTransport(httpx.AsyncBaseTransport):
        """The only way this test can answer; an unstubbed client would raise instead."""

        async def handle_async_request(self, request):
            served.append(request)
            return httpx.Response(200, json=payload)

    def _blocked(*args, **kwargs):
        raise AssertionError("no real network transport is allowed in this test")

    original_client = httpx.AsyncClient

    def _guard(*args, **kwargs):
        if kwargs.get("transport") is None:
            _blocked()
        return original_client(*args, **kwargs)

    httpx.AsyncClient = _guard
    try:
        core = asyncio.run(TinyFishWebProvider(
            WebRuntimeConfig(provider="tinyfish", tinyfish_api_key="not-a-real-credential"),
            transport=_StubTransport(),
        ).search("q"))
    finally:
        httpx.AsyncClient = original_client

    assert len(served) == 1, "the stub transport must be the only responder"
    assert served[0].url.host == "api.search.tinyfish.ai"
    runner = benchmark._normalize_items("tinyfish", payload, limit=5)
    assert [item.snippet for item in runner] == [evidence.snippet for evidence in core]
    assert [item.snippet for item in runner] == ["only summary", "only content", "s", ""]


@pytest.mark.parametrize(
    "fields",
    [{"text": "unsupported key only"}, {"title": "no snippet field"}, {}],
)
def test_tinyfish_benchmark_keeps_the_row_with_an_empty_snippet_on_unknown_or_missing_keys(fields):
    payload = {"results": [{**fields, "url": "https://example.com/t"}]}
    result = benchmark._normalize_items("tinyfish", payload, limit=5)
    assert len(result) == 1
    assert result[0].snippet == ""
    assert result[0].url == "https://example.com/t"
    assert result[0].title == (fields.get("title") or "https://example.com/t")


def test_tinyfish_published_and_score_metadata_stay_unchanged():
    payload = {"results": [
        {"title": "T1", "url": "https://example.com/t1", "summary": "u", "date": "2026-09-03", "score": 0.5},
        {"title": "T2", "url": "https://example.com/t2", "content": "c", "published_date": "2026-09-04"},
    ]}
    result = benchmark._normalize_items("tinyfish", payload, limit=5)
    assert [(item.rank, item.snippet) for item in result] == [(1, "u"), (2, "c")]
    assert [(item.published_at, item.score) for item in result] == [("2026-09-03", 0.5), ("2026-09-04", None)]


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"snippet": "s", "description": "d"}, "s"),
        ({"description": "d"}, "d"),
        ({"summary": "u", "content": "c"}, ""),
    ],
)
def test_other_providers_keep_their_existing_snippet_branch(fields, expected):
    payload = {"web": {"results": [{"title": "Brave", "url": "https://example.com/b", **fields}]}}
    result = benchmark._normalize_items("brave", payload, limit=5)
    assert [item.snippet for item in result] == [expected]
