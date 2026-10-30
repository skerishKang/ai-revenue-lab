"""Contract tests for the #5895 ④ post-deploy real model call (#5895).

The verdict table is the whole contract: a real answer passes, a provider-side
limit passes with a marker, and everything else - other status, malformed body,
empty text, transport failure, oversized body - fails. The request must carry no
model choice of its own, because the declared grade routing is what is being
proven, and no provider text or credential may ever reach the log.
"""

from __future__ import annotations

import importlib.util
import json
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/b14_real_model_call_smoke.py"

spec = importlib.util.spec_from_file_location("b14_real_model_call_smoke", SCRIPT)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def _ok(model="google/gemini-3.1-flash-lite", text="pong"):
    body = {
        "id": "chatcmpl-synthetic",
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}}],
        "business14": {"model_route": "b14/auto"},
    }
    return 200, json.dumps(body).encode("utf-8")


def _transport(status, raw):
    def call(url, body, timeout):
        call.calls.append((url, body, timeout))
        return status, raw
    call.calls = []
    return call


def test_a_real_answer_is_a_pass_and_names_the_resolved_model() -> None:
    status, raw = _ok()
    transport = _transport(status, raw)
    verdict, model = smoke.run(base_url="https://b14.example.test", transport=transport)
    assert (verdict, model) == ("PASS", "google/gemini-3.1-flash-lite")


@pytest.mark.parametrize("limit", sorted(smoke.PROVIDER_LIMIT_STATUSES))
def test_provider_limit_statuses_pass_with_a_marker(limit) -> None:
    verdict, model = smoke.run(
        base_url="https://b14.example.test",
        transport=_transport(limit, json.dumps({"error": {"code": "rate_limited"}}).encode()),
    )
    assert verdict == "PASS_PROVIDER_LIMIT"
    assert model == "b14/auto" or model.startswith("google/")


def test_any_other_status_fails() -> None:
    for status in (400, 401, 403, 404, 500, 502, 504):
        assert smoke.run(base_url="https://b14.example.test",
                         transport=_transport(status, b"{}"))[0] == "FAIL"


def test_malformed_or_truncated_body_fails_rather_than_passing() -> None:
    assert smoke.run(base_url="https://b14.example.test",
                     transport=_transport(200, b"{not json"))[0] == "FAIL"
    assert smoke.run(base_url="https://b14.example.test",
                     transport=_transport(200, b""))[0] == "FAIL"


def test_a_200_without_an_answer_text_fails() -> None:
    for payload in ({"model": "m", "choices": []},
                    {"model": "m", "choices": [{"message": {"content": "   "}}]},
                    {"model": "m"}):
        assert smoke.run(base_url="https://b14.example.test",
                         transport=_transport(200, json.dumps(payload).encode()))[0] == "FAIL"


def test_a_transport_failure_is_a_fail_not_a_provider_limit() -> None:
    def call(url, body, timeout):
        raise urllib.error.URLError("connection reset")
    assert smoke.run(base_url="https://b14.example.test", transport=call)[0] == "FAIL"


def test_an_oversized_response_fails() -> None:
    assert smoke.run(
        base_url="https://b14.example.test",
        transport=_transport(200, b"x" * (smoke.MAX_RESPONSE_BYTES + 1)),
    )[0] == "FAIL"


def test_the_request_declares_a_tier_and_names_no_model_of_its_own() -> None:
    body = json.loads(smoke.request_body())
    assert body["model"] == smoke.active_route_for(smoke.ProductTierLabel.FREE).model_id
    assert body["business14"]["product_tier"] == smoke.PRODUCT_TIER
    assert body["business14"]["max_retries"] == 0
    assert 0 < body["max_tokens"] <= 64
    assert set(body) == {"model", "messages", "max_tokens", "business14"}


def test_the_unsafe_model_name_never_reaches_the_verdict_line() -> None:
    payload = {"model": "leak" + chr(10) + "x" * 200,
               "choices": [{"message": {"content": "ok"}}]}
    status, raw = 200, json.dumps(payload).encode()
    assert smoke.decide(status, raw) == ("PASS", smoke.REQUESTED_ROUTE)


def test_a_provider_text_never_appears_in_the_verdict_output() -> None:
    verdict, model = smoke.decide(*_ok(text="PROVIDER-TEXT-MUST-NOT-APPEAR"))
    assert verdict == "PASS"
    assert "PROVIDER-TEXT-MUST-NOT-APPEAR" not in f"{verdict} {model}"


def test_main_reports_a_pass_without_the_provider_text(monkeypatch, capsys) -> None:
    status, raw = _ok(text="PROVIDER-TEXT-MUST-NOT-APPEAR")
    monkeypatch.setattr(smoke, "urlopen_transport", lambda *a, **k: _transport(status, raw))
    assert smoke.main(["--base-url", "https://b14.example.test"]) == 0
    out = capsys.readouterr().out
    assert out.strip() == "REAL_MODEL_CALL=PASS model=google/gemini-3.1-flash-lite"


def test_main_reports_and_exits_zero_on_a_pass(monkeypatch, capsys) -> None:
    status, raw = _ok()
    monkeypatch.setattr(smoke, "urlopen_transport", lambda *a, **k: _transport(status, raw))
    assert smoke.main(["--base-url", "https://b14.example.test"]) == 0
    out = capsys.readouterr().out
    assert out.strip() == "REAL_MODEL_CALL=PASS model=google/gemini-3.1-flash-lite"
    assert "PROVIDER-TEXT-MUST-NOT-APPEAR" not in out


def test_main_reports_and_exits_one_on_a_fail(monkeypatch, capsys) -> None:
    monkeypatch.setattr(smoke, "urlopen_transport", lambda *a, **k: _transport(500, b"{}"))
    assert smoke.main(["--base-url", "https://b14.example.test"]) == 1
    out = capsys.readouterr().out
    assert out.strip().startswith("REAL_MODEL_CALL=FAIL model=")


def test_a_plain_http_origin_is_refused_before_any_request(monkeypatch, capsys) -> None:
    def forbidden(*a, **k):
        raise AssertionError("no request may leave the runner for a non-https origin")
    monkeypatch.setattr(smoke, "urlopen_transport", forbidden)
    assert smoke.main(["--base-url", "http://b14.example.test"]) == 1
    assert "REAL_MODEL_CALL=FAIL" in capsys.readouterr().out


def test_the_served_origin_is_the_production_worker_route() -> None:
    assert smoke.SERVED_ORIGIN.startswith("https://")
    assert smoke.COMPLETIONS_PATH == "/api/pilot/v1/chat/completions"
    assert smoke.USER_AGENT == "b14-gate/1.0"
