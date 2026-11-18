"""#7960: a live Chat session with an expired B54 canonical session says so.

The AI customer round of 2026-11-18 06:33-08:06 hit this for real: the b62
product session was perfectly valid, only the shared B54 canonical session had
expired, and every PC command collapsed into ``chat_pc_identity_unavailable`` -
"사용자 확인 정보를 사용할 수 없습니다." - a refusal that names nothing the
person can do. The re-login that fixed it was found by trial.

The boundary decision behind this fix: the bridge refuses to let a b62 session
stand in for B54 authority ("A B62 session for the same person is never B54
authority"), and minting a B54 canonical session requires trusted server auth
evidence only a real login produces. Quietly re-establishing the B54 session
from the still-valid product session would build exactly that privilege path,
so the fix is the honest one instead: fail closed, but name the case and say
what the person should do.

Three contracts here:

* **Expired B54 + live b62** → a distinct 401 code with the re-login message,
  not the collapsed identity refusal.
* **A normal session** → exactly what it always returned (untouched contract).
* **A different owner's session** can never be recovered into this lane: the
  subject check still fails closed with the old collapsed error.

Every test runs against fakes in-process; nothing here touches a real login,
the operating session store or any production database.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app import chat_pc_drive

OWNER = "usr_" + "a" * 32
SUBJECT = "sub_" + "b" * 32
TENANT = "tenant-1"

#: The bridge's own verdict for an expired or revoked canonical session
#: (padiem_control_plane.b54_identity_bridge, session.is_active check).
BRIDGE_INACTIVE_CODE = "b54_control_plane_session_inactive"
#: What an expired B54 session must now look like to the person.
EXPECTED_MESSAGE = "로그인이 오래돼 PC 연결 확인이 필요합니다. 로그아웃 후 다시 로그인해 주세요."


def _bridge_error(code: str) -> Exception:
    from padiem_control_plane.b54_identity_bridge import B54IdentityBridgeError

    return B54IdentityBridgeError(status_code=401, code=code, safe_message="bridge")


class _Authority:
    """The b62 session answers; the bridge read is the test's switch."""

    def __init__(self, *, b54_error: Exception | None = None):
        self.calls: list[str] = []
        self.b54_error = b54_error

    async def resolve_current_auth_session(self, *, product_id, product_user_id):
        self.calls.append("b62")
        return SimpleNamespace(
            session_id="sess-b62", product_id="b62",
            subject=SimpleNamespace(subject_id=SUBJECT), tenant_id=TENANT,
            is_active=lambda *, now: True,
        )


def _patch(monkeypatch, authority) -> SimpleNamespace:
    from padiem_control_plane.b54_identity_bridge import B54IdentityBridgeError

    async def b54(auth, uid):
        authority.calls.append("b54")
        if authority.b54_error is not None:
            raise authority.b54_error
        return SimpleNamespace(auth_session=SimpleNamespace(
            session_id="sess-b54", subject=SimpleNamespace(subject_id=SUBJECT),
            tenant_id=TENANT, is_active=lambda *, now: True,
        ))

    async def memory(request, uid):
        return TENANT

    import padiem_control_plane.b54_identity_bridge as b54_module
    import app.claw_memory_routes as memory_module

    monkeypatch.setattr(b54_module, "resolve_current_b54_canonical_session", b54)
    monkeypatch.setattr(memory_module, "_resolve_memory_workspace", memory)
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        control_plane_identity_authority=authority,
    )))


def _run(request):
    return asyncio.run(chat_pc_drive._resolve_chat_owner(request, OWNER))


def test_an_expired_b54_session_names_the_relogin_walk(monkeypatch):
    """Live Chat session, expired canonical session → 401 with the person's next step.

    The code is its own word (``chat_pc_b54_session_expired``), the message is the
    action the person can take, and the collapse into ``chat_pc_identity_
    unavailable`` no longer hides it.
    """
    authority = _Authority(b54_error=_bridge_error(BRIDGE_INACTIVE_CODE))
    request = _patch(monkeypatch, authority)
    with pytest.raises(chat_pc_drive.ChatPCDriveError) as caught:
        _run(request)
    assert caught.value.code == "chat_pc_b54_session_expired"
    assert caught.value.user_message == EXPECTED_MESSAGE
    assert caught.value.status_code == 401
    # The projected browser error carries the message as-is, not just the code.
    projected = caught.value.public_error()
    assert projected["code"] == "chat_pc_b54_session_expired"
    assert projected["message"] == EXPECTED_MESSAGE
    # The journal names the case for the incident, as #7161 requires.
    assert authority.calls == ["b62", "b54"]


def test_another_bridge_failure_keeps_the_fail_closed_refusal(monkeypatch):
    """An authority outage or any other bridge verdict is not a re-login prompt."""
    authority = _Authority(b54_error=_bridge_error("b54_control_plane_session_unavailable"))
    request = _patch(monkeypatch, authority)
    with pytest.raises(chat_pc_drive.ChatPCDriveError) as caught:
        _run(request)
    assert caught.value.code == "chat_pc_identity_unavailable"
    assert caught.value.user_message == "사용자 확인 정보를 사용할 수 없습니다."
    assert caught.value.status_code == 503


def test_a_b54_error_of_another_shape_never_becomes_the_relogin_message(monkeypatch):
    """A plain exception on the bridge read keeps the collapsed refusal too."""
    authority = _Authority(b54_error=RuntimeError("b54 down"))
    request = _patch(monkeypatch, authority)
    with pytest.raises(chat_pc_drive.ChatPCDriveError) as caught:
        _run(request)
    assert caught.value.code == "chat_pc_identity_unavailable"


def test_a_live_session_returns_exactly_what_it_always_returned(monkeypatch):
    """The normal path is untouched: same triple, no new fields, no new code."""
    authority = _Authority()
    request = _patch(monkeypatch, authority)
    session, subject, workspace = _run(request)
    assert session.session_id == "sess-b54"
    assert subject == SUBJECT
    assert workspace == TENANT
    assert authority.calls == ["b62", "b54"]


def test_a_session_for_another_subject_is_not_recovered(monkeypatch):
    """A bridged session naming a different subject still fails closed.

    #6446's account isolation: the expiry path added here never widens into a
    recovery that accepts someone else's canonical session.
    """
    authority = _Authority()
    request = _patch(monkeypatch, authority)

    async def b54(auth, uid):
        return SimpleNamespace(auth_session=SimpleNamespace(
            session_id="sess-other", subject=SimpleNamespace(subject_id="sub_" + "c" * 32),
            tenant_id=TENANT, is_active=lambda *, now: True,
        ))

    async def memory(request, uid):
        return TENANT

    import padiem_control_plane.b54_identity_bridge as b54_module
    import app.claw_memory_routes as memory_module

    monkeypatch.setattr(b54_module, "resolve_current_b54_canonical_session", b54)
    monkeypatch.setattr(memory_module, "_resolve_memory_workspace", memory)
    with pytest.raises(chat_pc_drive.ChatPCDriveError) as caught:
        _run(request)
    assert caught.value.code == "chat_pc_identity_unavailable"
