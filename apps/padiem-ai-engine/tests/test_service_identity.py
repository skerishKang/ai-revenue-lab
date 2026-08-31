import pytest

from app.service_identity import (
    AuthenticatedEngineCaller,
    EngineCallerRegistry,
    ServiceIdentityError,
    TrustedEngineCaller,
    authenticate_engine_caller,
    caller_secret_digest,
)


SECRET = "a" * 40
OTHER_SECRET = "b" * 40


def caller(**overrides) -> TrustedEngineCaller:
    values = {
        "caller_id": "service:lovetree",
        "allowed_app_ids": ("lovetree", "lovebud"),
        "credential_sha256": caller_secret_digest(SECRET),
    }
    values.update(overrides)
    return TrustedEngineCaller(**values)


def registry() -> EngineCallerRegistry:
    return EngineCallerRegistry(callers=(caller(),))


def test_plaintext_secret_is_not_stored_or_public() -> None:
    record = caller()
    public = record.to_public_dict()

    assert record.credential_sha256 != SECRET
    assert SECRET not in repr(record)
    assert "credential_sha256" not in public
    assert "credential" not in repr(public).lower()


def test_valid_caller_is_bound_to_allowed_app() -> None:
    authenticated = authenticate_engine_caller(
        registry=registry(),
        caller_id="service:lovetree",
        credential=SECRET,
        requested_app_id="lovetree",
    )

    assert authenticated == AuthenticatedEngineCaller(
        caller_id="service:lovetree",
        app_id="lovetree",
    )


def test_wrong_secret_fails_without_disclosing_expected_identity() -> None:
    with pytest.raises(ServiceIdentityError) as exc_info:
        authenticate_engine_caller(
            registry=registry(),
            caller_id="service:lovetree",
            credential=OTHER_SECRET,
            requested_app_id="lovetree",
        )

    assert exc_info.value.code == "service_authentication_failed"
    assert SECRET not in exc_info.value.safe_message
    assert "sha" not in exc_info.value.safe_message.lower()


def test_unknown_caller_fails_as_generic_authentication_failure() -> None:
    with pytest.raises(ServiceIdentityError) as exc_info:
        authenticate_engine_caller(
            registry=registry(),
            caller_id="service:unknown",
            credential=SECRET,
            requested_app_id="lovetree",
        )

    assert exc_info.value.code == "service_authentication_failed"
    assert "unknown" not in exc_info.value.safe_message.lower()


def test_valid_credential_cannot_impersonate_another_app() -> None:
    with pytest.raises(ServiceIdentityError) as exc_info:
        authenticate_engine_caller(
            registry=registry(),
            caller_id="service:lovetree",
            credential=SECRET,
            requested_app_id="b62",
        )

    assert exc_info.value.code == "service_app_not_authorized"


def test_registry_rejects_duplicate_caller_ids() -> None:
    with pytest.raises(ServiceIdentityError) as exc_info:
        EngineCallerRegistry(callers=(caller(), caller()))
    assert exc_info.value.code == "duplicate_service_caller"


def test_caller_app_scope_must_be_explicit_and_unique() -> None:
    with pytest.raises(ServiceIdentityError):
        caller(allowed_app_ids=())

    with pytest.raises(ServiceIdentityError):
        caller(allowed_app_ids=("lovetree", "lovetree"))


def test_low_entropy_short_credentials_are_rejected() -> None:
    with pytest.raises(ServiceIdentityError) as exc_info:
        caller_secret_digest("short")
    assert exc_info.value.code == "invalid_service_credential"


def test_registry_contains_only_digest_not_runtime_permissions() -> None:
    record = caller()
    fields = set(record.__dataclass_fields__)

    assert fields == {"caller_id", "allowed_app_ids", "credential_sha256"}
    for forbidden in (
        "allowed_tools",
        "entitlement",
        "provider",
        "model",
        "routing",
        "oauth",
    ):
        assert forbidden not in fields
