"""#7088 Engine 층 시험: Gmail 초안 생성·삭제 활성화, 사용자 확인(승인) 강제 지점, 발송(SEND) 차단 고정."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from padiem_ai_core.connectors import (
    GMAIL_BASE_URL,
    GMAIL_COMPOSE_AUTH_SCOPE,
    GMAIL_COMPOSE_SCOPE,
    GMAIL_READONLY_AUTH_SCOPE,
    GMAIL_READONLY_SCOPE,
)
from padiem_ai_core.tool_runtime import ToolHandlerError

from app.approval_verifier import AuthenticatedFirstPartyApprovalDecisionVerifier
from app.connector_bindings import (
    GMAIL_MAIL_READER_AGENT_ID,
    GMAIL_REFERENCE_APP_ID,
    GmailGrant,
    build_tool_binding_resolver,
)
from app.gmail_port_cp_lease import (
    GMAIL_CREATE_DRAFT,
    GMAIL_DELETE_DRAFT,
    GMAIL_SEND,
    ControlPlaneLeaseGmailReadPort,
)
from app.google_oauth_access_lease import (
    CloudflareControlPlaneGoogleOAuthAccessLeaseClient,
    EngineGoogleOAuthAccessLease,
)
from app.orchestration_service import InMemoryContinuationStore
from app.tool_execution_service import ToolExecutionEngineService


NOW = datetime(2026, 11, 11, 9, 0, tzinfo=timezone.utc)
BINDING_REF = "gmail-binding-7088"
ACTOR_REF = "actor_7088"
TOKEN = "short-lived-compose-token"


class _ComposeLeaseClient:
    def __init__(self, scopes: tuple[str, ...]) -> None:
        self._scopes = scopes
        self.calls: list[dict] = []

    async def issue_access_lease(self, *, binding_ref: str, connector_id: str) -> EngineGoogleOAuthAccessLease:
        self.calls.append({"binding_ref": binding_ref, "connector_id": connector_id})
        return EngineGoogleOAuthAccessLease(
            access_token=TOKEN,
            binding_ref=binding_ref,
            connector_id=connector_id,
            actor_ref=ACTOR_REF,
            account_ref="acct_7088",
            workspace_ref="ws_7088",
            scopes=self._scopes,
            expires_at=NOW + timedelta(hours=1),
        )


def _decision(pause_id: str, outcome: str) -> dict:
    return {
        "decision_id": f"dec_{pause_id[-8:]}_{outcome}",
        "pause_id": pause_id,
        "outcome": outcome,
        "authority_ref": "b62_session:usr_7088",
        "evidence_ref": "b62_decision:ev_7088",
        "decided_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def _service(*, grant_scopes: tuple[str, ...], lease_scopes: tuple[str, ...], transport: httpx.AsyncBaseTransport):
    lease_client = _ComposeLeaseClient(lease_scopes)
    port = ControlPlaneLeaseGmailReadPort(lease_client=lease_client, transport=transport)
    grant = GmailGrant(
        app_id=GMAIL_REFERENCE_APP_ID,
        canonical_agent_id=GMAIL_MAIL_READER_AGENT_ID,
        binding_ref=BINDING_REF,
        actor_ref=ACTOR_REF,
        granted_scopes=grant_scopes,
    )
    resolver = build_tool_binding_resolver(
        gmail_port=port,
        grants={GMAIL_REFERENCE_APP_ID: grant},
    )
    store = InMemoryContinuationStore()
    service = ToolExecutionEngineService(
        tool_binding_resolver=resolver,
        continuation_store=store,
        approval_decision_verifier=AuthenticatedFirstPartyApprovalDecisionVerifier(),
    )
    return service, port, lease_client


def test_7088_cp_lease_client_accepts_readonly_plus_compose_and_rejects_send_scope():
    class _Binding:
        def __init__(self, scopes: list[str]):
            self.scopes = scopes

        async def issue_access_lease(self, payload):
            return {
                "ok": True,
                "lease": {
                    "access_token": TOKEN,
                    "binding_ref": BINDING_REF,
                    "connector_id": "gmail",
                    "actor_ref": ACTOR_REF,
                    "account_ref": "acct_7088",
                    "workspace_ref": "ws_7088",
                    "scopes": self.scopes,
                    "expires_at": (NOW + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
                },
            }

    ok_client = CloudflareControlPlaneGoogleOAuthAccessLeaseClient(
        _Binding([GMAIL_READONLY_SCOPE, GMAIL_COMPOSE_SCOPE]),
        clock=lambda: NOW,
    )
    lease = asyncio.run(ok_client.issue_access_lease(binding_ref=BINDING_REF, connector_id="gmail"))
    assert lease.scopes == (GMAIL_READONLY_SCOPE, GMAIL_COMPOSE_SCOPE)

    bad_client = CloudflareControlPlaneGoogleOAuthAccessLeaseClient(
        _Binding(["https://www.googleapis.com/auth/gmail.send"]),
        clock=lambda: NOW,
    )
    with pytest.raises(Exception):
        asyncio.run(bad_client.issue_access_lease(binding_ref=BINDING_REF, connector_id="gmail"))


def test_7088_engine_enforces_user_confirmation_for_draft_create_and_delete_and_blocks_replay():
    requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(200, json={"messages": [{"id": "m_search_1", "threadId": "t_1"}]})
        if request.method == "POST" and request.url.path == "/gmail/v1/users/me/drafts":
            return httpx.Response(200, json={"id": "dr_7088", "message": {"id": "m_dr_7088", "threadId": "t_dr_7088"}})
        if request.method == "DELETE" and request.url.path == "/gmail/v1/users/me/drafts/dr_7088":
            return httpx.Response(204)
        return httpx.Response(404)

    service, _port, _lease = _service(
        grant_scopes=(GMAIL_READONLY_AUTH_SCOPE, GMAIL_COMPOSE_AUTH_SCOPE),
        lease_scopes=(GMAIL_READONLY_SCOPE, GMAIL_COMPOSE_SCOPE),
        transport=httpx.MockTransport(handler),
    )

    # 1) 검색 1건: READ 도구는 확인 없이 즉시 실행된다.
    searched = asyncio.run(
        service.execute_payload(
            {
                "app_id": GMAIL_REFERENCE_APP_ID,
                "agent_id": GMAIL_MAIL_READER_AGENT_ID,
                "tool_id": "tool:google:gmail.search_messages@1",
                "arguments": {"query": "in:inbox"},
            }
        )
    )
    assert searched.status_code == 200
    assert searched.body["tool"]["status"] == "completed"
    assert requests == [("GET", "/gmail/v1/users/me/messages")]

    # 2) 초안 생성 1건: 첫 호출은 Core ToolRuntime + ToolExecutionEngineService에서 202 paused로 멈추고 외부 호출은 0건이다.
    paused_create = asyncio.run(
        service.execute_payload(
            {
                "app_id": GMAIL_REFERENCE_APP_ID,
                "agent_id": GMAIL_MAIL_READER_AGENT_ID,
                "tool_id": "tool:google:gmail.create_draft@1",
                "arguments": {
                    "to": ["partner@example.com"],
                    "subject": "견적 초안",
                    "body": "확인용 초안입니다.",
                },
            }
        )
    )
    assert paused_create.status_code == 202
    assert paused_create.body["tool"]["status"] == "paused"
    assert paused_create.body["tool"]["approval_pause"]["requirement"] == "user_confirmation"
    assert len(requests) == 1, "확인 전에는 Gmail 초안 생성 POST가 절대 나가면 안 된다"

    create_ref = paused_create.body["tool"]["continuation_ref"]
    create_pause_id = paused_create.body["tool"]["approval_pause"]["continuation_id"]
    resumed_create = asyncio.run(
        service.resume_payload(
            {
                "app_id": GMAIL_REFERENCE_APP_ID,
                "continuation_ref": create_ref,
                "decision": _decision(create_pause_id, "approved"),
            }
        )
    )
    assert resumed_create.status_code == 200
    assert resumed_create.body["tool"]["status"] == "completed"
    assert resumed_create.body["tool"]["output"]["draft_id"] == "dr_7088"
    assert resumed_create.body["tool"]["output"]["sent"] is False
    assert requests[-1] == ("POST", "/gmail/v1/users/me/drafts")

    # 같은 continuation_ref 재사용(replay)은 409로 거부되고 추가 POST는 0건이다.
    replayed = asyncio.run(
        service.resume_payload(
            {
                "app_id": GMAIL_REFERENCE_APP_ID,
                "continuation_ref": create_ref,
                "decision": _decision(create_pause_id, "approved"),
            }
        )
    )
    assert replayed.status_code == 409
    assert len(requests) == 2

    # 3) 초안 삭제 1건: 역시 202 paused 후 검증된 승인 결정 시에만 DELETE 1회 실행된다.
    paused_delete = asyncio.run(
        service.execute_payload(
            {
                "app_id": GMAIL_REFERENCE_APP_ID,
                "agent_id": GMAIL_MAIL_READER_AGENT_ID,
                "tool_id": "tool:google:gmail.delete_draft@1",
                "arguments": {"draftId": "dr_7088"},
            }
        )
    )
    assert paused_delete.status_code == 202
    assert len(requests) == 2, "확인 전에는 Gmail 초안 삭제 DELETE가 절대 나가면 안 된다"

    delete_ref = paused_delete.body["tool"]["continuation_ref"]
    delete_pause_id = paused_delete.body["tool"]["approval_pause"]["continuation_id"]
    resumed_delete = asyncio.run(
        service.resume_payload(
            {
                "app_id": GMAIL_REFERENCE_APP_ID,
                "continuation_ref": delete_ref,
                "decision": _decision(delete_pause_id, "approved"),
            }
        )
    )
    assert resumed_delete.status_code == 200
    assert resumed_delete.body["tool"]["output"]["deleted"] is True
    assert resumed_delete.body["tool"]["output"]["sent"] is False
    assert requests[-1] == ("DELETE", "/gmail/v1/users/me/drafts/dr_7088")


def test_7088_denied_or_cancelled_draft_and_send_attempts_execute_zero_provider_calls():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    service, port, _lease = _service(
        grant_scopes=(GMAIL_READONLY_AUTH_SCOPE, GMAIL_COMPOSE_AUTH_SCOPE),
        lease_scopes=(GMAIL_READONLY_SCOPE, GMAIL_COMPOSE_SCOPE),
        transport=httpx.MockTransport(handler),
    )

    # 거부(denied) 결정 시 외부 호출 0건
    paused = asyncio.run(
        service.execute_payload(
            {
                "app_id": GMAIL_REFERENCE_APP_ID,
                "agent_id": GMAIL_MAIL_READER_AGENT_ID,
                "tool_id": "tool:google:gmail.create_draft@1",
                "arguments": {"to": ["a@example.com"], "subject": "제목", "body": "본문"},
            }
        )
    )
    denied = asyncio.run(
        service.resume_payload(
            {
                "app_id": GMAIL_REFERENCE_APP_ID,
                "continuation_ref": paused.body["tool"]["continuation_ref"],
                "decision": _decision(paused.body["tool"]["approval_pause"]["continuation_id"], "denied"),
            }
        )
    )
    assert denied.status_code == 409
    assert denied.body["error"]["code"] == "approval_denied"

    # 취소(cancel) 시 외부 호출 0건
    paused2 = asyncio.run(
        service.execute_payload(
            {
                "app_id": GMAIL_REFERENCE_APP_ID,
                "agent_id": GMAIL_MAIL_READER_AGENT_ID,
                "tool_id": "tool:google:gmail.delete_draft@1",
                "arguments": {"draftId": "dr_cancel"},
            }
        )
    )
    cancelled = asyncio.run(
        service.cancel_payload(
            {
                "app_id": GMAIL_REFERENCE_APP_ID,
                "continuation_ref": paused2.body["tool"]["continuation_ref"],
                "reason": "user_cancelled",
            }
        )
    )
    assert cancelled.status_code == 200
    assert cancelled.body["status"] == "cancelled"
    assert cancelled.body["tool"]["terminal_state"] == "cancelled"

    # 발송(SEND)은 도구 표면과 HTTP 포트 양쪽에서 모두 차단된다 (외부 호출 0건)
    assert GMAIL_CREATE_DRAFT is True
    assert GMAIL_DELETE_DRAFT is True
    assert GMAIL_SEND is False
    send_tool = asyncio.run(
        service.execute_payload(
            {
                "app_id": GMAIL_REFERENCE_APP_ID,
                "agent_id": GMAIL_MAIL_READER_AGENT_ID,
                "tool_id": "tool:google:gmail.send_message@1",
                "arguments": {"draftId": "dr_1"},
            }
        )
    )
    assert send_tool.status_code == 403
    for forbidden_send_path in ("/users/me/messages/send", "/users/me/drafts/send"):
        with pytest.raises(ToolHandlerError) as port_err:
            asyncio.run(
                port.post_json(
                    binding_ref=BINDING_REF,
                    actor_ref=ACTOR_REF,
                    required_scopes=(GMAIL_COMPOSE_SCOPE,),
                    base_url=GMAIL_BASE_URL,
                    path=forbidden_send_path,
                    json_body={"id": "dr_1"},
                    timeout_seconds=10,
                    max_response_bytes=1024,
                )
            )
        assert port_err.value.code == "gmail_provider_unavailable"
    assert calls == 0
