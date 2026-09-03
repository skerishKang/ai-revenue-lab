from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.identity_enforcement import (
    CALLER_CREDENTIAL_HEADER,
    CALLER_ID_HEADER,
    CALLER_REGISTRY_V1_ENV,
    CALLER_REGISTRY_V1_VERSION,
    MAX_CALLER_REGISTRY_V1_BYTES,
    authenticate_request,
    build_registry_from_env,
    parse_caller_registry_v1,
)
from app.service_identity import (
    MAX_CALLER_APP_IDS,
    MAX_ENGINE_CALLERS,
    ServiceIdentityError,
    caller_secret_digest,
)


SECRET = "S" * 48


@dataclass
class Env:
    PADIEM_ENGINE_CALLER_ID: str = "b62-service"
    PADIEM_ENGINE_CALLER_SECRET: str = SECRET
    PADIEM_ENGINE_ALLOWED_APPS: str = "padiem-chat"


def test_registry_never_exposes_plaintext_secret() -> None:
    registry = build_registry_from_env(Env())
    assert registry is not None
    caller = registry.callers[0]
    assert caller.credential_sha256 == caller_secret_digest(SECRET)
    assert SECRET not in repr(caller)
    assert SECRET not in str(caller.to_public_dict())


def test_valid_caller_is_bound_to_requested_app() -> None:
    authenticate_request(
        env=Env(),
        headers={CALLER_ID_HEADER: "b62-service", CALLER_CREDENTIAL_HEADER: SECRET},
        requested_app_id="padiem-chat",
    )


def test_wrong_credential_fails_closed() -> None:
    with pytest.raises(ServiceIdentityError) as exc_info:
        authenticate_request(
            env=Env(),
            headers={CALLER_ID_HEADER: "b62-service", CALLER_CREDENTIAL_HEADER: "W" * 48},
            requested_app_id="padiem-chat",
        )
    assert exc_info.value.code == "service_authentication_failed"


def test_cross_app_impersonation_fails_closed() -> None:
    with pytest.raises(ServiceIdentityError) as exc_info:
        authenticate_request(
            env=Env(),
            headers={CALLER_ID_HEADER: "b62-service", CALLER_CREDENTIAL_HEADER: SECRET},
            requested_app_id="other-product",
        )
    assert exc_info.value.code == "service_app_not_authorized"


def test_missing_server_identity_fails_closed() -> None:
    class Unconfigured:
        pass

    with pytest.raises(ServiceIdentityError) as exc_info:
        authenticate_request(
            env=Unconfigured(),
            headers={CALLER_ID_HEADER: "b62-service", CALLER_CREDENTIAL_HEADER: SECRET},
            requested_app_id="padiem-chat",
        )
    assert exc_info.value.code == "service_identity_unavailable"


def test_partial_server_identity_configuration_fails_closed() -> None:
    class Partial:
        PADIEM_ENGINE_CALLER_ID = "b62-service"
        PADIEM_ENGINE_CALLER_SECRET = SECRET
        PADIEM_ENGINE_ALLOWED_APPS = ""

    with pytest.raises(ServiceIdentityError) as exc_info:
        build_registry_from_env(Partial())
    assert exc_info.value.code == "service_identity_misconfigured"


# ---------------------------------------------------------------------------
# #1698 multi-caller secret-backed registry (PADIEM_ENGINE_CALLER_REGISTRY_V1)
# ---------------------------------------------------------------------------

APP_ROOT = Path(__file__).resolve().parents[1]

SECRET_A = "A" * 48
SECRET_B = "B" * 48


def _registry_payload(*callers: dict[str, object]) -> str:
    return json.dumps({"version": CALLER_REGISTRY_V1_VERSION, "callers": list(callers)})


def _caller_entry(caller_id: str, credential: str, *app_ids: str) -> dict[str, object]:
    return {
        "caller_id": caller_id,
        "credential": credential,
        "allowed_app_ids": list(app_ids),
    }


TWO_CALLER_REGISTRY = _registry_payload(
    _caller_entry("caller-a", SECRET_A, "app-a"),
    _caller_entry("caller-b", SECRET_B, "app-b"),
)


@dataclass
class TwoCallerRegistryEnv:
    PADIEM_ENGINE_CALLER_REGISTRY_V1: str = TWO_CALLER_REGISTRY


def test_multi_caller_each_caller_authenticates_with_own_credential() -> None:
    authenticate_request(
        env=TwoCallerRegistryEnv(),
        headers={CALLER_ID_HEADER: "caller-a", CALLER_CREDENTIAL_HEADER: SECRET_A},
        requested_app_id="app-a",
    )
    authenticate_request(
        env=TwoCallerRegistryEnv(),
        headers={CALLER_ID_HEADER: "caller-b", CALLER_CREDENTIAL_HEADER: SECRET_B},
        requested_app_id="app-b",
    )


def test_multi_caller_credential_isolation_fails_closed() -> None:
    with pytest.raises(ServiceIdentityError) as exc_a:
        authenticate_request(
            env=TwoCallerRegistryEnv(),
            headers={CALLER_ID_HEADER: "caller-a", CALLER_CREDENTIAL_HEADER: SECRET_B},
            requested_app_id="app-a",
        )
    assert exc_a.value.code == "service_authentication_failed"

    with pytest.raises(ServiceIdentityError) as exc_b:
        authenticate_request(
            env=TwoCallerRegistryEnv(),
            headers={CALLER_ID_HEADER: "caller-b", CALLER_CREDENTIAL_HEADER: SECRET_A},
            requested_app_id="app-b",
        )
    assert exc_b.value.code == "service_authentication_failed"


def test_multi_caller_app_isolation_fails_closed() -> None:
    with pytest.raises(ServiceIdentityError) as exc_a:
        authenticate_request(
            env=TwoCallerRegistryEnv(),
            headers={CALLER_ID_HEADER: "caller-a", CALLER_CREDENTIAL_HEADER: SECRET_A},
            requested_app_id="app-b",
        )
    assert exc_a.value.code == "service_app_not_authorized"

    with pytest.raises(ServiceIdentityError) as exc_b:
        authenticate_request(
            env=TwoCallerRegistryEnv(),
            headers={CALLER_ID_HEADER: "caller-b", CALLER_CREDENTIAL_HEADER: SECRET_B},
            requested_app_id="app-a",
        )
    assert exc_b.value.code == "service_app_not_authorized"


def test_duplicate_caller_id_fails_closed() -> None:
    payload = _registry_payload(
        _caller_entry("caller-a", SECRET_A, "app-a"),
        _caller_entry("caller-a", SECRET_B, "app-b"),
    )

    with pytest.raises(ServiceIdentityError) as exc_info:
        build_registry_from_env(type("Env", (), {CALLER_REGISTRY_V1_ENV: payload})())
    assert exc_info.value.code == "duplicate_service_caller"


def test_duplicate_app_id_in_one_caller_fails_closed() -> None:
    payload = _registry_payload(
        _caller_entry("caller-a", SECRET_A, "app-a", "app-a"),
    )

    with pytest.raises(ServiceIdentityError) as exc_info:
        build_registry_from_env(type("Env", (), {CALLER_REGISTRY_V1_ENV: payload})())
    assert exc_info.value.code == "invalid_service_identity"


def test_registry_above_max_callers_fails_closed() -> None:
    payload = _registry_payload(
        *(
            _caller_entry(f"caller-{index:03d}", chr(65 + index % 26) * 48, f"app-{index:03d}")
            for index in range(MAX_ENGINE_CALLERS + 1)
        )
    )

    with pytest.raises(ServiceIdentityError) as exc_info:
        parse_caller_registry_v1(payload)
    assert exc_info.value.code == "invalid_caller_registry"


def test_registry_above_max_apps_per_caller_fails_closed() -> None:
    payload = _registry_payload(
        _caller_entry("caller-a", SECRET_A, *(f"app-{index:03d}" for index in range(MAX_CALLER_APP_IDS + 1))),
    )

    with pytest.raises(ServiceIdentityError) as exc_info:
        parse_caller_registry_v1(payload)
    assert exc_info.value.code == "invalid_service_identity"


def test_registry_above_bounded_input_size_fails_closed() -> None:
    oversized = '{"version":1,"callers":[]}' + " " * MAX_CALLER_REGISTRY_V1_BYTES

    with pytest.raises(ServiceIdentityError) as exc_info:
        parse_caller_registry_v1(oversized)
    assert exc_info.value.code == "invalid_caller_registry"


@pytest.mark.parametrize(
    "raw",
    [
        "{not-json",
        '{"version":2,"callers":[]}',
        '{"version":true,"callers":[]}',
        '{"callers":[]}',
        '{"version":1}',
        '{"version":1,"callers":{}}',
        '{"version":1,"callers":[]}',
        '{"version":1,"callers":["not-a-dict"]}',
        '{"version":1,"callers":[{"caller_id":"caller-a","allowed_app_ids":["app-a"]}]}',
        '{"version":1,"callers":[{"caller_id":"caller-a","credential":"A"}]}',
        '{"version":1,"callers":[{"credential":"' + "A" * 48 + '","allowed_app_ids":["app-a"]}]}',
        '{"version":1,"callers":[{"caller_id":"caller-a","credential":"' + "A" * 48 + '","allowed_app_ids":["app-a"],"extra":"bag"}]}',
        '{"version":1,"callers":[{"caller_id":"caller-a","credential":"' + "S" * 31 + '","allowed_app_ids":["app-a"]}]}',
        '{"version":1,"callers":[{"caller_id":"caller a","credential":"' + "A" * 48 + '","allowed_app_ids":["app-a"]}]}',
        '{"version":1,"callers":[{"caller_id":"caller-a","credential":"' + "A" * 48 + '","allowed_app_ids":"app-a"}]}',
        'null',
        '[]',
        '{"version":1,"callers":[1]}',
    ],
)
def test_malformed_registry_payload_fails_closed(raw: str) -> None:
    with pytest.raises(ServiceIdentityError) as exc_info:
        parse_caller_registry_v1(raw)
    assert exc_info.value.code in {
        "invalid_caller_registry",
        "invalid_service_identity",
        "invalid_service_credential",
    }
    assert SECRET_A not in str(exc_info.value)
    assert raw not in str(exc_info.value)


@pytest.mark.parametrize("blank", ["", "   ", "\n\t "])
def test_configured_blank_registry_fails_closed(blank: str) -> None:
    with pytest.raises(ServiceIdentityError) as exc_info:
        build_registry_from_env(type("Env", (), {CALLER_REGISTRY_V1_ENV: blank})())
    assert exc_info.value.code == "invalid_caller_registry"


def test_non_string_registry_value_fails_closed() -> None:
    with pytest.raises(ServiceIdentityError) as exc_info:
        build_registry_from_env(type("Env", (), {CALLER_REGISTRY_V1_ENV: 12345})())
    assert exc_info.value.code == "invalid_caller_registry"


def test_registry_absent_keeps_legacy_authority() -> None:
    registry = build_registry_from_env(Env())
    assert registry is not None
    assert len(registry.callers) == 1
    assert registry.callers[0].caller_id == "b62-service"
    assert registry.callers[0].credential_sha256 == caller_secret_digest(SECRET)


def test_registry_none_keeps_legacy_authority() -> None:
    @dataclass
    class LegacyWithNone:
        PADIEM_ENGINE_CALLER_REGISTRY_V1: None = None
        PADIEM_ENGINE_CALLER_ID: str = "b62-service"
        PADIEM_ENGINE_CALLER_SECRET: str = SECRET
        PADIEM_ENGINE_ALLOWED_APPS: str = "padiem-chat"

    registry = build_registry_from_env(LegacyWithNone())
    assert registry is not None
    assert len(registry.callers) == 1
    assert registry.callers[0].caller_id == "b62-service"


def test_fully_unconfigured_env_builds_no_registry() -> None:
    class Unconfigured:
        pass

    assert build_registry_from_env(Unconfigured()) is None


def test_registry_authority_excludes_legacy_caller() -> None:
    @dataclass
    class BothAuthorities:
        PADIEM_ENGINE_CALLER_REGISTRY_V1: str = TWO_CALLER_REGISTRY
        PADIEM_ENGINE_CALLER_ID: str = "legacy-caller"
        PADIEM_ENGINE_CALLER_SECRET: str = SECRET
        PADIEM_ENGINE_ALLOWED_APPS: str = "legacy-app"

    registry = build_registry_from_env(BothAuthorities())
    assert registry is not None
    assert tuple(caller.caller_id for caller in registry.callers) == ("caller-a", "caller-b")

    with pytest.raises(ServiceIdentityError) as exc_info:
        authenticate_request(
            env=BothAuthorities(),
            headers={CALLER_ID_HEADER: "legacy-caller", CALLER_CREDENTIAL_HEADER: SECRET},
            requested_app_id="legacy-app",
        )
    assert exc_info.value.code == "service_authentication_failed"


def test_malformed_registry_never_falls_back_to_legacy() -> None:
    @dataclass
    class MalformedPlusLegacy:
        PADIEM_ENGINE_CALLER_REGISTRY_V1: str = "{not-json"
        PADIEM_ENGINE_CALLER_ID: str = "b62-service"
        PADIEM_ENGINE_CALLER_SECRET: str = SECRET
        PADIEM_ENGINE_ALLOWED_APPS: str = "padiem-chat"

    with pytest.raises(ServiceIdentityError) as exc_build:
        build_registry_from_env(MalformedPlusLegacy())
    assert exc_build.value.code == "invalid_caller_registry"

    with pytest.raises(ServiceIdentityError) as exc_auth:
        authenticate_request(
            env=MalformedPlusLegacy(),
            headers={CALLER_ID_HEADER: "b62-service", CALLER_CREDENTIAL_HEADER: SECRET},
            requested_app_id="padiem-chat",
        )
    assert exc_auth.value.code == "invalid_caller_registry"


def test_registry_plaintext_and_digest_never_leak() -> None:
    registry = build_registry_from_env(TwoCallerRegistryEnv())
    assert registry is not None

    for caller, secret in (
        (registry.callers[0], SECRET_A),
        (registry.callers[1], SECRET_B),
    ):
        assert secret not in repr(caller)
        assert secret not in repr(registry)
        public = str(caller.to_public_dict())
        assert secret not in public
        assert caller.credential_sha256 not in public

    with pytest.raises(ServiceIdentityError) as exc_info:
        authenticate_request(
            env=TwoCallerRegistryEnv(),
            headers={CALLER_ID_HEADER: "caller-a", CALLER_CREDENTIAL_HEADER: SECRET_B},
            requested_app_id="app-a",
        )
    assert SECRET_A not in str(exc_info.value)
    assert SECRET_B not in str(exc_info.value)


def test_multi_caller_source_stays_product_neutral() -> None:
    source = (APP_ROOT / "app" / "identity_enforcement.py").read_text(encoding="utf-8")
    for forbidden in ("storymemory-b61", "b61", "lovebud-scout", "lovebud-scout-server", "padiem-chat"):
        assert forbidden not in source
