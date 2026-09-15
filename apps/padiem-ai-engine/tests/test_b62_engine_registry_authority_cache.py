"""#2542 caller-registry authority memoization contract tests.

The security review concluded that no sound memoization of the authority is
possible under the no-plaintext / no-content-surrogate constraint, because the
authoritative inputs are ``str`` bindings whose runtime identity (``id``) can be
recycled by a different payload after a reassignment (an ABA at an
authentication boundary). The sanctioned disposition is therefore to rebuild the
authority on every call (CENTRAL options B/C: correctness over hit rate).

These tests pin that disposition:

* no isolate-lifetime memo state exists in the module;
* the authority is freshly rebuilt each call, so a stale hit is impossible;
* the exact ABA reassignment sequence always honors the *current* binding;
* every authentication, authorization, and fail-closed behavior is unchanged.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from app import identity_enforcement
from app.identity_enforcement import (
    CALLER_CREDENTIAL_HEADER,
    CALLER_ID_HEADER,
    RETIRED_CALLER_IDS,
    authenticate_request,
    build_registry_from_env,
)
from app.service_identity import ServiceIdentityError

BASE_SECRET = "B" * 48
OVERLAY_SECRET = "O" * 48
OTHER_SECRET = "C" * 48


def _caller_entry(caller_id: str, credential: str, *app_ids: str) -> dict[str, object]:
    return {
        "caller_id": caller_id,
        "credential": credential,
        "allowed_app_ids": list(app_ids),
    }


def _base_payload(*callers: dict[str, object]) -> str:
    return json.dumps({"version": 1, "callers": list(callers)})


def _overlay_payload(caller_id: str = "p01-claw", credential: str = OVERLAY_SECRET) -> str:
    return json.dumps(
        {
            "version": 1,
            "caller": _caller_entry(caller_id, credential, "p01"),
        }
    )


BASE = _base_payload(_caller_entry("b62-service", BASE_SECRET, "padiem-chat"))
BASE_CHANGED = _base_payload(
    _caller_entry("b62-service", BASE_SECRET, "padiem-chat"),
    _caller_entry("b54-engine", OTHER_SECRET, "b54-engine"),
)
OVERLAY = _overlay_payload()


@dataclass
class V1Env:
    PADIEM_ENGINE_CALLER_REGISTRY_V1: object = BASE
    PADIEM_ENGINE_CALLER_REGISTRY_V1_OVERLAY: object = None


def _env(base: object = BASE, overlay: object = None) -> V1Env:
    return V1Env(
        PADIEM_ENGINE_CALLER_REGISTRY_V1=base,
        PADIEM_ENGINE_CALLER_REGISTRY_V1_OVERLAY=overlay,
    )


# --- the memoized design is gone -------------------------------------------

_REMOVED_SYMBOLS = (
    "_registry_authority_for_env",
    "_AuthorityCacheEntry",
    "_authority_cache",
    "_authority_cache_stats",
    "_reset_authority_cache_for_tests",
    "_weak_identity_ref",
)


@pytest.mark.parametrize("symbol", _REMOVED_SYMBOLS)
def test_no_isolate_lifetime_memo_state_exists(symbol: str) -> None:
    assert not hasattr(identity_enforcement, symbol)


def test_authority_is_freshly_rebuilt_on_every_call() -> None:
    env = _env(overlay=OVERLAY)
    first = build_registry_from_env(env)
    second = build_registry_from_env(env)
    assert first is not None and second is not None
    # No memo: each call constructs a new registry object. A shared object would
    # mean a cache that the ABA analysis forbids.
    assert first is not second
    assert first.callers == second.callers


def test_equal_content_different_env_rebuilds_to_equal_authority() -> None:
    first = build_registry_from_env(_env(overlay=OVERLAY))
    second = build_registry_from_env(_env(base=BASE, overlay=OVERLAY))
    assert first is not second
    assert first.callers == second.callers


# --- the ABA regression: reassignment must never stale-hit ------------------

def test_base_reassignment_on_the_same_env_is_always_honored() -> None:
    env = _env()
    assert len(build_registry_from_env(env).callers) == 1
    env.PADIEM_ENGINE_CALLER_REGISTRY_V1 = BASE_CHANGED
    assert len(build_registry_from_env(env).callers) == 2


def test_overlay_reassignment_on_the_same_env_is_always_honored() -> None:
    env = _env(overlay=OVERLAY)
    _, caller = identity_enforcement._build_registry_authority_from_env(env)
    assert caller is not None and caller.caller_id == "p01-claw"
    env.PADIEM_ENGINE_CALLER_REGISTRY_V1_OVERLAY = _overlay_payload(
        credential=OTHER_SECRET
    )
    _, caller = identity_enforcement._build_registry_authority_from_env(env)
    assert caller is not None and caller.caller_id == "p01-claw"


def test_equal_length_reassignment_reflects_new_content() -> None:
    same_length = _base_payload(_caller_entry("b62-servicf", BASE_SECRET, "padiem-chat"))
    assert len(same_length) == len(BASE)
    env = _env()
    build_registry_from_env(env)
    env.PADIEM_ENGINE_CALLER_REGISTRY_V1 = same_length
    assert build_registry_from_env(env).callers[0].caller_id == "b62-servicf"


def test_aba_reassignment_sequence_never_serves_a_stale_authority() -> None:
    # The exact attack the memo made possible: read value A, reassign to a
    # different value B, then reassign to a fresh value C that is distinct from
    # both. A recycled id() could previously make the memo serve A's authority
    # for C. With no memo, the current binding always wins.
    value_a = _base_payload(_caller_entry("caller-a", BASE_SECRET, "padiem-chat"))
    value_b = _base_payload(_caller_entry("caller-b", OTHER_SECRET, "padiem-chat"))
    value_c = _base_payload(_caller_entry("caller-c", "D" * 48, "padiem-chat"))
    env = _env(base=value_a)
    assert build_registry_from_env(env).callers[0].caller_id == "caller-a"
    env.PADIEM_ENGINE_CALLER_REGISTRY_V1 = value_b
    assert build_registry_from_env(env).callers[0].caller_id == "caller-b"
    env.PADIEM_ENGINE_CALLER_REGISTRY_V1 = value_c
    assert build_registry_from_env(env).callers[0].caller_id == "caller-c"
    # Returning to content equal to value_a must still reflect the live object.
    env.PADIEM_ENGINE_CALLER_REGISTRY_V1 = _base_payload(
        _caller_entry("caller-a", BASE_SECRET, "padiem-chat")
    )
    assert build_registry_from_env(env).callers[0].caller_id == "caller-a"


# --- fail-closed behavior is unchanged --------------------------------------

def test_malformed_is_rejected_every_time() -> None:
    env = _env()
    env.PADIEM_ENGINE_CALLER_REGISTRY_V1 = "{not-json"
    for _ in range(2):
        with pytest.raises(ServiceIdentityError) as exc_info:
            build_registry_from_env(env)
        assert exc_info.value.code == "invalid_caller_registry"


def test_blank_reassignment_still_fails_closed() -> None:
    env = _env()
    build_registry_from_env(env)
    env.PADIEM_ENGINE_CALLER_REGISTRY_V1 = "   "
    with pytest.raises(ServiceIdentityError) as exc_info:
        build_registry_from_env(env)
    assert exc_info.value.code == "invalid_caller_registry"


def test_non_string_reassignment_still_fails_closed() -> None:
    env = _env()
    env.PADIEM_ENGINE_CALLER_REGISTRY_V1 = 123
    with pytest.raises(ServiceIdentityError):
        build_registry_from_env(env)


def test_duplicate_caller_fails_closed_every_time() -> None:
    duplicate = _base_payload(
        _caller_entry("dup", BASE_SECRET, "padiem-chat"),
        _caller_entry("dup", OTHER_SECRET, "padiem-chat"),
    )
    for _ in range(2):
        with pytest.raises(ServiceIdentityError) as exc_info:
            build_registry_from_env(_env(base=duplicate))
        assert exc_info.value.code == "duplicate_service_caller"


def test_duplicate_base_and_overlay_fails_closed_every_time() -> None:
    base = _base_payload(_caller_entry("p01-claw", BASE_SECRET, "padiem-chat"))
    for _ in range(2):
        with pytest.raises(ServiceIdentityError) as exc_info:
            build_registry_from_env(_env(base=base, overlay=OVERLAY))
        assert exc_info.value.code == "duplicate_service_caller"


# --- authentication semantics are unchanged ---------------------------------

def test_retired_caller_is_denied_repeatedly() -> None:
    retired = "b54-kagent"
    assert retired in RETIRED_CALLER_IDS
    base = _base_payload(
        _caller_entry(retired, OTHER_SECRET, "padiem-chat"),
        _caller_entry("b62-service", BASE_SECRET, "padiem-chat"),
    )
    env = _env(base=base)
    for _ in range(2):
        with pytest.raises(ServiceIdentityError) as exc_info:
            authenticate_request(
                env=env,
                headers={CALLER_ID_HEADER: retired, CALLER_CREDENTIAL_HEADER: OTHER_SECRET},
                requested_app_id="padiem-chat",
            )
        assert exc_info.value.code == "service_authentication_failed"


def test_valid_caller_authenticates_repeatedly() -> None:
    env = _env(base=BASE_CHANGED)
    for _ in range(2):
        authenticate_request(
            env=env,
            headers={CALLER_ID_HEADER: "b54-engine", CALLER_CREDENTIAL_HEADER: OTHER_SECRET},
            requested_app_id="b54-engine",
        )


def test_overlay_caller_authenticates_repeatedly() -> None:
    env = _env(overlay=OVERLAY)
    for _ in range(2):
        authenticate_request(
            env=env,
            headers={CALLER_ID_HEADER: "p01-claw", CALLER_CREDENTIAL_HEADER: OVERLAY_SECRET},
            requested_app_id="p01",
        )


def test_wrong_credential_still_fails_closed() -> None:
    env = _env()
    authenticate_request(
        env=env,
        headers={CALLER_ID_HEADER: "b62-service", CALLER_CREDENTIAL_HEADER: BASE_SECRET},
        requested_app_id="padiem-chat",
    )
    with pytest.raises(ServiceIdentityError) as exc_info:
        authenticate_request(
            env=env,
            headers={CALLER_ID_HEADER: "b62-service", CALLER_CREDENTIAL_HEADER: "X" * 48},
            requested_app_id="padiem-chat",
        )
    assert exc_info.value.code == "service_authentication_failed"


def test_app_scope_enforcement_unchanged() -> None:
    env = _env()
    authenticate_request(
        env=env,
        headers={CALLER_ID_HEADER: "b62-service", CALLER_CREDENTIAL_HEADER: BASE_SECRET},
        requested_app_id="padiem-chat",
    )
    with pytest.raises(ServiceIdentityError) as exc_info:
        authenticate_request(
            env=env,
            headers={CALLER_ID_HEADER: "b62-service", CALLER_CREDENTIAL_HEADER: BASE_SECRET},
            requested_app_id="p01",
        )
    assert exc_info.value.code == "service_app_not_authorized"


def test_legacy_trio_still_builds() -> None:
    @dataclass
    class LegacyEnv:
        PADIEM_ENGINE_CALLER_ID: str = "b62-service"
        PADIEM_ENGINE_CALLER_SECRET: str = BASE_SECRET
        PADIEM_ENGINE_ALLOWED_APPS: str = "padiem-chat"

    registry = build_registry_from_env(LegacyEnv())
    assert registry is not None
    assert registry.callers[0].caller_id == "b62-service"


def test_unconfigured_env_returns_none() -> None:
    empty = _env(base=None)
    assert build_registry_from_env(empty) is None
    assert build_registry_from_env(empty) is None


def test_engine_caller_registry_public_dict_has_no_digest() -> None:
    registry = build_registry_from_env(_env())
    assert registry is not None
    dumped = json.dumps([caller.to_public_dict() for caller in registry.callers])
    assert BASE_SECRET not in dumped
    assert "credential_sha256" not in dumped
    assert "credential" not in dumped
