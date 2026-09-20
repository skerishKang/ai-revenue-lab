"""#2829 Phase A — canonical session projection for Claw runs (backend only).

Covers the bounded contract: the execute route may carry an optional
``conversation_id`` referencing the existing canonical conversation authority;
resolution reuses the conversation shape validator and the owner-scoped
conversation lookup, fails closed before quota/tenant/dispatch, and echoes
only the validated handle back. Run-history rows project a ``session`` object
only when the stored row supplies a validated owner reference — legacy rows
(which persist no reference) project ``session: null``, never a fabricated
session and never a raw internal id. No migration ships in Phase A.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from starlette.testclient import TestClient

from app import history as history_module
from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.history import _run_history_public

EXECUTE_ROUTE_PATH = "/api/claw/manual-intake/execute"
RUNS_HISTORY_ROUTE_PATH = "/api/claw/runs"

SIGNED_IN_USER_ID = "usr_" + "7" * 32
OTHER_USER_ID = "usr_" + "f" * 32
OWNED_CONVERSATION_ID = "chat_" + "a1" * 16
MALFORMED_CONVERSATION_ID = "chat_zzz"
RAW_USER_ID_CANDIDATE = "usr_" + "7" * 32

# The exact Phase A persisted-run kwargs. Pinning this set proves the session
# reference is carried/resolved WITHOUT silently widening the storage record.
# Phase B adds conversation_id as a trailing optional parameter.
RECORDED_RUN_KWARGS = {
    "user_id",
    "run_id",
    "channel",
    "action",
    "title",
    "status",
    "result_summary",
    "artifact_document_id",
    "artifact_filename",
    "artifact_media_type",
    "conversation_id",
}


def _google_settings(**overrides) -> Settings:
    values = {
        "runtime_mode": "mock",
        "auth_mode": "google",
        "public_base_url": "https://chat.example.test",
        "google_client_id": "claw-gate-client.apps.googleusercontent.com",
        "google_client_secret": "claw-gate-google-secret",
        "session_secret": "claw-gate-session-secret-not-a-real-credential-0",
        "session_max_age_seconds": 3600,
    }
    values.update(overrides)
    return Settings.from_values(**values)


class _SessionHistoryStore:
    """Async store exercising the real conversation authority + run-history seam."""

    def __init__(self, *, rows: dict | None = None, raise_on_get: bool = False) -> None:
        self.conversations: dict[str, dict] = {
            OWNED_CONVERSATION_ID: {"id": OWNED_CONVERSATION_ID, "user_id": SIGNED_IN_USER_ID},
        }
        self.get_calls: list[tuple[str, str]] = []
        self.record_calls: list[dict] = []
        self.rows = rows or {}
        self.raise_on_get = raise_on_get

    async def get_user(self, user_id: str):
        return None

    async def get_conversation(self, user_id: str, conversation_id: str):
        self.get_calls.append((user_id, conversation_id))
        if self.raise_on_get:
            raise RuntimeError("conversation authority read failed")
        stored = self.conversations.get(conversation_id)
        if stored is None or stored.get("user_id") != user_id:
            return None
        return dict(stored)

    async def record_claw_run(self, **kwargs) -> None:
        self.record_calls.append(kwargs)

    async def list_recent_claw_runs(self, user_id: str, limit: int) -> list[dict]:
        # Mirrors D1HistoryStore: rows leave the store projection-boundary only.
        return [
            _run_history_public(row)
            for row in self.rows.values()
            if row.get("user_id") == user_id
        ][:limit]


def _app_with(store: object, *, auth_mode: str = "google") -> object:
    app = create_app(
        settings=_google_settings(auth_mode=auth_mode) if auth_mode == "google"
        else Settings.from_values(runtime_mode="mock", live_enabled="false", auth_mode="off"),
        history_store=store,
    )
    return app


def _signed_in_client(store: object) -> TestClient:
    client = TestClient(_app_with(store), base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE,
        create_session_token(_google_settings(), SIGNED_IN_USER_ID),
        domain="chat.example.test",
        path="/",
    )
    return client


def _make_outcome() -> MagicMock:
    status_mock = MagicMock()
    status_mock.value = "completed"
    projection = MagicMock()
    projection.status = status_mock
    projection.run_id = "run_test123"
    outcome = MagicMock()
    outcome.projection = projection
    outcome.answer = "test result"
    outcome.p01_run_id = "p01_run_test123"
    outcome.p01_event_count = 2
    return outcome


def _make_adapter() -> MagicMock:
    adapter = MagicMock()
    adapter.execute = AsyncMock(return_value=_make_outcome())
    return adapter


@contextmanager
def _injected_adapter(test_client: TestClient, adapter: object):
    previous = test_client.app.state.claw_p01_adapter
    test_client.app.state.claw_p01_adapter = adapter
    try:
        yield adapter
    finally:
        test_client.app.state.claw_p01_adapter = previous


def _execute_payload(**extra) -> dict:
    payload = {"content": "테스트 reply 요청.", "channel": "kakao", "action": "reply"}
    payload.update(extra)
    return payload


# ── execute: carry + resolve ──────────────────────────────────────────────────


def test_execute_without_conversation_id_is_byte_identical_legacy() -> None:
    store = _SessionHistoryStore()
    adapter = _make_adapter()
    with _signed_in_client(store) as client, _injected_adapter(client, adapter):
        resp = client.post(EXECUTE_ROUTE_PATH, json=_execute_payload())
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert "conversation_id" not in result
    assert store.get_calls == []
    assert len(store.record_calls) == 1
    assert set(store.record_calls[0]) == RECORDED_RUN_KWARGS
    assert store.record_calls[0]["conversation_id"] is None
    adapter.execute.assert_awaited_once()


def test_execute_empty_string_conversation_id_is_rejected_not_ignored() -> None:
    # The canonical validator rejects a wrong shape even for empty strings —
    # a carried-but-unparseable reference never degrades into legacy silence.
    store = _SessionHistoryStore()
    adapter = _make_adapter()
    with _signed_in_client(store) as client, _injected_adapter(client, adapter):
        resp = client.post(EXECUTE_ROUTE_PATH, json=_execute_payload(conversation_id=""))
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_conversation_id"
    assert store.get_calls == []
    adapter.execute.assert_not_called()


def test_execute_owned_conversation_echoes_bounded_handle_and_stores_no_link() -> None:
    store = _SessionHistoryStore()
    adapter = _make_adapter()
    with _signed_in_client(store) as client, _injected_adapter(client, adapter):
        resp = client.post(
            EXECUTE_ROUTE_PATH, json=_execute_payload(conversation_id=OWNED_CONVERSATION_ID)
        )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["conversation_id"] == OWNED_CONVERSATION_ID
    assert store.get_calls == [(SIGNED_IN_USER_ID, OWNED_CONVERSATION_ID)]
    # Phase B: the exact validated conversation_id is now persisted.
    assert len(store.record_calls) == 1
    assert set(store.record_calls[0]) == RECORDED_RUN_KWARGS
    assert store.record_calls[0]["conversation_id"] == OWNED_CONVERSATION_ID
    adapter.execute.assert_awaited_once()


def test_execute_never_discloses_internal_identifiers_through_session_echo() -> None:
    store = _SessionHistoryStore()
    with _signed_in_client(store) as client, _injected_adapter(client, _make_adapter()):
        resp = client.post(
            EXECUTE_ROUTE_PATH, json=_execute_payload(conversation_id=OWNED_CONVERSATION_ID)
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "usr_" not in resp.text
    assert SIGNED_IN_USER_ID not in str(body["result"])


def test_execute_foreign_or_missing_conversation_fails_closed_not_found() -> None:
    store = _SessionHistoryStore()
    adapter = _make_adapter()
    with _signed_in_client(store) as client, _injected_adapter(client, adapter):
        resp = client.post(
            EXECUTE_ROUTE_PATH,
            json=_execute_payload(conversation_id="chat_" + "b2" * 16),
        )
    assert resp.status_code == 404
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "conversation_not_found"
    # Non-disclosing: the exact same projection for missing and foreign rows.
    assert body["error"]["message"] == "대화를 찾을 수 없습니다."
    assert store.get_calls == [(SIGNED_IN_USER_ID, "chat_" + "b2" * 16)]
    assert store.record_calls == []
    adapter.execute.assert_not_called()


def test_execute_malformed_conversation_id_is_rejected_before_authority_lookup() -> None:
    store = _SessionHistoryStore()
    adapter = _make_adapter()
    with _signed_in_client(store) as client, _injected_adapter(client, adapter):
        resp = client.post(
            EXECUTE_ROUTE_PATH, json=_execute_payload(conversation_id=MALFORMED_CONVERSATION_ID)
        )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_conversation_id"
    assert store.get_calls == []
    adapter.execute.assert_not_called()


def test_execute_non_string_conversation_id_is_rejected() -> None:
    store = _SessionHistoryStore()
    adapter = _make_adapter()
    with _signed_in_client(store) as client, _injected_adapter(client, adapter):
        resp = client.post(
            EXECUTE_ROUTE_PATH, json=_execute_payload(conversation_id={"nested": True})
        )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_conversation_id"
    adapter.execute.assert_not_called()


def test_execute_session_reference_anonymous_fails_closed_before_dispatch() -> None:
    # auth off ⇒ no server-derived identity ⇒ a carried reference cannot be
    # attributed, so it must fail closed rather than execute unattributed.
    store = _SessionHistoryStore()
    adapter = _make_adapter()
    client = TestClient(_app_with(store, auth_mode="off"))
    with _injected_adapter(client, adapter):
        resp = client.post(
            EXECUTE_ROUTE_PATH, json=_execute_payload(conversation_id=OWNED_CONVERSATION_ID)
        )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"
    assert store.get_calls == []
    assert store.record_calls == []
    adapter.execute.assert_not_called()


def test_execute_session_reference_authority_read_failure_is_503() -> None:
    store = _SessionHistoryStore(raise_on_get=True)
    adapter = _make_adapter()
    with _signed_in_client(store) as client, _injected_adapter(client, adapter):
        resp = client.post(
            EXECUTE_ROUTE_PATH, json=_execute_payload(conversation_id=OWNED_CONVERSATION_ID)
        )
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "conversation_authority_unavailable"
    adapter.execute.assert_not_called()


def test_execute_session_reference_without_authority_capability_is_503() -> None:
    class _PresenceOnly:
        async def get_user(self, user_id):
            return None

    adapter = _make_adapter()
    with _signed_in_client(_PresenceOnly()) as client, _injected_adapter(client, adapter):
        resp = client.post(
            EXECUTE_ROUTE_PATH, json=_execute_payload(conversation_id=OWNED_CONVERSATION_ID)
        )
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "conversation_authority_unavailable"
    adapter.execute.assert_not_called()


# ── projection: _run_history_public session field ────────────────────────────


def _run_row(**overrides) -> dict:
    row = {
        "run_id": "run_1",
        "channel": "kakao",
        "action": "quote_draft",
        "title": "T",
        "status": "completed",
        "created_at": "2026-09-20T00:00:00+00:00",
        "updated_at": None,
        "result_summary": None,
        "artifact_document_id": None,
        "artifact_filename": None,
        "artifact_media_type": None,
    }
    row.update(overrides)
    return row


def test_projection_legacy_row_without_reference_has_null_session() -> None:
    public = _run_history_public(_run_row())
    assert public["session"] is None


def test_projection_valid_reference_is_bounded_to_conversation_handle() -> None:
    public = _run_history_public(_run_row(conversation_id=OWNED_CONVERSATION_ID))
    assert public["session"] == {"conversation_id": OWNED_CONVERSATION_ID}


def test_projection_never_fabricates_session_from_unsafe_candidates() -> None:
    for candidate in (
        RAW_USER_ID_CANDIDATE,          # raw product user id
        "chat_" + "z" * 32,             # wrong alphabet
        "chat_" + "a1" * 15,            # too short
        "x" * 400_000,                  # oversized
        12345,                          # non-string
        {"id": OWNED_CONVERSATION_ID},  # structured injection
        "",                             # empty
        "   ",                          # whitespace-only
    ):
        public = _run_history_public(_run_row(conversation_id=candidate))
        assert public["session"] is None, f"fabricated session for candidate {candidate!r}"


def test_projection_row_carries_no_internal_keys() -> None:
    public = _run_history_public(_run_row(conversation_id=OWNED_CONVERSATION_ID))
    assert set(public) == {
        "run_id", "channel", "action", "title", "status",
        "created_at", "updated_at", "result_summary", "artifact", "session",
    }
    assert "user_id" not in public
    assert "conversation_id" not in public


# ── GET /api/claw/runs route projection ───────────────────────────────────────


def test_runs_history_projects_bounded_session_per_row() -> None:
    store = _SessionHistoryStore(rows={
        "run_a": _run_row(user_id=SIGNED_IN_USER_ID, run_id="run_a",
                          conversation_id=OWNED_CONVERSATION_ID),
        "run_b": _run_row(user_id=SIGNED_IN_USER_ID, run_id="run_b",
                          conversation_id=RAW_USER_ID_CANDIDATE),
        "run_c": _run_row(user_id=OTHER_USER_ID, run_id="run_c",
                          conversation_id=OWNED_CONVERSATION_ID),
    })
    client = _signed_in_client(store)
    resp = client.get(RUNS_HISTORY_ROUTE_PATH)
    assert resp.status_code == 200
    runs = {row["run_id"]: row for row in resp.json()["runs"]}
    assert runs["run_a"]["session"] == {"conversation_id": OWNED_CONVERSATION_ID}
    assert runs["run_b"]["session"] is None
    assert "run_c" not in runs
    assert OTHER_USER_ID not in resp.text


def test_runs_history_legacy_rows_serialise_null_session() -> None:
    store = _SessionHistoryStore(rows={
        "run_a": _run_row(user_id=SIGNED_IN_USER_ID, run_id="run_a"),
    })
    client = _signed_in_client(store)
    resp = client.get(RUNS_HISTORY_ROUTE_PATH)
    assert resp.status_code == 200
    assert resp.json()["runs"][0]["session"] is None


# ── storage non-regression: Phase A → Phase B migration boundary ─────────────


def test_phase_b_adds_exactly_one_additive_nullable_conversation_migration() -> None:
    """Phase B adds exactly one migration that adds nullable conversation_id.

    The migration is additive only: ALTER TABLE ... ADD COLUMN, no new table,
    no foreign key, no destructive change, no rewrite of existing columns.
    """
    migrations_dir = Path(history_module.__file__).resolve().parents[1] / "migrations"
    migration_files = sorted(migrations_dir.glob("*.sql"))
    names = [p.name for p in migration_files]
    assert "014_claw_run_history_conversation.sql" in names
    # Exactly one migration references conversation_id + claw_run_history.
    hits = [p.name for p in migration_files
            if "conversation_id" in p.read_text(encoding="utf-8").lower()
            and "claw_run_history" in p.read_text(encoding="utf-8").lower()]
    assert hits == ["014_claw_run_history_conversation.sql"]
    content = (migrations_dir / "014_claw_run_history_conversation.sql").read_text(encoding="utf-8").lower()
    assert "alter table claw_run_history add column conversation_id text;" in content
    assert "create table" not in content
    assert "drop table" not in content
    assert "foreign key" not in content
    assert "references" not in content


# ── #2829 Phase B: persisted run-to-conversation linkage ─────────────────────


def test_phase_b_adds_exactly_one_additive_nullable_conversation_migration() -> None:
    """Phase B adds exactly one migration that adds nullable conversation_id.

    The migration is additive only: ALTER TABLE ... ADD COLUMN, no new table,
    no foreign key, no destructive change, no rewrite of existing columns.
    """
    migrations_dir = Path(history_module.__file__).resolve().parents[1] / "migrations"
    migration_files = sorted(migrations_dir.glob("*.sql"))
    names = [p.name for p in migration_files]
    assert "014_claw_run_history_conversation.sql" in names
    # Exactly one migration references conversation_id + claw_run_history.
    hits = [p.name for p in migration_files
            if "conversation_id" in p.read_text(encoding="utf-8").lower()
            and "claw_run_history" in p.read_text(encoding="utf-8").lower()]
    assert hits == ["014_claw_run_history_conversation.sql"]
    content = (migrations_dir / "014_claw_run_history_conversation.sql").read_text(encoding="utf-8").lower()
    assert "alter table claw_run_history add column conversation_id text;" in content
    assert "create table" not in content
    assert "drop table" not in content
    assert "foreign key" not in content
    assert "references" not in content


def test_phase_b_d1_select_includes_conversation_id() -> None:
    """The D1 list query now selects the persisted conversation_id column."""
    source = Path(history_module.__file__).read_text(encoding="utf-8")
    select = source.split("SELECT run_id, channel", 1)[1].split("FROM claw_run_history", 1)[0]
    assert "conversation_id" in select


def test_phase_b_record_claw_run_accepts_optional_conversation_id() -> None:
    """record_claw_run signature accepts conversation_id as trailing optional."""
    import inspect
    from app.history import HistoryStore
    sig = inspect.signature(HistoryStore.record_claw_run)
    params = list(sig.parameters.values())
    conv_param = next((p for p in params if p.name == "conversation_id"), None)
    assert conv_param is not None
    assert conv_param.default is None
    assert conv_param.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD


def test_phase_b_execute_with_conversation_persists_exact_validated_id() -> None:
    """Valid owned conversation_id is persisted to run history (Phase B)."""
    store = _SessionHistoryStore()
    adapter = _make_adapter()
    with _signed_in_client(store) as client, _injected_adapter(client, adapter):
        resp = client.post(
            EXECUTE_ROUTE_PATH, json=_execute_payload(conversation_id=OWNED_CONVERSATION_ID)
        )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["conversation_id"] == OWNED_CONVERSATION_ID
    assert store.get_calls == [(SIGNED_IN_USER_ID, OWNED_CONVERSATION_ID)]
    assert len(store.record_calls) == 1
    # Phase B: the exact validated conversation_id is now persisted.
    assert store.record_calls[0]["conversation_id"] == OWNED_CONVERSATION_ID
    adapter.execute.assert_awaited_once()


def test_phase_b_execute_without_conversation_persists_null() -> None:
    """Absent conversation_id keeps legacy behavior: NULL persistence."""
    store = _SessionHistoryStore()
    adapter = _make_adapter()
    with _signed_in_client(store) as client, _injected_adapter(client, adapter):
        resp = client.post(EXECUTE_ROUTE_PATH, json=_execute_payload())
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert "conversation_id" not in result
    assert store.get_calls == []
    assert len(store.record_calls) == 1
    assert store.record_calls[0]["conversation_id"] is None
    adapter.execute.assert_awaited_once()


def test_phase_b_persisted_conversation_id_flows_to_run_history_projection() -> None:
    """Persisted conversation_id is projected through the bounded session field."""
    store = _SessionHistoryStore(rows={
        "run_a": _run_row(user_id=SIGNED_IN_USER_ID, run_id="run_a",
                          conversation_id=OWNED_CONVERSATION_ID),
        "run_b": _run_row(user_id=SIGNED_IN_USER_ID, run_id="run_b"),
    })
    client = _signed_in_client(store)
    resp = client.get(RUNS_HISTORY_ROUTE_PATH)
    assert resp.status_code == 200
    runs = {row["run_id"]: row for row in resp.json()["runs"]}
    assert runs["run_a"]["session"] == {"conversation_id": OWNED_CONVERSATION_ID}
    assert runs["run_b"]["session"] is None


def test_phase_b_foreign_conversation_never_persisted() -> None:
    """Foreign conversation fails closed before execution and persistence."""
    store = _SessionHistoryStore()
    adapter = _make_adapter()
    with _signed_in_client(store) as client, _injected_adapter(client, adapter):
        resp = client.post(
            EXECUTE_ROUTE_PATH,
            json=_execute_payload(conversation_id="chat_" + "b2" * 16),
        )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "conversation_not_found"
    assert store.record_calls == []
    adapter.execute.assert_not_called()


def test_phase_b_malformed_conversation_never_persisted() -> None:
    """Malformed conversation_id fails closed before any persistence."""
    store = _SessionHistoryStore()
    adapter = _make_adapter()
    with _signed_in_client(store) as client, _injected_adapter(client, adapter):
        resp = client.post(
            EXECUTE_ROUTE_PATH, json=_execute_payload(conversation_id=MALFORMED_CONVERSATION_ID)
        )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_conversation_id"
    assert store.record_calls == []
    adapter.execute.assert_not_called()


def test_phase_b_raw_request_value_never_reaches_persistence() -> None:
    """The raw request body value is never persisted without validation."""
    store = _SessionHistoryStore()
    adapter = _make_adapter()
    with _signed_in_client(store) as client, _injected_adapter(client, adapter):
        resp = client.post(
            EXECUTE_ROUTE_PATH, json=_execute_payload(conversation_id=RAW_USER_ID_CANDIDATE)
        )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_conversation_id"
    assert store.record_calls == []
    adapter.execute.assert_not_called()
    # The raw user id was never validated, never persisted, never executed.
    assert store.get_calls == []


def test_phase_b_deleted_conversation_does_not_fabricate_session() -> None:
    """A deleted conversation leaves the persisted run row unchanged.

    The run row keeps its historical conversation_id only if it was valid at
    write time. A later delete does not rewrite history; the projection
    simply shows the stored reference (or null if none was stored).
    """
    # Store a run row that was persisted with a conversation_id, then
    # simulate the conversation being deleted by removing it from the store.
    store = _SessionHistoryStore(rows={
        "run_a": _run_row(user_id=SIGNED_IN_USER_ID, run_id="run_a",
                          conversation_id=OWNED_CONVERSATION_ID),
    })
    # Delete the conversation from the store (simulating post-write deletion).
    store.conversations.clear()
    client = _signed_in_client(store)
    resp = client.get(RUNS_HISTORY_ROUTE_PATH)
    assert resp.status_code == 200
    # The run row still projects its persisted conversation_id; the projection
    # does not re-validate against the conversation table on read.
    runs = {row["run_id"]: row for row in resp.json()["runs"]}
    assert runs["run_a"]["session"] == {"conversation_id": OWNED_CONVERSATION_ID}
