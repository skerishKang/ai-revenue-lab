"""Contract tests for the Gemini-only B14 one-shot live gate (#4499).

These tests never make a live provider call: every transport is a synthetic
in-process fake. A default invocation of the gate module is blocked.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github" / "scripts" / "b14_gemini_live_oneshot.py"
WORKFLOW = ROOT / ".github" / "workflows" / "b14-gemini-live-oneshot.yml"

spec = importlib.util.spec_from_file_location("b14_gemini_live_oneshot", SCRIPT)
assert spec is not None and spec.loader is not None
oneshot = importlib.util.module_from_spec(spec)
# The module uses `from __future__ import annotations` together with a
# `@dataclass(frozen=True)`, whose decoration resolves annotation strings via
# `sys.modules[cls.__module__]`. Registering before exec is therefore required.
sys.modules[spec.name] = oneshot
spec.loader.exec_module(oneshot)


GEMINI_31 = "google/gemini-3.1-flash-lite"
GEMINI_35 = "google/gemini-3.5-flash-lite"


def _json(value: dict) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode("utf-8")


def _health(model_id: str, *, has_key: bool = True) -> bytes:
    return _json(
        {
            "status": "ok",
            "business14": {
                "provider_mode": "live",
                "providers": [
                    {"id": "google", "registered": True, "has_key": has_key}
                ],
            },
        }
    )


def _models(model_id: str, *, enabled: bool = True) -> bytes:
    upstream = model_id.split("/", 1)[1]
    routes = [
        {
            "id": model_id,
            "provider_id": "google",
            "upstream_model": upstream,
        }
    ]
    catalog = [{"id": model_id, "name": f"Google: {upstream}"}] if enabled else []
    return _json({"registered_routes": routes, "catalog": catalog})


def _chat(model_id: str) -> bytes:
    upstream = model_id.split("/", 1)[1]
    return _json(
        {
            "id": "synthetic",
            "object": "chat.completion",
            "model": upstream,
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
                "provider": "Google AI Studio",
                "selected_provider": "Google AI Studio",
                "model_route": model_id,
                "selected_model": model_id,
                "upstream_model": upstream,
                "selected_upstream_model": upstream,
                "actual_response_model": upstream,
                "route_mode": "manual",
                "fallback_used": False,
                "attempt_count": 1,
                "route_evidence_status": "live_verified",
            },
        }
    )


def _happy_transport(model_id: str, calls: list | None = None, **kwargs):
    has_key = kwargs.get("has_key", True)
    enabled = kwargs.get("enabled", True)

    def transport(method: str, path: str, body: dict | None):
        if calls is not None:
            calls.append((method, path, body))
        if path == oneshot.HEALTH_PATH:
            return 200, _health(model_id, has_key=has_key)
        if path == oneshot.MODELS_PATH:
            return 200, _models(model_id, enabled=enabled)
        if path == oneshot.CHAT_PATH:
            return 200, _chat(model_id)
        raise AssertionError(path)

    return transport


def _run_capture(model_id: str, transport, **kwargs) -> tuple[int, str]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = oneshot.run(model_id, transport=transport, **kwargs)
    return code, buf.getvalue()


# --------------------------------------------------------------------------
# Exact-ID allowlist
# --------------------------------------------------------------------------


def test_allowlist_is_exactly_the_two_gemini_ids() -> None:
    assert oneshot.GEMINI_MODEL_IDS == (GEMINI_31, GEMINI_35)
    assert set(oneshot.GEMINI_REGISTRY) == {GEMINI_31, GEMINI_35}
    for model_id in (GEMINI_31, GEMINI_35):
        resolved = oneshot.resolve_gemini(model_id)
        assert resolved.provider_id == "google"
        assert resolved.model_id == model_id
        assert resolved.upstream_model == model_id.split("/", 1)[1]


def test_auto_route_is_not_permitted() -> None:
    with pytest.raises(ValueError, match="auto_route_not_permitted"):
        oneshot.resolve_gemini("b14/auto")


def test_out_of_scope_models_are_rejected() -> None:
    for blocked in (
        "experiential/qwen3.8-flash-next-uncensored",
        "opencode-go/muse-spark-1.3-contributor",
        "b-ai/qwen3.8-flash",
    ):
        with pytest.raises(ValueError, match="model_out_of_scope"):
            oneshot.resolve_gemini(blocked)


def test_unknown_model_fails_closed() -> None:
    with pytest.raises(ValueError, match="model_not_allowlisted"):
        oneshot.resolve_gemini("google/gemini-9.9-flash-lite")
    code, out = _run_capture("google/gemini-9.9-flash-lite", transport=_happy_transport(GEMINI_31))
    assert code == 1
    assert "B14_CHAT_POST_COUNT=0" in out


def test_every_model_carries_exact_identity_and_binding_name() -> None:
    for model_id, resolved in oneshot.GEMINI_REGISTRY.items():
        assert resolved.model_id == model_id
        assert model_id == f"google/{resolved.upstream_model}"
        assert resolved.credential_binding == "PADIEM_GEMINI_API_KEY"
        assert resolved.expected_binding == "PADIEM_GEMINI_API_KEY"


def test_contract_constants_pin_one_call_no_retry_no_fallback() -> None:
    assert oneshot.MAX_PROVIDER_CALLS == 1
    assert oneshot.RETRY == 0
    assert oneshot.FALLBACK == 0
    assert oneshot.AUTO_MODEL_ID == "b14/auto"
    assert oneshot.DEFAULT_LIVE_EXECUTION == "BLOCKED"
    assert oneshot.PRIVATE_PAYLOAD_OUTPUT == 0
    assert oneshot.SECRET_VALUE_OUTPUT == 0
    assert oneshot.PRODUCTION_MUTATION == 0
    assert oneshot.RAW_RESPONSE_CONTENT_OUTPUT == 0


# --------------------------------------------------------------------------
# Bounded happy path — one POST per model, separately
# --------------------------------------------------------------------------


@pytest.mark.parametrize("model_id", [GEMINI_31, GEMINI_35])
def test_success_uses_two_gets_and_exactly_one_chat_post(model_id: str) -> None:
    calls: list = []
    code, out = _run_capture(model_id, transport=_happy_transport(model_id, calls))
    assert code == 0
    posts = [c for c in calls if c[0] == "POST"]
    assert len(calls) == 3
    assert len(posts) == 1
    assert posts[0][1] == oneshot.CHAT_PATH
    prefix = "GEMINI_3_1" if model_id == GEMINI_31 else "GEMINI_3_5"
    assert f"{prefix}_PRODUCTION_SMOKE=PASS" in out
    assert f"{prefix}_MODEL_ID_MATCH=YES" in out
    assert f"{prefix}_STREAMING=NOT_TESTED" in out
    assert "B14_CHAT_POST_COUNT=1" in out
    assert "NETWORK_RETRY_COUNT=0" in out
    assert "FALLBACK_CALL_COUNT=0" in out
    assert "RETRY=0" in out
    assert "FALLBACK=0" in out
    assert "AUTO_ROUTE_USED=0" in out
    assert "PRODUCTION_MUTATION=0" in out


@pytest.mark.parametrize("model_id", [GEMINI_31, GEMINI_35])
def test_chat_body_pins_exact_manual_model_never_auto(model_id: str) -> None:
    body = oneshot.canonical_chat_body(oneshot.resolve_gemini(model_id))
    assert body["model"] == model_id
    assert body["model"] != "b14/auto"
    assert body["max_tokens"] == oneshot.SYNTHETIC_MAX_TOKENS
    assert body["max_tokens"] <= 16
    # Synthetic prompt only: no customer payload markers.
    prompt = body["messages"][0]["content"]
    assert isinstance(prompt, str)
    assert "정상" in prompt
    for marker in ("customer", "quote", "견적서", "회사", "invoice"):
        assert marker not in prompt


def test_expected_binding_name_is_emitted_without_any_secret_value() -> None:
    _, out = _run_capture(GEMINI_31, transport=_happy_transport(GEMINI_31))
    assert "EXPECTED_BINDING=PADIEM_GEMINI_API_KEY" in out
    assert "CREDENTIAL_BOUND=YES" in out
    # No secret-looking value may appear; the sentinel answer stays private.
    assert "PRIVATE_ANSWER_SENTINEL_42" not in out
    assert "정상" not in out


def test_latency_evidence_is_recorded() -> None:
    _, out = _run_capture(GEMINI_31, transport=_happy_transport(GEMINI_31))
    assert "GEMINI_3_1_LATENCY_MS=" in out
    assert "GEMINI_3_1_LATENCY_CLASS=" in out
    assert "GEMINI_3_1_HTTP_CLASS=2xx" in out


# --------------------------------------------------------------------------
# Fail-closed gates before / at the single POST
# --------------------------------------------------------------------------


def test_missing_credential_fails_before_chat_post() -> None:
    calls: list = []
    code, out = _run_capture(
        GEMINI_31, transport=_happy_transport(GEMINI_31, calls, has_key=False)
    )
    assert code == 1
    assert "FAIL_CREDENTIAL_NOT_READY" in out
    assert "CREDENTIAL_BOUND=NO" in out
    assert "B14_CHAT_POST_COUNT=0" in out
    assert not [c for c in calls if c[0] == "POST"]


def test_disabled_route_fails_before_provider_post() -> None:
    calls: list = []
    code, out = _run_capture(
        GEMINI_31, transport=_happy_transport(GEMINI_31, calls, enabled=False)
    )
    assert code == 1
    assert "FAIL_ROUTE_NOT_ENABLED" in out
    assert "B14_CHAT_POST_COUNT=0" in out
    assert not [c for c in calls if c[0] == "POST"]


def test_wrong_route_identity_fails_before_provider_post() -> None:
    def transport(method: str, path: str, body: dict | None):
        if path == oneshot.HEALTH_PATH:
            return 200, _health(GEMINI_31)
        if path == oneshot.MODELS_PATH:
            return 200, _json(
                {
                    "registered_routes": [
                        {
                            "id": GEMINI_31,
                            "provider_id": "google",
                            "upstream_model": "gemini-9.9-flash-lite",
                        }
                    ],
                    "catalog": [{"id": GEMINI_31, "name": "x"}],
                }
            )
        raise AssertionError(path)

    code, out = _run_capture(GEMINI_31, transport=transport)
    assert code == 1
    assert "FAIL_ROUTE_IDENTITY" in out
    assert "B14_CHAT_POST_COUNT=0" in out


def test_actual_response_model_mismatch_is_failure_not_fallback() -> None:
    def transport(method: str, path: str, body: dict | None):
        if path == oneshot.HEALTH_PATH:
            return 200, _health(GEMINI_31)
        if path == oneshot.MODELS_PATH:
            return 200, _models(GEMINI_31)
        if path == oneshot.CHAT_PATH:
            payload = json.loads(_chat(GEMINI_31).decode("utf-8"))
            payload["business14"]["actual_response_model"] = "gemini-9.9-flash-lite"
            return 200, _json(payload)
        raise AssertionError(path)

    code, out = _run_capture(GEMINI_31, transport=transport)
    assert code == 1
    assert "FAIL_ROUTE_METADATA" in out
    assert "GEMINI_3_1_FAILED_METADATA_CHECKS=" in out
    assert "B14_CHAT_POST_COUNT=1" in out
    assert "FALLBACK_CALL_COUNT=0" in out


def test_attempt_count_two_or_fallback_true_is_failure() -> None:
    def transport(method: str, path: str, body: dict | None):
        if path == oneshot.HEALTH_PATH:
            return 200, _health(GEMINI_35)
        if path == oneshot.MODELS_PATH:
            return 200, _models(GEMINI_35)
        if path == oneshot.CHAT_PATH:
            payload = json.loads(_chat(GEMINI_35).decode("utf-8"))
            payload["business14"]["attempt_count"] = 2
            payload["business14"]["fallback_used"] = True
            return 200, _json(payload)
        raise AssertionError(path)

    code, out = _run_capture(GEMINI_35, transport=transport)
    assert code == 1
    assert "FAIL_ROUTE_METADATA" in out


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_non_200_chat_emits_only_safe_error_code_and_no_private_payload(status: int) -> None:
    def transport(method: str, path: str, body: dict | None):
        if path == oneshot.HEALTH_PATH:
            return 200, _health(GEMINI_31)
        if path == oneshot.MODELS_PATH:
            return 200, _models(GEMINI_31)
        if path == oneshot.CHAT_PATH:
            return status, _json(
                {"error": {"code": "rate_limit_error", "message": "SECRET_SENTINEL_9"}}
            )
        raise AssertionError(path)

    code, out = _run_capture(GEMINI_31, transport=transport)
    assert code == 1
    assert f"FAIL_CHAT_HTTP_{status}" in out
    assert "SECRET_SENTINEL_9" not in out
    expected_class = {401: "auth", 403: "auth", 429: "rate_limited", 500: "server_error"}[status]
    assert f"GEMINI_3_1_HTTP_CLASS={expected_class}" in out
    assert "B14_CHAT_POST_COUNT=1" in out
    assert "NETWORK_RETRY_COUNT=0" in out


def test_response_size_bound_is_enforced() -> None:
    big = b"x" * (oneshot.MAX_RESPONSE_BYTES + 1)

    def transport(method: str, path: str, body: dict | None):
        if path == oneshot.HEALTH_PATH:
            return 200, big
        raise AssertionError(path)

    code, out = _run_capture(GEMINI_31, transport=transport)
    assert code == 1
    assert "B14_CHAT_POST_COUNT=0" in out


# --------------------------------------------------------------------------
# Default invocation is blocked
# --------------------------------------------------------------------------


def test_default_run_without_transport_is_blocked() -> None:
    for model_id in (GEMINI_31, GEMINI_35):
        code, out = _run_capture(model_id, transport=None)
        assert code == 1
        assert "FAIL_TRANSPORT_NOT_AUTHORIZED" in out
        assert "DEFAULT_LIVE_EXECUTION=BLOCKED" in out
        assert "B14_CHAT_POST_COUNT=0" in out


def test_cli_without_arguments_is_blocked() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = oneshot.main([])
    assert code == 1
    assert "FAIL_MODEL_REQUIRED" in buf.getvalue()
    assert "DEFAULT_LIVE_EXECUTION=BLOCKED" in buf.getvalue()


def test_cli_without_authorization_marker_is_blocked() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = oneshot.main([GEMINI_31])
    assert code == 1
    assert "FAIL_AUTHORIZATION_REQUIRED" in buf.getvalue()


def test_cli_with_out_of_scope_model_is_blocked() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = oneshot.main(
            ["opencode-go/muse-spark-1.3-contributor", "--authorized-live-run"]
        )
    assert code == 1
    assert "FAIL_model_out_of_scope" in buf.getvalue()


def test_script_never_constructs_default_transport_on_import() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "transport=_request" in source
    # Only the authorized CLI entry wires the real transport.
    assert source.count("_request") <= 3


# --------------------------------------------------------------------------
# Canonical served-version reuse (not reimplementation)
# --------------------------------------------------------------------------


def _deployments_payload(versions: list) -> dict:
    return {
        "success": True,
        "result": {"deployments": [{"versions": versions}]},
    }


def test_canonical_resolver_is_reused_not_reimplemented() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "from cloudflare_served_version import" in source
    assert "resolve_served_version_id" in source
    # No local deployment-history scan shapes.
    assert "for deployment in deployments" not in source
    assert "deployments[0]" not in source


def test_active_first_deployment_expected_version_passes() -> None:
    payload = _deployments_payload(
        [{"version_id": "v-abc123", "percentage": 100}]
    )
    assert oneshot.assert_served_version(payload, "v-abc123") == "v-abc123"


def test_expected_version_only_in_historical_deployment_fails() -> None:
    payload = {
        "success": True,
        "result": {
            "deployments": [
                {"versions": [{"version_id": "v-new", "percentage": 100}]},
                {"versions": [{"version_id": "v-old", "percentage": 100}]},
            ]
        },
    }
    with pytest.raises(Exception):
        oneshot.assert_served_version(payload, "v-old")


def test_multiple_active_versions_fail() -> None:
    payload = _deployments_payload(
        [
            {"version_id": "v-a", "percentage": 50},
            {"version_id": "v-b", "percentage": 50},
        ]
    )
    with pytest.raises(Exception):
        oneshot.assert_served_version(payload, "v-a")


def test_missing_or_unsafe_version_id_fails() -> None:
    with pytest.raises(Exception):
        oneshot.assert_served_version({"success": True, "result": {}}, "v-a")
    payload = _deployments_payload(
        [{"version_id": "v;rm -rf", "percentage": 100}]
    )
    with pytest.raises(Exception):
        oneshot.assert_served_version(payload, "v;rm -rf")


# --------------------------------------------------------------------------
# Closed error-code vocabulary
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"error": {"code": "rate_limit_error"}}, "rate_limit_error"),
        ({"error": {"code": "authentication_error"}}, "authentication_error"),
        ({"error": {"code": "BOGUS_VENDOR_CODE_X"}}, "unknown"),
        ({"error": {"message": "no code"}}, "unknown"),
        ({}, "unknown"),
    ],
)
def test_safe_error_code_projection_is_closed(payload: dict, expected: str) -> None:
    assert oneshot._safe_error_code(payload) == expected


def test_source_contract_forbids_raw_error_code_echo() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "SAFE_ENGINE_ERROR_CODES" in source
    assert 'return code if code in SAFE_ENGINE_ERROR_CODES else "unknown"' in source


# --------------------------------------------------------------------------
# Source-contract pins on the workflow file itself
# --------------------------------------------------------------------------


def test_workflow_file_exists_with_exact_two_model_allowlist() -> None:
    assert WORKFLOW.exists()
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "google/gemini-3.1-flash-lite" in text
    assert "google/gemini-3.5-flash-lite" in text
    assert "RUN_B14_GEMINI_LIVE_ONESHOT_ONCE" in text
    assert "environment: production" in text
    assert "b14_gemini_live_oneshot.py" in text
    assert "resolve_served_version_id(payload)" in text
    assert "CANONICAL_SERVED_VERSION_REUSED=YES" in text
    # The generic candidate workflow must not be widened by this change.
    generic = ROOT / ".github" / "workflows" / "b14-candidate-live-smoke.yml"
    generic_text = generic.read_text(encoding="utf-8")
    assert "gemini" not in generic_text.lower()


def test_no_product_route_files_are_touched() -> None:
    forbidden = [
        "apps/padiem-chat/static/app.js",
        "app_factory.py",
        "product_tier_routes.py",
    ]
    for name in forbidden:
        assert name not in SCRIPT.read_text(encoding="utf-8")
