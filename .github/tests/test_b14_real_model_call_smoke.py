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

import hashlib
import hmac
import importlib.util
import json
import sys
import urllib.error
from pathlib import Path

import pytest

import os

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/b14_real_model_call_smoke.py"
ROUTES_DIR = ROOT / "packages/padiem-control-plane"
WORKFLOW = ROOT / ".github/workflows/b62-padiem-chat-ci.yml"

# 261109: the repository ships no model values, so the smoke contract runs as
# a switched host against the placeholder fixture unless the operator chose a
# registry. The resolved model id is derived from the same source below. The
# variable is scoped to this module: an autouse fixture re-applies it per test
# and the process environment is restored afterwards, so unrelated suites in
# the same pytest process keep reading the repository documents.
_PREV_REGISTRY = os.environ.get("PADIEM_MODELS_REGISTRY")
_FIXTURE = ROOT / "packages/padiem-control-plane/tests/fixtures/models_private_fixture.json"


def _apply_switch() -> None:
    if (os.environ.get("PADIEM_MODELS_REGISTRY", "").strip()
            or os.environ.get("PADIEM_MODELS_REGISTRY_OVERRIDE", "").strip()):
        return
    if not _FIXTURE.is_file():
        return
    # The loader refuses a world-readable document, so stage a private copy.
    import tempfile
    _handle = tempfile.NamedTemporaryFile(
        prefix="padiem-models-fixture-", suffix=".json", delete=False)
    _handle.write(_FIXTURE.read_bytes())
    _handle.close()
    os.chmod(_handle.name, 0o600)
    os.environ["PADIEM_MODELS_REGISTRY"] = _handle.name


def _restore_switch() -> None:
    if _PREV_REGISTRY is None:
        os.environ.pop("PADIEM_MODELS_REGISTRY", None)
    else:
        os.environ["PADIEM_MODELS_REGISTRY"] = _PREV_REGISTRY


_apply_switch()

spec = importlib.util.spec_from_file_location("b14_real_model_call_smoke", SCRIPT)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)

sys.path.insert(0, str(ROUTES_DIR))
from padiem_control_plane.product_tier_routes_private import (  # noqa: E402
    free_primary_model_id,
    paid_primary_model_id,
)

RESOLVED_MODEL = free_primary_model_id()
_restore_switch()


@pytest.fixture(autouse=True)
def _switched_registry_for_this_module():
    """Run every test here as a switched host, then restore the process env."""
    _apply_switch()
    yield
    _restore_switch()


def _ok(model=RESOLVED_MODEL, text="pong"):
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
    assert (verdict, model) == ("PASS", RESOLVED_MODEL)


@pytest.mark.parametrize("limit", sorted(smoke.PROVIDER_LIMIT_STATUSES))
def test_provider_limit_statuses_pass_with_a_marker(limit) -> None:
    verdict, model = smoke.run(
        base_url="https://b14.example.test",
        transport=_transport(limit, json.dumps({"error": {"code": "rate_limited"}}).encode()),
    )
    assert verdict == "PASS_PROVIDER_LIMIT"
    assert model == free_primary_model_id()


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
    assert body["model"] == smoke.declared_tier_model("free") == free_primary_model_id()
    assert not hasattr(smoke, "REQUESTED_ROUTE")
    assert body["business14"]["product_tier"] == smoke.PRODUCT_TIER
    assert body["business14"]["max_retries"] == 0
    # #7071: bounded, but large enough that reasoning-capable grade probes can
    # return visible text (32 exhausted on reasoning in 07:45 KST run).
    assert body["max_tokens"] == 256
    assert set(body) == {"model", "messages", "max_tokens", "business14"}


def test_each_grade_resolves_the_declared_executable_model() -> None:
    # The smoke reads the shared declaration; it never keeps a second list.
    assert smoke.declared_tier_model("free") == free_primary_model_id()
    for tier in ("plus", "pro", "max"):
        assert smoke.declared_tier_model(tier) == paid_primary_model_id()
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
    # The refusal carries no model name, so the match is unknown, not guessed.
    assert detail == {"status": 401, "error_code": "b14_service_proof_required",
                      "model_match": "unknown"}


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
    assert out.strip() == "REAL_MODEL_CALL=PASS tier=free model_match=yes"
    assert "PROVIDER-TEXT-MUST-NOT-APPEAR" not in out


def test_main_reports_and_exits_zero_on_a_pass(monkeypatch, capsys) -> None:
    status, raw = _ok()
    monkeypatch.setattr(smoke, "urlopen_transport", lambda *a, **k: _transport(status, raw))
    assert smoke.main(["--base-url", "https://b14.example.test"]) == 0
    out = capsys.readouterr().out
    assert out.strip() == "REAL_MODEL_CALL=PASS tier=free model_match=yes"


def test_main_reports_and_exits_one_on_a_fail(monkeypatch, capsys) -> None:
    monkeypatch.setattr(smoke, "urlopen_transport", lambda *a, **k: _transport(500, b"{}"))
    assert smoke.main(["--base-url", "https://b14.example.test"]) == 1
    out = capsys.readouterr().out
    assert out.strip().startswith("REAL_MODEL_CALL=FAIL tier=")
    assert "model=" not in out


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


def test_the_probe_prompt_carries_no_replacement_characters() -> None:
    """#7450: a broken-encoding re-save once shipped U+FFFD soup as the probe's
    real Korean prompt. The script and the contract test files must keep
    carrying real text, never a replacement character."""
    assert "\ufffd" not in SCRIPT.read_text(encoding="utf-8")
    contract_files = (
        Path(__file__),
        ROOT / ".github" / "tests" / "test_b14_production_deploy_gate.py",
    )
    for contract in contract_files:
        assert "\ufffd" not in contract.read_text(encoding="utf-8"), contract
    # The restored prompt is actual Hangul text, not an empty or ASCII stub.
    assert smoke.PROMPT.isprintable()
    assert any(0xAC00 <= ord(c) <= 0xD7A3 for c in smoke.PROMPT)


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
        "REAL_MODEL_CALL=FAIL tier=pro model_match=unknown"
    )
    assert lines[1] == (
        "GRADE_SMOKE tier=pro status=503 error_code=entitlement_unavailable "
        "verdict=FAIL model_match=unknown")


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


# -- #7450: the tier route may come from the serving authority itself ---------

FETCHED_MODEL = "example-provider/example-model-9"


def _admin_transport(response, status: int = 200):
    """A GET transport for the proven-caller model authority."""

    def get_call(url, headers, timeout):
        get_call.calls.append((url, headers, timeout))
        if isinstance(response, (bytes, bytearray)):
            return status, bytes(response)
        return status, json.dumps(response).encode("utf-8")

    get_call.calls = []
    return get_call


def _admin_payload(model: str = FETCHED_MODEL) -> dict:
    return {"tier_routes": {"free": model, "plus": model, "pro": model, "max": model}}


def test_the_route_read_proof_binds_to_the_empty_get_body() -> None:
    headers = smoke.proof_headers("k" * 40, b"", now_seconds=1700000000)
    expected = hmac.new(b"k" * 40, b"1700000000.", hashlib.sha256).hexdigest()
    assert headers == {
        smoke.PROOF_HEADER: expected,
        smoke.PROOF_TIME_HEADER: "1700000000",
    }


def test_the_tier_route_comes_from_the_serving_authority_when_the_contract_is_empty(
    monkeypatch,
) -> None:
    # The nightly runner holds no registry: the declaration answers "", and the
    # route comes from the same B14 that serves the grade, behind the proof.
    monkeypatch.setattr(smoke, "declared_tier_model", lambda tier: "")
    get_transport = _admin_transport(_admin_payload())
    post_transport = _transport(*_ok(model=FETCHED_MODEL))
    verdict, model = smoke.run(
        base_url="https://b14.example.test", transport=post_transport,
        tier="free", service_proof_secret="k" * 40, transport_get=get_transport,
    )
    assert (verdict, model) == ("PASS", FETCHED_MODEL)
    url, headers, _timeout = get_transport.calls[0]
    assert url == "https://b14.example.test/api/pilot/admin/models"
    assert smoke.PROOF_HEADER in headers and smoke.PROOF_TIME_HEADER in headers


@pytest.mark.parametrize("tier", smoke.PRODUCT_TIERS)
def test_each_grade_reads_its_own_route_from_the_authority(monkeypatch, tier) -> None:
    monkeypatch.setattr(smoke, "declared_tier_model", lambda _tier: "")
    payload = {"tier_routes": {"free": "a/free-1", "plus": "a/plus-1",
                               "pro": "a/pro-1", "max": "a/max-1"}}
    get_transport = _admin_transport(payload)
    post_transport = _transport(*_ok(model="a/" + tier + "-1"))
    verdict, model = smoke.run(
        base_url="https://b14.example.test", transport=post_transport,
        tier=tier, service_proof_secret="k" * 40, transport_get=get_transport,
    )
    assert verdict == "PASS"
    assert model == "a/" + tier + "-1"


def test_a_refused_route_read_fails_closed_and_makes_no_completion_call(monkeypatch) -> None:
    monkeypatch.setattr(smoke, "declared_tier_model", lambda _tier: "")
    get_transport = _admin_transport(
        {"error": {"code": "b14_service_proof_required"}}, status=401)
    post_transport = _transport(*_ok())
    detail: dict = {}
    verdict, model = smoke.run(
        base_url="https://b14.example.test", transport=post_transport,
        tier="free", service_proof_secret="k" * 40,
        transport_get=get_transport, report=detail,
    )
    assert verdict == "FAIL"
    assert model == "free"
    assert detail == {"status": 0, "error_code": "b14_service_proof_required"}
    assert post_transport.calls == []


def test_a_missing_route_surface_fails_closed_before_any_call(monkeypatch) -> None:
    # A B14 without the #7450 field yet (not deployed) is a named failure, not
    # a guessed model and not a silent pass.
    monkeypatch.setattr(smoke, "declared_tier_model", lambda _tier: "")
    get_transport = _admin_transport(b"{}", status=404)
    detail: dict = {}
    verdict, model = smoke.run(
        base_url="https://b14.example.test", transport=_transport(*_ok()),
        tier="max", service_proof_secret="k" * 40,
        transport_get=get_transport, report=detail,
    )
    assert verdict == "FAIL"
    assert model == "max"
    assert detail == {"status": 0, "error_code": "route_read_failed"}


def test_an_unreachable_route_read_is_a_named_transport_failure(monkeypatch) -> None:
    monkeypatch.setattr(smoke, "declared_tier_model", lambda _tier: "")

    def get_call(url, headers, timeout):
        raise urllib.error.URLError("connection reset")

    detail: dict = {}
    verdict, model = smoke.run(
        base_url="https://b14.example.test", transport=_transport(*_ok()),
        tier="plus", service_proof_secret="k" * 40,
        transport_get=get_call, report=detail,
    )
    assert verdict == "FAIL"
    assert model == "plus"
    assert detail == {"status": 0, "error_code": "route_transport_error"}


def test_a_grade_absent_from_the_route_surface_is_named_precisely(monkeypatch) -> None:
    monkeypatch.setattr(smoke, "declared_tier_model", lambda _tier: "")
    get_transport = _admin_transport({"tier_routes": {"free": FETCHED_MODEL}})
    detail: dict = {}
    verdict, model = smoke.run(
        base_url="https://b14.example.test", transport=_transport(*_ok()),
        tier="max", service_proof_secret="k" * 40,
        transport_get=get_transport, report=detail,
    )
    assert verdict == "FAIL"
    assert model == "max"
    assert detail == {"status": 0, "error_code": "tier_route_unavailable"}


def test_an_unsafe_model_from_the_route_surface_is_refused(monkeypatch) -> None:
    monkeypatch.setattr(smoke, "declared_tier_model", lambda _tier: "")
    get_transport = _admin_transport(_admin_payload(model="bad model\nid"))
    detail: dict = {}
    verdict, model = smoke.run(
        base_url="https://b14.example.test", transport=_transport(*_ok()),
        tier="free", service_proof_secret="k" * 40,
        transport_get=get_transport, report=detail,
    )
    assert verdict == "FAIL"
    assert detail == {"status": 0, "error_code": "tier_route_unavailable"}


def test_the_route_read_needs_the_proof_and_stays_unsigned_without_it(monkeypatch) -> None:
    monkeypatch.setattr(smoke, "declared_tier_model", lambda _tier: "")
    get_transport = _admin_transport(_admin_payload())
    detail: dict = {}
    verdict, model = smoke.run(
        base_url="https://b14.example.test", transport=_transport(*_ok()),
        tier="free", service_proof_secret="",
        transport_get=get_transport, report=detail,
    )
    assert verdict == "FAIL"
    assert model == "free"
    assert detail == {"status": 0, "error_code": "route_proof_unconfigured"}
    assert get_transport.calls == []


def test_the_deploy_gate_never_reads_the_route_surface(monkeypatch) -> None:
    # The deploy gate runs on a registry host and keeps its exact former
    # source: an empty declaration there is a plain tier_route_unavailable.
    monkeypatch.setattr(smoke, "declared_tier_model", lambda _tier: "")

    def forbidden_get(url, headers, timeout):
        raise AssertionError("the unsigned deploy gate may not read the authority detail")

    detail: dict = {}
    verdict, model = smoke.run(
        base_url="https://b14.example.test", transport=_transport(*_ok()),
        service_proof_secret="k" * 40, transport_get=forbidden_get, report=detail,
    )
    assert verdict == "FAIL"
    assert model == "free"
    assert detail == {"status": 0, "error_code": "tier_route_unavailable"}


def test_the_cli_nightly_path_reads_the_route_from_the_authority(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(smoke, "declared_tier_model", lambda _tier: "")
    get_transport = _admin_transport(_admin_payload())
    monkeypatch.setattr(smoke, "urlopen_get_transport", lambda *a, **k: get_transport)
    monkeypatch.setattr(
        smoke, "urlopen_transport", lambda *a, **k: _transport(*_ok(model=FETCHED_MODEL)))
    monkeypatch.setenv(smoke.PROOF_SECRET_ENV, "k" * 40)
    assert smoke.main(["--base-url", "https://b14.example.test",
                       "--tier", "pro", "--report"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0] == "REAL_MODEL_CALL=PASS tier=pro model_match=yes"
    assert lines[1] == "GRADE_SMOKE tier=pro status=200 error_code=- verdict=PASS model_match=yes"

# -- #7450 review: no output line ever carries a model value ------------------

LEAK_MODEL = "example-provider/leak-model-xyz"


def _leak_named_response(status: int, model: str = LEAK_MODEL,
                         text: str = "pong") -> tuple[int, bytes]:
    body = {"model": model,
            "choices": [{"index": 0,
                         "message": {"role": "assistant", "content": text}}]}
    return status, json.dumps(body).encode("utf-8")


def _assert_value_free(captured) -> None:
    output = captured.out + captured.err
    assert LEAK_MODEL not in output
    assert "leak-model" not in output
    assert "example-provider" not in output


def test_the_response_match_is_recorded_in_the_report() -> None:
    detail: dict = {}
    verdict, _ = smoke.run(
        base_url="https://b14.example.test", transport=_transport(*_ok()),
        tier="free", service_proof_secret="k" * 40, report=detail,
    )
    assert verdict == "PASS"
    assert detail == {"status": 200, "error_code": "-", "model_match": "yes"}


def test_a_switched_answer_records_model_match_no() -> None:
    detail: dict = {}
    verdict, _ = smoke.run(
        base_url="https://b14.example.test",
        transport=_transport(*_leak_named_response(200)),
        tier="free", service_proof_secret="k" * 40, report=detail,
    )
    assert verdict == "PASS"
    assert detail["model_match"] == "no"


def test_a_route_field_answer_names_the_requested_route() -> None:
    """rel203 finding: the server contract fills the top-level ``model`` with
    the upstream identity, while ``business14.model_route`` names the route
    the answer came on. A fully green smoke must answer ``model_match=yes``
    when the requested route served, regardless of the upstream name."""
    body = {
        "model": "upstream-example/other-identity-1",
        "choices": [{"index": 0,
                     "message": {"role": "assistant", "content": "pong"}}],
        "business14": {"model_route": RESOLVED_MODEL},
    }
    detail: dict = {}
    verdict, _ = smoke.run(
        base_url="https://b14.example.test",
        transport=_transport(200, json.dumps(body).encode("utf-8")),
        tier="free", service_proof_secret="k" * 40, report=detail,
    )
    assert verdict == "PASS"
    assert detail["model_match"] == "yes"


def test_a_fallback_route_answer_stays_honest_no() -> None:
    """The owner-pinned fallback is a real serving answer, not the requested
    route: the verdict records it as ``no`` instead of laundering it."""
    body = {
        "model": "upstream-example/other-identity-2",
        "choices": [{"index": 0,
                     "message": {"role": "assistant", "content": "pong"}}],
        "business14": {"model_route": "upstream-example/fallback-identity-1"},
    }
    detail: dict = {}
    verdict, _ = smoke.run(
        base_url="https://b14.example.test",
        transport=_transport(200, json.dumps(body).encode("utf-8")),
        tier="free", service_proof_secret="k" * 40, report=detail,
    )
    assert verdict == "PASS"
    assert detail["model_match"] == "no"


def test_the_report_line_never_names_a_model(monkeypatch, capsys) -> None:
    monkeypatch.setattr(smoke, "urlopen_transport",
                        lambda *a, **k: _transport(*_leak_named_response(200)))
    monkeypatch.setenv(smoke.PROOF_SECRET_ENV, "k" * 40)
    assert smoke.main(["--base-url", "https://b14.example.test",
                       "--tier", "free", "--report"]) == 0
    captured = capsys.readouterr()
    assert "model_match=no" in captured.out
    assert "tier=free" in captured.out
    _assert_value_free(captured)


def test_a_pass_never_prints_the_model_value(monkeypatch, capsys) -> None:
    monkeypatch.setattr(smoke, "urlopen_transport",
                        lambda *a, **k: _transport(*_leak_named_response(200)))
    monkeypatch.setenv(smoke.PROOF_SECRET_ENV, "k" * 40)
    for tier in smoke.PRODUCT_TIERS:
        assert smoke.main(["--base-url", "https://b14.example.test",
                           "--tier", tier, "--report"]) == 0
        captured = capsys.readouterr()
        assert "model_match=no" in captured.out
        _assert_value_free(captured)


def test_a_provider_limit_never_prints_the_model_value(monkeypatch, capsys) -> None:
    for status in sorted(smoke.PROVIDER_LIMIT_STATUSES):
        monkeypatch.setattr(smoke, "urlopen_transport",
                            lambda *a, **k: _transport(*_leak_named_response(status)))
        monkeypatch.setenv(smoke.PROOF_SECRET_ENV, "k" * 40)
        assert smoke.main(["--base-url", "https://b14.example.test",
                           "--tier", "max", "--report"]) == 0
        captured = capsys.readouterr()
        assert "model_match=no" in captured.out
        _assert_value_free(captured)


def test_a_fail_never_prints_the_model_value(monkeypatch, capsys) -> None:
    monkeypatch.setattr(smoke, "urlopen_transport",
                        lambda *a, **k: _transport(*_leak_named_response(500)))
    monkeypatch.setenv(smoke.PROOF_SECRET_ENV, "k" * 40)
    assert smoke.main(["--base-url", "https://b14.example.test",
                       "--tier", "pro", "--report"]) == 1
    captured = capsys.readouterr()
    # The refusal named a different model than the request: the switch is
    # recorded value-free, and no identity appears anywhere.
    assert "model_match=no" in captured.out
    _assert_value_free(captured)


def test_a_transport_failure_never_prints_the_model_value(
    monkeypatch, capsys
) -> None:
    # Even the exception path stays value-free: the raised error carries a
    # model-looking fragment, and the runner must swallow it whole.
    def call(url, body, headers, timeout):
        raise urllib.error.URLError(f"upstream said {LEAK_MODEL}")

    monkeypatch.setattr(smoke, "urlopen_transport", lambda *a, **k: call)
    monkeypatch.setenv(smoke.PROOF_SECRET_ENV, "k" * 40)
    assert smoke.main(["--base-url", "https://b14.example.test",
                       "--tier", "pro", "--report"]) == 1
    captured = capsys.readouterr()
    assert "model_match=unknown" in captured.out
    _assert_value_free(captured)


def test_a_route_failure_never_prints_the_model_value(monkeypatch, capsys) -> None:
    # Not deployed yet: the route read fails closed and the output still
    # carries no model value.
    monkeypatch.setattr(smoke, "declared_tier_model", lambda _tier: "")
    get_transport = _admin_transport(b"{}", status=404)
    monkeypatch.setattr(smoke, "urlopen_get_transport", lambda *a, **k: get_transport)
    monkeypatch.setenv(smoke.PROOF_SECRET_ENV, "k" * 40)
    assert smoke.main(["--base-url", "https://b14.example.test",
                       "--tier", "max", "--report"]) == 1
    captured = capsys.readouterr()
    assert "model_match=unknown" in captured.out
    _assert_value_free(captured)


def test_the_route_fetch_result_never_prints_the_model_value(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(smoke, "declared_tier_model", lambda _tier: "")
    get_transport = _admin_transport(_admin_payload(model=LEAK_MODEL))
    monkeypatch.setattr(smoke, "urlopen_get_transport", lambda *a, **k: get_transport)
    monkeypatch.setattr(smoke, "urlopen_transport",
                        lambda *a, **k: _transport(*_leak_named_response(200)))
    monkeypatch.setenv(smoke.PROOF_SECRET_ENV, "k" * 40)
    assert smoke.main(["--base-url", "https://b14.example.test",
                       "--tier", "free", "--report"]) == 0
    captured = capsys.readouterr()
    assert captured.out.startswith("REAL_MODEL_CALL=PASS tier=free model_match=")
    _assert_value_free(captured)


def test_the_origin_refusal_never_prints_the_model_value(capsys) -> None:
    assert smoke.main(["--base-url", "http://b14.example.test",
                       "--tier", "free", "--report"]) == 1
    captured = capsys.readouterr()
    assert "model_match=unknown" in captured.out
    assert RESOLVED_MODEL not in captured.out + captured.err


def test_the_grade_job_echoes_no_model_or_registry_content() -> None:
    """#7450 review: no other door in the nightly job prints a model value.

    The grade job runs the script, records one bounded GRADE_SMOKE line in the
    step summary when the credential is absent, and uploads nothing. No step
    may echo, cat or stage the private registry or any model identifier.
    """
    import yaml

    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/b62-padiem-chat-ci.yml").read_text(encoding="utf-8"))
    job = workflow["jobs"]["grade-live-smoke"]
    forbidden_tokens = ("PADIEM_MODELS_REGISTRY", "models-private",
                        "cat ", "install_token", "tier_routes")
    for step in job["steps"]:
        run_text = str(step.get("run", ""))
        for token in forbidden_tokens:
            assert token not in run_text, (step.get("name"), token)
        assert "actions/upload-artifact" not in str(step.get("uses", ""))
