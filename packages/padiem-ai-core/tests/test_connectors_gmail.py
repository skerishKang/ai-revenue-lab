"""Gmail read-only connector contract tests for P01 Core (WO-10 PR-A, #2010 Gmail leg).

Behavioural cases are transplanted from the reviewed Claw-side suite
(``apps/korean-ai-code-agent/tests/test_gmail_connector.py``) with the original
test names kept in comments, plus Core-side registry/runtime conformance checks
for the ToolSpec/ConnectorDescriptor/ToolRuntime contract surface.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re

import pytest

from padiem_ai_core import AgentProfile
from padiem_ai_core.connector_registry import (
    ConnectorRegistrySnapshot,
    validate_connector_tools,
)
from padiem_ai_core.connectors import (
    GMAIL_BASE_URL,
    GMAIL_CANONICAL_TOOL_IDS,
    GMAIL_CONNECTOR_ID,
    GMAIL_DESCRIPTOR,
    GMAIL_GET_MESSAGE_TOOL_ID,
    GMAIL_GET_THREAD_TOOL_ID,
    GMAIL_RAW_CREDENTIAL_IN_CORE,
    GMAIL_READONLY_AUTH_SCOPE,
    GMAIL_READONLY_SCOPE,
    GMAIL_SEARCH_MESSAGES_TOOL_ID,
    GMAIL_WRITE_TOOLS_PRESENT,
    GmailContractError,
    MESSAGE_BODY_CONTEXT_CHARS,
    SEARCH_RESULT_LIMIT,
    _bounded_envelope,
    build_gmail_read_handlers,
    gmail_read_tool_specs,
    register_gmail_read_tools,
)
from padiem_ai_core.contracts import ApprovalPolicy, ToolSideEffect
from padiem_ai_core.tool_registry import RegisteredTool, ToolRegistrySnapshot
from padiem_ai_core.tool_runtime import (
    MAX_TOOL_OUTPUT_BYTES,
    ToolAuthorizationContext,
    ToolInvocation,
    ToolRuntime,
    ToolRuntimeError,
)

BINDING_REF = "binding_gmail_1"
ACTOR_REF = "actor_1"


def run(coro):
    return asyncio.run(coro)


def encoded(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def message(
    number: int = 1,
    *,
    thread_id: str = "thread_1",
    body: str = "hello",
    payload_parts: list[dict] | None = None,
) -> dict:
    # ported verbatim from kagent tests/test_gmail_connector.py::message
    payload: dict = {
        "mimeType": "text/plain" if payload_parts is None else "multipart/mixed",
        "filename": "",
        "headers": [
            {"name": "From", "value": "Sender <sender@example.com>"},
            {"name": "To", "value": "Recipient <recipient@example.com>"},
            {"name": "Subject", "value": f"Subject {number}"},
            {"name": "Date", "value": "Fri, 4 Sep 2026 08:00:00 +0000"},
        ],
        "body": {"data": encoded(body), "size": len(body.encode("utf-8"))},
    }
    if payload_parts is not None:
        payload["body"] = {"size": 0}
        payload["parts"] = payload_parts
    return {
        "id": f"msg_{number}",
        "threadId": thread_id,
        "labelIds": ["INBOX"],
        "historyId": str(100 + number),
        "internalDate": str(1788508800000 + number),
        "payload": payload,
    }


class FakeGmailPort:
    # ported from kagent FakeAuthorizedGmailHttp
    def __init__(self) -> None:
        self.responses: list[dict] = []
        self.calls: list[dict] = []

    def get_json(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def gmail_handlers(port: FakeGmailPort) -> dict:
    return build_gmail_read_handlers(port, binding_ref=BINDING_REF, actor_ref=ACTOR_REF)


def gmail_profile(*allowed_tools: str, agent_id: str = "agent-1") -> AgentProfile:
    return AgentProfile(
        id=agent_id,
        title="Agent",
        description="Gmail connector test agent",
        system_instruction="Use only allowed tools.",
        task_type="general",
        optimize_for="balanced",
        max_tokens=500,
        allowed_tools=tuple(allowed_tools),
    )


def gmail_auth(
    *,
    app_id: str = "padiem-chat",
    agent_id: str = "agent-1",
    scopes: tuple[str, ...] = (),
) -> ToolAuthorizationContext:
    return ToolAuthorizationContext(
        app_id=app_id,
        agent_id=agent_id,
        granted_auth_scopes=scopes,
        user_confirmed_tools=(),
        externally_authorized_tools=(),
    )


# --- Core contract surface ---


def test_specs_mirror_reviewed_kagent_readonly_surface() -> None:
    specs = gmail_read_tool_specs()
    assert tuple(spec.id for spec in specs) == (
        "gmail.search_messages",
        "gmail.get_message",
        "gmail.get_thread",
    )
    for spec in specs:
        assert spec.side_effect is ToolSideEffect.READ
        assert spec.approval_policy is ApprovalPolicy.NOT_REQUIRED
        assert spec.owner == "core"
        assert spec.auth_scope == (GMAIL_READONLY_AUTH_SCOPE,)
        assert spec.input_schema["additionalProperties"] is False
    handlers = gmail_handlers(FakeGmailPort())
    assert set(handlers) == {
        GMAIL_SEARCH_MESSAGES_TOOL_ID,
        GMAIL_GET_MESSAGE_TOOL_ID,
        GMAIL_GET_THREAD_TOOL_ID,
    }
    assert GMAIL_WRITE_TOOLS_PRESENT is False
    assert GMAIL_RAW_CREDENTIAL_IN_CORE is False


def test_canonical_tool_ids_conform_to_core_registries() -> None:
    specs = {spec.id: spec for spec in gmail_read_tool_specs()}
    canonical_by_runtime_id = dict(
        zip(
            (
                GMAIL_SEARCH_MESSAGES_TOOL_ID,
                GMAIL_GET_MESSAGE_TOOL_ID,
                GMAIL_GET_THREAD_TOOL_ID,
            ),
            GMAIL_CANONICAL_TOOL_IDS,
        )
    )
    entries = sorted(
        (
            RegisteredTool.from_spec(
                canonical_tool_id=canonical_by_runtime_id[spec_id],
                runtime_spec=spec,
            )
            for spec_id, spec in specs.items()
        ),
        key=lambda entry: entry.canonical_tool_id,
    )
    tool_registry = ToolRegistrySnapshot.from_entries(tuple(entries))
    assert GMAIL_CONNECTOR_ID == "connector:google:gmail@1"
    assert all(
        re.fullmatch(r"tool:[A-Za-z0-9][A-Za-z0-9._:@-]{0,160}", tool_id)
        for tool_id in GMAIL_CANONICAL_TOOL_IDS
    )
    assert validate_connector_tools(GMAIL_DESCRIPTOR, tool_registry) is GMAIL_DESCRIPTOR
    registry = ConnectorRegistrySnapshot.from_connectors((GMAIL_DESCRIPTOR,))
    assert registry.connectors == (GMAIL_DESCRIPTOR,)


# --- transplanted kagent behavioural cases ---


def test_search_is_bounded_readonly_and_never_follows_provider_page() -> None:
    # kagent: test_search_is_bounded_readonly_and_never_follows_provider_page
    port = FakeGmailPort()
    port.responses.append(
        {
            "messages": [
                {"id": f"msg_{index}", "threadId": f"thread_{index}"}
                for index in range(SEARCH_RESULT_LIMIT)
            ],
            "nextPageToken": "opaque_next_page",
        }
    )
    rendered = run(
        gmail_handlers(port)[GMAIL_SEARCH_MESSAGES_TOOL_ID](
            {"query": "newer_than:1d from:supplier@example.com"}
        )
    )
    assert rendered["result_status"] == "REVIEW_REQUIRED"
    assert rendered["result_count"] == SEARCH_RESULT_LIMIT
    assert rendered["more_results_available"] is True
    assert rendered["page_followed"] is False
    assert rendered["mail_content_trusted"] is False
    assert rendered["raw_credentials_present"] is False
    call = port.calls[0]
    assert call["base_url"] == GMAIL_BASE_URL
    assert call["path"] == "/users/me/messages"
    assert call["query"]["maxResults"] == str(SEARCH_RESULT_LIMIT)
    assert call["required_scopes"] == (GMAIL_READONLY_SCOPE,)
    assert "token" not in call
    assert "authorization" not in call


def test_empty_search_is_explicit_unknown() -> None:
    # kagent: test_empty_search_is_explicit_unknown
    port = FakeGmailPort()
    port.responses.append({})
    rendered = run(
        gmail_handlers(port)[GMAIL_SEARCH_MESSAGES_TOOL_ID]({"query": "missing"})
    )
    assert rendered["result_status"] == "UNKNOWN"
    assert rendered["messages"] == []


def test_selected_message_projects_headers_body_and_provenance() -> None:
    # kagent: test_selected_message_projects_headers_body_and_provenance
    # Core deviation: the envelope must not echo binding_ref back to the model.
    port = FakeGmailPort()
    port.responses.append(message())
    rendered = run(
        gmail_handlers(port)[GMAIL_GET_MESSAGE_TOOL_ID]({"messageId": "msg_1"})
    )
    projection = rendered["projection"]
    assert rendered["result_status"] == "OK"
    assert rendered["operation"] == "messages.get"
    assert "binding_ref" not in rendered
    assert projection["message_id"] == "msg_1"
    assert projection["thread_id"] == "thread_1"
    assert projection["from_address"] == "sender@example.com"
    assert projection["to_addresses"] == ["recipient@example.com"]
    assert projection["body_segments"][0]["text"] == "hello"
    assert projection["mail_content_trusted"] is False
    assert rendered["raw_attachment_bytes_present"] is False
    call = port.calls[0]
    assert call["query"] == {"format": "full"}
    assert call["path"].endswith("/messages/msg_1")


def test_multipart_alternative_prefers_plain_text_instead_of_duplication() -> None:
    # kagent: test_multipart_alternative_prefers_plain_text_instead_of_duplication
    port = FakeGmailPort()
    parts = [
        {
            "mimeType": "text/plain",
            "filename": "",
            "body": {"data": encoded("plain version"), "size": 13},
        },
        {
            "mimeType": "text/html",
            "filename": "",
            "body": {"data": encoded("<p>html version</p>"), "size": 19},
        },
    ]
    provider = message(payload_parts=[])
    provider["payload"]["mimeType"] = "multipart/alternative"
    provider["payload"]["parts"] = parts
    port.responses.append(provider)
    rendered = run(
        gmail_handlers(port)[GMAIL_GET_MESSAGE_TOOL_ID]({"messageId": "msg_1"})
    )
    segments = rendered["projection"]["body_segments"]
    assert len(segments) == 1
    assert segments[0]["text"] == "plain version"


def test_attachment_is_manifest_only_and_never_downloaded() -> None:
    # kagent: test_attachment_is_manifest_only_and_never_downloaded
    port = FakeGmailPort()
    parts = [
        {
            "mimeType": "text/plain",
            "filename": "",
            "body": {"data": encoded("invoice attached"), "size": 16},
        },
        {
            "mimeType": "application/pdf",
            "filename": "invoice.pdf",
            "body": {"attachmentId": "att_1", "size": 1024},
        },
    ]
    port.responses.append(message(payload_parts=parts))
    rendered = run(
        gmail_handlers(port)[GMAIL_GET_MESSAGE_TOOL_ID]({"messageId": "msg_1"})
    )
    attachment = rendered["projection"]["attachments"][0]
    assert attachment["attachment_ref"] == "att_1"
    assert attachment["quarantine_state"] == "pending"
    assert attachment["raw_bytes_present"] is False
    assert attachment["model_usable"] is False
    assert len(port.calls) == 1
    assert all("/attachments/" not in call["path"] for call in port.calls)


def test_inline_attachment_without_provider_ref_is_not_treated_as_message_text() -> None:
    # kagent: test_inline_attachment_without_provider_ref_is_not_treated_as_message_text
    port = FakeGmailPort()
    parts = [
        {
            "mimeType": "text/plain",
            "filename": "secret.txt",
            "body": {"data": encoded("attachment bytes"), "size": 16},
        }
    ]
    port.responses.append(message(payload_parts=parts))
    rendered = run(
        gmail_handlers(port)[GMAIL_GET_MESSAGE_TOOL_ID]({"messageId": "msg_1"})
    )
    assert rendered["result_status"] == "REVIEW_REQUIRED"
    assert rendered["attachment_manifest_truncated"] is True
    assert rendered["projection"]["body_segments"] == []


def test_oversized_message_body_is_visibly_review_required() -> None:
    # kagent: test_oversized_message_body_is_visibly_review_required
    port = FakeGmailPort()
    port.responses.append(message(body="x" * (MESSAGE_BODY_CONTEXT_CHARS + 500)))
    rendered = run(
        gmail_handlers(port)[GMAIL_GET_MESSAGE_TOOL_ID]({"messageId": "msg_1"})
    )
    assert rendered["result_status"] == "REVIEW_REQUIRED"
    assert rendered["body_truncated"] is True
    assert len(rendered["projection"]["body_segments"][0]["text"]) <= MESSAGE_BODY_CONTEXT_CHARS


def test_thread_uses_latest_bounded_messages_and_marks_omissions() -> None:
    # kagent: test_thread_uses_latest_bounded_messages_and_marks_omissions
    port = FakeGmailPort()
    provider_messages = [message(index, thread_id="thread_1") for index in range(1, 11)]
    port.responses.append({"id": "thread_1", "messages": provider_messages})
    rendered = run(
        gmail_handlers(port)[GMAIL_GET_THREAD_TOOL_ID]({"threadId": "thread_1"})
    )
    assert rendered["result_status"] == "REVIEW_REQUIRED"
    assert rendered["provider_message_count"] == 10
    assert rendered["projected_message_count"] == 8
    assert rendered["omitted_message_count"] == 2
    projected_ids = [item["message_id"] for item in rendered["projection"]["messages"]]
    assert projected_ids[0] == "msg_3"
    assert projected_ids[-1] == "msg_10"
    assert rendered["projection"]["bulk_mailbox_dump"] is False


def test_malformed_provider_message_fails_closed_as_review_required() -> None:
    # kagent: test_malformed_provider_message_fails_closed_as_review_required
    # Core deviation: the handler raises GmailContractError (ValueError); the
    # ToolRuntime converts handler exceptions into tool_execution_failed, so
    # the fail-closed status is enforced at runtime (see runtime test below).
    port = FakeGmailPort()
    broken = message()
    broken["payload"]["headers"] = []
    port.responses.append(broken)
    with pytest.raises(GmailContractError) as exc_info:
        run(gmail_handlers(port)[GMAIL_GET_MESSAGE_TOOL_ID]({"messageId": "msg_1"}))
    assert BINDING_REF not in str(exc_info.value)
    assert ACTOR_REF not in str(exc_info.value)


def test_unknown_tool_is_explicit_error() -> None:
    # kagent: test_unknown_tool_is_explicit_error (Core ToolRuntime variant)
    port = FakeGmailPort()
    runtime = ToolRuntime()
    register_gmail_read_tools(runtime, port, binding_ref=BINDING_REF, actor_ref=ACTOR_REF)
    invocation = ToolInvocation("gmail.send_message", {})
    with pytest.raises(ToolRuntimeError) as info:
        run(
            runtime.execute(
                invocation,
                gmail_profile("gmail.send_message"),
                gmail_auth(scopes=(GMAIL_READONLY_AUTH_SCOPE,)),
            )
        )
    assert info.value.code == "tool_not_registered"
    assert port.calls == []


# --- Core runtime authority/conformance cases ---


def test_runtime_blocks_without_granted_scope_and_passes_provider_scope_to_port() -> None:
    port = FakeGmailPort()
    runtime = ToolRuntime()
    registered = register_gmail_read_tools(
        runtime, port, binding_ref=BINDING_REF, actor_ref=ACTOR_REF
    )
    assert registered == (
        GMAIL_SEARCH_MESSAGES_TOOL_ID,
        GMAIL_GET_MESSAGE_TOOL_ID,
        GMAIL_GET_THREAD_TOOL_ID,
    )
    invocation = ToolInvocation(GMAIL_SEARCH_MESSAGES_TOOL_ID, {"query": "invoice"})
    agent = gmail_profile(GMAIL_SEARCH_MESSAGES_TOOL_ID)

    with pytest.raises(ToolRuntimeError) as info:
        run(runtime.execute(invocation, agent, gmail_auth()))
    assert info.value.code == "tool_auth_scope_missing"
    assert port.calls == []

    port.responses.append({"messages": [{"id": "msg_1", "threadId": "thread_1"}]})
    result = run(
        runtime.execute(
            invocation, agent, gmail_auth(scopes=(GMAIL_READONLY_AUTH_SCOPE,))
        )
    )
    output = result.output_copy()
    assert output["operation"] == "messages.list"
    assert len(port.calls) == 1
    assert port.calls[0]["required_scopes"] == (GMAIL_READONLY_SCOPE,)
    assert port.calls[0]["binding_ref"] == BINDING_REF
    assert port.calls[0]["actor_ref"] == ACTOR_REF


def test_runtime_wraps_malformed_provider_output_as_execution_failure() -> None:
    port = FakeGmailPort()
    runtime = ToolRuntime()
    register_gmail_read_tools(runtime, port, binding_ref=BINDING_REF, actor_ref=ACTOR_REF)
    broken = message()
    broken["payload"]["headers"] = []
    port.responses.append(broken)
    invocation = ToolInvocation(GMAIL_GET_MESSAGE_TOOL_ID, {"messageId": "msg_1"})
    agent = gmail_profile(GMAIL_GET_MESSAGE_TOOL_ID)
    with pytest.raises(ToolRuntimeError) as info:
        run(
            runtime.execute(
                invocation,
                agent,
                gmail_auth(scopes=(GMAIL_READONLY_AUTH_SCOPE,)),
            )
        )
    assert info.value.code == "tool_execution_failed"
    error_text = f"{info.value.code} {info.value}"
    assert BINDING_REF not in error_text
    assert ACTOR_REF not in error_text


def test_port_failure_is_wrapped_and_never_leaks_refs() -> None:
    class LeakyPort(FakeGmailPort):
        def get_json(self, **kwargs):
            self.calls.append(kwargs)
            raise RuntimeError(
                f"boom bind:SECRET123 actor:XYZ required={kwargs.get('required_scopes')}"
            )

    binding_ref = "bind:SECRET123"
    actor_ref = "actor:XYZ"
    handlers = build_gmail_read_handlers(
        LeakyPort(), binding_ref=binding_ref, actor_ref=actor_ref
    )
    for tool_id, arguments in (
        (GMAIL_SEARCH_MESSAGES_TOOL_ID, {"query": "report"}),
        (GMAIL_GET_MESSAGE_TOOL_ID, {"messageId": "msg_1"}),
        (GMAIL_GET_THREAD_TOOL_ID, {"threadId": "thread_1"}),
    ):
        with pytest.raises(GmailContractError) as exc_info:
            run(handlers[tool_id](arguments))
        text = str(exc_info.value)
        assert "SECRET123" not in text
        assert "actor:XYZ" not in text
        assert "bind:SECRET123" not in text
        assert exc_info.value.__cause__ is None
        assert exc_info.value.__context__ is None

    runtime = ToolRuntime()
    port = LeakyPort()
    port.responses.append({})
    register_gmail_read_tools(runtime, port, binding_ref=binding_ref, actor_ref=actor_ref)
    invocation = ToolInvocation(GMAIL_SEARCH_MESSAGES_TOOL_ID, {"query": "report"})
    agent = gmail_profile(GMAIL_SEARCH_MESSAGES_TOOL_ID)
    with pytest.raises(ToolRuntimeError) as info:
        run(
            runtime.execute(
                invocation,
                agent,
                gmail_auth(scopes=(GMAIL_READONLY_AUTH_SCOPE,)),
            )
        )
    assert info.value.code == "tool_execution_failed"
    runtime_text = f"{info.value.code} {info.value}"
    assert "SECRET123" not in runtime_text
    assert "actor:XYZ" not in runtime_text


def test_output_never_leaks_binding_or_actor_refs() -> None:
    port = FakeGmailPort()
    port.responses.append({"messages": [{"id": "msg_1", "threadId": "thread_1"}]})
    port.responses.append(message())
    port.responses.append({"id": "thread_1", "messages": [message()]})
    handlers = gmail_handlers(port)
    outputs = [
        run(handlers[GMAIL_SEARCH_MESSAGES_TOOL_ID]({"query": "report"})),
        run(handlers[GMAIL_GET_MESSAGE_TOOL_ID]({"messageId": "msg_1"})),
        run(handlers[GMAIL_GET_THREAD_TOOL_ID]({"threadId": "thread_1"})),
    ]
    for output in outputs:
        rendered = json.dumps(output, ensure_ascii=False, sort_keys=True)
        assert BINDING_REF not in rendered
        assert ACTOR_REF not in rendered
        assert len(rendered.encode("utf-8")) <= MAX_TOOL_OUTPUT_BYTES


def test_bounded_envelope_replaces_oversized_output_with_digest() -> None:
    oversized = {"operation": "messages.list", "blob": "y" * (MAX_TOOL_OUTPUT_BYTES + 10)}
    replacement = _bounded_envelope(oversized)
    assert replacement["result_status"] == "REVIEW_REQUIRED"
    assert replacement["truncated"] is True
    assert replacement["operation"] == "messages.list"
    assert re.fullmatch(r"[0-9a-f]{64}", replacement["result_sha256"])
    encoded_envelope = json.dumps(
        replacement, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    assert len(encoded_envelope) <= MAX_TOOL_OUTPUT_BYTES
