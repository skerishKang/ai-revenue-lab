"""#2542 caller-registry authority cache contract tests.

The cache may only remove repeated construction work. Every authentication,
authorization, and fail-closed behavior must be byte-identical to the uncached
builder, and no secret-derived value may ever surface from the cache itself.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass

import pytest

from app import identity_enforcement
from app.identity_enforcement import (
    CALLER_CREDENTIAL_HEADER,
    CALLER_ID_HEADER,
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


def test_same_env_and_bindings_hit_the_cache() -> None:
    env = _env(overlay=OVERLAY)
    first = _registry_authority_for_env(env)
    second = _registry_authority_for_env(env)
    assert _misses() == 1
    assert _hits() == 1
    assert first is second


def test_equal_content_different_env_rebuilds_rather_than_content_hits() -> None:
    # Identical binding content but a different env object: the memo keys on
    # runtime identity, never on payload content, so it must miss and rebuild.
    first = _registry_authority_for_env(_env(overlay=OVERLAY))
    second = _registry_authority_for_env(_env(base=BASE, overlay=OVERLAY))
    assert _misses() == 2
    assert _hits() == 0
    assert first is not second


def test_base_reassignment_on_the_same_env_invalidates_the_cache() -> None:
    env = _env()
    _registry_authority_for_env(env)
    env.PADIEM_ENGINE_CALLER_REGISTRY_V1 = BASE_CHANGED
    authority, _ = _registry_authority_for_env(env)
    assert authority is not None
    assert len(authority.callers) == 2
    assert _misses() == 2
    assert _hits() == 0


def test_overlay_reassignment_on_the_same_env_invalidates_the_cache() -> None:
    env = _env(overlay=OVERLAY)
    _registry_authority_for_env(env)
    env.PADIEM_ENGINE_CALLER_REGISTRY_V1_OVERLAY = _overlay_payload(
        credential=OTHER_SECRET
    )
    _, caller = _registry_authority_for_env(env)
    assert caller is not None
    assert caller.caller_id == "p01-claw"
    assert _misses() == 2
    assert _hits() == 0


def test_equal_length_reassignment_is_not_a_stale_hit() -> None:
    # Same byte length, different content, same env object: a content-derived
    # surrogate key could not tell these apart, but object identity can.
    same_length = _base_payload(_caller_entry("b62-servicf", BASE_SECRET, "padiem-chat"))
    assert len(same_length) == len(BASE)
    env = _env()
    _registry_authority_for_env(env)
    env.PADIEM_ENGINE_CALLER_REGISTRY_V1 = same_length
    authority, _ = _registry_authority_for_env(env)
    assert authority.callers[0].caller_id == "b62-servicf"
    assert _hits() == 0
    assert _misses() == 2


def test_malformed_reassignment_still_fails_closed_and_is_not_cached() -> None:
    env = _env()
    _registry_authority_for_env(env)  # memoizes a valid authority for BASE
    env.PADIEM_ENGINE_CALLER_REGISTRY_V1 = "{not-json"
    for _ in range(2):
        with pytest.raises(ServiceIdentityError) as exc_info:
            _registry_authority_for_env(env)
        assert exc_info.value.code == "invalid_caller_registry"
    # A failed rebuild must never be served from, nor poison, the memo.
    assert _hits() == 0


def test_blank_reassignment_still_fails_closed() -> None:
    env = _env()
    _registry_authority_for_env(env)
    env.PADIEM_ENGINE_CALLER_REGISTRY_V1 = "   "
    with pytest.raises(ServiceIdentityError) as exc_info:
        _registry_authority_for_env(env)
    assert exc_info.value.code == "invalid_caller_registry"


def test_non_string_reassignment_still_fails_closed() -> None:
    env = _env()
    _registry_authority_for_env(env)
    env.PADIEM_ENGINE_CALLER_REGISTRY_V1 = 123
    with pytest.raises(ServiceIdentityError):
        _registry_authority_for_env(env)


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


def test_cache_state_holds_no_plaintext_or_content_derived_surrogate() -> None:
    env = _env(overlay=OVERLAY)
    _registry_authority_for_env(env)
    _registry_authority_for_env(env)  # a hit must not add any plaintext either
    cached = identity_enforcement._authority_cache
    assert cached is not None
    assert isinstance(cached, identity_enforcement._AuthorityCacheEntry)

    # The memo exposes only a weak env reference, two object addresses, and the
    # parsed authority. There is no raw binding-value field that could leak.
    assert {field.name for field in dataclasses.fields(cached)} == {
        "env_ref",
        "base_id",
        "overlay_id",
        "authority",
    }
    assert type(cached.base_id) is int
    assert type(cached.overlay_id) is int
    # The address fields are live object identities, not content-derived values.
    assert cached.base_id == id(env.PADIEM_ENGINE_CALLER_REGISTRY_V1)
    assert cached.overlay_id == id(env.PADIEM_ENGINE_CALLER_REGISTRY_V1_OVERLAY)

    # No raw registry/overlay plaintext appears anywhere in the cache state.
    rendered = repr(cached)
    for payload in (BASE, BASE_CHANGED, OVERLAY):
        assert payload not in rendered
    # No credential plaintext is stored or reachable from the memo repr.
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
