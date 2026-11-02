"""Contract tests for the #5895 ④ real model call and the nightly grade smoke.

Two invocations share the verdict table but not the wire:

* the deploy gate calls the script with no arguments: the Free grade's exact
  declared model, no credential, one ``REAL_MODEL_CALL=`` line;
* the nightly grade smoke passes ``--tier``: the tier's exact model id from the
  shared product-tier declaration, signed with the existing B14 service proof.

The verdict table is the whole failure contract: a real answer passes, a
provider-side limit passes with a marker, and everything else - other status,
malformed body, empty text, transport failure, oversized body, entitlement
refusal - fails. No provider text or secret may ever reach the log.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/b14_real_model_call_smoke.py"
ROUTES_DIR = ROOT / "packages/padiem-control-plane"
WORKFLOW = ROOT / ".github/workflows/b62-padiem-chat-ci.yml"

spec = importlib.util.spec_from_file_location("b14_real_model_call_smoke", SCRIPT)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)

sys.path.insert(0, str(ROUTES_DIR))
from padiem_control_plane.product_tier_routes import (  # noqa: E402
    FREE_PRIMARY_B14_MODEL_ID,
    TEST_PHASE_PRIMARY_B14_MODEL_ID,
)


def _ok(model="google/gemini-3.1-flash-lite", text="pong"):
    body = {
        "id": "chatcmpl-synthetic",
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}}],
    }
    return 200, json.dumps(body).encode("utf-8")


def _transport(status, raw):
    def call(url, body, headers, timeout):
        call.calls.append((url, body, headers, timeout))
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
    assert model == FREE_PRIMARY_B14_MODEL_ID


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
    def call(url, body, headers, timeout):
        raise urllib.error.URLError("connection reset")
    assert smoke.run(base_url="https://b14.example.test", transport=call)[0] == "FAIL"


def test_an_oversized_response_fails() -> None:
    assert smoke.run(
        base_url="https://b14.example.test",
        transport=_transport(200, b"x" * (smoke.MAX_RESPONSE_BYTES + 1)),
    )[0] == "FAIL"


def test_the_default_request_names_the_free_grade_model_of_its_own() -> None:
    body = json.loads(smoke.request_body(model=smoke.declared_tier_model(smoke.PRODUCT_TIER)))
    assert body["model"] == smoke.declared_tier_model("free") == FREE_PRIMARY_B14_MODEL_ID
    assert not hasattr(smoke, "REQUESTED_ROUTE")
    assert body["business14"]["product_tier"] == smoke.PRODUCT_TIER
    assert body["business14"]["max_retries"] == 0
    assert 0 < body["max_tokens"] <= 64
    assert set(body) == {"model", "messages", "max_tokens", "business14"}


def test_each_grade_resolves_the_declared_executable_model() -> None:
    # The smoke reads the shared declaration; it never keeps a second list.
    assert smoke.declared_tier_model("free") == FREE_PRIMARY_B14_MODEL_ID
    for tier in ("plus", "pro", "max"):
        assert smoke.declared_tier_model(tier) == TEST_PHASE_PRIMARY_B14_MODEL_ID
    assert smoke.declared_tier_model("gold") == ""


@pytest.mark.parametrize("tier", smoke.PRODUCT_TIERS)
def test_the_tier_request_names_the_exact_model(tier) -> None:
    transport = _transport(*_ok())
    smoke.run(base_url="https://b14.example.test", transport=transport, tier=tier,
              service_proof_secret="k" * 40)
    url, raw, headers, _timeout = transport.calls[0]
    body = json.loads(raw)
    assert body["model"] == smoke.declared_tier_model(tier)
    assert body["business14"]["product_tier"] == tier
    assert url == "https://b14.example.test/api/pilot/v1/chat/completions"
    assert smoke.PROOF_HEADER in headers and smoke.PROOF_TIME_HEADER in headers


def test_the_tier_request_is_signed_with_the_existing_service_proof() -> None:
    body = b'{"model":"x"}'
    headers = smoke.proof_headers(
        "0123456789abcdef0123456789abcdef", body, now_seconds=1700000000
    )
    assert headers == {
        "x-padiem-b14-proof": (
            "56f8630d39d82b7ec3445b91348abf381034a6a40c2cbd83e1837b5c383a3da4"
        ),
        "x-padiem-b14-time": "1700000000",
    }


@pytest.mark.parametrize("secret", ["", "short", None])
def test_an_unconfigured_proof_secret_sends_no_header(secret) -> None:
    # No header means B14 refuses the dispatch; the check fails closed.
    assert smoke.proof_headers(secret, b"{}") == {}


def test_a_refused_proof_fails_closed_with_the_b14_code() -> None:
    raw = json.dumps({"error": {"code": "b14_service_proof_required"}}).encode()
    detail = {}
    verdict, model = smoke.run(
        base_url="https://b14.example.test",
        transport=_transport(401, raw),
        tier="free",
        service_proof_secret="",
        report=detail,
    )
    assert verdict == "FAIL"
    assert model == smoke.declared_tier_model("free")
    assert detail == {"status": 401, "error_code": "b14_service_proof_required"}


def test_the_default_deploy_gate_call_stays_unsigned() -> None:
    # The deploy gate runs on the platform lane it always had; only --tier signs.
    transport = _transport(*_ok())
    smoke.run(base_url="https://b14.example.test", transport=transport,
              service_proof_secret="k" * 40)
    _url, raw, headers, _timeout = transport.calls[0]
    assert json.loads(raw)["model"] == smoke.declared_tier_model("free")
    assert headers == {}


def test_the_grade_job_references_the_existing_proof_secret_name() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert (
        "PADIEM_B14_SERVICE_PROOF_SECRET: "
        "${{ secrets.PADIEM_B14_SERVICE_PROOF_SECRET }}" in workflow
    )
    assert (
        'b14_real_model_call_smoke.py --tier "${{ matrix.tier }}"'
        " --base-url http://127.0.0.1:8789 --report" in workflow
    )


def test_the_cli_passes_the_requested_tier_through(monkeypatch) -> None:
    captured = {}

    def call(url, body, headers, timeout):
        captured.update(json.loads(body))
        return _ok()

    monkeypatch.setattr(smoke, "urlopen_transport", lambda *a, **k: call)
    monkeypatch.setenv(smoke.PROOF_SECRET_ENV, "k" * 40)
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
    assert smoke.decide(status, raw) == ("PASS", "")


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


@pytest.mark.parametrize("code", sorted(smoke.ENTITLEMENT_DENIAL_CODES))
@pytest.mark.parametrize("status", (403, 429, 503))
def test_an_entitlement_refusal_is_a_fail_not_a_provider_limit(code, status) -> None:
    # A product that will not spend on the request cannot be excused as an
    # upstream rate limit; the nightly must turn red and file the issue.
    raw = json.dumps({"error": {"code": code, "message": "denied"}}).encode()
    assert smoke.decide(status, raw)[0] == "FAIL"


def test_a_503_without_a_known_refusal_code_keeps_the_provider_limit_marker() -> None:
    for payload in ({"error": {"code": "rate_limited"}}, {}, {"error": "boom"}):
        raw = json.dumps(payload).encode()
        assert smoke.decide(503, raw)[0] == "PASS_PROVIDER_LIMIT"


def test_an_unsafe_error_code_is_replaced_instead_of_logged() -> None:
    raw = json.dumps({"error": {"code": "leak" + chr(10) + "x" * 200}}).encode()
    assert smoke.error_code(smoke._payload(raw)) == "-"


def test_report_prints_one_bounded_grade_line_with_status_and_error_code(
    monkeypatch, capsys
) -> None:
    raw = json.dumps({"error": {"code": "entitlement_unavailable"}}).encode()
    monkeypatch.setattr(smoke, "urlopen_transport", lambda *a, **k: _transport(503, raw))
    monkeypatch.setenv(smoke.PROOF_SECRET_ENV, "k" * 40)
    assert smoke.main(["--base-url", "https://b14.example.test",
                       "--tier", "pro", "--report"]) == 1
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0] == (
        "REAL_MODEL_CALL=FAIL model=google/gemini-3.5-flash-lite"
    )
    assert lines[1] == (
        "GRADE_SMOKE tier=pro status=503 error_code=entitlement_unavailable verdict=FAIL")


def test_report_names_a_transport_failure_without_inventing_a_status() -> None:
    def call(url, body, headers, timeout):
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