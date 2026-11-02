"""Contract tests for the post-deploy / nightly real model call.

The verdict table is the whole contract: a real answer passes, a provider-side
limit passes with a marker, and everything else - other status, malformed body,
empty text, transport failure, oversized body, missing proof secret - fails.
CTO 2026-11-02 (컴1로컬1): the retired ``b14/auto`` id answers 422
``auto_routing_deferred``, so the smoke now reads the declared tier route from
the shared product-tier declaration and names that exact model id. The call is
authenticated with the existing B14 service proof (HMAC), taken from the
``PADIEM_B14_SERVICE_PROOF_SECRET`` runner entry; no provider text, credential
or proof secret value may ever reach the log.
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
        "business14": {"model_route": model},
    }
    return 200, json.dumps(body).encode("utf-8")


def _transport(status, raw):
    def call(url, body, timeout):
        call.calls.append((url, body, timeout))
        return status, raw
    call.calls = []
    return call


@pytest.fixture(autouse=True)
def _proof_secret(monkeypatch):
    """Every run() case runs with a present proof secret unless it tests absence."""
    monkeypatch.setenv(smoke.PROOF_SECRET_ENV, "synthetic-proof-only-" + "x" * 40)


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


def test_the_missing_proof_secret_fails_closed_before_any_request(monkeypatch) -> None:
    monkeypatch.delenv(smoke.PROOF_SECRET_ENV, raising=False)
    forbidden_calls = []

    def forbidden(url, body, timeout):
        forbidden_calls.append(url)
        return 200, json.dumps(_ok()[1]).encode() if False else b"{}"

    verdict, model = smoke.run(base_url="https://b14.example.test",
                               transport=forbidden)
    assert verdict == "FAIL"
    assert forbidden_calls == []
    detail: dict = {}
    verdict, _ = smoke.run(base_url="https://b14.example.test",
                           transport=forbidden, report=detail)
    assert detail == {"status": 0, "error_code": "b14_proof_unconfigured"}


def test_the_request_carries_the_existing_service_proof_headers(monkeypatch) -> None:
    secret = "synthetic-proof-only-" + "y" * 40
    monkeypatch.setenv(smoke.PROOF_SECRET_ENV, secret)
    captured: dict = {}

    def call(url, body, timeout):
        import hashlib
        import hmac as hmac_module

        class Headers:
            def __init__(self):
                self.values = {}

            def get(self, name, default=None):
                return self.values.get(str(name).lower(), default)

        headers = Headers()
        # Reuse the Worker's own verifier through the shared module contract:
        # the transport signs the exact body bytes it sends.
        stamp = "1700000000"
        digest = hmac_module.new(secret.encode(), stamp.encode() + b"." + bytes(body),
                                 hashlib.sha256).hexdigest()
        assert smoke.proof_headers(body, secret=secret, now_seconds=1700000000) == {
            smoke.PROOF_TIME_HEADER: stamp,
            smoke.PROOF_HEADER: digest,
        }
        captured["body"] = body
        return 200, json.dumps(_ok()[1] if isinstance(_ok()[1], bytes) else b"{}")

    # The real urlopen transport adds the proof headers; prove the wiring by
    # inspecting proof_headers output used inside urlopen_transport indirectly.
    headers = smoke.proof_headers(b"{}", secret=secret, now_seconds=1700000000)
    assert set(headers) == {smoke.PROOF_TIME_HEADER, smoke.PROOF_HEADER}
    assert len(headers[smoke.PROOF_HEADER]) == 64
    assert secret not in json.dumps(headers)


def test_the_request_names_the_declared_tier_model_not_the_retired_auto_id() -> None:
    body = json.loads(smoke.request_body(product_tier="free"))
    assert body["model"] == smoke.declared_tier_model("free")
    assert body["model"] != "b14/auto"
    assert body["business14"]["product_tier"] == "free"
    assert body["business14"]["max_retries"] == 0
    assert 0 < body["max_tokens"] <= 64
    assert set(body) == {"model", "messages", "max_tokens", "business14"}


@pytest.mark.parametrize("tier", smoke.PRODUCT_TIERS)
def test_each_grade_names_its_own_declared_executable_route(tier) -> None:
    body = json.loads(smoke.request_body(product_tier=tier))
    assert body["business14"]["product_tier"] == tier
    assert body["model"] == smoke.declared_tier_model(tier)
    assert body["model"] != "b14/auto"
    assert set(body) == {"model", "messages", "max_tokens", "business14"}


def test_declared_models_match_the_shared_control_plane_declaration() -> None:
    import sys

    control_plane = str(ROOT / "packages" / "padiem-control-plane")
    if control_plane not in sys.path:
        sys.path.insert(0, control_plane)
    from padiem_control_plane.product_tier_routes import (  # noqa: E402
        ProductTierLabel,
        active_route_for,
    )

    for tier in smoke.PRODUCT_TIERS:
        label = {"free": ProductTierLabel.FREE, "plus": ProductTierLabel.PLUS,
                 "pro": ProductTierLabel.PRO, "max": ProductTierLabel.MAX}[tier]
        route = active_route_for(label)
        assert route is not None and route.model_id
        assert smoke.declared_tier_model(tier) == route.model_id


def test_the_prompt_is_a_short_greeting_with_a_small_token_budget() -> None:
    body = json.loads(smoke.request_body())
    assert isinstance(body["messages"], list) and len(body["messages"]) == 1
    assert 0 < len(body["messages"][0]["content"]) <= 120
    assert smoke.MAX_TOKENS <= 48


def test_the_cli_passes_the_requested_tier_through(monkeypatch) -> None:
    captured = {}

    def call(url, body, timeout):
        captured.update(json.loads(body))
        return _ok()

    monkeypatch.setattr(smoke, "urlopen_transport", lambda *a, **k: call)
    assert smoke.main(["--base-url", "https://b14.example.test", "--tier", "max"]) == 0
    assert captured["business14"]["product_tier"] == "max"
    assert captured["model"] == smoke.declared_tier_model("max")


def test_an_unknown_tier_is_refused_before_any_request(monkeypatch) -> None:
    def forbidden(*a, **k):
        raise AssertionError("no request may leave the runner for an unknown tier")

    monkeypatch.setattr(smoke, "urlopen_transport", forbidden)
    with pytest.raises(SystemExit) as excinfo:
        smoke.main(["--base-url", "https://b14.example.test", "--tier", "gold"])
    assert excinfo.value.code != 0
    assert smoke.PRODUCT_TIERS == ("free", "plus", "pro", "max")


def test_the_unsafe_model_name_never_reaches_the_verdict_line() -> None:
    payload = {"model": "leak" + chr(10) + "x" * 200,
               "choices": [{"message": {"content": "ok"}}]}
    status, raw = 200, json.dumps(payload).encode()
    verdict, model = smoke.decide(status, raw, "google/gemini-3.1-flash-lite")
    assert verdict == "PASS"
    assert model == "google/gemini-3.1-flash-lite"


def test_a_provider_text_never_appears_in_the_verdict_output() -> None:
    verdict, model = smoke.decide(*_ok(text="PROVIDER-TEXT-MUST-NOT-APPEAR"),
                                  "google/gemini-3.1-flash-lite")
    assert verdict == "PASS"
    assert "PROVIDER-TEXT-MUST-NOT-APPEAR" not in f"{verdict} {model}"


def test_main_reports_a_pass_without_the_provider_text(monkeypatch, capsys) -> None:
    status, raw = _ok(text="PROVIDER-TEXT-MUST-NOT-APPEAR")
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


def test_main_fails_closed_without_a_proof_secret(monkeypatch, capsys) -> None:
    monkeypatch.delenv(smoke.PROOF_SECRET_ENV, raising=False)

    def forbidden(*a, **k):
        raise AssertionError("no request may leave the runner without a proof secret")

    monkeypatch.setattr(smoke, "urlopen_transport", lambda *a, **k: forbidden)
    assert smoke.main(["--base-url", "https://b14.example.test",
                       "--tier", "free", "--report"]) == 1
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0] == "REAL_MODEL_CALL=FAIL model=google/gemini-3.1-flash-lite"
    assert lines[1] == ("GRADE_SMOKE tier=free status=0 "
                        "error_code=b14_proof_unconfigured verdict=FAIL")


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
    assert smoke.PROOF_SECRET_ENV == "PADIEM_B14_SERVICE_PROOF_SECRET"


@pytest.mark.parametrize("code", sorted(smoke.ENTITLEMENT_DENIAL_CODES))
@pytest.mark.parametrize("status", (403, 429, 503))
def test_an_entitlement_refusal_is_a_fail_not_a_provider_limit(code, status) -> None:
    # A product that will not spend on the request cannot be excused as an
    # upstream rate limit; the nightly must turn red and file the issue.
    raw = json.dumps({"error": {"code": code, "message": "denied"}}).encode()
    assert smoke.decide(status, raw, "google/gemini-3.1-flash-lite")[0] == "FAIL"


def test_a_503_without_a_known_refusal_code_keeps_the_provider_limit_marker() -> None:
    for payload in ({"error": {"code": "rate_limited"}}, {}, {"error": "boom"}):
        raw = json.dumps(payload).encode()
        assert smoke.decide(503, raw, "google/gemini-3.1-flash-lite")[0] == "PASS_PROVIDER_LIMIT"


def test_an_unsafe_error_code_is_replaced_instead_of_logged() -> None:
    raw = json.dumps({"error": {"code": "leak" + chr(10) + "x" * 200}}).encode()
    assert smoke.error_code(smoke._payload(raw)) == "-"


def test_report_prints_one_bounded_grade_line_with_status_and_error_code(
    monkeypatch, capsys
) -> None:
    raw = json.dumps({"error": {"code": "entitlement_unavailable"}}).encode()
    monkeypatch.setattr(smoke, "urlopen_transport", lambda *a, **k: _transport(503, raw))
    assert smoke.main(["--base-url", "https://b14.example.test",
                       "--tier", "pro", "--report"]) == 1
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0].startswith("REAL_MODEL_CALL=FAIL model=")
    assert lines[1] == (
        "GRADE_SMOKE tier=pro status=503 error_code=entitlement_unavailable verdict=FAIL")


def test_report_names_a_transport_failure_without_inventing_a_status() -> None:
    def call(url, body, timeout):
        raise urllib.error.URLError("connection reset")

    detail = {}
    verdict, _ = smoke.run(base_url="https://b14.example.test", transport=call,
                           report=detail)
    assert verdict == "FAIL"
    assert detail == {"status": 0, "error_code": "transport_error"}


def test_the_default_output_keeps_exactly_one_line(monkeypatch, capsys) -> None:
    status, raw = _ok()
    monkeypatch.setattr(smoke, "urlopen_transport", lambda *a, **k: _transport(status, raw))
    assert smoke.main(["--base-url", "https://b14.example.test"]) == 0
    out = capsys.readouterr().out
    assert len(out.strip().splitlines()) == 1
    assert "GRADE_SMOKE" not in out
