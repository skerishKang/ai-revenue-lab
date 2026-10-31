"""The Designer reuses PADIEM's session authority instead of re-implementing it."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.contracts import DesignerError
from app.identity import (
    SESSION_COOKIE,
    B62_APP_ROOT,
    load_session_authority,
    resolve_identity,
)


def test_the_session_cookie_is_the_one_the_b62_product_owns() -> None:
    assert SESSION_COOKIE == "padiem_session"


def test_the_b62_session_authority_is_reused_when_it_is_present() -> None:
    authority = load_session_authority()

    if authority is None:
        pytest.skip("the B62 product package is not present in this checkout")

    assert hasattr(authority, "decode_session_token")
    assert B62_APP_ROOT.name == "padiem-chat"


def test_without_a_session_secret_the_app_runs_in_an_explicit_development_mode() -> None:
    identity = resolve_identity(
        session_token=None,
        settings=Settings(dev_tenant_id="tenant-a", dev_user_id="user-a"),
    )

    assert identity.auth_mode == "dev_configured"
    assert identity.tenant_id == "tenant-a"
    assert identity.user_id == "user-a"


def test_a_configured_session_secret_refuses_a_missing_session() -> None:
    with pytest.raises(DesignerError) as error:
        resolve_identity(
            session_token=None,
            settings=Settings(b14_session_secret="x" * 40),
        )

    assert error.value.status_code == 401
    assert error.value.code == "session_required"


def test_a_configured_session_secret_refuses_an_invalid_session() -> None:
    if load_session_authority() is None:
        pytest.skip("the B62 product package is not present in this checkout")

    with pytest.raises(DesignerError) as error:
        resolve_identity(
            session_token="not-a-real-session",
            settings=Settings(b14_session_secret="x" * 40),
        )

    assert error.value.status_code == 401
    assert error.value.code == "session_invalid"


def test_a_valid_session_is_accepted_by_the_b62_authority() -> None:
    authority = load_session_authority()
    if authority is None:
        pytest.skip("the B62 product package is not present in this checkout")

    secret = "s" * 40
    settings = Settings(b14_session_secret=secret, tenant_id="tenant-a")
    import importlib

    config = importlib.import_module("padiem_chat_app.config")
    authority_settings = config.Settings(
        session_secret=secret,
        session_max_age_seconds=7 * 24 * 3600,
    )
    token = authority.create_session_token(authority_settings, "usr_designer_a")

    identity = resolve_identity(session_token=token, settings=settings)

    assert identity.auth_mode == "padiem_session"
    assert identity.user_id == "usr_designer_a"
    assert identity.tenant_id == "tenant-a"
