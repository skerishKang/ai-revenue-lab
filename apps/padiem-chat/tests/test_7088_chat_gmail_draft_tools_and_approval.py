"""#7088 Chat 서버 층 시험: Gmail 초안 생성·삭제 선언, 202 paused 확인 카드 연동, resume/cancel 및 발송 차단."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import secrets
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app import chat_connector_tools as tools_module
from app.app_factory import create_app
from app.auth import SESSION_COOKIE
from app.chat_routes import _connector_tool_lane
from app.connector_tool_engine_client import (
    CONNECTOR_TOOL_ENDPOINTS,
    TOOL_CANCEL_ENDPOINT,
    TOOL_EXECUTE_ENDPOINT,
    TOOL_RESUME_ENDPOINT,
    CloudflareConnectorToolEngineClient,
    ConnectorToolEngineError,
)
from app.history import UserProfile
from app.local_p01_engine import build_local_connector_tool_client
from app.orchestration_bridge import (
    B62OrchestrationError,
    OrchestrationSnapshot,
)
from app.orchestration_routes import install_orchestration_routes
from padiem_ai_core import AgentProfile
from padiem_ai_core.agent_approval import (
    ApprovalOutcome,
    ApprovalPause,
    ApprovalRequirement,
    VerifiedApprovalDecision,
    tool_invocation_digest,
)
from padiem_ai_core.connectors import (
    GMAIL_COMPOSE_AUTH_SCOPE,
    GMAIL_CREATE_DRAFT_TOOL_ID,
    GMAIL_DELETE_DRAFT_TOOL_ID,
    GMAIL_DRAFT_CANONICAL_TOOL_IDS,
    GMAIL_READONLY_AUTH_SCOPE,
    GMAIL_SEND_TOOLS_PRESENT,
    register_gmail_draft_tools,
    register_gmail_read_tools,
)
from padiem_ai_core.gmail_capability import GMAIL_MCP_SEND_TOOL_SUPPORTED
from padiem_ai_core.tool_runtime import (
    ToolAuthorizationContext,
    ToolInvocation,
    ToolRuntime,
    ToolRuntimeError,
)
from test_browser_orchestration_lifecycle_contract import LIFECYCLE_PATH, _run_node
from test_google_connector_ticket_bridge import cookie_for, settings

ORIGIN = "https://chat.example.test"


class _MemoryPauseStore:
    """Owner-scoped OrchestrationStateStore test double matching D1OrchestrationStateStore."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict[str, Any]] = {}
        self.decisions: list[dict[str, Any]] = []

    async def save_pause(
        self,
        *,
        user_id: str,
        continuation_ref: str,
        pause_id: str,
        engine_request: dict[str, Any],
        user_text: str,
        conversation_id: str | None,
        expires_at: str,
    ) -> None:
        self.rows[(user_id, continuation_ref)] = {
            "continuation_ref": continuation_ref,
            "user_id": user_id,
            "pause_id": pause_id,
            "engine_request": dict(engine_request),
            "user_text": user_text,
            "conversation_id": conversation_id,
            "expires_at": expires_at,
            "state": "active",
        }

    async def load_active(self, *, user_id: str, continuation_ref: str) -> OrchestrationSnapshot:
        row = self.rows.get((user_id, continuation_ref))
        if row is None or row["state"] != "active":
            raise B62OrchestrationError(
                "continuation_not_available",
                "이 작업은 더 이상 이어갈 수 없습니다.",
                status_code=409,
            )
        return OrchestrationSnapshot(
            continuation_ref=row["continuation_ref"],
            user_id=row["user_id"],
            pause_id=row["pause_id"],
            engine_request=dict(row["engine_request"]),
            user_text=row["user_text"],
            conversation_id=row["conversation_id"],
            expires_at=row["expires_at"],
            state="active",
        )

    async def record_decision(
        self,
        *,
        snapshot: OrchestrationSnapshot,
        decision_id: str,
        outcome: str,
        authority_ref: str,
        evidence_ref: str,
        decided_at: str,
    ) -> None:
        self.decisions.append(
            {
                "continuation_ref": snapshot.continuation_ref,
                "user_id": snapshot.user_id,
                "decision_id": decision_id,
                "pause_id": snapshot.pause_id,
                "outcome": outcome,
                "authority_ref": authority_ref,
                "evidence_ref": evidence_ref,
                "decided_at": decided_at,
            }
        )
        row = self.rows.get((snapshot.user_id, snapshot.continuation_ref))
        if row is not None and row["state"] == "active":
            row["state"] = "resuming"

    async def set_state(self, *, user_id: str, continuation_ref: str, state: str) -> None:
        row = self.rows.get((user_id, continuation_ref))
        if row is not None:
            row["state"] = state


class _TwoUserHistoryStore:
    def __init__(self) -> None:
        self.owner_a = UserProfile("usr_" + "a" * 32, "owner.a@example.test", "Owner A", "")
        self.owner_b = UserProfile("usr_" + "b" * 32, "owner.b@example.test", "Owner B", "")
        self.exchanges: list[dict[str, Any]] = []

    async def get_user(self, user_id: str) -> UserProfile | None:
        if user_id == self.owner_a.id:
            return self.owner_a
        if user_id == self.owner_b.id:
            return self.owner_b
        return None

    async def append_exchange(
        self,
        user_id: str,
        conversation_id: str | None,
        user_text: str,
        answer: str,
        *,
        product_scope: str = "chat",
    ) -> str:
        conv_id = conversation_id or "conv_7088_saved"
        self.exchanges.append(
            {
                "user_id": user_id,
                "conversation_id": conv_id,
                "user_text": user_text,
                "answer": answer,
                "product_scope": product_scope,
            }
        )
        return conv_id


class _ScriptedFollowUpModel:
    def __init__(self, reply: str = "확인하신 Gmail 초안을 저장했습니다. 메일은 발송되지 않았습니다.") -> None:
        self.reply = reply
        self.calls: list[dict[str, Any]] = []

    async def stream_text_auto(
        self,
        messages,
        *,
        skill=None,
        additional_system_context=None,
        tools=(),
        tool_choice=None,
        **kwargs,
    ):
        self.calls.append(
            {
                "messages": list(messages),
                "context": additional_system_context,
                "tools": tools,
            }
        )
        yield SimpleNamespace(delta_thought=None, delta_content=self.reply, done=False)
        yield SimpleNamespace(delta_thought=None, delta_content=None, done=True)


class _CoreBackedEngineBinding:
    """In-process Engine /internal/v1/tools/{execute,resume,cancel} backed by Core ToolRuntime."""

    _CANONICAL_TO_RUNTIME = {
        "tool:google:gmail.search_messages@1": "gmail.search_messages",
        "tool:google:gmail.get_message@1": "gmail.get_message",
        "tool:google:gmail.create_draft@1": GMAIL_CREATE_DRAFT_TOOL_ID,
        "tool:google:gmail.delete_draft@1": GMAIL_DELETE_DRAFT_TOOL_ID,
    }

    def __init__(self) -> None:
        self.provider_calls: list[tuple[str, str]] = []
        self.wire_paths: list[str] = []
        self.runtime = ToolRuntime()
        register_gmail_read_tools(
            self.runtime,
            self,
            binding_ref="gmail_bind_7088",
            actor_ref="actor_7088",
        )
        register_gmail_draft_tools(
            self.runtime,
            self,
            binding_ref="gmail_bind_7088",
            actor_ref="actor_7088",
        )
        self.agent_profile = AgentProfile(
            id="claw_mail_reader_v1",
            title="Claw mail reader",
            description="Gmail read and confirmation-gated draft agent",
            system_instruction="Read mail and manage drafts after user confirmation only.",
            task_type="general",
            optimize_for="balanced",
            max_tokens=500,
            allowed_tools=tuple(self._CANONICAL_TO_RUNTIME.values()),
        )
        self.continuations: dict[str, dict[str, Any]] = {}

    async def get_json(self, *, path: str, **kwargs) -> dict[str, Any]:
        self.provider_calls.append(("GET", path))
        return {"messages": [{"id": "m_1", "threadId": "t_1"}]}

    async def post_json(self, *, path: str, json_body: dict[str, Any], **kwargs) -> dict[str, Any]:
        assert path == "/users/me/drafts"
        self.provider_calls.append(("POST", path))
        return {"id": "dr_7088_1", "message": {"id": "msg_7088_1", "threadId": "thr_7088_1"}}

    async def delete(self, *, path: str, **kwargs) -> None:
        assert path.startswith("/users/me/drafts/")
        self.provider_calls.append(("DELETE", path))

    @staticmethod
    def _response(status: int, body: dict[str, Any]) -> Any:
        encoded = json.dumps(body, ensure_ascii=False)

        class _Resp:
            def __init__(self) -> None:
                self.status = status

            async def text(self) -> str:
                return encoded

        return _Resp()

    async def fetch(self, req: dict[str, Any]) -> Any:
        url = req["url"]
        path = "/" + url.split("://", 1)[-1].split("/", 1)[-1]
        self.wire_paths.append(path)
        payload = json.loads(req["body"])

        if path == TOOL_EXECUTE_ENDPOINT:
            canonical_id = payload["tool_id"]
            runtime_id = self._CANONICAL_TO_RUNTIME.get(canonical_id)
            if runtime_id is None:
                return self._response(403, {"ok": False, "error": {"code": "tool_not_registered"}})
            invocation = ToolInvocation(tool_id=runtime_id, arguments=payload["arguments"])
            auth = ToolAuthorizationContext(
                app_id=payload["app_id"],
                agent_id="claw_mail_reader_v1",
                granted_auth_scopes=(GMAIL_READONLY_AUTH_SCOPE, GMAIL_COMPOSE_AUTH_SCOPE),
                user_confirmed_tools=(),
            )
            try:
                result = await self.runtime.execute(invocation, self.agent_profile, auth)
            except ToolRuntimeError as exc:
                if exc.code == "tool_user_confirmation_required":
                    now = datetime.now(timezone.utc)
                    pause = ApprovalPause(
                        pause_id=f"pause:{secrets.token_hex(12)}",
                        run_id=f"torun:{secrets.token_hex(12)}",
                        agent_runtime_id=payload["agent_id"],
                        tool_id=runtime_id,
                        invocation_sha256=tool_invocation_digest(invocation),
                        requirement=ApprovalRequirement.USER_CONFIRMATION,
                        step_index=1,
                        created_at=now,
                        expires_at=now + timedelta(minutes=10),
                    )
                    cont_ref = f"cont_{secrets.token_hex(12)}"
                    self.continuations[cont_ref] = {
                        "state": "active",
                        "app_id": payload["app_id"],
                        "agent_id": payload["agent_id"],
                        "canonical_tool_id": canonical_id,
                        "invocation": invocation,
                        "pause": pause,
                    }
                    return self._response(
                        202,
                        {
                            "ok": True,
                            "tool": {
                                "status": "paused",
                                "canonical_tool_id": canonical_id,
                                "run_id": pause.run_id,
                                "continuation_ref": cont_ref,
                                "approval_pause": pause.to_public_dict(),
                            },
                        },
                    )
                return self._response(403, {"ok": False, "error": {"code": exc.code}})
            return self._response(
                200,
                {
                    "ok": True,
                    "tool": {
                        "status": "completed",
                        "canonical_tool_id": canonical_id,
                        "output": tools_module._plain_json(result.output),
                    },
                },
            )

        if path == TOOL_RESUME_ENDPOINT:
            cont_ref = payload["continuation_ref"]
            entry = self.continuations.get(cont_ref)
            if entry is None or entry["state"] != "active" or entry["app_id"] != payload["app_id"]:
                return self._response(
                    409,
                    {"ok": False, "error": {"code": "continuation_already_consumed"}},
                )
            dec = payload["decision"]
            pause: ApprovalPause = entry["pause"]
            decided_at = datetime.fromisoformat(dec["decided_at"].replace("Z", "+00:00"))
            verified = VerifiedApprovalDecision(
                decision_id=dec["decision_id"],
                pause_id=pause.pause_id,
                outcome=ApprovalOutcome(dec["outcome"]),
                authority_ref=dec["authority_ref"],
                evidence_ref=dec["evidence_ref"],
                decided_at=decided_at,
            )
            assert dec["pause_id"] == pause.pause_id
            assert pause.created_at <= verified.decided_at <= pause.expires_at
            entry["state"] = "consumed"
            if verified.outcome is ApprovalOutcome.DENIED:
                return self._response(
                    409,
                    {"ok": False, "error": {"code": "approval_denied"}},
                )
            invocation = entry["invocation"]
            auth = ToolAuthorizationContext(
                app_id=entry["app_id"],
                agent_id="claw_mail_reader_v1",
                granted_auth_scopes=(GMAIL_READONLY_AUTH_SCOPE, GMAIL_COMPOSE_AUTH_SCOPE),
                user_confirmed_tools=(invocation.tool_id,),
            )
            result = await self.runtime.execute(invocation, self.agent_profile, auth)
            return self._response(
                200,
                {
                    "ok": True,
                    "tool": {
                        "status": "completed",
                        "canonical_tool_id": entry["canonical_tool_id"],
                        "continuation_ref": cont_ref,
                        "output": tools_module._plain_json(result.output),
                    },
                },
            )

        if path == TOOL_CANCEL_ENDPOINT:
            cont_ref = payload["continuation_ref"]
            entry = self.continuations.get(cont_ref)
            if entry is None or entry["state"] != "active" or entry["app_id"] != payload["app_id"]:
                return self._response(
                    409,
                    {"ok": False, "error": {"code": "continuation_not_found"}},
                )
            entry["state"] = "cancelled"
            return self._response(
                200,
                {
                    "ok": True,
                    "status": "cancelled",
                    "continuation_ref": cont_ref,
                    "tool": {"terminal_state": "cancelled"},
                },
            )

        return self._response(404, {"ok": False, "error": {"code": "not_found"}})


def _request_factory(url: str, *, method: str, headers: dict[str, str], body: str) -> Any:
    return SimpleNamespace(
        js_object={"url": url, "method": method, "headers": dict(headers), "body": body}
    )


class _FakeTiming:
    def __init__(self) -> None:
        self.outcomes: list[str] = []

    def set_outcome(self, value: str) -> None:
        self.outcomes.append(value)


def _authed_client(app: Any, user_id: str) -> httpx.AsyncClient:
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN)
    client.cookies.set(SESSION_COOKIE, cookie_for(user_id), domain="chat.example.test")
    return client


def _parse_sse(frames: list[bytes]) -> list[tuple[str, dict[str, Any]]]:
    text = b"".join(frames).decode("utf-8")
    parsed: list[tuple[str, dict[str, Any]]] = []
    for chunk in text.strip().split("\n\n"):
        if not chunk.strip():
            continue
        ev_name = "message"
        data_text = "{}"
        for line in chunk.splitlines():
            if line.startswith("event: "):
                ev_name = line[len("event: "):]
            elif line.startswith("data: "):
                data_text = line[len("data: "):]
        parsed.append((ev_name, json.loads(data_text)))
    return parsed


def test_7088_gmail_draft_declarations_and_send_block_invariants() -> None:
    assert GMAIL_SEND_TOOLS_PRESENT is False
    assert GMAIL_MCP_SEND_TOOL_SUPPORTED is False
    names = [decl.name for decl in tools_module.CONNECTOR_TOOL_DECLARATIONS]
    assert "gmail_create_draft" in names
    assert "gmail_delete_draft" in names
    assert all("send" not in name for name in names)
    assert all("send" not in name for name in tools_module.CONNECTOR_TOOL_BINDINGS)
    assert tools_module.CONNECTOR_TOOL_BINDINGS["gmail_create_draft"] == (
        GMAIL_DRAFT_CANONICAL_TOOL_IDS[0],
        "b54-padiem-claw",
        "agent:padiem:claw_mail_reader@1",
    )
    assert tools_module.CONNECTOR_TOOL_BINDINGS["gmail_delete_draft"] == (
        GMAIL_DRAFT_CANONICAL_TOOL_IDS[1],
        "b54-padiem-claw",
        "agent:padiem:claw_mail_reader@1",
    )
    # Local COM2 binding allowlists execute, resume and cancel, and nothing else.
    client, diag = build_local_connector_tool_client(
        {
            "PADIEM_CHAT_LOCAL_P01_ENGINE_ORIGIN": "http://127.0.0.1:8788",
            "PADIEM_CHAT_LOCAL_P01_CALLER_ID": "b54-p01-overlay-20260914-a1",
            "PADIEM_CHAT_LOCAL_P01_ENGINE_CREDENTIAL": "c" * 64,
        }
    )
    assert client is not None and diag is None
    assert client._binding._paths == frozenset(CONNECTOR_TOOL_ENDPOINTS)


@pytest.mark.asyncio
async def test_7088_chat_pauses_draft_create_and_delete_for_confirmation_and_resumes_once(
    capsys: pytest.CaptureFixture[str],
) -> None:
    history = _TwoUserHistoryStore()
    pause_store = _MemoryPauseStore()
    engine_binding = _CoreBackedEngineBinding()
    engine_client = CloudflareConnectorToolEngineClient(
        engine_binding,
        caller_id="b54-p01-overlay-20260914-a1",
        credential="cred-test-only",
        request_factory=_request_factory,
    )
    follow_model = _ScriptedFollowUpModel()

    app = create_app(settings=settings(), history_store=history)
    install_orchestration_routes(app, None)
    app.state.connector_tool_engine_client = engine_client
    app.state.connector_tool_pause_store = pause_store
    app.state.b14_client = follow_model

    secret_subject = "비공개_초안_제목_7088"
    secret_body = "비공개_초안_본문_절대_로그_금지_7088"
    secret_recipient = "confidential.partner@example.com"

    # 1) Create draft -> 202 paused -> SSE orchestration_pause (0 Gmail POSTs before confirmation)
    create_frames: list[bytes] = []
    timing = _FakeTiming()
    async for frame in _connector_tool_lane(
        SimpleNamespace(app=app),
        tool_name="gmail_create_draft",
        tool_arguments={
            "to": [secret_recipient],
            "subject": secret_subject,
            "body": secret_body,
        },
        client=follow_model,
        messages=[{"role": "user", "content": "지메일 초안 하나 만들어줘"}],
        skill=None,
        reference_context=None,
        conversation_id=None,
        uid=history.owner_a.id,
        store=history,
        latest_user="지메일 초안 하나 만들어줘",
        timing=timing,
    ):
        create_frames.append(frame)

    events = _parse_sse(create_frames)
    assert len(events) == 1
    event_name, pause_data = events[0]
    assert event_name == "orchestration_pause"
    orch = pause_data["orchestration"]
    assert [e["kind"] for e in orch["events"]] == [
        "run_started",
        "tool_started",
        "approval_paused",
    ]
    assert orch["approval_pause"]["status"] == "paused"
    assert orch["approval_pause"]["requirement"] == "user_confirmation"
    cont_ref = orch["continuation_ref"]
    pause_id = orch["approval_pause"]["continuation_id"]
    assert engine_binding.provider_calls == [], "확인 전에는 Gmail API 호출이 절대 일어나면 안 된다"
    assert follow_model.calls == [], "확인 전에는 후속 답변 생성이 실행되면 안 된다"

    # Cross-user isolation: owner_b cannot resume owner_a's paused draft
    async with _authed_client(app, history.owner_b.id) as foreign_client:
        foreign_resp = await foreign_client.post(
            "/api/orchestration/resume",
            headers={"Origin": ORIGIN},
            json={
                "continuationRef": cont_ref,
                "pauseId": pause_id,
                "outcome": "approved",
                "requiresTrustedDecision": True,
            },
        )
    assert foreign_resp.status_code == 409
    assert engine_binding.provider_calls == []

    # Approved resume by owner_a -> Engine /internal/v1/tools/resume -> 1 POST /users/me/drafts
    async with _authed_client(app, history.owner_a.id) as owner_client:
        resume_resp = await owner_client.post(
            "/api/orchestration/resume",
            headers={"Origin": ORIGIN},
            json={
                "continuationRef": cont_ref,
                "pauseId": pause_id,
                "outcome": "approved",
                "requiresTrustedDecision": True,
            },
        )
        replay_resp = await owner_client.post(
            "/api/orchestration/resume",
            headers={"Origin": ORIGIN},
            json={
                "continuationRef": cont_ref,
                "pauseId": pause_id,
                "outcome": "approved",
                "requiresTrustedDecision": True,
            },
        )

    assert resume_resp.status_code == 200, resume_resp.text
    resumed_json = resume_resp.json()
    assert resumed_json["decision_status"] == "approved"
    assert resumed_json["answer"] == follow_model.reply
    assert resumed_json["conversation_id"] == "conv_7088_saved"
    assert [e["kind"] for e in resumed_json["orchestration"]["events"]] == [
        "run_started",
        "run_resumed",
        "tool_completed",
        "run_completed",
    ]
    assert engine_binding.provider_calls == [("POST", "/users/me/drafts")]
    assert engine_binding.wire_paths == [TOOL_EXECUTE_ENDPOINT, TOOL_RESUME_ENDPOINT]
    assert replay_resp.status_code == 409
    assert len(engine_binding.provider_calls) == 1
    assert len(history.exchanges) == 1

    # 2) Delete draft -> 202 paused -> approved resume -> 1 DELETE /users/me/drafts/dr_7088_1
    delete_frames: list[bytes] = []
    async for frame in _connector_tool_lane(
        SimpleNamespace(app=app),
        tool_name="gmail_delete_draft",
        tool_arguments={"draftId": "dr_7088_1"},
        client=follow_model,
        messages=[{"role": "user", "content": "방금 만든 지메일 초안 삭제해줘"}],
        skill=None,
        reference_context=None,
        conversation_id="conv_7088_saved",
        uid=history.owner_a.id,
        store=history,
        latest_user="방금 만든 지메일 초안 삭제해줘",
        timing=_FakeTiming(),
    ):
        delete_frames.append(frame)

    del_event_name, del_pause_data = _parse_sse(delete_frames)[0]
    assert del_event_name == "orchestration_pause"
    assert len(engine_binding.provider_calls) == 1, "확인 전에는 Gmail 초안 삭제가 나가면 안 된다"

    del_ref = del_pause_data["orchestration"]["continuation_ref"]
    del_pause_id = del_pause_data["orchestration"]["approval_pause"]["continuation_id"]
    async with _authed_client(app, history.owner_a.id) as owner_client:
        del_resume_resp = await owner_client.post(
            "/api/orchestration/resume",
            headers={"Origin": ORIGIN},
            json={
                "continuationRef": del_ref,
                "pauseId": del_pause_id,
                "outcome": "approved",
                "requiresTrustedDecision": True,
            },
        )
    assert del_resume_resp.status_code == 200
    assert engine_binding.provider_calls[-1] == ("DELETE", "/users/me/drafts/dr_7088_1")

    # Journal/log redaction: recipient, subject and body never appear in stdout/stderr
    captured = capsys.readouterr()
    combined_logs = captured.out + "\n" + captured.err
    assert secret_recipient not in combined_logs
    assert secret_subject not in combined_logs
    assert secret_body not in combined_logs
    assert "cred-test-only" not in combined_logs


@pytest.mark.asyncio
async def test_7088_denied_cancel_and_send_attempts_execute_zero_gmail_calls() -> None:
    history = _TwoUserHistoryStore()
    pause_store = _MemoryPauseStore()
    engine_binding = _CoreBackedEngineBinding()
    engine_client = CloudflareConnectorToolEngineClient(
        engine_binding,
        caller_id="b54-p01-overlay-20260914-a1",
        credential="cred-test-only",
        request_factory=_request_factory,
    )
    follow_model = _ScriptedFollowUpModel()

    app = create_app(settings=settings(), history_store=history)
    install_orchestration_routes(app, None)
    app.state.connector_tool_engine_client = engine_client
    app.state.connector_tool_pause_store = pause_store
    app.state.b14_client = follow_model

    # Denied flow -> /internal/v1/tools/resume -> decision_status == "denied", 0 provider calls
    frames_deny: list[bytes] = []
    async for frame in _connector_tool_lane(
        SimpleNamespace(app=app),
        tool_name="gmail_create_draft",
        tool_arguments={"to": ["x@example.com"], "subject": "제목", "body": "본문"},
        client=follow_model,
        messages=[{"role": "user", "content": "지메일 초안 작성"}],
        skill=None,
        reference_context=None,
        conversation_id=None,
        uid=history.owner_a.id,
        store=history,
        latest_user="지메일 초안 작성",
        timing=_FakeTiming(),
    ):
        frames_deny.append(frame)
    deny_orch = _parse_sse(frames_deny)[0][1]["orchestration"]

    async with _authed_client(app, history.owner_a.id) as owner_client:
        denied_resp = await owner_client.post(
            "/api/orchestration/resume",
            headers={"Origin": ORIGIN},
            json={
                "continuationRef": deny_orch["continuation_ref"],
                "pauseId": deny_orch["approval_pause"]["continuation_id"],
                "outcome": "denied",
                "requiresTrustedDecision": True,
            },
        )
    assert denied_resp.status_code == 200
    assert denied_resp.json()["decision_status"] == "denied"
    assert denied_resp.json()["answer"] is None

    # Cancel flow -> /internal/v1/tools/cancel -> decision_status == "cancelled", 0 provider calls
    frames_cancel: list[bytes] = []
    async for frame in _connector_tool_lane(
        SimpleNamespace(app=app),
        tool_name="gmail_delete_draft",
        tool_arguments={"draftId": "dr_cancel_1"},
        client=follow_model,
        messages=[{"role": "user", "content": "지메일 초안 삭제"}],
        skill=None,
        reference_context=None,
        conversation_id=None,
        uid=history.owner_a.id,
        store=history,
        latest_user="지메일 초안 삭제",
        timing=_FakeTiming(),
    ):
        frames_cancel.append(frame)
    cancel_orch = _parse_sse(frames_cancel)[0][1]["orchestration"]

    async with _authed_client(app, history.owner_a.id) as owner_client:
        cancelled_resp = await owner_client.post(
            "/api/orchestration/cancel",
            headers={"Origin": ORIGIN},
            json={"continuationRef": cancel_orch["continuation_ref"]},
        )
    assert cancelled_resp.status_code == 200
    assert cancelled_resp.json()["decision_status"] == "cancelled"
    assert cancelled_resp.json()["orchestration"]["events"][-1]["kind"] == "run_cancelled"
    assert engine_binding.wire_paths[-1] == TOOL_CANCEL_ENDPOINT

    # Mail send attempts remain hard-blocked in both Chat lane and Engine client
    for forbidden_send_name in ("gmail_send", "gmail_send_message", "gmail_send_draft"):
        send_frames: list[bytes] = []
        async for frame in _connector_tool_lane(
            SimpleNamespace(app=app),
            tool_name=forbidden_send_name,
            tool_arguments={"to": ["x@example.com"], "subject": "발송", "body": "금지"},
            client=follow_model,
            messages=[{"role": "user", "content": "메일 보내줘"}],
            skill=None,
            reference_context=None,
            conversation_id=None,
            uid=history.owner_a.id,
            store=history,
            latest_user="메일 보내줘",
            timing=_FakeTiming(),
        ):
            send_frames.append(frame)
        ev_name, err_data = _parse_sse(send_frames)[0]
        assert ev_name == "error"
        assert err_data["error"]["code"] == "connector_tool_unsupported"
        with pytest.raises(ConnectorToolEngineError) as send_err:
            await engine_client.execute(tool_name=forbidden_send_name, arguments={})
        assert send_err.value.status_code == 422

    assert engine_binding.provider_calls == []
    assert history.exchanges == []


@pytest.mark.asyncio
async def test_7088_paused_orchestration_wires_into_browser_confirmation_card_intents() -> None:
    history = _TwoUserHistoryStore()
    pause_store = _MemoryPauseStore()
    engine_binding = _CoreBackedEngineBinding()
    engine_client = CloudflareConnectorToolEngineClient(
        engine_binding,
        caller_id="b54-p01-overlay-20260914-a1",
        credential="cred-test-only",
        request_factory=_request_factory,
    )
    follow_model = _ScriptedFollowUpModel()

    app = create_app(settings=settings(), history_store=history)
    install_orchestration_routes(app, None)
    app.state.connector_tool_engine_client = engine_client
    app.state.connector_tool_pause_store = pause_store
    app.state.b14_client = follow_model

    frames: list[bytes] = []
    async for frame in _connector_tool_lane(
        SimpleNamespace(app=app),
        tool_name="gmail_create_draft",
        tool_arguments={"to": ["card@example.com"], "subject": "카드확인", "body": "본문"},
        client=follow_model,
        messages=[{"role": "user", "content": "지메일 초안 작성"}],
        skill=None,
        reference_context=None,
        conversation_id=None,
        uid=history.owner_a.id,
        store=history,
        latest_user="지메일 초안 작성",
        timing=_FakeTiming(),
    ):
        frames.append(frame)

    orch = _parse_sse(frames)[0][1]["orchestration"]
    lifecycle_js = LIFECYCLE_PATH.read_text(encoding="utf-8")
    card = _run_node(
        """
global.window = globalThis;
global.CustomEvent = class CustomEvent { constructor(t, o={}) { this.type = t; this.detail = o.detail; } };
"""
        + lifecycle_js
        + f"""
const orch = {json.dumps(orch, ensure_ascii=False)};
const model = PadiemChatOrchestrationUI.viewModel(orch);
const approve = PadiemChatOrchestrationUI.approvalIntent(orch, "approved");
const cancel = PadiemChatOrchestrationUI.cancelIntent(orch);
console.log(JSON.stringify({{ model, approve, cancel }}));
"""
    )
    assert card["model"]["valid"] is True
    assert card["model"]["approval"]["requirement"] == "user_confirmation"
    assert card["cancel"] == {"continuationRef": orch["continuation_ref"]}

    async with _authed_client(app, history.owner_a.id) as owner_client:
        resumed = await owner_client.post(
            "/api/orchestration/resume",
            headers={"Origin": ORIGIN},
            json=card["approve"],
        )
    assert resumed.status_code == 200
    resumed_model = _run_node(
        """
global.window = globalThis;
global.CustomEvent = class CustomEvent { constructor(t, o={}) { this.type = t; this.detail = o.detail; } };
"""
        + lifecycle_js
        + f"""
const orch = {json.dumps(resumed.json()["orchestration"], ensure_ascii=False)};
console.log(JSON.stringify(PadiemChatOrchestrationUI.viewModel(orch)));
"""
    )
    assert resumed_model["valid"] is True
    assert resumed_model["terminal"] == "completed"
    assert engine_binding.provider_calls == [("POST", "/users/me/drafts")]

