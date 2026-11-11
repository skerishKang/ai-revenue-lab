"""#7088 Core 층 시험: Gmail 초안 생성·삭제 등록, USER_CONFIRMATION 강제 지점, 발송(SEND) 비활성 고정."""
from __future__ import annotations

import asyncio
import base64
from email import message_from_bytes

import pytest

from padiem_ai_core import AgentProfile
from padiem_ai_core.connectors import (
    GMAIL_BASE_URL,
    GMAIL_COMPOSE_AUTH_SCOPE,
    GMAIL_COMPOSE_SCOPE,
    GMAIL_CREATE_DRAFT_TOOL_ID,
    GMAIL_DELETE_DRAFT_TOOL_ID,
    GMAIL_DRAFT_CANONICAL_TOOL_IDS,
    GMAIL_DRAFT_TOOL_IDS,
    GMAIL_READONLY_AUTH_SCOPE,
    GMAIL_SEND_TOOLS_PRESENT,
    gmail_draft_tool_specs,
    gmail_read_tool_specs,
    register_gmail_draft_tools,
)
from padiem_ai_core.contracts import ApprovalPolicy, ToolSideEffect
from padiem_ai_core.gmail_capability import (
    GMAIL_MCP_SEND_TOOL_SUPPORTED,
    GmailCapability,
    GmailCapabilityClassification,
    capability_requires_user_confirmation,
    classify_gmail_tool_id,
    is_promoted_gmail_draft_tool_id,
)
from padiem_ai_core.tool_runtime import (
    ToolAuthorizationContext,
    ToolInvocation,
    ToolRuntime,
    ToolRuntimeError,
)


BINDING_REF = "binding_gmail_7088"
ACTOR_REF = "actor_7088"


class _FakeDraftPort:
    def __init__(self) -> None:
        self.post_calls: list[dict] = []
        self.delete_calls: list[dict] = []

    async def post_json(self, **kwargs):
        self.post_calls.append(kwargs)
        return {"id": "draft_7088_1", "message": {"id": "msg_7088_1", "threadId": "thr_7088_1"}}

    async def delete(self, **kwargs):
        self.delete_calls.append(kwargs)
        return None


def _profile(*tools: str) -> AgentProfile:
    return AgentProfile(
        id="agent-7088",
        title="Agent",
        description="Gmail draft test agent",
        system_instruction="Use only allowed tools.",
        task_type="general",
        optimize_for="balanced",
        max_tokens=500,
        allowed_tools=tuple(tools),
    )


def test_7088_core_registers_draft_create_and_delete_with_user_confirmation_and_keeps_send_off():
    specs = gmail_draft_tool_specs()
    assert tuple(s.id for s in specs) == (GMAIL_CREATE_DRAFT_TOOL_ID, GMAIL_DELETE_DRAFT_TOOL_ID)
    assert GMAIL_DRAFT_TOOL_IDS == ("gmail.create_draft", "gmail.delete_draft")
    assert GMAIL_DRAFT_CANONICAL_TOOL_IDS == (
        "tool:google:gmail.create_draft@1",
        "tool:google:gmail.delete_draft@1",
    )
    for spec in specs:
        assert spec.side_effect is ToolSideEffect.WRITE
        assert spec.approval_policy is ApprovalPolicy.USER_CONFIRMATION
        assert spec.auth_scope == (GMAIL_COMPOSE_AUTH_SCOPE,)
        assert spec.input_schema["additionalProperties"] is False

    assert capability_requires_user_confirmation(GmailCapability.READ) is False
    assert capability_requires_user_confirmation(GmailCapability.CREATE_DRAFT) is True
    assert capability_requires_user_confirmation(GmailCapability.DELETE_DRAFT) is True

    # 발송(SEND)은 범위 밖이며 어떤 도구 목록에도 등록되지 않는다.
    assert GMAIL_SEND_TOOLS_PRESENT is False
    assert GMAIL_MCP_SEND_TOOL_SUPPORTED is False
    all_ids = {s.id for s in gmail_read_tool_specs() + gmail_draft_tool_specs()}
    assert all("send" not in tid for tid in all_ids)
    for send_id in ("gmail.send_message", "gmail.send_draft", "gmail.drafts.send", "tool:google:gmail.send@1"):
        assert is_promoted_gmail_draft_tool_id(send_id) is False
        assert classify_gmail_tool_id(send_id) is GmailCapabilityClassification.WRITE_OR_MATERIAL
    for draft_id in (*GMAIL_DRAFT_TOOL_IDS, *GMAIL_DRAFT_CANONICAL_TOOL_IDS):
        assert is_promoted_gmail_draft_tool_id(draft_id) is True


def test_7088_core_tool_runtime_enforces_user_confirmation_and_compose_scope_before_port_call():
    port = _FakeDraftPort()
    runtime = ToolRuntime()
    registered = register_gmail_draft_tools(
        runtime, port, binding_ref=BINDING_REF, actor_ref=ACTOR_REF
    )
    assert registered == (GMAIL_CREATE_DRAFT_TOOL_ID, GMAIL_DELETE_DRAFT_TOOL_ID)
    profile = _profile(*registered)

    create_inv = ToolInvocation(
        tool_id=GMAIL_CREATE_DRAFT_TOOL_ID,
        arguments={"to": ["recipient@example.com"], "subject": "회의 안내", "body": "초안 본문"},
    )
    delete_inv = ToolInvocation(
        tool_id=GMAIL_DELETE_DRAFT_TOOL_ID,
        arguments={"draftId": "draft_7088_1"},
    )

    # 1) gmail.readonly 만 있으면 gmail.compose 스코프 부족으로 차단 (포트 호출 0)
    with pytest.raises(ToolRuntimeError) as scope_err:
        asyncio.run(
            runtime.execute(
                create_inv,
                profile,
                ToolAuthorizationContext(
                    app_id="b54-padiem-claw",
                    agent_id="agent-7088",
                    granted_auth_scopes=(GMAIL_READONLY_AUTH_SCOPE,),
                    user_confirmed_tools=(GMAIL_CREATE_DRAFT_TOOL_ID,),
                ),
            )
        )
    assert scope_err.value.code == "tool_auth_scope_missing"
    assert port.post_calls == []

    # 2) gmail.compose 스코프가 있어도 사용자 확인(user_confirmed_tools) 없이는 Core ToolRuntime이 즉시 차단 (포트 호출 0)
    for inv in (create_inv, delete_inv):
        with pytest.raises(ToolRuntimeError) as confirm_err:
            asyncio.run(
                runtime.execute(
                    inv,
                    profile,
                    ToolAuthorizationContext(
                        app_id="b54-padiem-claw",
                        agent_id="agent-7088",
                        granted_auth_scopes=(GMAIL_COMPOSE_AUTH_SCOPE,),
                        user_confirmed_tools=(),
                    ),
                )
            )
        assert confirm_err.value.code == "tool_user_confirmation_required"
    assert port.post_calls == [] and port.delete_calls == []

    # 3) create_draft 확인만으로 delete_draft가 실행되지 않는다 (도구별 개별 확인)
    with pytest.raises(ToolRuntimeError) as cross_err:
        asyncio.run(
            runtime.execute(
                delete_inv,
                profile,
                ToolAuthorizationContext(
                    app_id="b54-padiem-claw",
                    agent_id="agent-7088",
                    granted_auth_scopes=(GMAIL_COMPOSE_AUTH_SCOPE,),
                    user_confirmed_tools=(GMAIL_CREATE_DRAFT_TOOL_ID,),
                ),
            )
        )
    assert cross_err.value.code == "tool_user_confirmation_required"
    assert port.delete_calls == []

    # 4) 검증된 사용자 확인 시에만 정확히 1회 초안 생성(/users/me/drafts) 및 초안 삭제(/users/me/drafts/{id}) 실행
    created = asyncio.run(
        runtime.execute(
            create_inv,
            profile,
            ToolAuthorizationContext(
                app_id="b54-padiem-claw",
                agent_id="agent-7088",
                granted_auth_scopes=(GMAIL_COMPOSE_AUTH_SCOPE,),
                user_confirmed_tools=(GMAIL_CREATE_DRAFT_TOOL_ID,),
            ),
        )
    )
    out_create = created.output_copy()
    assert out_create["operation"] == "drafts.create"
    assert out_create["draft_id"] == "draft_7088_1"
    assert out_create["sent"] is False
    assert len(port.post_calls) == 1
    assert port.post_calls[0]["base_url"] == GMAIL_BASE_URL
    assert port.post_calls[0]["path"] == "/users/me/drafts"
    assert port.post_calls[0]["required_scopes"] == (GMAIL_COMPOSE_SCOPE,)
    raw_b64 = port.post_calls[0]["json_body"]["message"]["raw"]
    parsed_mime = message_from_bytes(base64.urlsafe_b64decode(raw_b64 + "=" * (-len(raw_b64) % 4)))
    assert "recipient@example.com" in parsed_mime["To"]

    deleted = asyncio.run(
        runtime.execute(
            delete_inv,
            profile,
            ToolAuthorizationContext(
                app_id="b54-padiem-claw",
                agent_id="agent-7088",
                granted_auth_scopes=(GMAIL_COMPOSE_AUTH_SCOPE,),
                user_confirmed_tools=(GMAIL_DELETE_DRAFT_TOOL_ID,),
            ),
        )
    )
    out_delete = deleted.output_copy()
    assert out_delete["operation"] == "drafts.delete"
    assert out_delete["draft_id"] == "draft_7088_1"
    assert out_delete["deleted"] is True
    assert out_delete["sent"] is False
    assert len(port.delete_calls) == 1
    assert port.delete_calls[0]["path"] == "/users/me/drafts/draft_7088_1"
    assert port.delete_calls[0]["required_scopes"] == (GMAIL_COMPOSE_SCOPE,)

    # 5) 발송 도구는 등록조차 되어 있지 않아 ToolRuntime에서 tool_not_registered로 즉시 거부된다.
    with pytest.raises(ToolRuntimeError) as send_err:
        asyncio.run(
            runtime.execute(
                ToolInvocation(tool_id="gmail.send_message", arguments={}),
                _profile(*registered, "gmail.send_message"),
                ToolAuthorizationContext(
                    app_id="b54-padiem-claw",
                    agent_id="agent-7088",
                    granted_auth_scopes=(GMAIL_COMPOSE_AUTH_SCOPE,),
                    user_confirmed_tools=("gmail.send_message",),
                ),
            )
        )
    assert send_err.value.code == "tool_not_registered"
