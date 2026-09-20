"""Contract tests for the provider-neutral B14 candidate live-smoke gate (#2798).

These tests never make a live provider call: every transport is a synthetic
in-process fake, matching the Agnes gate's testing posture.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github" / "scripts" / "b14_candidate_live_smoke.py"
WORKFLOW = ROOT / ".github" / "workflows" / "b14-candidate-live-smoke.yml"

spec = importlib.util.spec_from_file_location("b14_candidate_live_smoke", SCRIPT)
assert spec is not None and spec.loader is not None
smoke = importlib.util.module_from_spec(spec)
# The module uses `from __future__ import annotations` together with a
# `@dataclass(frozen=True)`, whose decoration resolves annotation strings via
# `sys.modules[cls.__module__]`. Registering before exec is therefore required.
sys.modules[spec.name] = smoke
spec.loader.exec_module(smoke)


def _json(value: dict) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode("utf-8")


def _health(spec: "smoke.CandidateSpec", *, has_key: bool = True) -> bytes:
    return _json(
        {
            "status": "ok",
            "business14": {
                "provider_mode": "live",
                "providers": [
                    {"id": spec.provider_id, "registered": True, "has_key": has_key}
                ],
            },
        }
    )


def _models(spec: "smoke.CandidateSpec") -> bytes:
    return _json(
        {
            "registered_routes": [
                {
                    "id": spec.model_id,
                    "provider_id": spec.provider_id,
                    "upstream_model": spec.upstream_model,
                }
            ]
        }
    )


def _chat(spec: "smoke.CandidateSpec") -> bytes:
    return _json(
        {
            "id": "synthetic",
            "object": "chat.completion",
            "model": spec.upstream_model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "PRIVATE_ANSWER_SENTINEL_42"},
                    "finish_reason": "stop",
                }
            ],
            "business14": {
                "mode": "live",
                "provider_mode": "live",
                "provider": spec.provider_name,
                "selected_provider": spec.provider_name,
                "model_route": spec.model_id,
                "selected_model": spec.model_id,
                "upstream_model": spec.upstream_model,
                "selected_upstream_model": spec.upstream_model,
                "actual_response_model": spec.upstream_model,
                "route_mode": "manual",
                "fallback_used": False,
                "attempt_count": 1,
                "route_evidence_status": "live_verified",
            },
        }
    )


def _happy_transport(spec, calls: list | None = None):
    def transport(method: str, path: str, body: dict | None):
        if calls is not None:
            calls.append((method, path, body))
        if path == smoke.HEALTH_PATH:
            return 200, _health(spec)
        if path == smoke.MODELS_PATH:
            return 200, _models(spec)
        if path == smoke.CHAT_PATH:
            return 200, _chat(spec)
        raise AssertionError(path)

    return transport


# --------------------------------------------------------------------------
# Allowlist / authority correction
# --------------------------------------------------------------------------


def test_allowlist_matches_2798_authority_correction() -> None:
    assert smoke.PLUS_CANDIDATE_IDS == (
        "agnes",
        "sensenova",
        "poolside",
        "motif",
        "mercury",
        "atria",
    )
    assert smoke.PRO_CANDIDATE_IDS == ("luna",)
    assert set(smoke.candidate_ids()) == {
        "agnes",
        "sensenova",
        "poolside",
        "motif",
        "mercury",
        "atria",
        "luna",
    }


def test_bai_qwen_is_excluded() -> None:
    for blocked in ("b-ai-qwen3.8", "bai", "qwen"):
        with pytest.raises(ValueError, match="candidate_excluded"):
            smoke.resolve_candidate(blocked)
    assert not any(
        spec.model_id == "b-ai/qwen3.8-flash" for spec in smoke.CANDIDATE_REGISTRY.values()
    )


def test_auto_route_is_not_permitted() -> None:
    with pytest.raises(ValueError, match="auto_route_not_permitted"):
        smoke.resolve_candidate(smoke.AUTO_MODEL_ID)
    assert smoke.AUTO_ROUTE_USED is False
    assert smoke.AUTO_MODEL_ID not in {s.model_id for s in smoke.CANDIDATE_REGISTRY.values()}


def test_unknown_candidate_fails_closed() -> None:
    with pytest.raises(ValueError, match="candidate_not_allowlisted"):
        smoke.resolve_candidate("does-not-exist")


def test_every_candidate_carries_exact_identity_and_binding_name() -> None:
    for cid, spec in smoke.CANDIDATE_REGISTRY.items():
        assert spec.candidate_id == cid
        assert spec.provider_id and spec.provider_name
        assert spec.model_id and spec.upstream_model
        assert spec.model_id != smoke.AUTO_MODEL_ID
        assert spec.credential_binding == spec.expected_binding
        assert spec.credential_binding.isupper()


def test_contract_constants_pin_one_call_no_retry_no_fallback() -> None:
    assert smoke.MAX_PROVIDER_CALLS == 1
    assert smoke.RETRY == 0
    assert smoke.FALLBACK == 0


# --------------------------------------------------------------------------
# Bounded execution
# --------------------------------------------------------------------------


@pytest.mark.parametrize("candidate_id", sorted(smoke.CANDIDATE_REGISTRY))
def test_success_uses_two_gets_and_exactly_one_chat_post(candidate_id: str) -> None:
    spec_obj = smoke.CANDIDATE_REGISTRY[candidate_id]
    calls: list[tuple[str, str, dict | None]] = []

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        rc = smoke.run(candidate_id, transport=_happy_transport(spec_obj, calls))

    assert rc == 0
    assert [(m, p) for m, p, _ in calls] == [
        ("GET", smoke.HEALTH_PATH),
        ("GET", smoke.MODELS_PATH),
        ("POST", smoke.CHAT_PATH),
    ]
    output = stdout.getvalue()
    assert f"{candidate_id.upper()}_PRODUCTION_SMOKE=PASS" in output
    assert "B14_CHAT_POST_COUNT=1" in output
    assert "NETWORK_RETRY_COUNT=0" in output
    assert "MAX_PROVIDER_CALLS=1" in output
    assert "RETRY=0" in output
    assert "FALLBACK=0" in output
    assert "AUTO_ROUTE_USED=0" in output
    assert "PRIVATE_PAYLOAD_OUTPUT=0" in output
    assert "SECRET_VALUE_OUTPUT=0" in output
    assert "PRIVATE_ANSWER_SENTINEL_42" not in output


@pytest.mark.parametrize("candidate_id", sorted(smoke.CANDIDATE_REGISTRY))
def test_chat_body_pins_exact_manual_model_never_auto(candidate_id: str) -> None:
    spec_obj = smoke.CANDIDATE_REGISTRY[candidate_id]
    body = smoke.canonical_chat_body(spec_obj)
    assert body["model"] == spec_obj.model_id
    assert body["model"] != smoke.AUTO_MODEL_ID


def test_expected_binding_name_is_emitted_without_any_secret_value() -> None:
    spec_obj = smoke.CANDIDATE_REGISTRY["mercury"]
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        rc = smoke.run("mercury", transport=_happy_transport(spec_obj))

    output = stdout.getvalue()
    assert rc == 0
    assert "MERCURY_EXPECTED_BINDING=PADIEM_INCEPTION_MERCURY_API_KEY" in output


def test_latency_evidence_is_recorded() -> None:
    spec_obj = smoke.CANDIDATE_REGISTRY["poolside"]
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        smoke.run("poolside", transport=_happy_transport(spec_obj))

    output = stdout.getvalue()
    assert "POOLSIDE_LATENCY_MS=" in output
    assert "POOLSIDE_LATENCY_CLASS=" in output


def test_missing_credential_fails_before_chat_post() -> None:
    spec_obj = smoke.CANDIDATE_REGISTRY["atria"]
    calls: list[tuple[str, str]] = []

    def transport(method: str, path: str, body: dict | None):
        calls.append((method, path))
        if path == smoke.HEALTH_PATH:
            return 200, _health(spec_obj, has_key=False)
        raise AssertionError("must fail before models/chat")

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        rc = smoke.run("atria", transport=transport)

    assert rc == 1
    assert calls == [("GET", smoke.HEALTH_PATH)]
    assert "FAIL_CREDENTIAL_NOT_READY" in stdout.getvalue()
    assert "B14_CHAT_POST_COUNT=0" in stdout.getvalue()


def test_wrong_route_identity_fails_before_provider_post() -> None:
    spec_obj = smoke.CANDIDATE_REGISTRY["motif"]

    def transport(method: str, path: str, body: dict | None):
        if path == smoke.HEALTH_PATH:
            return 200, _health(spec_obj)
        if path == smoke.MODELS_PATH:
            return 200, _json(
                {
                    "registered_routes": [
                        {
                            "id": spec_obj.model_id,
                            "provider_id": "wrong-provider",
                            "upstream_model": spec_obj.upstream_model,
                        }
                    ]
                }
            )
        raise AssertionError("must fail before chat")

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        rc = smoke.run("motif", transport=transport)

    assert rc == 1
    assert "FAIL_ROUTE_IDENTITY" in stdout.getvalue()
    assert "B14_CHAT_POST_COUNT=0" in stdout.getvalue()


def test_actual_response_model_mismatch_is_failure_not_fallback() -> None:
    spec_obj = smoke.CANDIDATE_REGISTRY["sensenova"]
    payload = json.loads(_chat(spec_obj).decode("utf-8"))
    payload["business14"]["actual_response_model"] = "some-other-model"

    def transport(method: str, path: str, body: dict | None):
        if path == smoke.HEALTH_PATH:
            return 200, _health(spec_obj)
        if path == smoke.MODELS_PATH:
            return 200, _models(spec_obj)
        return 200, _json(payload)

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        rc = smoke.run("sensenova", transport=transport)

    output = stdout.getvalue()
    assert rc == 1
    assert "FAIL_ROUTE_METADATA" in output
    assert "actual_response_model" in output
    assert "B14_CHAT_POST_COUNT=1" in output
    assert "FALLBACK=0" in output


def test_attempt_count_two_or_fallback_true_is_failure() -> None:
    spec_obj = smoke.CANDIDATE_REGISTRY["luna"]
    payload = json.loads(_chat(spec_obj).decode("utf-8"))
    payload["business14"]["attempt_count"] = 2
    payload["business14"]["fallback_used"] = True

    def transport(method: str, path: str, body: dict | None):
        if path == smoke.HEALTH_PATH:
            return 200, _health(spec_obj)
        if path == smoke.MODELS_PATH:
            return 200, _models(spec_obj)
        return 200, _json(payload)

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        rc = smoke.run("luna", transport=transport)

    output = stdout.getvalue()
    assert rc == 1
    assert "FAIL_ROUTE_METADATA" in output
    assert "attempt_count" in output
    assert "fallback_used" in output


def test_non_200_chat_emits_only_safe_error_code_and_no_private_payload() -> None:
    spec_obj = smoke.CANDIDATE_REGISTRY["mercury"]
    raw_secret = "sensitive-provider-detail"

    def transport(method: str, path: str, body: dict | None):
        if path == smoke.HEALTH_PATH:
            return 200, _health(spec_obj)
        if path == smoke.MODELS_PATH:
            return 200, _models(spec_obj)
        return 503, _json({"error": {"code": "no_safe_route", "message": raw_secret}})

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        rc = smoke.run("mercury", transport=transport)

    output = stdout.getvalue()
    assert rc == 1
    assert "FAIL_CHAT_HTTP_503" in output
    assert "ENGINE_ERROR_CODE=no_safe_route" in output
    assert raw_secret not in output
    assert "B14_CHAT_POST_COUNT=1" in output


def test_response_size_bound_is_enforced() -> None:
    spec_obj = smoke.CANDIDATE_REGISTRY["agnes"]

    def transport(method: str, path: str, body: dict | None):
        if path == smoke.HEALTH_PATH:
            return 200, _health(spec_obj)
        return 200, b"{" + b" " * (smoke.MAX_RESPONSE_BYTES + 10) + b"}"

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        rc = smoke.run("agnes", transport=transport)

    assert rc == 1
    assert "FAIL_MODELS_response_too_large" in stdout.getvalue()


# --------------------------------------------------------------------------
# Default invocation must not be able to reach Production
# --------------------------------------------------------------------------


def test_default_run_without_transport_is_blocked() -> None:
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        rc = smoke.run("agnes")

    output = stdout.getvalue()
    assert rc == 1
    assert "FAIL_TRANSPORT_NOT_AUTHORIZED" in output
    assert "DEFAULT_LIVE_EXECUTION=BLOCKED" in output
    assert "B14_CHAT_POST_COUNT=0" in output


def test_cli_without_arguments_is_blocked() -> None:
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        rc = smoke.main([])

    output = stdout.getvalue()
    assert rc == 1
    assert "FAIL_CANDIDATE_REQUIRED" in output
    assert "DEFAULT_LIVE_EXECUTION=BLOCKED" in output


def test_cli_without_authorization_marker_is_blocked() -> None:
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        rc = smoke.main(["agnes"])

    output = stdout.getvalue()
    assert rc == 1
    assert "FAIL_AUTHORIZATION_REQUIRED" in output
    assert "DEFAULT_LIVE_EXECUTION=BLOCKED" in output


def test_cli_with_excluded_candidate_is_blocked() -> None:
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        rc = smoke.main(["b-ai-qwen3.8", "--authorized-live-run"])

    assert rc == 1
    assert "FAIL_candidate_excluded" in stdout.getvalue()


def test_script_never_constructs_default_transport_on_import() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    # _request is only wired in from main() behind the explicit marker.
    assert "transport=_request" in source
    assert source.count("transport=_request") == 1
    # No module-level live execution.
    assert "if __name__ == \"__main__\":" in source


# --------------------------------------------------------------------------
# The Agnes-specific gate must remain intact and non-duplicated
# --------------------------------------------------------------------------


def test_agnes_gate_still_exists_with_its_own_contract() -> None:
    agnes_script = ROOT / ".github" / "scripts" / "b14_agnes_production_smoke.py"
    agnes_test = ROOT / ".github" / "tests" / "test_b14_agnes_production_smoke.py"
    agnes_wf = ROOT / ".github" / "workflows" / "b14-agnes-production-smoke.yml"
    assert agnes_script.is_file()
    assert agnes_test.is_file()
    assert agnes_wf.is_file()

    text = agnes_script.read_text(encoding="utf-8")
    assert 'MODEL_ID = "agnes-ai/agnes-3.0-flash"' in text
    assert "AGNES_ATTEMPT_COUNT=1" in text


def test_common_contract_and_agnes_gate_agree_on_agnes_identity() -> None:
    agnes = smoke.CANDIDATE_REGISTRY["agnes"]
    assert agnes.model_id == "agnes-ai/agnes-3.0-flash"
    assert agnes.upstream_model == "agnes-3.0-flash"
    assert agnes.provider_id == "agnes-ai"
    assert agnes.provider_name == "Agnes AI"
    assert agnes.credential_binding == "PADIEM_AGNES_API_KEY"


def test_neutral_module_does_not_duplicate_agnes_only_literals_as_globals() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    # The neutral module must not redefine the legacy Agnes-only globals as
    # module-level names. Match a declaration at column 0 only, so that
    # `AUTO_MODEL_ID = ...` is not mistaken for `MODEL_ID = ...`.
    lines = source.splitlines()
    assert not any(line.startswith("MODEL_ID = ") for line in lines)
    assert not any(line.startswith("PROVIDER_ID = ") for line in lines)
    assert not any(line.startswith("PROVIDER_NAME = ") for line in lines)
    assert not any(line.startswith("UPSTREAM_MODEL = ") for line in lines)
    # The Agnes-only model literal must not be re-globalized here either.
    assert 'PROVIDER_NAME = "Agnes AI"' not in source


# --------------------------------------------------------------------------
# BLOCKER 1 -- canonical served-version resolver reuse
#
# The gate must NOT scan the deployment history. It must hand the whole
# Cloudflare envelope to the shared canonical resolver, which pins the active
# deployment to result.deployments[0].
# --------------------------------------------------------------------------

ACTIVE_VERSION = "11111111-1111-1111-1111-111111111111"
HISTORICAL_VERSION = "22222222-2222-2222-2222-222222222222"


def _cf_envelope(*deployments, success: bool = True) -> dict:
    return {"success": success, "result": {"deployments": list(deployments)}}


def _cf_deployment(*versions) -> dict:
    return {"versions": list(versions)}


def _cf_served(version_id: object = ACTIVE_VERSION, percentage: object = 100) -> dict:
    return {"version_id": version_id, "percentage": percentage}


def test_canonical_resolver_is_reused_not_reimplemented() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "from cloudflare_served_version import" in source
    assert "resolve_served_version_id" in source
    assert "ServedVersionReason" in source
    # A local history walk is exactly the defect this replaces.
    assert "for deployment in deployments" not in source
    assert "cloudflare_served_version" in source


def test_active_first_deployment_expected_version_passes() -> None:
    payload = _cf_envelope(
        _cf_deployment(_cf_served(ACTIVE_VERSION)),
        _cf_deployment(_cf_served(HISTORICAL_VERSION, 0)),
    )
    assert smoke.assert_served_version(payload, ACTIVE_VERSION) == ACTIVE_VERSION


def test_expected_version_only_in_historical_deployment_fails() -> None:
    # The active deployment serves a *different* version; the expected id shows
    # up only in the previous deployment. Scanning history would pass this.
    payload = _cf_envelope(
        _cf_deployment(_cf_served(ACTIVE_VERSION)),
        _cf_deployment(_cf_served(HISTORICAL_VERSION)),
    )
    with pytest.raises(smoke.ServedVersionResolutionError):
        smoke.assert_served_version(payload, HISTORICAL_VERSION)


def test_historical_deployment_matching_100_percent_never_passes() -> None:
    # Both deployments claim 100 percent, but only the first is active.
    payload = _cf_envelope(
        _cf_deployment(_cf_served(ACTIVE_VERSION)),
        _cf_deployment(_cf_served(HISTORICAL_VERSION, 100)),
    )
    assert smoke.assert_served_version(payload, ACTIVE_VERSION) == ACTIVE_VERSION
    with pytest.raises(smoke.ServedVersionResolutionError):
        smoke.assert_served_version(payload, HISTORICAL_VERSION)


def test_multiple_active_versions_fails() -> None:
    payload = _cf_envelope(
        _cf_deployment(_cf_served(ACTIVE_VERSION), _cf_served(HISTORICAL_VERSION)),
    )
    with pytest.raises(smoke.ServedVersionResolutionError) as exc:
        smoke.assert_served_version(payload, ACTIVE_VERSION)
    assert exc.value.reason == smoke.ServedVersionReason.VERSION_COUNT


def test_active_version_fifty_fifty_fails() -> None:
    # A single version at 50 percent is not the canonical shape.
    payload = _cf_envelope(_cf_deployment({"version_id": ACTIVE_VERSION, "percentage": 50}))
    with pytest.raises(smoke.ServedVersionResolutionError) as exc:
        smoke.assert_served_version(payload, ACTIVE_VERSION)
    assert exc.value.reason == smoke.ServedVersionReason.TRAFFIC


def test_missing_or_unsafe_version_id_fails() -> None:
    for bad in (None, "", "   ", 12345, "ver A; rm -rf /", "a:b", "9" * 65):
        payload = _cf_envelope(_cf_deployment(_cf_served(bad)))
        with pytest.raises(smoke.ServedVersionResolutionError) as exc:
            smoke.resolve_active_served_version(payload)
        assert exc.value.reason == smoke.ServedVersionReason.VERSION_ID


def test_raw_list_and_result_versions_shortcut_fail() -> None:
    raw_list = [
        {"versions": [{"version_id": ACTIVE_VERSION, "percentage": 100}]},
        {"versions": [{"version_id": HISTORICAL_VERSION, "percentage": 100}]},
    ]
    with pytest.raises(smoke.ServedVersionResolutionError) as exc:
        smoke.resolve_active_served_version(raw_list)
    assert exc.value.reason == smoke.ServedVersionReason.ENVELOPE

    shortcut = {
        "success": True,
        "result": {"versions": [{"version_id": ACTIVE_VERSION, "percentage": 100}]},
    }
    with pytest.raises(smoke.ServedVersionResolutionError) as exc:
        smoke.resolve_active_served_version(shortcut)
    assert exc.value.reason == smoke.ServedVersionReason.DEPLOYMENT_RECORDS


def test_unsuccessful_envelope_fails() -> None:
    payload = _cf_envelope(_cf_deployment(_cf_served(ACTIVE_VERSION)), success=False)
    with pytest.raises(smoke.ServedVersionResolutionError) as exc:
        smoke.resolve_active_served_version(payload)
    assert exc.value.reason == smoke.ServedVersionReason.ENVELOPE


def test_workflow_uses_canonical_resolver_and_no_history_scan() -> None:
    wf = WORKFLOW.read_text(encoding="utf-8")
    assert "resolve_served_version_id(payload)" in wf
    assert "from cloudflare_served_version import" in wf
    assert "CANONICAL_SERVED_VERSION_REUSED=YES" in wf
    assert "HISTORICAL_DEPLOYMENT_ACCEPTED=NO" in wf

    # The workflow's own guard step quotes the forbidden shapes as grep
    # patterns and documents them in comments, so a plain substring check would
    # false-positive. Inspect only the executable Python embedded in the
    # resolver step: there must be no local loop over deployment history, no
    # entry-position selection, and no envelope re-serialization.
    resolver_step = wf.split("GET-only B14 served-version guard")[1]
    resolver_step = resolver_step.split("Execute exactly one bounded candidate")[0]
    code_lines = []
    for line in resolver_step.splitlines():
        stripped = line.strip()
        if "grep" in line or stripped.startswith("#"):
            continue
        code_lines.append(line)
    code = "\n".join(code_lines)
    assert "for deployment in deployments" not in code
    assert "deployments[0]" not in code  # the resolver owns entry selection
    assert 'result", {}).get("deployments"' not in code


# --------------------------------------------------------------------------
# BLOCKER 2 -- untrusted provider error.code must be redacted
#
# error.code and error.message are untrusted diagnostic input from an upstream
# provider body. Only a closed local vocabulary may reach stdout.
# --------------------------------------------------------------------------

SECRET_SENTINEL = "SECRET_SENTINEL_123"
PRIVATE_SENTINEL = "PRIVATE_SENTINEL"


def test_arbitrary_error_code_is_redacted() -> None:
    spec_obj = smoke.CANDIDATE_REGISTRY["agnes"]

    def transport(method: str, path: str, body: dict | None):
        if path == smoke.HEALTH_PATH:
            return 200, _health(spec_obj)
        if path == smoke.MODELS_PATH:
            return 200, _models(spec_obj)
        return 503, _json({"error": {"code": SECRET_SENTINEL, "message": PRIVATE_SENTINEL}})

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        rc = smoke.run("agnes", transport=transport)

    output = stdout.getvalue()
    assert rc == 1
    assert SECRET_SENTINEL not in output
    assert PRIVATE_SENTINEL not in output
    assert "ENGINE_ERROR_CODE=unknown" in output
    assert "FAIL_CHAT_HTTP_503" in output


def test_canonical_safe_error_code_is_projected() -> None:
    spec_obj = smoke.CANDIDATE_REGISTRY["agnes"]

    def transport(method: str, path: str, body: dict | None):
        if path == smoke.HEALTH_PATH:
            return 200, _health(spec_obj)
        if path == smoke.MODELS_PATH:
            return 200, _models(spec_obj)
        return 429, _json({"error": {"code": "rate_limit_error", "message": PRIVATE_SENTINEL}})

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        smoke.run("agnes", transport=transport)

    output = stdout.getvalue()
    assert "ENGINE_ERROR_CODE=rate_limit_error" in output
    assert PRIVATE_SENTINEL not in output


def test_unparseable_body_is_locally_classified() -> None:
    spec_obj = smoke.CANDIDATE_REGISTRY["agnes"]

    def transport(method: str, path: str, body: dict | None):
        if path == smoke.HEALTH_PATH:
            return 200, _health(spec_obj)
        if path == smoke.MODELS_PATH:
            return 200, _models(spec_obj)
        return 500, b"not json at all " + PRIVATE_SENTINEL.encode()

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        smoke.run("agnes", transport=transport)

    output = stdout.getvalue()
    assert "ENGINE_ERROR_CODE=unparseable" in output
    assert PRIVATE_SENTINEL not in output


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"error": {"code": SECRET_SENTINEL}}, "unknown"),
        ({"error": {"code": "rate_limit_error"}}, "rate_limit_error"),
        ({"error": {"code": "totally_made_up"}}, "unknown"),
        ({"error": {"code": 42}}, "unknown"),
        ({"error": {"code": None}}, "unknown"),
        ({"error": "not-a-dict"}, "unknown"),
        ({}, "unknown"),
        ({"error": {"message": PRIVATE_SENTINEL}}, "unknown"),
    ],
)
def test_safe_error_code_projection_is_closed(payload: dict, expected: str) -> None:
    projected = smoke._safe_error_code(payload)
    assert projected == expected
    assert projected in smoke.SAFE_ENGINE_ERROR_CODES
    assert SECRET_SENTINEL not in projected
    assert PRIVATE_SENTINEL not in projected


def test_error_code_vocabulary_is_closed_and_bounded() -> None:
    assert "unknown" in smoke.SAFE_ENGINE_ERROR_CODES
    assert "unparseable" in smoke.SAFE_ENGINE_ERROR_CODES
    for code in smoke.SAFE_ENGINE_ERROR_CODES:
        assert code == code.strip().lower()
        assert " " not in code
        assert 1 <= len(code) <= 64


def test_source_contract_forbids_raw_error_code_echo() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "SAFE_ENGINE_ERROR_CODES" in source
    # The pre-fix shape returned an arbitrary bounded-length string verbatim.
    legacy = (
        "return code if isinstance(code, str) "
        'and 1 <= len(code) <= 96 else "unknown"'
    )
    assert legacy not in source
    assert 'return code if code in SAFE_ENGINE_ERROR_CODES else "unknown"' in source
