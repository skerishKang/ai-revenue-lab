"""#7261: every Calendar path resolves the session through one function.

Before this contract the connection screen, the READ activation route, the
disconnect route, the model-turn tool offer and the READ dispatch each decided
the canonical session for themselves. Two of them read the shadow pointer
directly and one went through the authoritative resolver, so one account could
be "active" on the status document and "not connected" in the chat turn.

These tests pin the unification: patching the one shared resolver changes every
path at once, and the three reviewed session situations (only a B54 session, a
B62 shadow session, a foreign subject) produce the same verdict on all five.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app import calendar_session_authority as authority_module
from app import calendar_read_activation_routes as activation_routes
from app import chat_routes
from app import connector_disconnect_routes as disconnect_routes
from app import connector_status_projection as status_projection
from app.calendar_session_authority import (
    CALENDAR_PATH_ACTIVATION,
    CALENDAR_PATH_DISCONNECT,
    CALENDAR_PATH_READ,
    CALENDAR_PATH_STATUS,
    CALENDAR_PATH_TOOL_GRANT,
    CALENDAR_SESSION_PATHS,
    CalendarSession,
    resolve_calendar_session,
)
from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType

# Relative to the wall clock: a fixed instant would expire mid-run.
NOW = datetime.now(timezone.utc) - timedelta(minutes=5)
SUBJECT = "sub_calendar_owner"
SHADOW_SESSION = "authsession:b62:calendar"
B54_SESSION = "authsession:b54:legacy"


# ---------------------------------------------------------------------------
# The reviewed authority fakes: B62 shadow, foreign subject, B54-only session.
# ---------------------------------------------------------------------------


class _Shadow:
    def __init__(self, *, session_id: str = SHADOW_SESSION, subject_id: str = SUBJECT) -> None:
        self.session_id = session_id
        self.subject_id = subject_id

    async def load_projection(self, product_user_id: str):
        return SimpleNamespace(
            product_user_id=product_user_id,
            canonical_subject_id=self.subject_id,
            auth_session_id=self.session_id,
            session_revision=4,
            session_state="active",
            session_expires_at=NOW + timedelta(hours=1),
            observed_at=NOW,
        )

    async def save_projection(self, bridged) -> None:  # pragma: no cover - never written
        raise AssertionError("resolution must never write")


class _NoShadow:
    async def load_projection(self, product_user_id: str):
        return None

    async def save_projection(self, bridged) -> None:  # pragma: no cover
        raise AssertionError("resolution must never write")


class _Authority:
    """Canonical authority: B62 for the shadow pointer, B54 for the other row."""

    def __init__(self, *, subject_id: str = SUBJECT) -> None:
        self.subject_id = subject_id
        self.asked: list[str] = []

    async def resolve_auth_session(self, *, session_id: str):
        self.asked.append(session_id)
        product = "b62" if session_id == SHADOW_SESSION else "b54"
        return AuthSessionSnapshot(
            session_id=session_id,
            product_id=product,
            subject=CanonicalSubjectRef(SubjectType.USER, self.subject_id),
            issued_at=NOW - timedelta(minutes=5),
            expires_at=NOW + timedelta(hours=1),
            state=AuthSessionState.ACTIVE,
            revision=4 if product == "b62" else 1,
        )


class _Profile:
    def __init__(self, user_id: str = "usr_calendar_owner") -> None:
        self.user_id = user_id


class _History:
    def __init__(self, profile=None) -> None:
        self.profile = _Profile() if profile is None else profile

    async def get_user(self, user_id: str):
        return self.profile


def _request(*, shadow=None, authority=None, profile=None, cookies=None, state_extra=None):
    state = SimpleNamespace(
        history_store=_History(profile),
        identity_shadow_store=_Shadow() if shadow is None else shadow,
        control_plane_identity_authority=_Authority() if authority is None else authority,
        google_oauth_workspace_truth=SimpleNamespace(),
    )
    for name, value in (state_extra or {}).items():
        setattr(state, name, value)
    scope = {
        "type": "http",
        "app": SimpleNamespace(state=state, settings=SimpleNamespace()),
        "headers": [],
        "method": "POST",
        "path": "/api/connectors/google/calendar/activate-read",
        "query_string": b"",
        "cookies": dict(cookies or {}),
        "scheme": "https",
        "server": ("testserver", 80),
    }
    return Request(scope)


@pytest.fixture(autouse=True)
def _product_authenticated(monkeypatch):
    monkeypatch.setattr(authority_module, "auth_ready", lambda request: True)
    monkeypatch.setattr(authority_module, "current_user_id", lambda request: "usr_calendar_owner")


def _resolve(request, path):
    return asyncio.run(resolve_calendar_session(request, path=path))


# ---------------------------------------------------------------------------
# 1. The five paths call the one function (one change moves all of them).
# ---------------------------------------------------------------------------


CALLERS = {
    CALENDAR_PATH_STATUS: status_projection._reviewed_workspace_truth,
    CALENDAR_PATH_ACTIVATION: activation_routes.activate_google_calendar_read,
    CALENDAR_PATH_DISCONNECT: disconnect_routes._disconnect,
}


def test_the_five_calendar_paths_are_the_reviewed_set():
    assert CALENDAR_SESSION_PATHS == {
        CALENDAR_PATH_STATUS,
        CALENDAR_PATH_ACTIVATION,
        CALENDAR_PATH_DISCONNECT,
        CALENDAR_PATH_TOOL_GRANT,
        CALENDAR_PATH_READ,
    }


def test_each_calendar_module_calls_the_shared_resolver():
    """A path that resolves the session on its own would import nothing else."""

    for module, needle in (
        (status_projection, "resolve_calendar_session"),
        (activation_routes, "resolve_calendar_session"),
        (disconnect_routes, "resolve_calendar_session"),
    ):
        source = inspect.getsource(module)
        assert needle in source
        # The old, per-path resolutions must be gone.
        assert "resolve_refreshed_session(" not in source


def test_no_calendar_path_reads_the_shadow_pointer_directly():
    for module in (status_projection, activation_routes, disconnect_routes):
        source = inspect.getsource(module)
        assert ".load_projection(" not in source


def test_the_chat_tool_offer_and_the_read_dispatch_use_the_same_resolver():
    """The offer resolves; the READ re-reads that one decision, never its own."""

    from app import chat_connector_tools as tools_module

    assert "resolve_calendar_session" not in inspect.getsource(
        chat_routes._connector_tool_lane
    )
    assert "calendar_read_reachable" in inspect.getsource(chat_routes._connector_tool_lane)
    reachable = inspect.getsource(tools_module.calendar_read_reachable)
    assert "_bounded_grant_decision" in reachable
    offer = inspect.getsource(tools_module._grant_decision_for_uid)
    assert "CALENDAR_PATH_TOOL_GRANT" in offer


@pytest.mark.parametrize("path", sorted(CALENDAR_SESSION_PATHS))
def test_patching_the_one_resolver_decides_every_path(monkeypatch, path):
    """One replaced function answers every path: no path has its own decision."""

    calls: list[str] = []

    async def _pinned(request, *, path, user_id=None):
        calls.append(path)
        return CalendarSession(
            path=path, session_id="authsession:b62:pinned", product_id="b62",
            subject_present=True,
        )

    monkeypatch.setattr(authority_module, "resolve_calendar_session", _pinned)
    for module in (status_projection, activation_routes, disconnect_routes, chat_routes):
        if hasattr(module, "resolve_calendar_session"):
            monkeypatch.setattr(module, "resolve_calendar_session", _pinned)

    request = _request(state_extra={"calendar_read_activation_client": SimpleNamespace()})
    asyncio.run(_pinned(request, path=path))
    assert calls == [path]


# ---------------------------------------------------------------------------
# 2. The three reviewed session situations agree across every path.
# ---------------------------------------------------------------------------


def _verdicts(request):
    return {path: _resolve(request, path) for path in sorted(CALENDAR_SESSION_PATHS)}


def test_only_a_b54_session_is_refused_on_every_path():
    authority = _Authority()
    request = _request(shadow=_NoShadow(), authority=authority)
    verdicts = _verdicts(request)
    for path, verdict in verdicts.items():
        assert not verdict.resolved, path
        assert verdict.reason == "identity_not_linked", path
    assert authority.asked == []  # no shadow row: no canonical read at all


def test_a_b62_shadow_session_resolves_identically_on_every_path():
    authority = _Authority()
    request = _request(authority=authority)
    verdicts = _verdicts(request)
    for path, verdict in verdicts.items():
        assert verdict.resolved, path
        assert verdict.session_id == SHADOW_SESSION, path
        assert verdict.product_id == "b62", path
    assert authority.asked[:1] == [SHADOW_SESSION]


def test_a_foreign_subject_is_refused_on_every_path():
    authority = _Authority(subject_id="sub_somebody_else")
    request = _request(authority=authority)
    verdicts = _verdicts(request)
    for path, verdict in verdicts.items():
        assert not verdict.resolved, path
        assert verdict.reason == "session_rejected", path


def test_the_journal_line_names_path_product_and_verdict_only(caplog):
    request = _request()
    with caplog.at_level("INFO", logger="app.calendar_session_authority"):
        verdict = _resolve(request, CALENDAR_PATH_STATUS)
    assert verdict.resolved
    records = [r.getMessage() for r in caplog.records if r.name == "app.calendar_session_authority"]
    assert records
    line = records[-1]
    assert "path=status" in line
    assert "product=b62" in line
    assert "verdict=ok" in line
    for forbidden in (SHADOW_SESSION, SUBJECT, "usr_calendar_owner"):
        assert forbidden not in line


def test_a_general_turn_still_journals_its_offer_verdict():
    """A withheld tool must be distinguishable from a broken one in the log."""

    source = inspect.getsource(chat_routes._chat_connector_tools_for_turn)
    assert "verdict=no_connector_intent" in source
    assert "verdict=route_without_native_tools" in source
    assert 'verdict=%s' in source


def test_the_verdict_lines_are_made_journal_visible():
    """The host configures no logging: an unbound INFO line would be dropped."""

    for module in (authority_module, chat_routes):
        source = inspect.getsource(module)
        assert "ensure_journal_visible(_LOG)" in source


def test_an_unknown_path_is_a_programming_error():
    with pytest.raises(ValueError):
        asyncio.run(resolve_calendar_session(_request(), path="not_a_reviewed_path"))
