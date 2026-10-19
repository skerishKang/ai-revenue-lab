"""Verified Google superadmin can select every grade; forged identities cannot."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.member_grade_access import selected_grade_denial, verified_member_grade


def _request(store):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        b66_member_admin_store=store, settings=SimpleNamespace(runtime_mode="b14")
    )))


def test_verified_google_admin_gets_max_even_when_membership_free():
    class Store:
        async def is_google_admin(self, user_id):
            return user_id == "usr_verified_owner"
        async def runtime_access(self, user_id):
            return {"status": "approved", "tier": "FREE"}

    request = _request(Store())
    grade = asyncio.run(verified_member_grade(request, "usr_verified_owner"))
    assert grade == "max"
    for tier in ("free", "plus", "pro", "max"):
        assert asyncio.run(selected_grade_denial(request, "usr_verified_owner", tier)) is None


def test_non_admin_stays_free_and_cannot_claim_max():
    class Store:
        async def is_google_admin(self, user_id):
            return False
        async def runtime_access(self, user_id):
            return {"status": "approved", "tier": "FREE"}

    response = asyncio.run(selected_grade_denial(_request(Store()), "usr_customer", "max"))
    assert response.status_code == 403


def test_admin_lookup_error_never_elevates():
    class Store:
        async def is_google_admin(self, user_id):
            raise RuntimeError("lookup unavailable")
        async def runtime_access(self, user_id):
            return {"status": "approved", "tier": "FREE"}

    response = asyncio.run(selected_grade_denial(_request(Store()), "usr_customer", "pro"))
    assert response.status_code == 403
