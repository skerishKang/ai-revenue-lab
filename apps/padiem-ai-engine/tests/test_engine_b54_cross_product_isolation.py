"""Engine-level cross-product session isolation regression tests for #2964.

Verifies that `AuthSessionScopeAuthority.scope_for_request` enforces
`auth_session.product_id == app_id` unconditionally for B54 and B62 combinations.

The Engine `AuthSessionScopeAuthority` is NOT changed by #2964; these tests confirm
the existing firewall remains intact after the CP identity authority is extended
to support B54.

Hard requirement: DO NOT weaken `auth_session.product_id == app_id` check.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.auth_session_scope_authority import AuthSessionScopeAuthority
from app.document_context_service import DocumentAuthorityError

_NOW = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)
_SESSION_ID = "auths_2964regressiontest"

B62_APP_ID = "padiem-chat"
B54_APP_ID = "b54-padiem-claw"


class FakeSessionClient:
    def __init__(self, payload: Any = None) -> None:
        self.payload = payload

    def resolve_auth_session(self, *, session_id: str) -> Any:
        return self.payload


def _make_session_payload(
    *, product_id: str, tenant_id: str = "tenant_test", subject_id: str = "user_2964"
) -> dict[str, Any]:
    return {
        "session_id": _SESSION_ID,
        "product_id": product_id,
        "subject": {"subject_type": "user", "subject_id": subject_id},
        "issued_at": (_NOW - timedelta(hours=1)).isoformat(),
        "expires_at": (_NOW + timedelta(hours=1)).isoformat(),
        "state": "active",
        "revision": 1,
        "tenant_id": tenant_id,
    }


def _authority() -> AuthSessionScopeAuthority:
    return AuthSessionScopeAuthority(
        session_client=FakeSessionClient(_make_session_payload(product_id=B54_APP_ID)),
        clock=lambda: _NOW,
    )


# ---------------------------------------------------------------------------
# B54 app accepts B54 session (the positive case)
# ---------------------------------------------------------------------------


async def test_b54_session_accepted_by_b54_app() -> None:
    """B54 session → B54 app: Engine accepts (product_id == app_id)."""
    authority = AuthSessionScopeAuthority(
        session_client=FakeSessionClient(_make_session_payload(product_id=B54_APP_ID)),
        clock=lambda: _NOW,
    )
    scope = await authority.scope_for_request(app_id=B54_APP_ID, auth_session_id=_SESSION_ID)
    assert scope.app_id == B54_APP_ID
    assert scope.subject_id == "user_2964"
    assert scope.tenant_id == "tenant_test"


# ---------------------------------------------------------------------------
# R07: B62 session → B54 app: Engine rejects (product_id != app_id)
# ---------------------------------------------------------------------------


async def test_r07_b62_session_rejected_by_b54_app() -> None:
    """R07: B62 session → B54 app 거부. Engine firewall: product_id ('b62') != app_id ('b54-padiem-claw')."""
    authority = AuthSessionScopeAuthority(
        session_client=FakeSessionClient(_make_session_payload(product_id=B62_APP_ID)),
        clock=lambda: _NOW,
    )
    with pytest.raises(DocumentAuthorityError) as exc:
        await authority.scope_for_request(app_id=B54_APP_ID, auth_session_id=_SESSION_ID)
    assert exc.value.code == "auth_scope_mismatch"
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# R08: B54 session → B62 app: Engine rejects (product_id != app_id)
# ---------------------------------------------------------------------------


async def test_r08_b54_session_rejected_by_b62_app() -> None:
    """R08: B54 session → B62 app 거부. Engine firewall: product_id ('b54-padiem-claw') != app_id ('padiem-chat'/'b62')."""
    authority = AuthSessionScopeAuthority(
        session_client=FakeSessionClient(_make_session_payload(product_id=B54_APP_ID)),
        clock=lambda: _NOW,
    )
    with pytest.raises(DocumentAuthorityError) as exc:
        await authority.scope_for_request(app_id=B62_APP_ID, auth_session_id=_SESSION_ID)
    assert exc.value.code == "auth_scope_mismatch"
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# Invariant confirmation: B62 session still accepted by B62 app (regression)
# ---------------------------------------------------------------------------


async def test_b62_session_accepted_by_b62_app_regression() -> None:
    """B62 session → B62 app: Engine still accepts after #2964 (no regression)."""
    authority = AuthSessionScopeAuthority(
        session_client=FakeSessionClient(_make_session_payload(product_id=B62_APP_ID)),
        clock=lambda: _NOW,
    )
    scope = await authority.scope_for_request(app_id=B62_APP_ID, auth_session_id=_SESSION_ID)
    assert scope.app_id == B62_APP_ID
    assert scope.tenant_id == "tenant_test"


# ---------------------------------------------------------------------------
# Invariant guard: product_id != app_id check must exist in source
# ---------------------------------------------------------------------------


def test_product_id_equality_check_is_present_in_source() -> None:
    """The Engine source must contain the product_id == app_id equality check.

    This test fails if someone removes or weakens the cross-product firewall.
    """
    import pathlib
    source_path = pathlib.Path(__file__).parent.parent / "app" / "auth_session_scope_authority.py"
    source = source_path.read_text(encoding="utf-8")
    # The check must compare product_id to app_id (inequality → reject)
    assert "product_id" in source
    assert "app_id" in source
    # Must contain a mismatch/rejection pattern
    assert any(pattern in source for pattern in (
        "product_id != app_id",
        "product_id == app_id",
        "auth_scope_mismatch",
    )), "Engine product/app_id firewall check must be present in source"


# ---------------------------------------------------------------------------
# Canonical Control Plane product ids (the #2964 pair), not display aliases.
#
# The store mints product_id="b62" and product_id="b54-padiem-claw", so those two
# literals are the only pair a real B54 canonical session can ever arrive with.
# ---------------------------------------------------------------------------


CP_B62_PRODUCT = "b62"
CP_B54_PRODUCT = "b54-padiem-claw"
CP_SUBJECT_ID = "sub_" + "ab" * 16
CP_TENANT_ID = "tenant_" + "cd" * 16


async def test_real_cp_b54_session_accepted_by_b54_app() -> None:
    """ENGINE_ACCEPTS_B54_SESSION_FOR_B54_APP=YES for the canonical product id pair."""
    authority = AuthSessionScopeAuthority(
        session_client=FakeSessionClient(
            _make_session_payload(
                product_id=CP_B54_PRODUCT, tenant_id=CP_TENANT_ID, subject_id=CP_SUBJECT_ID
            )
        ),
        clock=lambda: _NOW,
    )
    scope = await authority.scope_for_request(
        app_id=CP_B54_PRODUCT, auth_session_id=_SESSION_ID
    )
    assert scope.app_id == CP_B54_PRODUCT
    assert scope.subject_id == CP_SUBJECT_ID
    assert scope.tenant_id == CP_TENANT_ID


async def test_real_cp_b54_session_rejected_by_b62_app() -> None:
    """ENGINE_REJECTS_B54_SESSION_FOR_B62=YES."""
    authority = AuthSessionScopeAuthority(
        session_client=FakeSessionClient(_make_session_payload(product_id=CP_B54_PRODUCT)),
        clock=lambda: _NOW,
    )
    with pytest.raises(DocumentAuthorityError) as exc:
        await authority.scope_for_request(app_id=CP_B62_PRODUCT, auth_session_id=_SESSION_ID)
    assert exc.value.code == "auth_scope_mismatch"
    assert exc.value.status_code == 403


async def test_real_cp_b62_session_rejected_by_b54_app() -> None:
    """ENGINE_REJECTS_B62_SESSION_FOR_B54=YES."""
    authority = AuthSessionScopeAuthority(
        session_client=FakeSessionClient(_make_session_payload(product_id=CP_B62_PRODUCT)),
        clock=lambda: _NOW,
    )
    with pytest.raises(DocumentAuthorityError) as exc:
        await authority.scope_for_request(app_id=CP_B54_PRODUCT, auth_session_id=_SESSION_ID)
    assert exc.value.code == "auth_scope_mismatch"
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# Tenant postures the B54 producer must never emit
# ---------------------------------------------------------------------------


async def test_b54_session_without_a_tenant_is_not_defaulted() -> None:
    """A tenant-less B54 session fails closed: no default, no alias, no fallback."""
    payload = _make_session_payload(product_id=CP_B54_PRODUCT)
    payload.pop("tenant_id")
    authority = AuthSessionScopeAuthority(
        session_client=FakeSessionClient(payload), clock=lambda: _NOW
    )
    with pytest.raises(DocumentAuthorityError) as exc:
        await authority.scope_for_request(app_id=CP_B54_PRODUCT, auth_session_id=_SESSION_ID)
    assert exc.value.code == "tenant_unavailable"


@pytest.mark.parametrize("alias", [CP_B54_PRODUCT, CP_SUBJECT_ID])
async def test_b54_tenant_may_not_be_the_product_or_the_subject(alias: str) -> None:
    authority = AuthSessionScopeAuthority(
        session_client=FakeSessionClient(
            _make_session_payload(
                product_id=CP_B54_PRODUCT, tenant_id=alias, subject_id=alias
            )
        ),
        clock=lambda: _NOW,
    )
    with pytest.raises(DocumentAuthorityError) as exc:
        await authority.scope_for_request(app_id=CP_B54_PRODUCT, auth_session_id=_SESSION_ID)
    assert exc.value.code == "tenant_unavailable"
