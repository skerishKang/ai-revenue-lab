"""Network-free tests for the bounded #2445 Chat<->Engine auth-boundary diagnostic.

These prove the required properties without any live Cloudflare call, network
access, or real secret: the closed-vocabulary classification, exact reuse of the
live constant-time credential comparison, fail-closed behavior on malformed
input, and — after the #2447 rework — that no output/projection path can reflect
arbitrary caller-supplied (secret-shaped) strings.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.auth_boundary_diagnostic import (
    ABSENT,
    ENGINE_WORKER,
    ENVIRONMENT_ALLOWLIST,
    NONCANONICAL,
    OUTPUT_KEYS,
    P01_APP_ID,
    P01_CHAT_CALLER_ID,
    AuthBoundaryDiagnosticResult,
    AuthBoundaryEvidenceError,
    render,
    run_auth_boundary_diagnostic,
    run_auth_boundary_diagnostic_from_env,
)
from app.identity_enforcement import (
    CALLER_REGISTRY_V1_ENV,
    authenticate_request,
)
from app.service_identity import (
    EngineCallerRegistry,
    ServiceIdentityError,
    TrustedEngineCaller,
    authenticate_engine_caller,
    caller_secret_digest,
)

STORED_CREDENTIAL = "stored-canonical-credential-0123456789abcdef"
OTHER_CREDENTIAL = "different-served-credential-9876543210fedcba"
SENTINEL = "SUPER-SECRET-SENTINEL-0123456789abcdef-DO-NOT-LEAK"
HEX64 = re.compile(r"^[0-9a-f]{64}$")

_MODULE_SOURCE = (
    Path(__file__).resolve().parents[1] / "app" / "auth_boundary_diagnostic.py"
).read_text(encoding="utf-8")


def _caller(caller_id: str = P01_CHAT_CALLER_ID, credential: str = STORED_CREDENTIAL, **over):
    values = {
        "caller_id": caller_id,
        "allowed_app_ids": (P01_APP_ID,),
        "credential_sha256": caller_secret_digest(credential),
    }
    values.update(over)
    return TrustedEngineCaller(**values)


def _registry(caller: TrustedEngineCaller | None = None) -> EngineCallerRegistry:
    return EngineCallerRegistry(callers=(caller or _caller(),))


def _run(**over):
    kwargs = {
        "registry": _registry(),
        "overlay_caller": None,
        "chat_service_target": ENGINE_WORKER,
        "chat_service_environment": "production",
        "chat_caller_id": P01_CHAT_CALLER_ID,
        "app_id": P01_APP_ID,
        "canonical_credential": STORED_CREDENTIAL,
        "chat_supplied_credential": STORED_CREDENTIAL,
    }
    kwargs.update(over)
    return run_auth_boundary_diagnostic(**kwargs)


def _forged_result_dict(string_value: str) -> dict[str, str]:
    return {
        "CHAT_SERVICE_TARGET": string_value,
        "CHAT_SERVICE_ENVIRONMENT": string_value,
        "CHAT_CALLER_ID": string_value,
        "CALLER_PRESENT": "TRUE",
        "APP_ALLOWED": "TRUE",
        "ENGINE_MATCH": "TRUE",
        "CHAT_MATCH": "TRUE",
    }


# --- vocabulary / exactness ---------------------------------------------------


def test_result_vocabulary_is_exact_seven_keys() -> None:
    result = _run()
    assert isinstance(result, AuthBoundaryDiagnosticResult)
    assert tuple(result) == OUTPUT_KEYS
    assert set(result) == {
        "CHAT_SERVICE_TARGET",
        "CHAT_SERVICE_ENVIRONMENT",
        "CHAT_CALLER_ID",
        "CALLER_PRESENT",
        "APP_ALLOWED",
        "ENGINE_MATCH",
        "CHAT_MATCH",
    }


def test_boolean_fields_use_closed_true_false_vocabulary() -> None:
    result = _run()
    for key in ("CALLER_PRESENT", "APP_ALLOWED", "ENGINE_MATCH", "CHAT_MATCH"):
        assert result[key] in {"TRUE", "FALSE"}


def test_service_target_environment_caller_id_are_exact() -> None:
    result = _run()
    assert result["CHAT_SERVICE_TARGET"] == ENGINE_WORKER
    assert result["CHAT_CALLER_ID"] == P01_CHAT_CALLER_ID
    assert result["CHAT_SERVICE_ENVIRONMENT"] == "production"


def test_environment_absent_for_none_and_blank() -> None:
    assert _run(chat_service_environment=None)["CHAT_SERVICE_ENVIRONMENT"] == ABSENT
    assert _run(chat_service_environment="   ")["CHAT_SERVICE_ENVIRONMENT"] == ABSENT


def test_environment_allowlist_is_closed_and_grounded() -> None:
    assert ENVIRONMENT_ALLOWLIST == frozenset({"production", "preview"})
    assert _run(chat_service_environment="preview")["CHAT_SERVICE_ENVIRONMENT"] == "preview"


# --- decision contract branches ----------------------------------------------


def test_happy_path_both_match_true() -> None:
    result = _run()
    assert result["CALLER_PRESENT"] == "TRUE"
    assert result["APP_ALLOWED"] == "TRUE"
    assert result["ENGINE_MATCH"] == "TRUE"
    assert result["CHAT_MATCH"] == "TRUE"


def test_canonical_mismatch_is_engine_overlay_drift() -> None:
    result = _run(canonical_credential=OTHER_CREDENTIAL)
    assert result["ENGINE_MATCH"] == "FALSE"
    assert result["CHAT_MATCH"] == "TRUE"


def test_served_chat_drift_when_engine_matches_but_chat_does_not() -> None:
    result = _run(chat_supplied_credential=OTHER_CREDENTIAL)
    assert result["ENGINE_MATCH"] == "TRUE"
    assert result["CHAT_MATCH"] == "FALSE"


def test_unknown_caller_reports_absent_authority() -> None:
    result = _run(chat_caller_id="b54-not-registered")
    assert result["CALLER_PRESENT"] == "FALSE"
    assert result["APP_ALLOWED"] == "FALSE"
    assert result["ENGINE_MATCH"] == "FALSE"
    assert result["CHAT_MATCH"] == "FALSE"


def test_app_not_allowed_when_caller_present_but_scope_differs() -> None:
    result = _run(app_id="some-other-app")
    assert result["CALLER_PRESENT"] == "TRUE"
    assert result["APP_ALLOWED"] == "FALSE"
    assert result["ENGINE_MATCH"] == "TRUE"
    assert result["CHAT_MATCH"] == "TRUE"


def test_overlay_authority_is_resolved_before_base() -> None:
    overlay = _caller(caller_id=P01_CHAT_CALLER_ID, credential=STORED_CREDENTIAL)
    base = EngineCallerRegistry(callers=(_caller(caller_id="other-caller"),))
    result = run_auth_boundary_diagnostic(
        registry=base,
        overlay_caller=overlay,
        chat_service_target=ENGINE_WORKER,
        chat_service_environment="production",
        chat_caller_id=P01_CHAT_CALLER_ID,
        app_id=P01_APP_ID,
        canonical_credential=STORED_CREDENTIAL,
        chat_supplied_credential=OTHER_CREDENTIAL,
    )
    assert result["CALLER_PRESENT"] == "TRUE"
    assert result["ENGINE_MATCH"] == "TRUE"
    assert result["CHAT_MATCH"] == "FALSE"


# --- exact reuse of the live comparison primitive ----------------------------


def test_match_booleans_agree_with_real_authentication() -> None:
    registry = _registry()
    for credential in (STORED_CREDENTIAL, OTHER_CREDENTIAL):
        expected = True
        try:
            authenticate_engine_caller(
                registry=registry,
                caller_id=P01_CHAT_CALLER_ID,
                credential=credential,
                requested_app_id=P01_APP_ID,
            )
        except ServiceIdentityError:
            expected = False
        result = _run(registry=registry, canonical_credential=credential)
        assert (result["ENGINE_MATCH"] == "TRUE") is expected


def test_short_credential_is_false_not_an_error_oracle() -> None:
    result = _run(canonical_credential="short")
    assert result["ENGINE_MATCH"] == "FALSE"


# --- closed classification of arbitrary metadata (no reflection) --------------


def test_arbitrary_metadata_is_classified_not_echoed() -> None:
    # The old bug: these strings all satisfied a generic identifier regex and
    # would have been echoed verbatim. They must now collapse to NONCANONICAL.
    for bad in ("bad target!", "-leading-dash", "has space", "b54-rotated-secret-caller-xyz"):
        assert _run(chat_service_target=bad)["CHAT_SERVICE_TARGET"] == NONCANONICAL
        assert _run(chat_caller_id=bad)["CHAT_CALLER_ID"] == NONCANONICAL
        assert _run(chat_service_environment=bad)["CHAT_SERVICE_ENVIRONMENT"] == NONCANONICAL


def test_nonstring_metadata_is_classified_not_raised() -> None:
    assert _run(chat_service_target=123)["CHAT_SERVICE_TARGET"] == ABSENT
    assert _run(chat_service_environment=["x"])["CHAT_SERVICE_ENVIRONMENT"] == ABSENT


# --- fail-closed on malformed structural authority ----------------------------


def test_missing_authority_fails_closed() -> None:
    with pytest.raises(AuthBoundaryEvidenceError):
        _run(registry=None, overlay_caller=None)


def test_wrong_authority_types_fail_closed() -> None:
    with pytest.raises(AuthBoundaryEvidenceError):
        _run(registry="not-a-registry")
    with pytest.raises(AuthBoundaryEvidenceError):
        _run(overlay_caller="not-a-caller")


# --- non-disclosure -----------------------------------------------------------


def test_no_credential_material_is_emitted() -> None:
    result = _run(
        registry=_registry(_caller(credential=SENTINEL)),
        canonical_credential=SENTINEL,
        chat_supplied_credential=SENTINEL,
    )
    blob = "\n".join(f"{k}={v}" for k, v in result.items())
    assert SENTINEL not in blob
    assert caller_secret_digest(SENTINEL) not in blob
    for value in result.values():
        assert not HEX64.match(value)
        assert value != str(len(SENTINEL))


def test_render_is_bounded_and_marker_safe() -> None:
    result = _run(
        registry=_registry(_caller(credential=SENTINEL)),
        canonical_credential=SENTINEL,
        chat_supplied_credential=OTHER_CREDENTIAL,
    )
    text = render(result)
    assert SENTINEL not in text
    assert caller_secret_digest(SENTINEL) not in text
    for marker in (
        "SECRET_VALUE_OUTPUT=0",
        "SECRET_HASH_OUTPUT=0",
        "SECRET_LENGTH_OUTPUT=0",
        "PUBLIC_DIAGNOSTIC_ROUTE=NONE",
        "DIAGNOSTIC_ONLY=YES",
        "PRODUCTION_MUTATION=0",
    ):
        assert marker in text.splitlines()
    assert len(text.splitlines()) == len(OUTPUT_KEYS) + 6


# --- adversarial projection tests (#2447 finding) -----------------------------


def test_adv_A_forge_result_with_raw_credential_is_rejected() -> None:
    forged = _forged_result_dict(SENTINEL)
    with pytest.raises(AuthBoundaryEvidenceError) as exc_info:
        AuthBoundaryDiagnosticResult(forged)
    assert SENTINEL not in str(exc_info.value)
    with pytest.raises(AuthBoundaryEvidenceError) as exc_info:
        render(forged)
    assert SENTINEL not in str(exc_info.value)
    # Even through the classifier path, the raw credential is never reflected.
    result = _run(chat_service_target=SENTINEL, chat_caller_id=SENTINEL)
    assert SENTINEL not in "\n".join(result.values())


def test_adv_B_forge_result_with_sha256_digest_is_rejected() -> None:
    digest = caller_secret_digest(SENTINEL)
    assert HEX64.match(digest)
    with pytest.raises(AuthBoundaryEvidenceError):
        AuthBoundaryDiagnosticResult(_forged_result_dict(digest))
    with pytest.raises(AuthBoundaryEvidenceError):
        render(_forged_result_dict(digest))
    assert digest not in "\n".join(_run(chat_service_environment=digest).values())


def test_adv_C_forge_result_with_digest_fragment_is_rejected() -> None:
    digest = caller_secret_digest(SENTINEL)
    for fragment in (digest[:16], digest[-16:], digest[:8]):
        with pytest.raises(AuthBoundaryEvidenceError):
            AuthBoundaryDiagnosticResult(_forged_result_dict(fragment))
        assert fragment not in "\n".join(_run(chat_service_target=fragment).values())


def test_adv_D_numeric_secret_length_is_never_echoed() -> None:
    for length in ("32", "64", "128", "512"):
        result = _run(chat_service_target=length, chat_service_environment=length, chat_caller_id=length)
        assert length not in result.values()
        assert result["CHAT_SERVICE_TARGET"] == NONCANONICAL
        assert result["CHAT_SERVICE_ENVIRONMENT"] == NONCANONICAL
        assert result["CHAT_CALLER_ID"] == NONCANONICAL


def test_adv_E_direct_metadata_secret_injection_never_reflected() -> None:
    result = _run(
        chat_service_target=SENTINEL,
        chat_service_environment=OTHER_CREDENTIAL,
        chat_caller_id=caller_secret_digest(SENTINEL),
    )
    blob = render(result)
    for secret in (SENTINEL, OTHER_CREDENTIAL, caller_secret_digest(SENTINEL)):
        assert secret not in blob
    assert set(result.values()) <= {
        ENGINE_WORKER,
        P01_CHAT_CALLER_ID,
        ABSENT,
        NONCANONICAL,
        "TRUE",
        "FALSE",
        *ENVIRONMENT_ALLOWLIST,
    }


def test_adv_F_boolean_field_rejects_non_boolean_vocabulary() -> None:
    forged = _forged_result_dict(ENGINE_WORKER)
    forged["CHAT_CALLER_ID"] = P01_CHAT_CALLER_ID
    forged["CHAT_SERVICE_ENVIRONMENT"] = "production"
    forged["CALLER_PRESENT"] = "MAYBE"
    with pytest.raises(AuthBoundaryEvidenceError) as exc_info:
        AuthBoundaryDiagnosticResult(forged)
    assert "MAYBE" not in str(exc_info.value)


def test_adv_G_result_keys_must_be_exact() -> None:
    good = _run().as_dict()
    with pytest.raises(AuthBoundaryEvidenceError):
        AuthBoundaryDiagnosticResult({**good, "EXTRA": "production"})
    with pytest.raises(AuthBoundaryEvidenceError):
        del_key = dict(good)
        del_key.pop("CHAT_MATCH")
        AuthBoundaryDiagnosticResult(del_key)


def test_adv_I_drift_classified_without_reflecting_raw_value() -> None:
    unexpected_target = "attacker-controlled-engine.example"
    unexpected_caller = "b54-kagent-rotated-leaked-id"
    result = _run(chat_service_target=unexpected_target, chat_caller_id=unexpected_caller)
    assert result["CHAT_SERVICE_TARGET"] == NONCANONICAL
    assert result["CHAT_CALLER_ID"] == NONCANONICAL
    assert result["CALLER_PRESENT"] == "FALSE"
    assert unexpected_target not in "\n".join(result.values())
    assert unexpected_caller not in "\n".join(result.values())


def test_adv_J_authority_error_message_has_no_supplied_secret() -> None:
    env = _FakeEnv(**{CALLER_REGISTRY_V1_ENV: SENTINEL})
    with pytest.raises(AuthBoundaryEvidenceError) as exc_info:
        run_auth_boundary_diagnostic_from_env(
            env,
            chat_service_target=ENGINE_WORKER,
            chat_service_environment="production",
            chat_caller_id=P01_CHAT_CALLER_ID,
            canonical_credential=SENTINEL,
            chat_supplied_credential=SENTINEL,
        )
    assert SENTINEL not in str(exc_info.value)


# --- no public credential oracle / runtime unchanged --------------------------


def test_render_refuses_foreign_vocabulary() -> None:
    with pytest.raises(AuthBoundaryEvidenceError):
        render({"CHAT_SERVICE_TARGET": ENGINE_WORKER})


def test_module_defines_no_http_route_or_fetch_handler() -> None:
    lowered = _MODULE_SOURCE.lower()
    for forbidden in ("async def fetch", "def fetch(", "add_route", "web.jsonresponse", "onrequest"):
        assert forbidden not in lowered
    assert "class Request" not in _MODULE_SOURCE
    assert "export default" not in lowered


def test_diagnostic_is_not_wired_into_worker_entrypoints() -> None:
    app_root = Path(__file__).resolve().parents[1]
    for entry in ("worker.py", "worker_identity.py", "app/service.py", "app/identity_enforcement.py"):
        source = (app_root / entry).read_text(encoding="utf-8")
        assert "auth_boundary_diagnostic" not in source


def test_existing_authentication_request_semantics_unchanged() -> None:
    registry = _registry()
    with pytest.raises(ServiceIdentityError):
        authenticate_engine_caller(
            registry=registry,
            caller_id=P01_CHAT_CALLER_ID,
            credential=OTHER_CREDENTIAL,
            requested_app_id=P01_APP_ID,
        )
    assert callable(authenticate_request)


# --- env-driven authority resolution -----------------------------------------


class _FakeEnv:
    def __init__(self, **values):
        for key, value in values.items():
            setattr(self, key, value)


def test_from_env_resolves_base_registry_authority() -> None:
    import json

    payload = json.dumps(
        {
            "version": 1,
            "callers": [
                {
                    "caller_id": P01_CHAT_CALLER_ID,
                    "credential": STORED_CREDENTIAL,
                    "allowed_app_ids": [P01_APP_ID],
                }
            ],
        }
    )
    env = _FakeEnv(**{CALLER_REGISTRY_V1_ENV: payload})
    result = run_auth_boundary_diagnostic_from_env(
        env,
        chat_service_target=ENGINE_WORKER,
        chat_service_environment=None,
        chat_caller_id=P01_CHAT_CALLER_ID,
        canonical_credential=STORED_CREDENTIAL,
        chat_supplied_credential=OTHER_CREDENTIAL,
    )
    assert result["CHAT_SERVICE_ENVIRONMENT"] == ABSENT
    assert result["ENGINE_MATCH"] == "TRUE"
    assert result["CHAT_MATCH"] == "FALSE"


def test_from_env_fails_closed_on_unparseable_authority() -> None:
    env = _FakeEnv(**{CALLER_REGISTRY_V1_ENV: "not-json"})
    with pytest.raises(AuthBoundaryEvidenceError) as exc_info:
        run_auth_boundary_diagnostic_from_env(
            env,
            chat_service_target=ENGINE_WORKER,
            chat_service_environment="production",
            chat_caller_id=P01_CHAT_CALLER_ID,
            canonical_credential=STORED_CREDENTIAL,
            chat_supplied_credential=STORED_CREDENTIAL,
        )
    assert SENTINEL not in str(exc_info.value)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
