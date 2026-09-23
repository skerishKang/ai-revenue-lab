"""#2956 owner-scoped approval handoff context (SOURCE_ONLY).

NETWORK_FREE: no live D1, no provider call, no Engine resume/cancel, no
approval decision. Covers the durable handoff written only after canonical
WAITING_APPROVAL + Engine pause wire + continuation_ref.

Contract:
  * store: exact replay idempotent, conflicting identity fail closed,
    cross-owner / cross-workspace non-disclosing, expired unusable,
    reconstructable trusted request, closed shape rejects browser authority.
  * route: WAITING writes exactly one handoff; completed/failed write zero;
    browser cannot override server-derived owner/workspace/session/trace/
    model/tool authority; store failure fails closed; presence-only store is
    a no-op.
  * adapter: WAITING outcome carries pause identity + trusted snapshot;
    completed outcome does not; missing Engine pause identity fails closed.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.history import (
    D1HistoryStore,
    HistoryConflict,
    HistoryError,
    _handoff_trusted_request_json,
)
from app.control_plane_identity import PADIEM_CHAT_PRODUCT_ID
from app.control_plane_identity_shadow import IdentityShadowRecord
from padiem_control_plane import (
    AuthSessionSnapshot,
    AuthSessionState,
    CanonicalSubjectRef,
    SubjectType,
)
from datetime import datetime, timedelta, timezone

EXECUTE_ROUTE_PATH = "/api/claw/manual-intake/execute"
SIGNED_IN_USER_ID = "usr_" + "7" * 32
FUTURE_EXPIRES = "2099-01-01T00:00:00+00:00"
PAST_EXPIRES = "2020-01-01T00:00:00+00:00"
WORKSPACE_A = "ws-alpha"
WORKSPACE_B = "ws-beta"
ENGINE_REF = "cont_EngineOpaqueRef_01"
PAUSE_ID = "pause_fake001"


def _trusted(**overrides: Any) -> dict[str, Any]:
    payload = {
        "app_id": "b54-padiem-claw",
        "agent": {"id": "b54-padiem-claw", "model_policy": {"model": "agnes-ai/agnes-3.0-flash"}},
        "messages": [{"role": "user", "content": "테스트 견적 요청."}],
        "session_id": "run_test123",
        "additional_system_context": None,
        "trace_id": "claw_trace_test",
        "execution_context": {
            "trace_id": "claw_trace_test",
            "idempotency_key": None,
            "timeout_seconds": 20.0,
        },
    }
    payload.update(overrides)
    return payload


class _FakeStatement:
    def __init__(self, db: "_FakeD1", sql: str) -> None:
        self._db = db
        self._sql = " ".join(sql.split())
        self._values: tuple[Any, ...] = ()

    def bind(self, *values: Any) -> "_FakeStatement":
        self._values = values
        return self

    def _where_predicates(self) -> list[tuple[str, str]]:
        """Parse ``col=?``, ``col IS NULL`` and ``col IS NOT NULL`` predicates.

        #2961 added NULL-guarded reads and a consumed-row update, so the fake
        must interpret them with the same semantics D1 has; a predicate the fake
        could not evaluate would let a scope filter pass vacuously.
        """
        where = self._sql.split(" WHERE ", 1)[1]
        where = where.split(" ORDER BY ", 1)[0]
        predicates: list[tuple[str, str]] = []
        for clause in where.split(" AND "):
            clause = clause.strip()
            if clause.endswith("IS NOT NULL"):
                predicates.append((clause[: -len("IS NOT NULL")].strip(), "not_null"))
            elif clause.endswith("IS NULL"):
                predicates.append((clause[: -len("IS NULL")].strip(), "null"))
            else:
                predicates.append((clause[: clause.index("=")].strip(), "eq"))
        return predicates

    def _matches(self, row: dict[str, Any]) -> bool:
        values = iter(self._values)
        for name, kind in self._where_predicates():
            if kind == "null":
                if row.get(name) is not None:
                    return False
            elif kind == "not_null":
                if row.get(name) is None:
                    return False
            else:
                if row.get(name) != next(values):
                    return False
        return True

    def _candidates(self) -> Any:
        return (
            self._db.handoff_rows
            if "claw_approval_handoff" in self._sql
            else self._db.rows.values()
        )

    def _apply_handoff_update(self) -> dict[str, Any]:
        assignments = self._sql.split(" SET ", 1)[1].split(" WHERE ", 1)[0]
        row_id = self._values[-1]
        target = next((row for row in self._db.handoff_rows if row.get("id") == row_id), None)
        if target is None:
            return {"success": True, "meta": {"changes": 0}}
        values = iter(self._values[:-1])
        for clause in assignments.split(","):
            column, _, raw = clause.strip().partition("=")
            if raw.strip().upper() == "NULL":
                target[column.strip()] = None
            else:
                target[column.strip()] = next(values)
        return {"success": True, "meta": {"changes": 1}}

    async def run(self) -> dict[str, Any]:
        sql = self._sql
        if sql.startswith("INSERT INTO claw_approval_handoff"):
            cols = [c.strip() for c in sql[sql.index("(") + 1: sql.index(")")].split(",")]
            row = {col: value for col, value in zip(cols, self._values)}
            self._db.handoff_rows.append(row)
            return {"success": True, "meta": {"changes": 1}}
        if sql.startswith("INSERT INTO claw_run_history"):
            cols = [c.strip() for c in sql[sql.index("(") + 1: sql.index(")")].split(",")]
            row = {col: value for col, value in zip(cols, self._values)}
            self._db.rows[row["run_id"]] = row
            return {"success": True, "meta": {"changes": 1}}
        if sql.startswith("UPDATE claw_approval_handoff"):
            return self._apply_handoff_update()
        if sql.startswith("UPDATE claw_run_history"):
            return {"success": True, "meta": {"changes": 1}}
        if sql.startswith("SELECT"):
            if "claw_approval_handoff" in sql:
                candidates = self._db.handoff_rows
            else:
                candidates = list(self._db.rows.values())
            rows = [dict(row) for row in candidates if self._matches(row)]
            return {"success": True, "results": rows}
        raise AssertionError(f"unexpected SQL for run(): {sql!r}")

    async def first(self) -> dict[str, Any] | None:
        for row in self._candidates():
            if self._matches(row):
                return dict(row)
        return None


class _FakeD1:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.handoff_rows: list[dict[str, Any]] = []

    def prepare(self, sql: str) -> _FakeStatement:
        return _FakeStatement(self, sql)


def _store() -> D1HistoryStore:
    return D1HistoryStore(_FakeD1())


async def _record(
    store: D1HistoryStore,
    *,
    user_id: str = SIGNED_IN_USER_ID,
    run_id: str = "run_handoff_1",
    continuation_ref: str = ENGINE_REF,
    pause_id: str = PAUSE_ID,
    pause_expires_at: str = FUTURE_EXPIRES,
    trusted: dict[str, Any] | None = None,
    workspace_id: str | None = WORKSPACE_A,
    conversation_id: str | None = None,
) -> None:
    await store.record_claw_approval_handoff(
        user_id,
        run_id,
        continuation_ref,
        pause_id,
        pause_expires_at,
        trusted if trusted is not None else _trusted(),
        workspace_id=workspace_id,
        conversation_id=conversation_id,
    )


# ── store: #2956 durable handoff authority ────────────────────────────────────


async def test_record_then_exact_replay_is_idempotent() -> None:
    store = _store()
    await _record(store)
    await _record(store)
    assert len(store.db.handoff_rows) == 1


async def test_conflicting_continuation_ref_fails_closed() -> None:
    store = _store()
    await _record(store)
    with pytest.raises(HistoryConflict):
        await _record(store, continuation_ref="cont_EngineOpaqueRef_02")


async def test_conflicting_pause_id_fails_closed() -> None:
    store = _store()
    await _record(store)
    with pytest.raises(HistoryConflict):
        await _record(store, pause_id="pause_other")


async def test_conflicting_trusted_request_fails_closed() -> None:
    store = _store()
    await _record(store)
    with pytest.raises(HistoryConflict):
        await _record(store, trusted=_trusted(messages=[{"role": "user", "content": "changed"}]))


async def test_cross_owner_load_is_non_disclosing() -> None:
    store = _store()
    await _record(store, user_id=SIGNED_IN_USER_ID)
    assert (
        await store.load_claw_approval_handoff("usr_" + "f" * 32, "run_handoff_1")
        is None
    )
    assert await store.load_claw_approval_handoff(SIGNED_IN_USER_ID, "run_missing") is None


async def test_cross_workspace_load_is_non_disclosing() -> None:
    store = _store()
    await _record(store, workspace_id=WORKSPACE_A)
    assert await store.load_claw_approval_handoff(
        SIGNED_IN_USER_ID, "run_handoff_1", workspace_id=WORKSPACE_B
    ) is None
    allowed = await store.load_claw_approval_handoff(
        SIGNED_IN_USER_ID, "run_handoff_1", workspace_id=WORKSPACE_A
    )
    assert allowed is not None
    assert allowed["workspace_id"] == WORKSPACE_A


async def test_expired_handoff_is_unusable() -> None:
    store = _store()
    await _record(store, pause_expires_at=PAST_EXPIRES)
    assert await store.load_claw_approval_handoff(SIGNED_IN_USER_ID, "run_handoff_1") is None


async def test_naive_pause_expiry_is_rejected_fail_closed() -> None:
    store = _store()
    with pytest.raises(HistoryError):
        await _record(store, pause_expires_at="2099-01-01T00:00:00")
    assert store.db.handoff_rows == []


async def test_tampered_trusted_request_fingerprint_is_non_disclosing() -> None:
    store = _store()
    await _record(store)
    assert len(store.db.handoff_rows) == 1
    store.db.handoff_rows[0]["trusted_request_json"] = json.dumps(
        _trusted(messages=[{"role": "user", "content": "tampered"}]),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    assert await store.load_claw_approval_handoff(
        SIGNED_IN_USER_ID, "run_handoff_1", workspace_id=WORKSPACE_A
    ) is None


async def test_trusted_request_is_reconstructable_without_browser_authority() -> None:
    store = _store()
    trusted = _trusted()
    await _record(store, trusted=trusted)
    loaded = await store.load_claw_approval_handoff(
        SIGNED_IN_USER_ID, "run_handoff_1", workspace_id=WORKSPACE_A
    )
    assert loaded is not None
    assert loaded["continuation_ref"] == ENGINE_REF
    assert loaded["pause_id"] == PAUSE_ID
    assert loaded["pause_expires_at"] == FUTURE_EXPIRES
    assert loaded["trusted_request"] == trusted
    assert loaded["trusted_request"]["app_id"] == "b54-padiem-claw"
    assert loaded["trusted_request"]["session_id"] == "run_test123"
    assert loaded["trusted_request"]["trace_id"] == "claw_trace_test"
    assert loaded["trusted_request"]["messages"][0]["content"] == "테스트 견적 요청."


async def test_real_p01_frozen_agent_snapshot_is_deeply_json_safe_and_durable() -> None:
    from collections.abc import Mapping
    from types import MappingProxyType

    from kagent.contracts import ClawTaskIntent, ExecutionMode
    from kagent.p01_adapter import P01RequestFactory, _trusted_p01_request_snapshot
    from kagent.runs import ClawRun

    run_id = "run_real_p01_handoff_json"
    run = ClawRun.create(
        run_id,
        ClawTaskIntent(
            task_id="task_real_p01_handoff_json",
            task="실제 frozen AgentProfile 승인 handoff 직렬화를 검증해줘",
            repository_ref="skerishKang/ai-revenue-lab",
            execution_mode=ExecutionMode.LOCAL,
        ),
    )
    bundle = P01RequestFactory().build(run)

    # Prove the fixture is the real frozen Core identity that triggered #2973.
    self_agent = bundle.execution_request.agent
    assert isinstance(self_agent.model_policy, MappingProxyType)
    assert isinstance(self_agent.context_policy, MappingProxyType)
    assert isinstance(self_agent.output_contract, MappingProxyType)

    trusted = _trusted_p01_request_snapshot(bundle)
    assert isinstance(trusted, dict)
    assert set(trusted) == {
        "app_id",
        "agent",
        "messages",
        "session_id",
        "additional_system_context",
        "trace_id",
        "execution_context",
    }
    assert isinstance(trusted["agent"], dict)
    assert not isinstance(trusted["agent"]["model_policy"], MappingProxyType)

    def assert_json_containers(value: object) -> None:
        assert not isinstance(value, MappingProxyType)
        if isinstance(value, Mapping):
            for key, item in value.items():
                assert isinstance(key, str)
                assert_json_containers(item)
        elif isinstance(value, list):
            for item in value:
                assert_json_containers(item)
        else:
            assert value is None or isinstance(value, (str, bool, int, float))

    assert_json_containers(trusted)

    encoded_1, fingerprint_1 = _handoff_trusted_request_json(trusted)
    encoded_2, fingerprint_2 = _handoff_trusted_request_json(trusted)
    assert encoded_1 == encoded_2
    assert fingerprint_1 == fingerprint_2

    store = _store()
    await store.record_claw_approval_handoff(
        SIGNED_IN_USER_ID,
        run_id,
        ENGINE_REF,
        PAUSE_ID,
        FUTURE_EXPIRES,
        trusted,
        workspace_id=WORKSPACE_A,
    )
    loaded = await store.load_claw_approval_handoff(
        SIGNED_IN_USER_ID,
        run_id,
        workspace_id=WORKSPACE_A,
    )
    assert loaded is not None
    assert loaded["trusted_request"] == trusted
    _encoded_loaded, fingerprint_loaded = _handoff_trusted_request_json(
        loaded["trusted_request"]
    )
    assert fingerprint_loaded == fingerprint_1


async def test_browser_authority_keys_rejected_at_store_boundary() -> None:
    store = _store()
    with pytest.raises(HistoryError):
        await _record(store, trusted=_trusted(workspace_id=WORKSPACE_B))
    with pytest.raises(HistoryError):
        await _record(store, trusted=_trusted(user_id="usr_attacker"))
    with pytest.raises(HistoryError):
        await _record(store, trusted=_trusted(tool_arguments={"cmd": "rm"}))
    assert store.db.handoff_rows == []


async def test_credential_like_keys_rejected() -> None:
    store = _store()
    with pytest.raises(HistoryError):
        await _record(store, trusted=_trusted(access_token="sk-live-secret"))
    with pytest.raises(HistoryError):
        await _record(store, trusted=_trusted(provider_credential={"key": "x"}))
    assert store.db.handoff_rows == []


def test_migration_is_additive_handoff_table() -> None:
    migrations_dir = Path(__file__).resolve().parents[1] / "migrations"
    content = (migrations_dir / "016_claw_approval_handoff.sql").read_text(encoding="utf-8")
    lowered = content.lower()
    assert "create table if not exists claw_approval_handoff" in lowered
    assert "unique (user_id, run_id)" in lowered
    assert "continuation_ref" in lowered
    assert "pause_id" in lowered
    assert "trusted_request_json" in lowered
    assert "drop table" not in lowered
    assert "delete from" not in lowered
    assert "foreign key" not in lowered


# ── route: WAITING writes one handoff; terminal writes zero ───────────────────


def _google_settings(**overrides: Any) -> Settings:
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


def _identity_store() -> MagicMock:
    now = datetime.now(timezone.utc)
    record = IdentityShadowRecord(
        product_user_id=SIGNED_IN_USER_ID,
        canonical_subject_id="subject_test",
        auth_session_id="session_test123",
        session_revision=1,
        session_state="active",
        session_expires_at=now + timedelta(hours=1),
        observed_at=now,
    )
    store = MagicMock()
    store.load_projection = AsyncMock(return_value=record)
    return store


def _authority() -> MagicMock:
    now = datetime.now(timezone.utc)
    snapshot = AuthSessionSnapshot(
        session_id="session_test123",
        product_id=PADIEM_CHAT_PRODUCT_ID,
        subject=CanonicalSubjectRef(SubjectType.USER, "subject_test"),
        issued_at=now - timedelta(hours=1),
        expires_at=now + timedelta(hours=1),
        state=AuthSessionState.ACTIVE,
        revision=1,
        tenant_id="tenant_test",
    )
    authority = MagicMock()
    authority.resolve_auth_session = AsyncMock(return_value=snapshot)
    return authority


class _RecordingHandoffStore:
    def __init__(self) -> None:
        self.history_rows: dict[str, dict] = {}
        self.handoffs: list[dict] = []

    async def get_user(self, user_id: str):
        return None

    async def record_claw_run(self, *, user_id, run_id, channel, action, title, status,
                              result_summary=None, artifact_document_id=None,
                              artifact_filename=None, artifact_media_type=None,
                              conversation_id=None, workspace_id=None) -> None:
        self.history_rows[run_id] = {
            "user_id": user_id, "run_id": run_id, "status": status,
        }

    async def list_recent_claw_runs(self, user_id: str, limit: int) -> list[dict]:
        return [r for r in self.history_rows.values() if r["user_id"] == user_id][:limit]

    async def record_claw_approval_handoff(
        self,
        *,
        user_id,
        run_id,
        continuation_ref,
        pause_id,
        pause_expires_at,
        trusted_request,
        workspace_id=None,
        conversation_id=None,
        p01_run_id=None,
    ) -> None:
        self.handoffs.append({
            "user_id": user_id,
            "run_id": run_id,
            "continuation_ref": continuation_ref,
            "pause_id": pause_id,
            "pause_expires_at": pause_expires_at,
            "trusted_request": dict(trusted_request),
            "workspace_id": workspace_id,
            "conversation_id": conversation_id,
            "p01_run_id": p01_run_id,
        })


def _handoff_client(store: object) -> TestClient:
    settings = _google_settings()
    app = create_app(
        settings=settings,
        history_store=store,
        d1_binding=MagicMock(),
        r2_binding=MagicMock(),
    )
    app.state.identity_shadow_store = _identity_store()
    app.state.control_plane_identity_authority = _authority()
    app.state.workspace_document_store = MagicMock()
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE,
        create_session_token(_google_settings(), SIGNED_IN_USER_ID),
        domain="chat.example.test",
        path="/",
    )
    return client


def _make_outcome(answer: str | None = "test result", status_value: str = "completed") -> MagicMock:
    status_mock = MagicMock()
    status_mock.value = status_value
    projection = MagicMock()
    projection.status = status_mock
    projection.run_id = "run_test123"
    outcome = MagicMock()
    outcome.projection = projection
    outcome.answer = answer
    outcome.p01_run_id = "p01_run_test123"
    outcome.p01_event_count = 2
    outcome.continuation_ref = None
    outcome.pause_id = None
    outcome.pause_expires_at = None
    outcome.trusted_request = None
    return outcome


def _waiting_outcome() -> MagicMock:
    outcome = _make_outcome(answer=None, status_value="waiting_approval")
    outcome.continuation_ref = ENGINE_REF
    outcome.pause_id = PAUSE_ID
    outcome.pause_expires_at = FUTURE_EXPIRES
    outcome.trusted_request = _trusted()
    return outcome


@contextmanager
def _injected_adapter(client: TestClient, adapter: object):
    previous = client.app.state.claw_p01_adapter
    client.app.state.claw_p01_adapter = adapter
    try:
        yield adapter
    finally:
        client.app.state.claw_p01_adapter = previous


def _adapter(outcome: MagicMock) -> MagicMock:
    adapter = MagicMock()
    adapter.execute = AsyncMock(return_value=outcome)
    return adapter


def _post_waiting(client: TestClient, **body_extra: Any):
    payload = {"content": "테스트.", "channel": "kakao", "action": "reply"}
    payload.update(body_extra)
    with _injected_adapter(client, _adapter(_waiting_outcome())):
        return client.post(EXECUTE_ROUTE_PATH, json=payload)


def test_waiting_approval_writes_exactly_one_owner_scoped_handoff() -> None:
    store = _RecordingHandoffStore()
    client = _handoff_client(store)
    resp = _post_waiting(client)
    assert resp.status_code == 200
    assert resp.json()["result"]["status"] == "waiting_approval"
    assert len(store.history_rows) == 1
    assert len(store.handoffs) == 1
    handoff = store.handoffs[0]
    assert handoff["user_id"] == SIGNED_IN_USER_ID
    assert handoff["run_id"] == next(iter(store.history_rows))
    assert handoff["continuation_ref"] == ENGINE_REF
    assert handoff["pause_id"] == PAUSE_ID
    assert handoff["pause_expires_at"] == FUTURE_EXPIRES
    assert handoff["workspace_id"] == "tenant_test"
    assert handoff["trusted_request"]["app_id"] == "b54-padiem-claw"
    # Browser response never echoes server-only handoff fields.
    result = resp.json()["result"]
    assert "pause_id" not in result
    assert "trusted_request" not in result
    assert "workspace_id" not in result
    assert "session_id" not in result
    assert "trace_id" not in result


def test_completed_run_writes_zero_handoffs() -> None:
    store = _RecordingHandoffStore()
    client = _handoff_client(store)
    completed = _make_outcome(answer="완료", status_value="completed")
    with _injected_adapter(client, _adapter(completed)):
        resp = client.post(
            EXECUTE_ROUTE_PATH,
            json={"content": "테스트.", "channel": "kakao", "action": "reply"},
        )
    assert resp.status_code == 200
    assert len(store.history_rows) == 1
    assert store.handoffs == []


def test_failed_run_writes_zero_handoffs() -> None:
    store = _RecordingHandoffStore()
    client = _handoff_client(store)
    failed = _make_outcome(answer=None, status_value="failed")
    with _injected_adapter(client, _adapter(failed)):
        resp = client.post(
            EXECUTE_ROUTE_PATH,
            json={"content": "테스트.", "channel": "kakao", "action": "reply"},
        )
    assert resp.status_code == 502
    assert store.handoffs == []


def test_browser_cannot_override_server_derived_handoff_authority() -> None:
    store = _RecordingHandoffStore()
    client = _handoff_client(store)
    resp = _post_waiting(
        client,
        user_id="usr_attacker",
        workspace_id=WORKSPACE_B,
        tenant_id="tenant_attacker",
        session_id="run_attacker",
        trace_id="trace_attacker",
        app_id="attacker-app",
        agent_id="attacker-agent",
        model="evil/model",
        tool_arguments={"cmd": "rm"},
        continuation_ref="cont_AttackerRef_01",
        pause_id="pause_attacker",
    )
    assert resp.status_code == 200
    assert len(store.handoffs) == 1
    handoff = store.handoffs[0]
    assert handoff["user_id"] == SIGNED_IN_USER_ID
    assert handoff["workspace_id"] == "tenant_test"
    assert handoff["continuation_ref"] == ENGINE_REF
    assert handoff["pause_id"] == PAUSE_ID
    assert handoff["trusted_request"]["session_id"] == "run_test123"
    assert handoff["trusted_request"]["trace_id"] == "claw_trace_test"
    assert handoff["trusted_request"]["app_id"] == "b54-padiem-claw"
    assert "model" not in handoff["trusted_request"].get("execution_context", {})
    assert "tool_arguments" not in handoff["trusted_request"]
    assert "workspace_id" not in handoff["trusted_request"]
    assert "user_id" not in handoff["trusted_request"]


def test_handoff_store_failure_fails_closed() -> None:
    class _Failing(_RecordingHandoffStore):
        async def record_claw_approval_handoff(self, **kwargs):
            raise RuntimeError("d1 handoff write down")

    store = _Failing()
    client = _handoff_client(store)
    resp = _post_waiting(client)
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "approval_handoff_write_failed"
    assert store.handoffs == []


def test_presence_only_store_skips_handoff_without_broken_execute() -> None:
    class _PresenceOnly:
        async def get_user(self, user_id: str):
            return None

        async def record_claw_run(self, **kwargs) -> None:
            return None

    store = _PresenceOnly()
    client = _handoff_client(store)
    resp = _post_waiting(client)
    assert resp.status_code == 200


def test_waiting_without_pause_identity_fails_closed_before_write() -> None:
    store = _RecordingHandoffStore()
    client = _handoff_client(store)
    outcome = _waiting_outcome()
    outcome.pause_id = None
    with _injected_adapter(client, _adapter(outcome)):
        resp = client.post(
            EXECUTE_ROUTE_PATH,
            json={"content": "테스트.", "channel": "kakao", "action": "reply"},
        )
    assert resp.status_code == 502
    assert resp.json()["error"]["detail"] == "p01_contract_failure"
    assert store.handoffs == []


def test_handoff_only_after_history_success() -> None:
    class _HistoryFails(_RecordingHandoffStore):
        async def record_claw_run(self, **kwargs):
            raise RuntimeError("history down")

    store = _HistoryFails()
    client = _handoff_client(store)
    resp = _post_waiting(client)
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "run_history_write_failed"
    assert store.handoffs == []