"""Runtime-internal content-blind caller-authority diagnostic (#2439 rework).

The Cloudflare control plane never returns secret_text plaintext, so the
surviving #2439 401 candidates (malformed V1 base vs base already containing
the overlay caller id) can only be classified where the registry payloads
legitimately exist: inside the Engine runtime. These tests lock the closed
six-field classifier, the closed immutable projection, the token-gated
fail-closed authorization contract, registry independence (the route answers
even when the base registry itself is malformed), and the canonical-entrypoint
fetch wiring including the health non-advertisement invariant.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.authority_diagnostic import (  # noqa: E402
    AUTHORITY_DIAGNOSTIC_PATH,
    CLOSED_FIELDS,
    DIAGNOSTIC_TOKEN_ENV,
    DIAGNOSTIC_TOKEN_HEADER,
    OUTPUT_KEYS,
    AuthorityDiagnosticError,
    AuthorityDiagnosticResult,
    classify_authority_payloads,
    diagnostic_response,
)

OPERATOR_TOKEN = "diag-token-" + "t" * 40
CRED_B61 = "cred-sentinel-" + "b" * 40
CRED_UNRELATED = "cred-sentinel-" + "u" * 40
CRED_OVERLAY = "cred-sentinel-" + "o" * 40
CRED_B54_IN_BASE = "cred-sentinel-" + "x" * 40
UNRELATED_CALLER_ID = "caller-sentinel-unrelated"
UNRELATED_APP_ID = "app-sentinel-allowed"
B61_APP_ID = "app-sentinel-b61"

SENTINELS = (
    CRED_B61,
    CRED_UNRELATED,
    CRED_OVERLAY,
    CRED_B54_IN_BASE,
    UNRELATED_CALLER_ID,
    UNRELATED_APP_ID,
    B61_APP_ID,
    OPERATOR_TOKEN,
)


def _caller(caller_id: str, credential: str, app_id: str) -> dict[str, object]:
    return {"caller_id": caller_id, "credential": credential, "allowed_app_ids": [app_id]}


def _base(callers: list[dict[str, object]]) -> str:
    return json.dumps({"version": 1, "callers": callers})


def _overlay(caller: dict[str, object]) -> str:
    return json.dumps({"version": 1, "caller": caller})


def _valid_base() -> str:
    return _base(
        [
            _caller("storymemory-b61", CRED_B61, B61_APP_ID),
            _caller(UNRELATED_CALLER_ID, CRED_UNRELATED, UNRELATED_APP_ID),
        ]
    )


def _valid_overlay() -> str:
    return _overlay(_caller("b54-kagent", CRED_OVERLAY, "b54-padiem-claw"))


class _Env:
    def __init__(self, **values: Any) -> None:
        for name, value in values.items():
            setattr(self, name, value)


def _env(**extra: Any) -> _Env:
    env = _Env(
        **{
            DIAGNOSTIC_TOKEN_ENV: OPERATOR_TOKEN,
            "PADIEM_ENGINE_CALLER_REGISTRY_V1": _valid_base(),
            "PADIEM_ENGINE_CALLER_REGISTRY_V1_OVERLAY": _valid_overlay(),
        }
    )
    for name, value in extra.items():
        setattr(env, name, value)
    return env


class _Headers(dict):
    """Case-insensitive ``.get`` like the Workers Headers object."""

    def get(self, key: str, default: Any = None) -> Any:
        for name, value in self.items():
            if name.lower() == key.lower():
                return value
        return default


def _authorized_headers() -> _Headers:
    return _Headers({DIAGNOSTIC_TOKEN_HEADER: OPERATOR_TOKEN})


# --- classifier fixtures (CI-side mirror parity) ----------------------------


def test_fixture_1_valid_base_valid_nonduplicate_overlay() -> None:
    fields = classify_authority_payloads(_valid_base(), _valid_overlay())
    assert fields == {
        "BASE_PARSE": "OK",
        "OVERLAY_PARSE": "OK",
        "BASE_CONTAINS_B54_KAGENT": "NO",
        "DUPLICATE_CALLER_ID": "NO",
        "BASE_CALLER_COUNT": "2",
        "OVERLAY_CALLER_ID_MATCH": "YES",
    }


def test_fixture_2_malformed_base() -> None:
    fields = classify_authority_payloads("{not-json", _valid_overlay())
    assert fields["BASE_PARSE"] == "INVALID"
    assert fields["BASE_CONTAINS_B54_KAGENT"] == "NO"
    assert fields["BASE_CALLER_COUNT"] == "0"


def test_fixture_2b_malformed_base_still_detects_duplicate_structurally() -> None:
    callers = [_caller(f"caller-{index:03d}", CRED_B61, B61_APP_ID) for index in range(65)]
    callers.append(_caller("b54-kagent", CRED_B54_IN_BASE, "b54-padiem-claw"))
    fields = classify_authority_payloads(_base(callers), _valid_overlay())
    assert fields["BASE_PARSE"] == "INVALID"
    assert fields["BASE_CONTAINS_B54_KAGENT"] == "YES"
    assert fields["DUPLICATE_CALLER_ID"] == "YES"
    assert fields["BASE_CALLER_COUNT"] == "64"


def test_fixture_3_malformed_overlay_id_still_matches() -> None:
    broken = json.dumps(
        {"version": 2, "caller": _caller("b54-kagent", CRED_OVERLAY, "b54-padiem-claw")}
    )
    fields = classify_authority_payloads(_valid_base(), broken)
    assert fields["OVERLAY_PARSE"] == "INVALID"
    assert fields["OVERLAY_CALLER_ID_MATCH"] == "YES"


def test_fixture_4_base_contains_b54_kagent_duplicate() -> None:
    duplicate_base = _base(
        [
            _caller("storymemory-b61", CRED_B61, B61_APP_ID),
            _caller("b54-kagent", CRED_B54_IN_BASE, "b54-padiem-claw"),
        ]
    )
    fields = classify_authority_payloads(duplicate_base, _valid_overlay())
    assert fields["BASE_PARSE"] == "OK"
    assert fields["BASE_CONTAINS_B54_KAGENT"] == "YES"
    assert fields["DUPLICATE_CALLER_ID"] == "YES"


def test_blank_and_absent_inputs_classify_invalid() -> None:
    fields = classify_authority_payloads("   ", None)
    assert fields["BASE_PARSE"] == "INVALID"
    assert fields["OVERLAY_PARSE"] == "INVALID"
    assert fields["BASE_CALLER_COUNT"] == "0"


def test_classifier_never_emits_registry_content() -> None:
    scenarios = (
        (_valid_base(), _valid_overlay()),
        ("{not-json", _valid_overlay()),
        (_valid_base(), json.dumps({"version": 2, "caller": {}})),
        (None, _valid_overlay()),
        (_valid_base(), None),
    )
    for base, overlay in scenarios:
        fields = classify_authority_payloads(base, overlay)
        rendered = "\n".join(f"{key}={fields[key]}" for key in CLOSED_FIELDS)
        for sentinel in SENTINELS:
            assert sentinel not in rendered
        for fragment in ("callers", "allowed_app_ids", "credential", "{", "}"):
            assert fragment not in rendered


# --- closed immutable projection --------------------------------------------


def test_result_rejects_out_of_vocabulary_values() -> None:
    with pytest.raises(AuthorityDiagnosticError):
        AuthorityDiagnosticResult(
            {
                "BASE_PARSE": CRED_B61,
                "OVERLAY_PARSE": "OK",
                "BASE_CONTAINS_B54_KAGENT": "NO",
                "DUPLICATE_CALLER_ID": "NO",
                "BASE_CALLER_COUNT": "2",
                "OVERLAY_CALLER_ID_MATCH": "YES",
            }
        )
    with pytest.raises(AuthorityDiagnosticError):
        AuthorityDiagnosticResult(
            {
                "BASE_PARSE": "OK",
                "OVERLAY_PARSE": "OK",
                "BASE_CONTAINS_B54_KAGENT": "MAYBE",
                "DUPLICATE_CALLER_ID": "NO",
                "BASE_CALLER_COUNT": "65",
                "OVERLAY_CALLER_ID_MATCH": "YES",
            }
        )


def test_result_is_immutable_and_revalidates_on_every_surface() -> None:
    result = AuthorityDiagnosticResult(classify_authority_payloads(_valid_base(), _valid_overlay()))
    with pytest.raises(AttributeError):
        result.BASE_PARSE = "INVALID"  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        del result._values
    object.__setattr__(result, "_values", (CRED_B61, "OK", "NO", "NO", "2", "YES"))
    with pytest.raises(AuthorityDiagnosticError):
        result["BASE_PARSE"]
    with pytest.raises(AuthorityDiagnosticError):
        result.as_dict()
    with pytest.raises(AuthorityDiagnosticError):
        repr(result)


# --- token-gated authorization contract --------------------------------------


def test_non_get_method_is_rejected() -> None:
    status, body = diagnostic_response(_env(), "POST", _authorized_headers())
    assert status == 405
    assert body["ok"] is False
    assert body["error"]["code"] == "method_not_allowed"


def test_unconfigured_or_weak_server_token_fails_closed() -> None:
    for env in (object(), _Env(**{DIAGNOSTIC_TOKEN_ENV: ""}), _Env(**{DIAGNOSTIC_TOKEN_ENV: "short"})):
        status, body = diagnostic_response(env, "GET", _authorized_headers())
        assert status == 503
        assert body["error"]["code"] == "authority_diagnostic_unavailable"


def test_missing_wrong_or_oversized_presentation_is_401() -> None:
    env = _env()
    for headers in (
        _Headers(),
        None,
        _Headers({DIAGNOSTIC_TOKEN_HEADER: "a" * 48}),
        _Headers({DIAGNOSTIC_TOKEN_HEADER: OPERATOR_TOKEN + "x" * 600}),
    ):
        status, body = diagnostic_response(env, "GET", headers)
        assert status == 401
        assert body["ok"] is False
        assert body["error"]["code"] == "authority_diagnostic_unauthorized"


def test_authorized_success_body_is_the_closed_projection() -> None:
    status, body = diagnostic_response(_env(), "GET", _authorized_headers())
    assert status == 200
    assert tuple(sorted(body)) == tuple(sorted(OUTPUT_KEYS))
    assert body["ok"] is True
    assert body["BASE_PARSE"] == "OK"
    assert body["OVERLAY_CALLER_ID_MATCH"] == "YES"
    assert body["SECRET_VALUE_OUTPUT"] == "0"
    assert body["RAW_REGISTRY_JSON_OUTPUT"] == "0"
    assert body["PRODUCTION_MUTATION"] == "0"
    rendered = json.dumps(body)
    for sentinel in SENTINELS:
        assert sentinel not in rendered


def test_diagnostic_answers_even_when_the_registry_is_the_broken_component() -> None:
    env = _env(PADIEM_ENGINE_CALLER_REGISTRY_V1="{not-json")
    status, body = diagnostic_response(env, "GET", _authorized_headers())
    assert status == 200
    assert body["BASE_PARSE"] == "INVALID"


# --- canonical-entrypoint fetch wiring ----------------------------------------


@pytest.fixture(scope="module")
def identity_module():
    saved = {name: sys.modules.get(name) for name in ("workers", "worker", "worker_identity")}

    class _FakeResponse:
        def __init__(self, body: Any = None, status: int = 200, headers: Any = None) -> None:
            self.body = body
            self.status = status
            self.headers = headers or {}

    class _FakeWorkerEntrypoint:
        def __init__(self, ctx: Any = None, env: Any = None) -> None:
            self.ctx = ctx
            self.env = env

    stub = types.ModuleType("workers")
    stub.Request = lambda *args, **kwargs: None  # type: ignore[attr-defined]
    stub.Response = _FakeResponse  # type: ignore[attr-defined]
    stub.WorkerEntrypoint = _FakeWorkerEntrypoint  # type: ignore[attr-defined]
    sys.modules["workers"] = stub
    for name in ("worker", "worker_identity"):
        sys.modules.pop(name, None)
    try:
        importlib.import_module("worker")
        yield importlib.import_module("worker_identity")
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


class _Request:
    def __init__(self, path: str, method: str = "GET", headers: Any = None) -> None:
        self.url = f"https://engine.padiem.net{path}"
        self.method = method
        self.headers = headers if headers is not None else _Headers()


def _fetch(identity: Any, env: Any, request: Any) -> Any:
    return asyncio.run(identity.Default(ctx=None, env=env).fetch(request))


def test_fetch_route_is_token_gated_and_closed(identity_module: Any) -> None:
    env = _env()
    granted = _fetch(
        identity_module, env, _Request(AUTHORITY_DIAGNOSTIC_PATH, headers=_authorized_headers())
    )
    assert granted.status == 200
    body = json.loads(str(granted.body))
    assert tuple(sorted(body)) == tuple(sorted(OUTPUT_KEYS))
    assert body["BASE_CALLER_COUNT"] == "2"

    denied = _fetch(identity_module, env, _Request(AUTHORITY_DIAGNOSTIC_PATH))
    assert denied.status == 401
    assert OPERATOR_TOKEN not in str(denied.body)

    wrong_way = _fetch(
        identity_module,
        env,
        _Request(AUTHORITY_DIAGNOSTIC_PATH, method="POST", headers=_authorized_headers()),
    )
    assert wrong_way.status == 405


def test_diagnostic_route_is_not_advertised_and_bypasses_registry_auth(
    identity_module: Any,
) -> None:
    service_source = (APP_ROOT / "app" / "service.py").read_text(encoding="utf-8")
    assert AUTHORITY_DIAGNOSTIC_PATH not in service_source

    identity_source = (APP_ROOT / "worker_identity.py").read_text(encoding="utf-8")
    start = identity_source.index("def _fetch_authority_diagnostic")
    end = identity_source.index("def ", start + len("def _fetch_authority_diagnostic"))
    handler_source = identity_source[start:end]
    assert "_authenticate_non_health_request" not in handler_source
    assert "authenticate_request" not in handler_source
    assert "engine_services" not in handler_source
    assert "diagnostic_response" in handler_source


def test_fetch_intercepts_the_diagnostic_path_before_super() -> None:
    identity_source = (APP_ROOT / "worker_identity.py").read_text(encoding="utf-8")
    fetch_start = identity_source.index("async def fetch(self, request")
    fetch_body = identity_source[fetch_start : identity_source.index("def ", fetch_start + 10)]
    assert fetch_body.index("AUTHORITY_DIAGNOSTIC_PATH") < fetch_body.index("super().fetch")
    assert set(CLOSED_FIELDS) == {
        "BASE_PARSE",
        "OVERLAY_PARSE",
        "BASE_CONTAINS_B54_KAGENT",
        "DUPLICATE_CALLER_ID",
        "BASE_CALLER_COUNT",
        "OVERLAY_CALLER_ID_MATCH",
    }
