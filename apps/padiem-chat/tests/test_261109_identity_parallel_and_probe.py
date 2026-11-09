"""2026-11-09: independent identity reads run together; each RPC is observable.

Two changes, one contract each.

**Parallelism.** ``_resolve_chat_owner`` asked the Control Plane three
questions with no dependency between them (b62 product session, B54 bridge
session, memory workspace) and paid their round trips serially; the measured
cost per identity call is dominated by the trip to the Control Plane, not by
the read. They are now issued together while every verdict and the *order* in
which a refusal is reported stay exactly as before.

**Observability.** Each identity RPC logs one bounded line: client TTFB, the
Cloudflare edge location that answered (``cf-ray`` suffix), and whether a
pooled TLS connection was reused. No payload, token, session or address.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest

from app import chat_pc_drive
from app import local_service_bridge as bridge


OWNER = "usr_" + "a" * 32
SUBJECT = "sub_" + "b" * 32
WORKSPACE = "ws-1"


class _Authority:
    """Both reads answer, and each records when it was entered and left."""

    def __init__(self, *, b62_error=None, b54_error=None, workspace_error=None):
        self.events: list[str] = []
        self.b62_error = b62_error
        self.b54_error = b54_error
        self.workspace_error = workspace_error

    async def resolve_current_auth_session(self, *, product_id, product_user_id):
        self.events.append("b62:enter")
        await asyncio.sleep(0.05)
        self.events.append("b62:leave")
        if self.b62_error is not None:
            raise self.b62_error
        return SimpleNamespace(
            session_id="sess-b62", product_id="b62",
            subject=SimpleNamespace(subject_id=SUBJECT), tenant_id=WORKSPACE,
            is_active=lambda *, now: True,
        )


def _patch(monkeypatch, authority, *, workspace_result="ws-memory"):
    async def memory(request, uid):
        authority.events.append("workspace:enter")
        await asyncio.sleep(0.05)
        authority.events.append("workspace:leave")
        if authority.workspace_error is not None:
            raise authority.workspace_error
        return workspace_result

    async def b54(auth, uid):
        authority.events.append("b54:enter")
        await asyncio.sleep(0.05)
        authority.events.append("b54:leave")
        if authority.b54_error is not None:
            raise authority.b54_error
        return SimpleNamespace(auth_session=SimpleNamespace(
            session_id="sess-b54", subject=SimpleNamespace(subject_id=SUBJECT),
            tenant_id=WORKSPACE, is_active=lambda *, now: True,
        ))

    import padiem_control_plane.b54_identity_bridge as b54_module
    import app.claw_memory_routes as memory_module

    monkeypatch.setattr(b54_module, "resolve_current_b54_canonical_session", b54)
    monkeypatch.setattr(memory_module, "_resolve_memory_workspace", memory)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        control_plane_identity_authority=authority,
    )))
    return request


def _run(request):
    return asyncio.run(chat_pc_drive._resolve_chat_owner(request, OWNER))


def test_the_post_gate_reads_overlap(monkeypatch):
    """The B54 bridge read and the memory workspace are issued together.

    The b62 read stays first on purpose: its gate decides whether the lane may
    ask for anything else at all (the P01 roundtrip contract pins that a refused
    b62 must not produce a second identity call).
    """
    authority = _Authority()
    request = _patch(monkeypatch, authority)
    session, subject, workspace = _run(request)

    assert subject == SUBJECT and workspace == "ws-memory"
    assert session.session_id == "sess-b54"
    events = authority.events
    assert events.index("b62:leave") < events.index("b54:enter")
    b54_enter = events.index("b54:enter")
    workspace_enter = events.index("workspace:enter")
    first_leave = min(events.index("b54:leave"), events.index("workspace:leave"))
    assert b54_enter < first_leave and workspace_enter < first_leave, events


def test_a_b62_failure_is_reported_without_asking_for_anything_else(monkeypatch):
    """A refused b62 never produces a second identity RPC (unchanged contract)."""
    authority = _Authority(
        b62_error=RuntimeError("b62 down"), b54_error=RuntimeError("b54 down"),
    )
    request = _patch(monkeypatch, authority)
    with pytest.raises(chat_pc_drive.ChatPCDriveError) as caught:
        _run(request)
    assert caught.value.code == "chat_pc_identity_unavailable"
    assert isinstance(caught.value.__cause__, RuntimeError)
    assert str(caught.value.__cause__) == "b62 down"
    assert "b54:enter" not in authority.events
    assert "workspace:enter" not in authority.events


def test_a_b54_failure_is_still_reported_when_b62_succeeds(monkeypatch):
    authority = _Authority(b54_error=RuntimeError("b54 down"))
    request = _patch(monkeypatch, authority)
    with pytest.raises(chat_pc_drive.ChatPCDriveError) as caught:
        _run(request)
    assert str(caught.value.__cause__) == "b54 down"


def test_an_invalid_b62_session_is_still_refused(monkeypatch):
    authority = _Authority()
    request = _patch(monkeypatch, authority)

    async def wrong_product(**kwargs):
        return SimpleNamespace(
            session_id="s", product_id="b54",
            subject=SimpleNamespace(subject_id=SUBJECT), tenant_id=WORKSPACE,
            is_active=lambda *, now: True,
        )

    authority.resolve_current_auth_session = wrong_product  # type: ignore[assignment]
    with pytest.raises(chat_pc_drive.ChatPCDriveError):
        _run(request)


def test_a_workspace_failure_falls_back_to_the_verified_tenant(monkeypatch):
    authority = _Authority(workspace_error=RuntimeError("memory down"))
    request = _patch(monkeypatch, authority)
    _session, _subject, workspace = _run(request)
    assert workspace == WORKSPACE


# ------------------------------------------------------------------ probe
def _response(*, status=200, headers=None, ssl_object=None):
    stream = None
    if ssl_object is not None:
        stream = SimpleNamespace(get_extra_info=lambda name: ssl_object
                                 if name == "ssl_object" else None)
    return SimpleNamespace(
        status_code=status, headers=headers or {},
        extensions={"network_stream": stream} if stream is not None else {},
    )


def test_the_edge_location_is_only_the_three_letter_code():
    assert bridge._colo_of(_response(headers={"cf-ray": "8abc123def456-ICN"})) == "ICN"
    assert bridge._colo_of(_response(headers={"cf-ray": "nonsense"})) == "none"
    assert bridge._colo_of(_response(headers={"cf-ray": "abc-12"})) == "none"
    assert bridge._colo_of(_response()) == "none"


def test_connection_reuse_is_reported_only_when_it_is_known():
    # Distinct live objects: ids of freshly created temporaries can be reused
    # by the interpreter once they are collected, which is not what a real
    # client produces (it holds its connections).
    first_connection, second_connection = object(), object()
    first, marker = bridge._connection_reused(
        _response(ssl_object=first_connection), None,
    )
    assert first == "first"
    same, _ = bridge._connection_reused(_response(ssl_object=second_connection), marker)
    assert same == "false"
    # Same connection twice is a reuse.
    _, marker2 = bridge._connection_reused(
        _response(ssl_object=first_connection), None,
    )
    reused, _ = bridge._connection_reused(
        _response(ssl_object=first_connection), marker2,
    )
    assert reused == "true"
    # No stream exposed (Cloudflare runtime / injected transport) is unknown.
    assert bridge._connection_reused(_response(), None)[0] == "unknown"


def test_the_rpc_line_reaches_stderr_with_every_field(capsys):
    logger = logging.getLogger("padiem_chat.identity_rpc_client")
    root = logging.getLogger()
    saved = (list(root.handlers), list(logger.handlers), logger.propagate, logger.level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    logger.propagate = True
    logger.setLevel(logging.NOTSET)
    try:
        bridge.ensure_journal_visible(logger)
        logger.info(
            "identity_rpc_client method=%s status=%s ttfb_ms=%d reused=%s colo=%s attempt=%d",
            "resolve_current_auth_session", 200, 412, "true", "ICN", 1,
        )
    finally:
        captured = capsys.readouterr()
        root.handlers[:] = saved[0]
        logger.handlers[:] = saved[1]
        logger.propagate = saved[2]
        logger.setLevel(saved[3])
    line = captured.err.strip()
    assert line.startswith("identity_rpc_client method=resolve_current_auth_session")
    for field in ("status=200", "ttfb_ms=412", "reused=true", "colo=ICN", "attempt=1"):
        assert field in line, line
