from __future__ import annotations

import base64
import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/experiments/benchmark_padiem_fetch_providers.py"
spec = importlib.util.spec_from_file_location("fetch_benchmark", SCRIPT)
benchmark = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = benchmark
spec.loader.exec_module(benchmark)

CORPUS = ROOT / "docs/experiments/PADIEM_FETCH_PROVIDER_BENCHMARK_URLS_v1.tsv"


def _case(url_id: str = "EN-EDGE-01"):
    return next(case for case in benchmark.load_corpus(CORPUS) if case.id == url_id)


def _fixture(payload: dict, *, status: int = 200, encoding: str = "utf-8") -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode(encoding)
    return {
        "url_id": "x",
        "status": status,
        "headers": {"content-type": "application/json; charset=utf-8"},
        "body_b64": base64.b64encode(body).decode("ascii"),
    }


def test_frozen_fetch_corpus_shape():
    cases = benchmark.load_corpus(CORPUS)
    assert len(cases) == 16
    assert len({case.id for case in cases}) == 16
    assert sum(case.language == "ko" for case in cases) == 6
    assert sum(case.language == "en" for case in cases) == 10
    assert all(benchmark._safe_url(case.url) for case in cases)


def test_provider_inventory_is_fixed_and_non_secret(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "secret-that-must-not-leak")
    assert set(benchmark.PROVIDERS) == {"tinyfish", "firecrawl", "daum"}
    assert benchmark.PROVIDERS["tinyfish"].fetch_supported is True
    assert benchmark.PROVIDERS["firecrawl"].fetch_supported is True
    assert benchmark.PROVIDERS["daum"].fetch_supported is False
    public = benchmark.provider_public_metadata(benchmark.PROVIDERS["firecrawl"])
    assert public["credential_env"] == "FIRECRAWL_API_KEY"
    assert public["credential_configured"] is True
    assert "secret-that-must-not-leak" not in json.dumps(public)


def test_tinyfish_fetch_request_contract():
    case = _case()
    spec = benchmark.PROVIDERS["tinyfish"]
    method, url, headers, body = benchmark._request_for(spec, case, "tf-key")
    assert method == "POST"
    assert url == "https://api.fetch.tinyfish.ai"
    assert headers["X-API-Key"] == "tf-key"
    # Published Fetch API field is `urls` (array), not `url`.
    assert json.loads(body) == {"urls": [case.url]}


def test_tinyfish_documented_results_envelope_is_measured():
    case = _case()
    fixture = _fixture(
        {
            "results": [
                {
                    "url": case.url,
                    "final_url": "https://www.example.com/final",
                    "title": "Doc title",
                    "description": "short description",
                    "language": "en",
                    "format": "markdown",
                    "text": "# Doc title\n\nBody text.",
                }
            ],
            "errors": [],
        }
    )
    record = benchmark.run_case(benchmark.PROVIDERS["tinyfish"], case, fixture=fixture)
    assert record["error"] is None
    assert record["content_chars"] > 0
    assert record["final_url"] == "https://www.example.com/final"
    assert record["title"] == "Doc title"


def test_firecrawl_fetch_request_contract():
    case = _case()
    spec = benchmark.PROVIDERS["firecrawl"]
    method, url, headers, body = benchmark._request_for(spec, case, "fc-key")
    assert method == "POST"
    assert url == "https://api.firecrawl.dev/v2/scrape"
    assert headers["Authorization"] == "Bearer fc-key"
    assert json.loads(body) == {"url": case.url, "formats": ["markdown"], "onlyMainContent": True}


def test_daum_fetch_is_reported_unsupported():
    case = _case()
    record = benchmark.run_case(benchmark.PROVIDERS["daum"], case, fixture={"status": 200, "body": "{}"})
    assert record["error"] == "FETCH_UNSUPPORTED"
    assert record["content_chars"] == 0
    assert record["latency_ms"] is None


def test_offline_replay_measures_content_fidelity():
    case = _case()
    fixture = _fixture({"data": {"markdown": "page body content", "title": "T", "url": "https://www.example.com/final"}})
    record = benchmark.run_case(benchmark.PROVIDERS["tinyfish"], case, fixture=fixture)
    assert record["error"] is None
    assert record["content_chars"] == len("page body content")
    assert record["final_url"] == "https://www.example.com/final"
    assert record["title"] == "T"
    assert record["response_bytes"] > 0
    assert record["latency_ms"] is None  # never estimated offline


def test_offline_replay_never_calls_network(monkeypatch):
    case = _case()
    monkeypatch.setenv("TINYFISH_API_KEY", "tf-key")

    def _boom(*args, **kwargs):
        raise AssertionError("network must not be used during offline replay")

    fixture = _fixture({"data": {"markdown": "offline"}})
    record = benchmark.run_case(benchmark.PROVIDERS["tinyfish"], case, transport=_boom, fixture=fixture)
    assert record["content_chars"] == len("offline")


def test_missing_credential_fails_before_transport(monkeypatch):
    monkeypatch.delenv("TINYFISH_API_KEY", raising=False)
    calls = []

    def transport(*args, **kwargs):
        calls.append(args)
        raise AssertionError("transport must not run without a credential")

    with pytest.raises(benchmark.MissingCredential):
        benchmark.run_case(benchmark.PROVIDERS["tinyfish"], _case(), transport=transport)
    assert calls == []


def test_http_429_is_distinct(monkeypatch):
    monkeypatch.setenv("TINYFISH_API_KEY", "tf-key")

    def transport(*args, **kwargs):
        raise benchmark.BenchmarkHttpError(429)

    with pytest.raises(benchmark.BenchmarkHttpError) as info:
        benchmark.run_case(benchmark.PROVIDERS["tinyfish"], _case(), transport=transport)
    assert info.value.code == "HTTP_429"


def test_offline_replay_handles_non_utf8_body():
    case = _case()
    fixture = _fixture({"data": {"markdown": "안녕하세요 본문"}}, encoding="cp949")
    record = benchmark.run_case(benchmark.PROVIDERS["tinyfish"], case, fixture=fixture)
    assert record["decode_ok"] is True
    assert record["payload_encoding"] == "cp949"
    assert record["content_chars"] == len("안녕하세요 본문")


def test_offline_replay_bounds_response_size():
    case = _case()
    huge = base64.b64encode(b"x" * (benchmark.MAX_RESPONSE_BYTES + 10)).decode("ascii")
    with pytest.raises(benchmark.ResponseTooLarge):
        benchmark.run_case(
            benchmark.PROVIDERS["tinyfish"], case,
            fixture={"url_id": "x", "status": 200, "headers": {}, "body_b64": huge},
        )


def test_unknown_fetch_shape_fails_closed():
    case = _case()
    with pytest.raises(benchmark.MalformedResponse):
        benchmark.run_case(
            benchmark.PROVIDERS["tinyfish"], case,
            fixture=_fixture({"results": [{"unexpected": "shape"}]}),
        )


def test_cross_provider_fidelity_fingerprint_is_comparable():
    case = _case()
    tinyfish = benchmark.run_case(
        benchmark.PROVIDERS["tinyfish"], case,
        fixture=_fixture({"data": {"markdown": "shared body", "url": case.url}}),
    )
    firecrawl = benchmark.run_case(
        benchmark.PROVIDERS["firecrawl"], case,
        fixture=_fixture({"data": {"markdown": "shared body", "metadata": {"sourceURL": case.url}}}),
    )
    assert tinyfish["content_sha256"] == firecrawl["content_sha256"]
    assert tinyfish["final_url"] == firecrawl["final_url"] == case.url


def test_private_url_is_rejected_by_the_corpus_guard():
    assert benchmark._safe_url("http://127.0.0.1/private") == ""
    assert benchmark._safe_url("https://user:pass@example.com/x") == ""
    assert benchmark._safe_url("file:///etc/passwd") == ""
    assert benchmark._safe_url("https://example.com/ok") == "https://example.com/ok"


def test_dry_run_never_calls_network(capsys, monkeypatch):
    monkeypatch.delenv("TINYFISH_API_KEY", raising=False)
    exit_code = benchmark.main(["--provider", "tinyfish", "--corpus", str(CORPUS)])
    assert exit_code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "DRY_RUN_NETWORK_DENIED"
    assert out["request_count"] == 16
    assert out["retries"] == 0
    assert out["production_mutation"] == 0


def test_live_output_cannot_be_written_inside_repository():
    with pytest.raises(ValueError):
        benchmark._output_handle(str(ROOT / "tmp_fetch_out.jsonl"))


def test_allow_network_and_fixture_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        benchmark.main(["--provider", "tinyfish", "--allow-network", "--fixture", "x.jsonl"])
