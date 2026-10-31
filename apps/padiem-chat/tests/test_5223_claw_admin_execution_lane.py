"""#5223 (LOCAL 3): the Claw administrator execution lane, verified by behaviour.

#5223 absorbed #5227 and #5229.  The reviewed defect was that the manual
execution route answered a *valid* administrator with ``422 invalid_tier``,
because that route carried its own copy of the grade map instead of reusing
the administrator lane the composer lane already had.

The contract pinned here is behavioural, at the HTTP boundary, and it is
pinned for BOTH lanes because they share one grade authority:

* a verified administrator is not refused with ``422`` and reaches the
  dispatch exactly once, with the one exact administrator model;
* an ordinary member that forges the administrator grade is refused and
  dispatches nothing at all;
* an unauthenticated caller is refused and dispatches nothing at all;
* the four member grades keep working and keep their own route model.

No provider, Engine or B14 endpoint is contacted: the P01 adapter is a
recording seam, so "dispatch" is counted at the seam the route itself uses.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.model_policy import ADMIN_B14_MODEL_ID

EXECUTE_PATH = "/api/claw/manual-intake/execute"

ADMIN_USER_ID = "usr_" + "9" * 32
MEMBER_USER_ID = "usr_" + "7" * 32
ANONYMOUS_USER_ID = "usr_" + "5" * 32

PLUS_ROUTE_MODEL_ID = "test/route-plus-model"


def _settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="claw-admin-lane-client.apps.googleusercontent.com",
        google_client_secret="claw-admin-lane-google-secret",
        session_secret="claw-admin-lane-session-secret-not-a-real-credential",
        session_max_age_seconds=3600,
    )


class _AuthStore:
    """Presence-only history stub: no run history is recorded."""

    async def get_user(self, user_id: str):
        return None

    async def get_conversation(self, user_id: str, conversation_id: str):
        return None


class _AdminStore:
    """The B66 member-admin authority: only one account is an administrator."""

    def __init__(self) -> None:
        self.calls: list[str | None] = []

    async def is_google_admin(self, user_id: str | None) -> bool:
        self.calls.append(user_id)
        return user_id == ADMIN_USER_ID


class _RecordingAdapter:
    """The P01 seam: it records the dispatch instead of calling the Engine."""

    subject_identity_lane = False

    def __init__(self) -> None:
        self.dispatches: list[dict] = []

    async def execute(self, run, **kwargs):
        self.dispatches.append(dict(kwargs))
        return SimpleNamespace(
            projection=SimpleNamespace(status=SimpleNamespace(value="completed")),
            answer="실행 결과",
            p01_run_id="p01_test_run",
            p01_event_count=1,
            continuation_ref=None,
        )


@contextmanager
def _client(*, adapter: _RecordingAdapter, admin_store: _AdminStore, user_id: str | None):
    app = create_app(
        settings=_settings(),
        history_store=_AuthStore(),
        b66_member_admin_store=admin_store,
        claw_p01_adapter=adapter,
    )
    client = TestClient(app, base_url="https://chat.example.test")
    if user_id is not None:
        client.cookies.set(
            SESSION_COOKIE,
            create_session_token(_settings(), user_id),
            domain="chat.example.test",
            path="/",
        )
    with client:
        yield client


def _payload(tier: str) -> dict:
    return {
        "content": "A업체 견적 요청",
        "channel": "kakao",
        "action": "summary",
        "tier": tier,
    }


def _error_code(response) -> str | None:
    try:
        return response.json()["error"]["code"]
    except Exception:
        return None


# ── the administrator lane ─────────────────────────────────────────────────


def test_a_verified_administrator_is_not_refused_and_dispatches_the_exact_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reviewed defect: a valid administrator got ``422 invalid_tier``."""
    import app.central_model_route_runtime as route_runtime

    monkeypatch.setattr(
        route_runtime, "active_route_for", lambda label: None
    )
    adapter = _RecordingAdapter()
    admin_store = _AdminStore()
    with _client(adapter=adapter, admin_store=admin_store, user_id=ADMIN_USER_ID) as client:
        response = client.post(EXECUTE_PATH, json=_payload("admin"))

    assert response.status_code != 422, response.text
    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True
    # Exactly one dispatch, with the one exact administrator model.
    assert len(adapter.dispatches) == 1
    assert adapter.dispatches[0]["central_route_model_id"] == ADMIN_B14_MODEL_ID
    # The administrator authority was actually consulted.
    assert ADMIN_USER_ID in admin_store.calls


def test_an_ordinary_member_that_forges_the_administrator_grade_dispatches_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.central_model_route_runtime as route_runtime

    monkeypatch.setattr(
        route_runtime, "active_route_for", lambda label: None
    )
    adapter = _RecordingAdapter()
    admin_store = _AdminStore()
    with _client(adapter=adapter, admin_store=admin_store, user_id=MEMBER_USER_ID) as client:
        response = client.post(EXECUTE_PATH, json=_payload("admin"))

    assert response.status_code == 403, response.text
    assert _error_code(response) == "admin_forbidden"
    # No downstream dispatch at all.
    assert adapter.dispatches == []
    # The server asked the authority about THIS user, it did not trust the body.
    assert MEMBER_USER_ID in admin_store.calls


def test_an_unauthenticated_caller_dispatches_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.central_model_route_runtime as route_runtime

    monkeypatch.setattr(
        route_runtime, "active_route_for", lambda label: None
    )
    adapter = _RecordingAdapter()
    admin_store = _AdminStore()
    with _client(adapter=adapter, admin_store=admin_store, user_id=None) as client:
        response = client.post(EXECUTE_PATH, json=_payload("admin"))

    assert response.status_code in (401, 403), response.text
    assert adapter.dispatches == []


# ── the four member grades keep working ────────────────────────────────────


def test_a_member_grade_keeps_its_own_route_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.central_model_route_runtime as route_runtime

    monkeypatch.setattr(
        route_runtime,
        "active_route_for",
        lambda label: SimpleNamespace(model_id=PLUS_ROUTE_MODEL_ID),
    )
    adapter = _RecordingAdapter()
    admin_store = _AdminStore()
    with _client(adapter=adapter, admin_store=admin_store, user_id=MEMBER_USER_ID) as client:
        response = client.post(EXECUTE_PATH, json=_payload("plus"))

    assert response.status_code == 200, response.text
    assert len(adapter.dispatches) == 1
    # The member grade keeps its own route model and never the admin one.
    assert adapter.dispatches[0]["central_route_model_id"] == PLUS_ROUTE_MODEL_ID
    assert adapter.dispatches[0]["central_route_model_id"] != ADMIN_B14_MODEL_ID


def test_an_unknown_grade_is_still_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.central_model_route_runtime as route_runtime

    monkeypatch.setattr(
        route_runtime, "active_route_for", lambda label: None
    )
    adapter = _RecordingAdapter()
    admin_store = _AdminStore()
    with _client(adapter=adapter, admin_store=admin_store, user_id=ADMIN_USER_ID) as client:
        response = client.post(EXECUTE_PATH, json=_payload("superadmin"))

    assert response.status_code == 422, response.text
    assert _error_code(response) == "invalid_tier"
    assert adapter.dispatches == []


def test_the_browser_cannot_grant_itself_a_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A browser-supplied model id is never a grant.

    The administrator lane selects the one exact administrator model on the
    server.  A model id in the body cannot change that, so a forged body
    model never reaches the dispatch.
    """
    import app.central_model_route_runtime as route_runtime

    monkeypatch.setattr(
        route_runtime, "active_route_for", lambda label: None
    )
    adapter = _RecordingAdapter()
    admin_store = _AdminStore()
    payload = _payload("admin")
    payload["model_id"] = "attacker/chosen-model"
    with _client(adapter=adapter, admin_store=admin_store, user_id=ADMIN_USER_ID) as client:
        response = client.post(EXECUTE_PATH, json=payload)

    assert response.status_code == 200, response.text
    assert len(adapter.dispatches) == 1
    assert adapter.dispatches[0]["central_route_model_id"] == ADMIN_B14_MODEL_ID


# ── one shared grade authority for both Claw lanes ─────────────────────────


def test_both_claw_lanes_resolve_the_administrator_grade_identically() -> None:
    """The lanes must not carry their own copy of the grade map again.

    This is the structural defect behind the 422: the manual lane parsed the
    browser grade on its own.  Both lanes now resolve the grade through the
    same authority, so the administrator lane cannot drift again.
    """
    from app.claw_routes import resolve_claw_execution_grade

    admin = resolve_claw_execution_grade("admin")
    assert admin is not None
    assert admin.admin_lane is True
    assert admin.product_tier is not None
    assert admin.tier_id == "admin"

    for grade in ("free", "plus", "pro", "max"):
        member = resolve_claw_execution_grade(grade)
        assert member is not None, grade
        assert member.admin_lane is False, grade
        assert member.tier_id == grade, grade

    assert resolve_claw_execution_grade("superadmin") is None
    assert resolve_claw_execution_grade("ADMIN ") is not None  # case/space tolerant
    assert resolve_claw_execution_grade(None) is None
    assert resolve_claw_execution_grade(7) is None


def test_both_claw_lanes_call_the_shared_grade_authority() -> None:
    """Neither lane may parse the browser grade on its own again."""
    from pathlib import Path

    app_dir = Path(__file__).resolve().parents[1] / "app"
    for name in ("claw_routes.py", "claw_general_routes.py"):
        source = (app_dir / name).read_text(encoding="utf-8")
        assert "resolve_claw_execution_grade(" in source, name
        # No lane keeps a private grade map.
        assert "_BROWSER_TIER_MAP: dict[" not in source, name
        # No lane keeps a private administrator-grade comparison.
        assert '== "admin"' not in source, name
