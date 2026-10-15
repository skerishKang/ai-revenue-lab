"""B14 four-grade membership ceiling: only server-proven grade can unlock paid fallback."""
import asyncio
from types import SimpleNamespace

from app.member_grade_access import selected_grade_denial, verified_member_grade


class MemberStore:
    def __init__(self, grade="PRO", status="approved"):
        self.grade, self.status, self.calls = grade, status, []

    async def runtime_access(self, uid):
        self.calls.append(uid)
        return {"status": self.status, "tier": self.grade}


def request(store=None, mode="production"):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        b66_member_admin_store=store,
        settings=SimpleNamespace(runtime_mode=mode)
    )))


def check(req, user, tier):
    return asyncio.run(selected_grade_denial(req, user, tier))


def test_missing_server_membership_is_free_only():
    req=request()
    assert check(req, "valid-user", "free") is None
    denied=check(req, "valid-user", "plus")
    assert denied.status_code == 403
    assert b"tier_not_available" in denied.body
    assert check(req, None, "free").status_code == 401


def test_pro_member_can_choose_own_or_lower_but_not_max():
    store=MemberStore()
    req=request(store)
    for grade in ("free", "plus", "pro"):
        assert check(req, "canonical-user", grade) is None
    assert check(req, "canonical-user", "max").status_code == 403
    assert store.calls and set(store.calls)=={"canonical-user"}


def test_unapproved_record_never_grants_paid_grade():
    for status in ("pending", "suspended"):
        req=request(MemberStore(grade="MAX",status=status))
        assert check(req, "canonical-user", "max").status_code == 403
        assert check(req, "canonical-user", "free") is None


def test_offline_mock_fixture_does_not_affect_production():
    assert check(request(mode="mock"), None, "max") is None
    assert check(request(mode="production"), None, "max").status_code == 401


def test_bad_browser_grade_never_reaches_dispatch():
    assert check(request(MemberStore("MAX")), "canonical-user", "supermax").status_code == 422
    assert asyncio.run(verified_member_grade(request(MemberStore("FREE")), "canonical-user"))=="free"
