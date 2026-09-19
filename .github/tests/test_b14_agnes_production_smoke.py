from __future__ import annotations

import contextlib
import importlib.util
import io
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github" / "scripts" / "b14_agnes_production_smoke.py"

spec = importlib.util.spec_from_file_location("b14_agnes_production_smoke", SCRIPT)
assert spec is not None and spec.loader is not None
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def _json(value: dict) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode("utf-8")


def _health(*, has_key: bool = True) -> bytes:
    return _json(
        {
            "status": "ok",
            "business14": {
                "provider_mode": "live",
                "providers": [
                    {"id": "agnes-ai", "registered": True, "has_key": has_key}
                ],
            },
        }
    )


def _models() -> bytes:
    return _json(
        {
            "registered_routes": [
                {
                    "id": smoke.MODEL_ID,
                    "provider_id": smoke.PROVIDER_ID,
                    "upstream_model": smoke.UPSTREAM_MODEL,
                }
            ]
        }
    )


def _chat() -> bytes:
    return _json(
        {
            "id": "synthetic",
            "object": "chat.completion",
            "model": smoke.UPSTREAM_MODEL,
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
                "provider": smoke.PROVIDER_NAME,
                "selected_provider": smoke.PROVIDER_NAME,
                "model_route": smoke.MODEL_ID,
                "selected_model": smoke.MODEL_ID,
                "upstream_model": smoke.UPSTREAM_MODEL,
                "selected_upstream_model": smoke.UPSTREAM_MODEL,
                "actual_response_model": smoke.UPSTREAM_MODEL,
                "route_mode": "manual",
                "fallback_used": False,
                "attempt_count": 1,
                "route_evidence_status": "live_verified",
            },
        }
    )


def test_fixed_contract_is_exact_agnes_manual_route() -> None:
    assert smoke.MODEL_ID == "agnes-ai/agnes-3.0-flash"
    assert smoke.UPSTREAM_MODEL == "agnes-3.0-flash"
    assert smoke.PROVIDER_ID == "agnes-ai"
    assert smoke.PROVIDER_NAME == "Agnes AI"
    assert smoke.canonical_chat_body() == {
        "model": "agnes-ai/agnes-3.0-flash",
        "messages": [
            {
                "role": "user",
                "content": "Production route smoke. Reply with the single word OK.",
            }
        ],
        "temperature": 0,
        "max_tokens": 8,
    }


def test_success_uses_two_gets_and_exactly_one_chat_post() -> None:
    calls: list[tuple[str, str, dict | None]] = []

    def transport(method: str, path: str, body: dict | None):
        calls.append((method, path, body))
        if path == smoke.HEALTH_PATH:
            return 200, _health()
        if path == smoke.MODELS_PATH:
            return 200, _models()
        if path == smoke.CHAT_PATH:
            return 200, _chat()
        raise AssertionError(path)

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        rc = smoke.run(transport=transport)

    assert rc == 0
    assert [(m, p) for m, p, _ in calls] == [
        ("GET", smoke.HEALTH_PATH),
        ("GET", smoke.MODELS_PATH),
        ("POST", smoke.CHAT_PATH),
    ]
    output = stdout.getvalue()
    assert "AGNES_PRODUCTION_SMOKE=PASS" in output
    assert "AGNES_ATTEMPT_COUNT=1" in output
    assert "B14_CHAT_POST_COUNT=1" in output
    assert "NETWORK_RETRY_COUNT=0" in output
    assert "RAW_RESPONSE_CONTENT_OUTPUT=0" in output
    assert "SECRET_VALUE_OUTPUT=0" in output
    assert "PRIVATE_ANSWER_SENTINEL_42" not in output


def test_missing_credential_fails_before_chat_post() -> None:
    calls: list[tuple[str, str]] = []

    def transport(method: str, path: str, body: dict | None):
        calls.append((method, path))
        if path == smoke.HEALTH_PATH:
            return 200, _health(has_key=False)
        raise AssertionError("must fail before models/chat")

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        rc = smoke.run(transport=transport)

    assert rc == 1
    assert calls == [("GET", smoke.HEALTH_PATH)]
    assert "FAIL_CREDENTIAL_NOT_READY" in stdout.getvalue()
    assert "B14_CHAT_POST_COUNT=0" in stdout.getvalue()


def test_wrong_route_fails_before_provider_post() -> None:
    def transport(method: str, path: str, body: dict | None):
        if path == smoke.HEALTH_PATH:
            return 200, _health()
        if path == smoke.MODELS_PATH:
            return 200, _json(
                {
                    "registered_routes": [
                        {
                            "id": smoke.MODEL_ID,
                            "provider_id": "wrong-provider",
                            "upstream_model": smoke.UPSTREAM_MODEL,
                        }
                    ]
                }
            )
        raise AssertionError("must fail before chat")

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        rc = smoke.run(transport=transport)

    assert rc == 1
    assert "FAIL_ROUTE_IDENTITY" in stdout.getvalue()
    assert "B14_CHAT_POST_COUNT=0" in stdout.getvalue()


def test_non_200_chat_emits_only_safe_error_code() -> None:
    raw_secret = "sensitive-provider-detail"

    def transport(method: str, path: str, body: dict | None):
        if path == smoke.HEALTH_PATH:
            return 200, _health()
        if path == smoke.MODELS_PATH:
            return 200, _models()
        if path == smoke.CHAT_PATH:
            return 503, _json(
                {
                    "error": {
                        "code": "no_safe_route",
                        "message": raw_secret,
                    }
                }
            )
        raise AssertionError(path)

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        rc = smoke.run(transport=transport)

    output = stdout.getvalue()
    assert rc == 1
    assert "FAIL_CHAT_HTTP_503" in output
    assert "ENGINE_ERROR_CODE=no_safe_route" in output
    assert raw_secret not in output
    assert "B14_CHAT_POST_COUNT=1" in output
    assert "NETWORK_RETRY_COUNT=0" in output


def test_success_requires_exact_live_agnes_metadata_and_one_attempt() -> None:
    payload = json.loads(_chat().decode("utf-8"))
    payload["business14"]["attempt_count"] = 2
    payload["business14"]["fallback_used"] = True
    payload["business14"]["actual_response_model"] = "other-model"

    def transport(method: str, path: str, body: dict | None):
        if path == smoke.HEALTH_PATH:
            return 200, _health()
        if path == smoke.MODELS_PATH:
            return 200, _models()
        return 200, _json(payload)

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        rc = smoke.run(transport=transport)

    output = stdout.getvalue()
    assert rc == 1
    assert "AGNES_PRODUCTION_SMOKE=FAIL_ROUTE_METADATA" in output
    assert "actual_response_model" in output
    assert "attempt_count" in output
    assert "fallback_used" in output
    assert "B14_CHAT_POST_COUNT=1" in output


# --------------------------------------------------------------------------
# #2804 -- served-version guard convergence onto the canonical resolver.
#
# The served-version rule lives in the workflow, not in the smoke runtime, so
# the convergence is asserted against the workflow's embedded resolver code.
# This never makes a live call: every payload below is synthetic.
# --------------------------------------------------------------------------

WORKFLOW = ROOT / ".github" / "workflows" / "b14-agnes-production-smoke.yml"

ACTIVE_VERSION = "11111111-1111-1111-1111-111111111111"
HISTORICAL_VERSION = "22222222-2222-2222-2222-222222222222"


def _cf_envelope(*deployments, success: bool = True) -> dict:
    return {"success": success, "result": {"deployments": list(deployments)}}


def _cf_deployment(*versions) -> dict:
    return {"versions": list(versions)}


def _cf_served(version_id: object = ACTIVE_VERSION, percentage: object = 100) -> dict:
    return {"version_id": version_id, "percentage": percentage}


def _canonical_resolver():
    """Load the shared canonical served-version resolver."""
    import importlib.util
    import sys as _sys

    path = ROOT / ".github" / "scripts" / "cloudflare_served_version.py"
    _spec = importlib.util.spec_from_file_location("cloudflare_served_version", path)
    assert _spec is not None and _spec.loader is not None
    module = importlib.util.module_from_spec(_spec)
    _sys.modules[_spec.name] = module
    _spec.loader.exec_module(module)
    return module


def _workflow_embedded_resolver_code() -> str:
    """Return the workflow's embedded served-version Python, minus comments.

    The source-contract pin step also embeds Python and quotes both the
    resolver call and the forbidden shapes as strings, so that block is
    skipped explicitly -- otherwise it would inspect itself.
    """
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    for idx, line in enumerate(lines):
        if "<<'PY'" not in line:
            continue
        end = next(
            (i for i in range(idx + 1, len(lines)) if lines[i].strip() == "PY"),
            None,
        )
        if end is None:
            continue
        block = lines[idx + 1 : end]
        if "CANONICAL_SERVED_VERSION_REUSE_CONTRACT" in "\n".join(block):
            continue
        if not any("resolve_served_version_id(payload)" in l for l in block):
            continue
        exec_lines = [
            l for l in block if "grep" not in l and not l.strip().startswith("#")
        ]
        return "\n".join(exec_lines)
    raise AssertionError("workflow embedded resolver not found")


def test_workflow_delegates_to_the_canonical_resolver() -> None:
    wf = WORKFLOW.read_text(encoding="utf-8")
    assert "from cloudflare_served_version import" in wf
    assert "resolve_served_version_id(payload)" in wf
    assert "CANONICAL_SERVED_VERSION_REUSED=YES" in wf
    assert "HISTORICAL_DEPLOYMENT_ACCEPTED=NO" in wf


def test_no_local_history_scan_or_envelope_reserialization() -> None:
    code = _workflow_embedded_resolver_code()
    assert "for " + "deployment in deployments" not in code
    assert "deployments" + "[0]" not in code
    assert 'payload.get("result", {}).get("deployments"' not in code


def test_active_first_deployment_expected_version_resolves() -> None:
    resolver = _canonical_resolver()
    payload = _cf_envelope(
        _cf_deployment(_cf_served(ACTIVE_VERSION)),
        _cf_deployment(_cf_served(HISTORICAL_VERSION, 0)),
    )
    assert resolver.resolve_served_version_id(payload) == ACTIVE_VERSION


def test_expected_version_only_in_historical_deployment_fails() -> None:
    # The active deployment serves a different version; the expected id appears
    # only in a previous deployment. The resolver still resolves the ACTIVE
    # version, so the guard's `resolved == expected` comparison must fail.
    # Scanning history is what would have accepted this before.
    resolver = _canonical_resolver()
    payload = _cf_envelope(
        _cf_deployment(_cf_served(ACTIVE_VERSION)),
        _cf_deployment(_cf_served(HISTORICAL_VERSION, 100)),
    )
    resolved = resolver.resolve_served_version_id(payload)
    assert resolved == ACTIVE_VERSION
    # The guard rejects this: the expected (historical-only) id is not served.
    assert resolved != HISTORICAL_VERSION


def test_historical_deployment_at_100_never_satisfies_expected() -> None:
    # Both deployments claim 100 percent, but only the first is active.
    resolver = _canonical_resolver()
    payload = _cf_envelope(
        _cf_deployment(_cf_served(ACTIVE_VERSION)),
        _cf_deployment(_cf_served(HISTORICAL_VERSION, 100)),
    )
    assert resolver.resolve_served_version_id(payload) == ACTIVE_VERSION


def test_raw_list_is_refused() -> None:
    resolver = _canonical_resolver()
    raw_list = [
        {"versions": [{"version_id": ACTIVE_VERSION, "percentage": 100}]},
        {"versions": [{"version_id": HISTORICAL_VERSION, "percentage": 100}]},
    ]
    try:
        resolver.resolve_served_version_id(raw_list)
    except resolver.ServedVersionResolutionError as exc:
        assert exc.reason == resolver.ServedVersionReason.ENVELOPE
        return
    raise AssertionError("raw list was accepted")


def test_result_versions_shortcut_is_refused() -> None:
    resolver = _canonical_resolver()
    shortcut = {
        "success": True,
        "result": {"versions": [{"version_id": ACTIVE_VERSION, "percentage": 100}]},
    }
    try:
        resolver.resolve_served_version_id(shortcut)
    except resolver.ServedVersionResolutionError as exc:
        assert exc.reason == resolver.ServedVersionReason.DEPLOYMENT_RECORDS
        return
    raise AssertionError("result.versions shortcut was accepted")


def test_multiple_active_versions_and_partial_traffic_are_refused() -> None:
    resolver = _canonical_resolver()
    two = _cf_envelope(
        _cf_deployment(_cf_served(ACTIVE_VERSION), _cf_served(HISTORICAL_VERSION)),
    )
    try:
        resolver.resolve_served_version_id(two)
    except resolver.ServedVersionResolutionError as exc:
        assert exc.reason == resolver.ServedVersionReason.VERSION_COUNT
    else:
        raise AssertionError("two active versions were accepted")

    partial = _cf_envelope(_cf_deployment({"version_id": ACTIVE_VERSION, "percentage": 50}))
    try:
        resolver.resolve_served_version_id(partial)
    except resolver.ServedVersionResolutionError as exc:
        assert exc.reason == resolver.ServedVersionReason.TRAFFIC
    else:
        raise AssertionError("partial traffic was accepted")


def test_unsafe_version_id_is_refused() -> None:
    resolver = _canonical_resolver()
    for bad in (None, "", "   ", 12345, "ver A; rm -rf /", "a:b", "9" * 65):
        payload = _cf_envelope(_cf_deployment(_cf_served(bad)))
        try:
            resolver.resolve_served_version_id(payload)
        except resolver.ServedVersionResolutionError as exc:
            assert exc.reason == resolver.ServedVersionReason.VERSION_ID
        else:
            raise AssertionError(f"unsafe version id accepted: {bad!r}")


def test_agnes_runtime_contract_is_still_pinned() -> None:
    # #2804 must not disturb the Agnes smoke runtime itself.
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'MODEL_ID = "agnes-ai/agnes-3.0-flash"' in source
    assert 'UPSTREAM_MODEL = "agnes-3.0-flash"' in source
    assert "AGNES_ATTEMPT_COUNT=1" in source
