"""#2542 caller-registry authority cache contract tests.

The cache may only remove repeated construction work. Every authentication,
authorization, and fail-closed behavior must be byte-identical to the uncached
builder, and no secret-derived value may ever surface from the cache itself.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from app import identity_enforcement
from app.identity_enforcement import (
    CALLER_CREDENTIAL_HEADER,
    CALLER_ID_HEADER,
    CALLER_REGISTRY_V1_ENV,
    CALLER_REGISTRY_V1_OVERLAY_ENV,
    RETIRED_CALLER_IDS,
    _registry_authority_for_env,
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


@pytest.fixture(autouse=True)
def _isolate_cache() -> None:
    identity_enforcement._reset_authority_cache_for_tests()
    yield
    identity_enforcement._reset_authority_cache_for_tests()


def _hits() -> int:
    return identity_enforcement._authority_cache_stats["hits"]


def _misses() -> int:
    return identity_enforcement._authority_cache_stats["misses"]


def test_first_parse_is_a_miss() -> None:
    assert _hits() == 0 and _misses() == 0
    _registry_authority_for_env(_env())
    assert _misses() == 1
    assert _hits() == 0


def test_same_bindings_hit_the_cache() -> None:
    env = _env(overlay=OVERLAY)
    first = _registry_authority_for_env(env)
    second = _registry_authority_for_env(_env(base=BASE, overlay=OVERLAY))
    assert _misses() == 1
    assert _hits() == 1
    assert first is second


def test_base_change_invalidates_the_cache() -> None:
    _registry_authority_for_env(_env())
    authority, _ = _registry_authority_for_env(_env(base=BASE_CHANGED))
    assert authority is not None
    assert len(authority.callers) == 2
    assert _misses() == 2
    assert _hits() == 0


def test_overlay_change_invalidates_the_cache() -> None:
    _registry_authority_for_env(_env(overlay=OVERLAY))
    _, caller = _registry_authority_for_env(
        _env(overlay=_overlay_payload(credential=OTHER_SECRET))
    )
    assert caller is not None
    assert caller.caller_id == "p01-claw"
    assert _misses() == 2
    assert _hits() == 0


def test_equal_length_base_change_is_not_a_stale_hit() -> None:
    # Same byte length, different content: equality-keyed caching must rebuild.
    same_length = _base_payload(_caller_entry("b62-servicf", BASE_SECRET, "padiem-chat"))
    assert len(same_length) == len(BASE)
    _registry_authority_for_env(_env())
    authority, _ = _registry_authority_for_env(_env(base=same_length))
    assert authority.callers[0].caller_id == "b62-servicf"
    assert _hits() == 0


def test_malformed_changed_binding_still_fails_closed() -> None:
    _registry_authority_for_env(_env())
    with pytest.raises(ServiceIdentityError) as exc_info:
        _registry_authority_for_env(_env(base="{not-json"))
    assert exc_info.value.code == "invalid_caller_registry"
    # The failed rebuild must not poison or be served from the cache.
    with pytest.raises(ServiceIdentityError):
        _registry_authority_for_env(_env(base="{not-json"))
    assert _hits() == 0


def test_blank_changed_binding_still_fails_closed() -> None:
    _registry_authority_for_env(_env())
    with pytest.raises(ServiceIdentityError) as exc_info:
        _registry_authority_for_env(_env(base="   "))
    assert exc_info.value.code == "invalid_caller_registry"


def test_non_string_changed_binding_still_fails_closed() -> None:
    _registry_authority_for_env(_env())
    with pytest.raises(ServiceIdentityError):
        _registry_authority_for_env(_env(base=123))


def test_duplicate_caller_fails_closed_and_is_never_cached() -> None:
    duplicate = _base_payload(
        _caller_entry("dup", BASE_SECRET, "padiem-chat"),
        _caller_entry("dup", OTHER_SECRET, "padiem-chat"),
    )
    for _ in range(2):
        with pytest.raises(ServiceIdentityError) as exc_info:
            _registry_authority_for_env(_env(base=duplicate))
        assert exc_info.value.code == "duplicate_service_caller"
    assert _hits() == 0


def test_duplicate_base_and_overlay_fails_closed_every_time() -> None:
    base = _base_payload(_caller_entry("p01-claw", BASE_SECRET, "padiem-chat"))
    for _ in range(2):
        with pytest.raises(ServiceIdentityError) as exc_info:
            _registry_authority_for_env(_env(base=base, overlay=OVERLAY))
        assert exc_info.value.code == "duplicate_service_caller"
    assert _hits() == 0


def test_retired_caller_behavior_unchanged() -> None:
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
    # The second authentication ran against the cached authority and still
    # denied the retired caller at the wire boundary.
    assert _hits() == 1


def test_unrelated_base_caller_still_authenticates_via_cache() -> None:
    env = _env(base=BASE_CHANGED)
    for _ in range(2):
        authenticate_request(
            env=env,
            headers={CALLER_ID_HEADER: "b54-engine", CALLER_CREDENTIAL_HEADER: OTHER_SECRET},
            requested_app_id="b54-engine",
        )
    assert _hits() == 1


def test_overlay_caller_still_authenticates_via_cache() -> None:
    env = _env(overlay=OVERLAY)
    for _ in range(2):
        authenticate_request(
            env=env,
            headers={CALLER_ID_HEADER: "p01-claw", CALLER_CREDENTIAL_HEADER: OVERLAY_SECRET},
            requested_app_id="p01",
        )
    assert _hits() == 1


def test_wrong_credential_still_fails_closed_via_cache() -> None:
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
    assert _hits() == 1


def test_app_scope_enforcement_unchanged_via_cache() -> None:
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


def test_legacy_trio_is_not_cached() -> None:
    @dataclass
    class LegacyEnv:
        PADIEM_ENGINE_CALLER_ID: str = "b62-service"
        PADIEM_ENGINE_CALLER_SECRET: str = BASE_SECRET
        PADIEM_ENGINE_ALLOWED_APPS: str = "padiem-chat"

    env = LegacyEnv()
    registry = build_registry_from_env(env)
    assert registry is not None
    assert registry.callers[0].caller_id == "b62-service"
    assert _hits() == 0
    assert _misses() == 1


def test_unconfigured_env_is_not_cached() -> None:
    empty = _env(base=None)
    assert build_registry_from_env(empty) is None
    assert build_registry_from_env(empty) is None
    assert _hits() == 0
    assert _misses() == 2


def test_cache_never_emits_secret_derived_evidence() -> None:
    env = _env(overlay=OVERLAY)
    _registry_authority_for_env(env)
    _registry_authority_for_env(env)
    cached = identity_enforcement._authority_cache
    assert cached is not None
    rendered = repr(_authority_public_shape())
    for secret in (BASE_SECRET, OVERLAY_SECRET, OTHER_SECRET):
        assert secret not in rendered
        assert secret not in json.dumps(_authority_public_shape())


def _authority_public_shape() -> dict[str, object]:
    """Public-safe view of cache observability: counters and caller identity only."""

    registry = build_registry_from_env(_env(overlay=OVERLAY))
    return {
        "stats": dict(identity_enforcement._authority_cache_stats),
        "callers": [caller.to_public_dict() for caller in (registry.callers if registry else ())],
    }


def test_engine_caller_registry_public_dict_has_no_digest() -> None:
    registry = build_registry_from_env(_env())
    assert registry is not None
    dumped = json.dumps([caller.to_public_dict() for caller in registry.callers])
    assert BASE_SECRET not in dumped
    assert "credential_sha256" not in dumped
    assert "credential" not in dumped
