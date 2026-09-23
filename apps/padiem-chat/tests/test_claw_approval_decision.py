"""#2961 owner approve/deny decision surface on the B54 Claw route (SOURCE_ONLY).

NETWORK_FREE: one fake Engine transport stands in for the Service Binding. No
Production Engine, no provider call, no workflow dispatch, no live pause
producer, no UI change.

The route is exercised end to end through the real lane:
  browser {run_id, decision} → server-derived owner/workspace → #2956 handoff
  load → trusted P01 reconstruction → bounded first-party submission → existing
  canonical Engine resume transport → existing Core public parser → existing
  ClawResumeProjector.

Contract proven here: caller authority is exactly two fields; every other
deviation fails closed before any Engine transport is touched; a foreign or
unusable handoff is one bounded non-disclosing result; consumption happens only
after the Engine proves it; and a failure keeps the handoff retry-safe.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.control_plane_identity import PADIEM_CHAT_PRODUCT_ID
from app.control_plane_identity_shadow import IdentityShadowRecord
from kagent.p01_approval_continuation import (
    P01EngineApprovalContinuationClient,
    reconstruct_trusted_resume_request,
)
from padiem_ai_core import ApprovalPause, ApprovalRequirement, ExecutionContext, OrchestrationResult
from padiem_ai_core.b14_execution import B14RouteMetadata
from padiem_ai_core.contracts import RunMetadata, RunStatus
from padiem_ai_core.execution_runtime import ExecutionResult
from padiem_ai_core.orchestration_events import (
    OrchestrationEventKind,
    public_orchestration_event,
)
from padiem_ai_engine_client import PadiemAiEngineClientError
from padiem_control_plane import (
    AuthSessionSnapshot,
    AuthSessionState,
    CanonicalSubjectRef,
    SubjectType,
)

DECISION_PATH = "/api/claw/approvals/decision"
EXECUTE_PATH = "/api/claw/manual-intake/execute"
OWNER = "usr_" + "7" * 32
FOREIGN_OWNER = "usr_" + "f" * 32
WORKSPACE = "tenant_test"
RUN_ID = "run_test123"
P01_RUN_ID = "orch_resume_test123"
TRACE_ID = "claw_trace_test"
CONTINUATION_REF = "cont_EngineOpaqueRef_01"
NEXT_CONTINUATION_REF = "cont_EngineOpaqueRef_02"
PAUSE_ID = "pause_fake001"
NEXT_PAUSE_ID = "pause_fake002"
NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
FUTURE_EXPIRES_AT = datetime(2099, 1, 1, tzinfo=timezone.utc)
FUTURE_EXPIRES = FUTURE_EXPIRES_AT.isoformat()
AGENT_ID = "b54-padiem-claw"
APP_ID = "b54-padiem-claw"
MODEL_ID = "agnes-ai/agnes-3.0-flash"

# Every field a caller might try to promote into authority. §3/§8 forbid each one.
BROWSER_AUTHORITY_FIELDS = (
    "continuation_ref",
    "pause_id",
    "app_id",
    "agent_id",
    "session_id",
    "trace_id",
    "workspace_id",
    "tenant_id",
    "subject_id",
    "authority_ref",
    "evidence_ref",
    "decision_id",
    "decided_at",
    "model",
    "tool_id",
    "tool_arguments",
    "approval_scope",
    "trusted_request",
    "user_id",
)


def trusted_request(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "app_id": APP_ID,
        "agent": {
            "id": AGENT_ID,
            "title": "Padiem Claw",
            "description": "B54 repository task execution consumer",
            "system_instruction": None,
            "task_type": "coding",
            "optimize_for": "balanced",
            "max_tokens": None,
            "allowed_tools": [],
            "required_capabilities": [],
            "context_policy": {},
            "model_policy": {"model": MODEL_ID},
            "max_steps": 1,
            "output_contract": {},
        },
        "messages": [{"role": "user", "content": "테스트 견적 요청."}],
        "session_id": RUN_ID,
        "additional_system_context": None,
        "trace_id": TRACE_ID,
        "execution_context": {
            "trace_id": TRACE_ID,
            "idempotency_key": None,
            "timeout_seconds": 20.0,
        },
    }
    payload.update(overrides)
    return payload


class _HandoffStore:
    """Owner+workspace scoped handoff rows with the real consumption semantics."""

    def __init__(self, *, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = list(rows or [])
        self.recorded: list[dict[str, Any]] = []
        self.status_updates: list[dict[str, Any]] = []
        self.history_rows: dict[str, dict[str, Any]] = {}

    async def get_user(self, user_id: str):
        return None

    async def record_claw_run(self, **kwargs: Any) -> None:
        self.history_rows[kwargs["run_id"]] = dict(kwargs)

    async def list_recent_claw_runs(self, user_id: str, limit: int = 20) -> list[dict]:
        return []

    async def record_claw_approval_handoff(self, **kwargs: Any) -> None:
        self.recorded.append(dict(kwargs))
        self.rows = [
            row
            for row in self.rows
            if not (row["user_id"] == kwargs["user_id"] and row["run_id"] == kwargs["run_id"])
        ]
        self.rows.append(
            {
                **kwargs,
                "trusted_request": dict(kwargs["trusted_request"]),
                "consumed_at": None,
            }
        )

    async def load_claw_approval_handoff(
        self, *, user_id: str, run_id: str, workspace_id: str | None = None
    ) -> dict[str, Any] | None:
        for row in self.rows:
            if row["user_id"] != user_id or row["run_id"] != run_id:
                continue
            if row.get("consumed_at") is not None:
                continue
            if workspace_id is not None and row.get("workspace_id") != workspace_id:
                continue
            if str(row["pause_expires_at"]) <= _now_stamp():
                continue
            return {key: value for key, value in row.items() if key != "consumed_at"}
        return None

    async def consume_claw_approval_handoff(
        self, *, user_id: str, run_id: str, workspace_id: str | None = None
    ) -> bool:
        for row in self.rows:
            if (
                row["user_id"] == user_id
                and row["run_id"] == run_id
                and row.get("consumed_at") is None
                and (workspace_id is None or row.get("workspace_id") == workspace_id)
            ):
                row["consumed_at"] = _now_stamp()
                return True
        return False

    async def update_claw_run_status(
        self, *, user_id: str, run_id: str, status: str, result_summary: str | None = None
    ) -> bool:
        if run_id not in self.history_rows:
            return False
        self.status_updates.append(
            {"user_id": user_id, "run_id": run_id, "status": status, "result_summary": result_summary}
        )
        return True


def _now_stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _handoff_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "user_id": OWNER,
        "run_id": RUN_ID,
        "workspace_id": WORKSPACE,
        "conversation_id": None,
        "continuation_ref": CONTINUATION_REF,
        "pause_id": PAUSE_ID,
        "pause_expires_at": FUTURE_EXPIRES,
        "trusted_request": trusted_request(),
        "p01_run_id": P01_RUN_ID,
        "consumed_at": None,
    }
    row.update(overrides)
    return row


class _FakeEngineTransport:
    """Records the canonical resume payloads and replays a prepared response."""

    app_id = APP_ID

    def __init__(
        self,
        *,
        events: list[OrchestrationEventKind] | None = None,
        next_pause: ApprovalPause | None = None,
        continuation_ref: str | None = None,
        answer: str | None = "재개 완료",
        error: Exception | None = None,
    ) -> None:
        self.payloads: list[dict[str, Any]] = []
        self._events = events
        self._next_pause = next_pause
        self._continuation_ref = continuation_ref
        self._answer = answer
        self._error = error

    async def resume_orchestration(self, request: Any) -> dict[str, Any]:
        self.payloads.append(dict(request))
        if self._error is not None:
            raise self._error
        assert self._events is not None
        status = RunStatus.PAUSED if self._next_pause is not None else RunStatus.COMPLETED
        result = OrchestrationResult(
            execution_result=ExecutionResult(
                answer=self._answer,
                route=B14RouteMetadata(),
                metadata=RunMetadata(
                    trace_id=TRACE_ID,
                    app_id=APP_ID,
                    agent_id=AGENT_ID,
                    session_id=RUN_ID,
                    status=status,
                ),
            ),
            context=ExecutionContext(trace_id=TRACE_ID, timeout_seconds=20.0),
            app_id=APP_ID,
            subject_id=None,
            plan=None,
            activated_skill=None,
            resolved_tool_ids=(),
            evidence_graph=None,
            claim_assessments=(),
            grounded_citations=(),
            events=tuple(
                public_orchestration_event(
                    event_id=f"evt_{index}",
                    run_id=P01_RUN_ID,
                    trace_id=TRACE_ID,
                    app_id=APP_ID,
                    kind=kind,
                    sequence=index,
                    message=None,
                    timestamp_iso="2026-09-23T12:10:00+00:00",
                )
                for index, kind in enumerate(self._events, start=1)
            ),
            approval_pause=self._next_pause,
        )
        payload = result.to_public_dict()
        if self._continuation_ref is not None:
            payload["continuation_ref"] = self._continuation_ref
        return payload


def _pause(pause_id: str) -> ApprovalPause:
    return ApprovalPause(
        pause_id=pause_id,
        run_id=P01_RUN_ID,
        agent_runtime_id=AGENT_ID,
        tool_id="tool_write_file",
        invocation_sha256="a" * 64,
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1,
        created_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        trace_id=TRACE_ID,
        plan_id="plan_test123",
        approval_scope=("workspace_write",),
    )


RESUMED_TO_COMPLETED = [
    OrchestrationEventKind.RUN_STARTED,
    OrchestrationEventKind.RUN_RESUMED,
    OrchestrationEventKind.RUN_COMPLETED,
]
RESUMED_TO_PAUSE_AGAIN = [
    OrchestrationEventKind.RUN_STARTED,
    OrchestrationEventKind.RUN_RESUMED,
    OrchestrationEventKind.APPROVAL_PAUSED,
]


def _client(
    store: _HandoffStore,
    transport: _FakeEngineTransport | None = None,
    *,
    signed_in: bool = True,
) -> TestClient:
    settings = _google_settings()
    app = create_app(
        settings=settings,
        history_store=store,
        d1_binding=MagicMock(),
        r2_binding=MagicMock(),
        claw_p01_continuation_client=(
            P01EngineApprovalContinuationClient(transport) if transport is not None else None
        ),
    )
    app.state.identity_shadow_store = _identity_store()
    app.state.control_plane_identity_authority = _authority()
    app.state.workspace_document_store = MagicMock()
    client = TestClient(app, base_url="https://chat.example.test")
    if signed_in:
        client.cookies.set(
            SESSION_COOKIE, create_session_token(settings, OWNER), domain="chat.example.test", path="/"
        )
    return client


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
    record = IdentityShadowRecord(
        product_user_id=OWNER,
        canonical_subject_id="subject_test",
        auth_session_id="session_test123",
        session_revision=1,
        session_state="active",
        session_expires_at=FUTURE_EXPIRES_AT,
        observed_at=NOW,
    )
    store = MagicMock()
    store.load_projection = AsyncMock(return_value=record)
    return store


def _authority() -> MagicMock:
    snapshot = AuthSessionSnapshot(
        session_id="session_test123",
        product_id=PADIEM_CHAT_PRODUCT_ID,
        subject=CanonicalSubjectRef(SubjectType.USER, "subject_test"),
        issued_at=NOW - timedelta(hours=1),
        expires_at=FUTURE_EXPIRES_AT,
        state=AuthSessionState.ACTIVE,
        revision=1,
        tenant_id=WORKSPACE,
    )
    authority = MagicMock()
    authority.resolve_auth_session = AsyncMock(return_value=snapshot)
    return authority


def _post(client: TestClient, payload: dict[str, Any]):
    return client.post(DECISION_PATH, json=payload)


def _store_with(**overrides: Any) -> _HandoffStore:
    row = _handoff_row(**overrides)
    store = _HandoffStore(rows=[row])
    store.history_rows[RUN_ID] = {"run_id": RUN_ID, "user_id": OWNER, "status": "waiting_approval"}
    return store


# ── caller authority is exactly two fields ───────────────────────────────────


def test_unauthenticated_decision_is_rejected_before_any_state_read() -> None:
    store = _store_with()
    client = _client(store, _FakeEngineTransport(events=RESUMED_TO_COMPLETED), signed_in=False)
    response = _post(client, {"run_id": RUN_ID, "decision": "approve"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert store.rows[0]["consumed_at"] is None
    assert store.status_updates == []


def test_decision_outside_approve_deny_is_rejected() -> None:
    store = _store_with()
    transport = _FakeEngineTransport(events=RESUMED_TO_COMPLETED)
    client = _client(store, transport)
    for value in ("maybe", "APPROVE", True, None, "", "skip", 1, ["approve"]):
        response = _post(client, {"run_id": RUN_ID, "decision": value})
        assert response.status_code == 422, value
        assert response.json()["error"]["code"] == "invalid_approval_decision"
    assert transport.payloads == []
    assert store.rows[0]["consumed_at"] is None


@pytest.mark.parametrize("field", BROWSER_AUTHORITY_FIELDS)
def test_browser_cannot_supply_or_override_any_authority_field(field: str) -> None:
    store = _store_with()
    transport = _FakeEngineTransport(events=RESUMED_TO_COMPLETED)
    client = _client(store, transport)
    response = _post(
        client,
        {
            "run_id": RUN_ID,
            "decision": "approve",
            field: "attacker-value" if field != "tool_arguments" else {"cmd": "rm"},
        },
    )
    assert response.status_code == 400, field
    assert response.json()["error"]["code"] == "unexpected_approval_authority_field"
    # Refused outright: nothing is read, called, or written.
    assert transport.payloads == []
    assert store.rows[0]["consumed_at"] is None
    assert store.recorded == []


def test_missing_run_id_and_non_object_body_are_bounded() -> None:
    store = _store_with()
    client = _client(store, _FakeEngineTransport(events=RESUMED_TO_COMPLETED))
    assert _post(client, {"decision": "approve"}).status_code == 400
    assert _post(client, {"run_id": "   ", "decision": "approve"}).status_code == 400
    assert client.post(DECISION_PATH, content="[]").status_code in (400, 415)


# ── owner and workspace are server-derived ───────────────────────────────────


def test_owner_scope_is_server_derived_into_the_submission() -> None:
    store = _store_with()
    transport = _FakeEngineTransport(events=RESUMED_TO_COMPLETED)
    response = _post(_client(store, transport), {"run_id": RUN_ID, "decision": "approve"})
    assert response.status_code == 200
    decision = transport.payloads[0]["decision"]
    assert decision["authority_ref"] == f"b54_session:{OWNER}"
    assert decision["pause_id"] == PAUSE_ID
    assert decision["outcome"] == "approved"
    assert decision["evidence_ref"] == f"b54_decision:{decision['decision_id']}"


def test_workspace_scope_is_server_derived_for_the_handoff_lookup() -> None:
    store = _HandoffStore(rows=[_handoff_row(workspace_id="tenant_other")])
    store.history_rows[RUN_ID] = {"run_id": RUN_ID, "user_id": OWNER}
    transport = _FakeEngineTransport(events=RESUMED_TO_COMPLETED)
    response = _post(_client(store, transport), {"run_id": RUN_ID, "decision": "approve"})
    # The authenticated session resolves to tenant_test, so the row written under
    # another workspace is invisible without disclosing that it exists.
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "approval_not_available"
    assert transport.payloads == []


@pytest.mark.parametrize("foreign", [
    _handoff_row(user_id=FOREIGN_OWNER),
    _handoff_row(workspace_id="tenant_beta"),
])
def test_foreign_owner_and_workspace_are_non_disclosing(foreign: dict[str, Any]) -> None:
    store = _HandoffStore(rows=[foreign])
    transport = _FakeEngineTransport(events=RESUMED_TO_COMPLETED)
    response = _post(_client(store, transport), {"run_id": RUN_ID, "decision": "approve"})
    assert response.status_code == 404
    assert response.json() == {
        "ok": False,
        "error": {
            "code": "approval_not_available",
            "message": "승인 요청을 확인할 수 없습니다.",
        },
    }
    assert transport.payloads == []
    assert store.rows[0]["consumed_at"] is None


# ── fail closed before the Engine is touched ────────────────────────────────


def test_missing_handoff_fails_closed_before_any_engine_call() -> None:
    store = _HandoffStore()
    transport = _FakeEngineTransport(events=RESUMED_TO_COMPLETED)
    response = _post(_client(store, transport), {"run_id": RUN_ID, "decision": "approve"})
    assert response.status_code == 404
    assert transport.payloads == []
    assert store.status_updates == []


def test_expired_handoff_fails_closed_and_is_not_consumed() -> None:
    store = _store_with(pause_expires_at="2020-01-01T00:00:00+00:00")
    transport = _FakeEngineTransport(events=RESUMED_TO_COMPLETED)
    response = _post(_client(store, transport), {"run_id": RUN_ID, "decision": "approve"})
    assert response.status_code == 404
    assert transport.payloads == []
    assert store.rows[0]["consumed_at"] is None


def test_consumed_handoff_cannot_be_replayed() -> None:
    store = _store_with()
    store.rows[0]["consumed_at"] = _now_stamp()
    transport = _FakeEngineTransport(events=RESUMED_TO_COMPLETED)
    response = _post(_client(store, transport), {"run_id": RUN_ID, "decision": "approve"})
    assert response.status_code == 404
    assert transport.payloads == []


def test_corrupt_trusted_request_fails_closed_before_the_engine() -> None:
    store = _store_with()
    store.rows[0]["trusted_request"] = trusted_request(app_id="b62-padiem-chat")
    transport = _FakeEngineTransport(events=RESUMED_TO_COMPLETED)
    response = _post(_client(store, transport), {"run_id": RUN_ID, "decision": "approve"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "approval_handoff_unusable"
    assert transport.payloads == []
    # A rejected reconstruction leaves the pause retry-safe, not consumed.
    assert store.rows[0]["consumed_at"] is None


def test_missing_p01_run_identity_fails_closed_before_the_engine() -> None:
    store = _store_with(p01_run_id=None)
    transport = _FakeEngineTransport(events=RESUMED_TO_COMPLETED)
    response = _post(_client(store, transport), {"run_id": RUN_ID, "decision": "approve"})
    assert response.status_code == 409
    assert transport.payloads == []


def test_unusable_continuation_reference_fails_closed_before_the_engine() -> None:
    store = _store_with()
    store.rows[0]["continuation_ref"] = "attacker_ref_0000"
    transport = _FakeEngineTransport(events=RESUMED_TO_COMPLETED)
    response = _post(_client(store, transport), {"run_id": RUN_ID, "decision": "approve"})
    assert response.status_code == 409
    assert transport.payloads == []


def test_unconfigured_engine_lane_never_dispatches_a_decision() -> None:
    store = _store_with()
    response = _post(_client(store, None), {"run_id": RUN_ID, "decision": "approve"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "engine_not_configured"
    assert store.rows[0]["consumed_at"] is None


# ── approve / deny over the one canonical transport ──────────────────────────


def test_approve_resumes_once_and_projects_completed_from_canonical_evidence() -> None:
    store = _store_with()
    transport = _FakeEngineTransport(events=RESUMED_TO_COMPLETED, answer="견적 완료")
    response = _post(_client(store, transport), {"run_id": RUN_ID, "decision": "approve"})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["result"]["status"] == "completed"
    assert body["result"]["approval_required"] is False
    assert body["result"]["result_text"] == "견적 완료"
    assert body["result"]["run_id"] == RUN_ID

    assert len(transport.payloads) == 1
    payload = transport.payloads[0]
    assert payload["continuation_ref"] == CONTINUATION_REF
    assert payload["session_id"] == RUN_ID
    assert payload["trace_id"] == TRACE_ID
    assert payload["agent"]["id"] == AGENT_ID
    for forbidden in ("pause", "tool_authorization", "tool_arguments", "workspace_id", "user_id"):
        assert forbidden not in payload

    assert store.rows[0]["consumed_at"] is not None
    assert store.status_updates == [
        {
            "user_id": OWNER,
            "run_id": RUN_ID,
            "status": "completed",
            "result_summary": "견적 완료",
        }
    ]


def test_deny_uses_the_same_canonical_resume_authority() -> None:
    store = _store_with()
    transport = _FakeEngineTransport(
        events=RESUMED_TO_COMPLETED, error=PadiemAiEngineClientError("approval_denied", "denied")
    )
    response = _post(_client(store, transport), {"run_id": RUN_ID, "decision": "deny"})
    assert response.status_code == 200
    body = response.json()
    assert body["result"]["status"] == "cancelled"
    assert body["result"]["approval_required"] is False
    assert body["result"]["result_text"] == "승인이 거절되었습니다."
    # One transport, one protocol: deny is an outcome on the resume route.
    assert len(transport.payloads) == 1
    assert transport.payloads[0]["decision"]["outcome"] == "denied"
    assert store.rows[0]["consumed_at"] is not None


def test_public_response_never_leaks_snapshot_or_pause_internals() -> None:
    store = _store_with()
    transport = _FakeEngineTransport(
        events=RESUMED_TO_PAUSE_AGAIN,
        next_pause=_pause(NEXT_PAUSE_ID),
        continuation_ref=NEXT_CONTINUATION_REF,
    )
    body = _post(
        _client(store, transport), {"run_id": RUN_ID, "decision": "approve"}
    ).json()
    rendered = repr(body)
    assert body["result"]["status"] == "waiting_approval"
    assert body["result"]["approval_required"] is True
    assert body["result"]["continuation_ref"] == NEXT_CONTINUATION_REF
    for secret in (
        "trusted_request",
        "pause_id",
        "authority_ref",
        "evidence_ref",
        "tool_arguments",
        "invocation_sha256",
        "approval_scope",
        "session_secret",
        "model_policy",
        "pause_fake001",
    ):
        assert secret not in rendered, secret


def test_second_engine_pause_is_preserved_as_a_new_generation() -> None:
    store = _store_with()
    transport = _FakeEngineTransport(
        events=RESUMED_TO_PAUSE_AGAIN,
        next_pause=_pause(NEXT_PAUSE_ID),
        continuation_ref=NEXT_CONTINUATION_REF,
    )
    response = _post(_client(store, transport), {"run_id": RUN_ID, "decision": "approve"})
    assert response.status_code == 200
    assert len(store.recorded) == 1
    fresh = store.recorded[0]
    assert fresh["continuation_ref"] == NEXT_CONTINUATION_REF
    assert fresh["pause_id"] == NEXT_PAUSE_ID
    assert fresh["user_id"] == OWNER
    assert fresh["workspace_id"] == WORKSPACE
    assert fresh["p01_run_id"] == P01_RUN_ID
    # The next generation is reconstructed from the stored snapshot only.
    assert fresh["trusted_request"] == trusted_request()
    assert reconstruct_trusted_resume_request(
        trusted_request=fresh["trusted_request"], run_id=RUN_ID, p01_run_id=P01_RUN_ID
    ).payload["session_id"] == RUN_ID


def test_transport_failure_keeps_the_handoff_retry_safe() -> None:
    store = _store_with()
    transport = _FakeEngineTransport(
        events=RESUMED_TO_COMPLETED, error=PadiemAiEngineClientError("engine_http_error", "down")
    )
    response = _post(_client(store, transport), {"run_id": RUN_ID, "decision": "approve"})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "engine_execution_failed"
    assert store.rows[0]["consumed_at"] is None
    assert store.status_updates == []
    # A retry after recovery still has its stored pause.
    recovered = _FakeEngineTransport(events=RESUMED_TO_COMPLETED)
    retry = _post(_client(store, recovered), {"run_id": RUN_ID, "decision": "approve"})
    assert retry.status_code == 200
    assert store.rows[0]["consumed_at"] is not None


def test_engine_rejection_of_the_decision_is_retry_safe_and_not_consumed() -> None:
    store = _store_with()
    transport = _FakeEngineTransport(
        events=RESUMED_TO_COMPLETED,
        error=PadiemAiEngineClientError("continuation_identity_mismatch", "mismatch"),
    )
    response = _post(_client(store, transport), {"run_id": RUN_ID, "decision": "approve"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "approval_decision_rejected"
    assert store.rows[0]["consumed_at"] is None
    assert store.status_updates == []


def test_history_write_failure_is_reported_instead_of_false_success() -> None:
    store = _store_with()
    store.history_rows = {}  # no durable row to move forward
    transport = _FakeEngineTransport(events=RESUMED_TO_COMPLETED)
    response = _post(_client(store, transport), {"run_id": RUN_ID, "decision": "approve"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "approval_not_available"


def test_migration_017_is_additive_consumption_columns_only() -> None:
    from pathlib import Path

    sql = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "017_claw_approval_handoff_consumption.sql"
    ).read_text(encoding="utf-8").lower()
    assert "alter table claw_approval_handoff add column p01_run_id text" in sql
    assert "alter table claw_approval_handoff add column consumed_at text" in sql
    # No new continuation store, and nothing destructive.
    for forbidden in ("create table", "drop ", "delete from", "truncate", "foreign key"):
        assert forbidden not in sql, forbidden
