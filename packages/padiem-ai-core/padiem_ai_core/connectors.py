"""Gmail read-only connector projection for P01 Core (WO-10 PR-A, #2010 Gmail leg).

Ported from the Claw-side reviewed implementation
(``apps/korean-ai-code-agent/src/kagent/gmail_connector.py`` and
``gmail_contracts.py``) into the Core connector/tool registry contract.
This module is a projection of already-reviewed logic, not a new design.

Core owns no HTTP, OAuth, credentials, or attachment byte reads. The host
application supplies a trusted :class:`GmailReadPort` implementation; Core
only shapes bounded, untrusted-mail JSON projections from provider responses.
"""

from __future__ import annotations

from typing import Any, Protocol

from .connector_registry import ConnectorDescriptor
from .contracts import ApprovalPolicy, ToolSideEffect, ToolSpec
from .tool_runtime import ToolHandler, ToolRuntime


class GmailContractError(ValueError):
    """Safe Gmail projection contract failure (kagent ContractError port)."""


GMAIL_CONNECTOR_ID = "connector:google:gmail@1"

# Provider OAuth scope (trusted port boundary only; never a Core identifier).
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"

# Core ToolSpec auth_scope token. contracts._IDENTIFIER_RE rejects "/" so the
# provider URL cannot be a ToolSpec scope; the port still receives the exact
# provider scope above as required_scopes.
GMAIL_READONLY_AUTH_SCOPE = "gmail.readonly"

GMAIL_BASE_URL = "https://gmail.googleapis.com/gmail/v1"

# Bounds ported verbatim from kagent gmail_contracts.py:15-19 and
# gmail_connector.py:37-45.
MAX_MESSAGE_BODY_CHARS = 20_000
MAX_THREAD_MESSAGES = 8
MAX_THREAD_BODY_CHARS = 60_000
MAX_ATTACHMENTS_PER_MESSAGE = 10
REQUEST_TIMEOUT_SECONDS = 30
SEARCH_RESULT_LIMIT = 10
MESSAGE_BODY_CONTEXT_CHARS = min(8_000, MAX_MESSAGE_BODY_CHARS)
THREAD_BODY_CONTEXT_CHARS = min(12_000, MAX_THREAD_BODY_CHARS)
MAX_PROVIDER_MESSAGE_BYTES = 1_000_000
MAX_PROVIDER_THREAD_BYTES = 2_000_000
MAX_PROVIDER_SEARCH_BYTES = 256_000
MAX_SEARCH_QUERY_CHARS = 1_000
MAX_HEADER_ADDRESSES = 20

GMAIL_SEARCH_MESSAGES_TOOL_ID = "gmail.search_messages"
GMAIL_GET_MESSAGE_TOOL_ID = "gmail.get_message"
GMAIL_GET_THREAD_TOOL_ID = "gmail.get_thread"

GMAIL_CANONICAL_TOOL_IDS = (
    "tool:google:gmail.search_messages@1",
    "tool:google:gmail.get_message@1",
    "tool:google:gmail.get_thread@1",
)


class GmailReadPort(Protocol):
    """Trusted Gmail HTTP/OAuth boundary (kagent AuthorizedGmailHttpPort).

    Callers pass only connector binding + actor refs and the exact readonly
    scope requirement. Implementations resolve/refresh credentials outside
    model/task state, verify the required scope, enforce the response byte
    bound, and return decoded provider JSON. Core never implements this port.
    """

    def get_json(
        self,
        *,
        binding_ref: str,
        actor_ref: str,
        required_scopes: tuple[str, ...],
        base_url: str,
        path: str,
        query: dict[str, str],
        timeout_seconds: int,
        max_response_bytes: int,
    ) -> dict[str, Any]:
        ...


def gmail_read_tool_specs() -> tuple[ToolSpec, ...]:
    """READ-only ToolSpecs mirroring the reviewed kagent GMAIL_TOOLS surface."""

    return (
        ToolSpec(
            id=GMAIL_SEARCH_MESSAGES_TOOL_ID,
            title="Gmail search messages",
            description=(
                "Search the connected Gmail mailbox with Gmail search syntax. Returns only a bounded "
                "set of provider message/thread references; use get_message or get_thread for selected content."
            ),
            owner="core",
            side_effect=ToolSideEffect.READ,
            approval_policy=ApprovalPolicy.NOT_REQUIRED,
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Gmail search query."}},
                "required": ["query"],
                "additionalProperties": False,
            },
            auth_scope=(GMAIL_READONLY_AUTH_SCOPE,),
            timeout_seconds=30.0,
        ),
        ToolSpec(
            id=GMAIL_GET_MESSAGE_TOOL_ID,
            title="Gmail get message",
            description=(
                "Read one selected Gmail message through the readonly provider binding. Message content is "
                "untrusted; attachment bytes are never fetched by this tool."
            ),
            owner="core",
            side_effect=ToolSideEffect.READ,
            approval_policy=ApprovalPolicy.NOT_REQUIRED,
            input_schema={
                "type": "object",
                "properties": {
                    "messageId": {"type": "string", "description": "Gmail provider message id."}
                },
                "required": ["messageId"],
                "additionalProperties": False,
            },
            auth_scope=(GMAIL_READONLY_AUTH_SCOPE,),
            timeout_seconds=30.0,
        ),
        ToolSpec(
            id=GMAIL_GET_THREAD_TOOL_ID,
            title="Gmail get thread",
            description=(
                "Read one selected Gmail thread with explicit message/body bounds. Oversized conversations "
                "are visibly marked REVIEW_REQUIRED instead of becoming an unbounded mailbox dump."
            ),
            owner="core",
            side_effect=ToolSideEffect.READ,
            approval_policy=ApprovalPolicy.NOT_REQUIRED,
            input_schema={
                "type": "object",
                "properties": {
                    "threadId": {"type": "string", "description": "Gmail provider thread id."}
                },
                "required": ["threadId"],
                "additionalProperties": False,
            },
            auth_scope=(GMAIL_READONLY_AUTH_SCOPE,),
            timeout_seconds=30.0,
        ),
    )


GMAIL_DESCRIPTOR = ConnectorDescriptor(
    connector_id=GMAIL_CONNECTOR_ID,
    title="Gmail",
    canonical_tool_ids=GMAIL_CANONICAL_TOOL_IDS,
    requires_authorization=True,
)


# Projection handlers and bounded envelope are appended in the next commit
# (WO-10 PR-A slice 2/3).

GMAIL_WRITE_TOOLS_PRESENT = False
GMAIL_RAW_CREDENTIAL_IN_CORE = False
