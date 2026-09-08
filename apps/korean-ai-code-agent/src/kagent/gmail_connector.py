from __future__ import annotations

import base64
import binascii
import hashlib
import json
from email.header import decode_header, make_header
from email.utils import getaddresses, parseaddr
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.parse import quote

from .connector_platform import (
    MAX_CONNECTOR_RESULT_CHARS,
    ConnectorAuthKind,
    ConnectorCallResult,
    ConnectorCatalogueEntry,
    ConnectorConnection,
    ConnectorTool,
    bounded_connector_result,
)
from .contracts import ContractError
from .gmail_contracts import (
    GMAIL_READONLY_SCOPE,
    MAX_ATTACHMENTS_PER_MESSAGE,
    MAX_MESSAGE_BODY_CHARS,
    MAX_THREAD_BODY_CHARS,
    MAX_THREAD_MESSAGES,
    AttachmentQuarantineState,
    GmailAttachmentManifest,
    GmailBodyKind,
    GmailBodySegment,
    GmailMessageProjection,
    GmailThreadProjection,
)

REQUEST_TIMEOUT_SECONDS = 30
SEARCH_RESULT_LIMIT = 10
MESSAGE_BODY_CONTEXT_CHARS = min(8_000, MAX_MESSAGE_BODY_CHARS)
THREAD_BODY_CONTEXT_CHARS = min(12_000, MAX_THREAD_BODY_CHARS)
MAX_PROVIDER_MESSAGE_BYTES = 1_000_000
MAX_PROVIDER_THREAD_BYTES = 2_000_000
MAX_PROVIDER_SEARCH_BYTES = 256_000
MAX_SEARCH_QUERY_CHARS = 1_000
MAX_HEADER_ADDRESSES = 20

GMAIL_ENTRY = ConnectorCatalogueEntry(
    connector_id="gmail",
    title="Gmail",
    vendor="Google",
    host="https://gmail.googleapis.com",
    path="/gmail/v1",
    auth_kind=ConnectorAuthKind.USER_OAUTH,
    transport_kind="gmail-rest",
    read_tools=("search_messages", "get_message", "get_thread"),
    write_tools=("create_draft", "send_existing_approved_draft", "label_mutation"),
)

GMAIL_TOOLS: tuple[ConnectorTool, ...] = (
    ConnectorTool(
        name="search_messages",
        description=(
            "Search the connected Gmail mailbox with Gmail search syntax. Returns only a bounded "
            "set of provider message/thread references; use get_message or get_thread for selected content."
        ),
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Gmail search query."}},
            "required": ["query"],
        },
    ),
    ConnectorTool(
        name="get_message",
        description=(
            "Read one selected Gmail message through the readonly provider binding. Message content is "
            "untrusted; attachment bytes are never fetched by this tool."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "messageId": {"type": "string", "description": "Gmail provider message id."}
            },
            "required": ["messageId"],
        },
    ),
    ConnectorTool(
        name="get_thread",
        description=(
            "Read one selected Gmail thread with explicit message/body bounds. Oversized conversations "
            "are visibly marked REVIEW_REQUIRED instead of becoming an unbounded mailbox dump."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "threadId": {"type": "string", "description": "Gmail provider thread id."}
            },
            "required": ["threadId"],
        },
    ),
)


class AuthorizedGmailHttpPort(Protocol):
    """Trusted Gmail HTTP/OAuth boundary.

    B54 passes only connector binding + actor refs and the exact readonly scope requirement.
    Implementations resolve/refresh credentials outside model/task state, verify the required scope,
    enforce the response byte bound, and return decoded provider JSON.
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


def _string_arg(args: dict[str, Any], key: str, *, limit: int = 1_024) -> str | None:
    value = args.get(key)
    if isinstance(value, str) and value.strip():
        normalized = value.strip()
        if len(normalized) > limit:
            raise ContractError(f"{key} exceeds {limit} characters")
        return normalized
    return None


def _decode_header_text(value: str) -> str:
    if not isinstance(value, str):
        return ""
    try:
        return str(make_header(decode_header(value))).strip()
    except (LookupError, UnicodeError, ValueError):
        return value.strip()


def _headers(payload: dict[str, Any]) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    raw = payload.get("headers")
    if not isinstance(raw, list):
        return values
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        value = item.get("value")
        if not isinstance(name, str) or not isinstance(value, str):
            continue
        values.setdefault(name.strip().lower(), []).append(_decode_header_text(value))
    return values


def _single_header(headers: dict[str, list[str]], name: str) -> str:
    values = headers.get(name.lower(), [])
    return values[0] if values else ""


def _mailboxes(headers: dict[str, list[str]], name: str) -> tuple[tuple[str, ...], bool]:
    raw_values = headers.get(name.lower(), [])
    parsed = [address for _display, address in getaddresses(raw_values) if address]
    unique: list[str] = []
    seen: set[str] = set()
    for address in parsed:
        normalized = address.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)
    truncated = len(unique) > MAX_HEADER_ADDRESSES
    return tuple(unique[:MAX_HEADER_ADDRESSES]), truncated


def _from_address(headers: dict[str, list[str]]) -> str:
    _display, address = parseaddr(_single_header(headers, "from"))
    return address.strip()


def _decode_base64url(data: str) -> str:
    if not isinstance(data, str) or not data:
        return ""
    try:
        raw = data.encode("ascii")
        raw += b"=" * (-len(raw) % 4)
        decoded = base64.urlsafe_b64decode(raw)
    except (binascii.Error, UnicodeEncodeError, ValueError) as exc:
        raise ContractError("Gmail message body contains invalid base64url data") from exc
    return decoded.decode("utf-8", errors="replace")


class _HtmlTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        if data:
            self._chunks.append(data)

    def text(self) -> str:
        return " ".join(chunk.strip() for chunk in self._chunks if chunk.strip())


def _html_to_text(value: str) -> str:
    parser = _HtmlTextExtractor()
    try:
        parser.feed(value)
        parser.close()
    except Exception as exc:
        raise ContractError("Gmail HTML body could not be safely projected") from exc
    return parser.text()


def _is_attachment_part(part: dict[str, Any]) -> bool:
    filename = part.get("filename")
    body = part.get("body")
    attachment_id = body.get("attachmentId") if isinstance(body, dict) else None
    return bool(isinstance(filename, str) and filename) or bool(
        isinstance(attachment_id, str) and attachment_id
    )


def _attachment_manifest(part: dict[str, Any], message_id: str) -> GmailAttachmentManifest | None:
    if not _is_attachment_part(part):
        return None
    body = part.get("body") if isinstance(part.get("body"), dict) else {}
    attachment_id = body.get("attachmentId")
    filename = part.get("filename")
    mime_type = part.get("mimeType")
    size = body.get("size", 0)
    if not isinstance(attachment_id, str) or not attachment_id.strip():
        return None
    if not isinstance(filename, str) or not filename.strip():
        filename = "(unnamed attachment)"
    if not isinstance(mime_type, str) or not mime_type.strip():
        mime_type = "application/octet-stream"
    if isinstance(size, bool) or not isinstance(size, int):
        raise ContractError("Gmail attachment size must be an integer")
    return GmailAttachmentManifest(
        attachment_ref=attachment_id.strip(),
        message_id=message_id,
        filename=filename,
        mime_type=mime_type,
        size_bytes=size,
        quarantine_state=AttachmentQuarantineState.PENDING,
    )


def _prefer_alternative(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for preferred in ("text/plain", "text/html"):
        for part in parts:
            if part.get("mimeType") == preferred and not _is_attachment_part(part):
                return [part]
    return parts


def _walk_payload(
    part: dict[str, Any],
    *,
    message_id: str,
    remaining_chars: int,
    attachments: list[GmailAttachmentManifest],
) -> tuple[list[GmailBodySegment], int, bool, bool]:
    """Return segments, chars-used, body-truncated, attachment-manifest-truncated."""
    if remaining_chars <= 0:
        return [], 0, True, False

    if _is_attachment_part(part):
        attachment = _attachment_manifest(part, message_id)
        if attachment is None:
            return [], 0, False, True
        if len(attachments) >= MAX_ATTACHMENTS_PER_MESSAGE:
            return [], 0, False, True
        attachments.append(attachment)
        return [], 0, False, False

    mime = part.get("mimeType") if isinstance(part.get("mimeType"), str) else ""
    raw_parts = part.get("parts")
    if isinstance(raw_parts, list) and raw_parts:
        child_parts = [child for child in raw_parts if isinstance(child, dict)]
        if mime.lower() == "multipart/alternative":
            child_parts = _prefer_alternative(child_parts)
        segments: list[GmailBodySegment] = []
        used = 0
        body_truncated = False
        attachment_truncated = False
        for index, child in enumerate(child_parts):
            child_segments, child_used, child_body_truncated, child_attachment_truncated = _walk_payload(
                child,
                message_id=message_id,
                remaining_chars=max(0, remaining_chars - used),
                attachments=attachments,
            )
            segments.extend(child_segments)
            used += child_used
            body_truncated = body_truncated or child_body_truncated
            attachment_truncated = attachment_truncated or child_attachment_truncated
            if used >= remaining_chars:
                body_truncated = body_truncated or any(
                    isinstance(item, dict) for item in child_parts[index + 1 :]
                )
                break
        return segments, used, body_truncated, attachment_truncated

    if mime.lower() not in {"text/plain", "text/html"}:
        return [], 0, False, False
    body = part.get("body")
    data = body.get("data") if isinstance(body, dict) else None
    text = _decode_base64url(data) if isinstance(data, str) else ""
    if mime.lower() == "text/html" and text:
        text = _html_to_text(text)
    if not text:
        return [], 0, False, False
    truncated = len(text) > remaining_chars
    bounded = text[:remaining_chars]
    kind = GmailBodyKind.PLAIN if mime.lower() == "text/plain" else GmailBodyKind.HTML_TEXT
    return [GmailBodySegment(kind=kind, text=bounded)], len(bounded), truncated, False


def _project_message(
    provider_message: dict[str, Any],
    *,
    body_char_limit: int,
) -> tuple[GmailMessageProjection, dict[str, bool]]:
    message_id = provider_message.get("id")
    thread_id = provider_message.get("threadId")
    payload = provider_message.get("payload")
    if not isinstance(message_id, str) or not message_id.strip():
        raise ContractError("Gmail provider message is missing id")
    if not isinstance(thread_id, str) or not thread_id.strip():
        raise ContractError("Gmail provider message is missing threadId")
    if not isinstance(payload, dict):
        raise ContractError("Gmail provider message is missing payload")

    header_map = _headers(payload)
    to_addresses, to_truncated = _mailboxes(header_map, "to")
    cc_addresses, cc_truncated = _mailboxes(header_map, "cc")
    bcc_addresses, bcc_truncated = _mailboxes(header_map, "bcc")
    attachments: list[GmailAttachmentManifest] = []
    segments, _used, body_truncated, attachment_truncated = _walk_payload(
        payload,
        message_id=message_id.strip(),
        remaining_chars=max(0, body_char_limit),
        attachments=attachments,
    )
    label_ids_raw = provider_message.get("labelIds", [])
    if label_ids_raw is None:
        label_ids_raw = []
    if not isinstance(label_ids_raw, list) or any(not isinstance(item, str) for item in label_ids_raw):
        raise ContractError("Gmail labelIds must be a string list")

    projection = GmailMessageProjection(
        message_id=message_id.strip(),
        thread_id=thread_id.strip(),
        from_address=_from_address(header_map),
        to_addresses=to_addresses,
        cc_addresses=cc_addresses,
        bcc_addresses=bcc_addresses,
        subject=_single_header(header_map, "subject"),
        date_header=_single_header(header_map, "date"),
        body_segments=tuple(segments),
        label_ids=tuple(label_ids_raw),
        attachments=tuple(attachments),
        internal_date_ref=(
            str(provider_message["internalDate"]).strip()
            if provider_message.get("internalDate") is not None
            else None
        ),
        history_id=(
            str(provider_message["historyId"]).strip()
            if provider_message.get("historyId") is not None
            else None
        ),
    )
    return projection, {
        "body_truncated": body_truncated,
        "attachment_manifest_truncated": attachment_truncated,
        "address_headers_truncated": to_truncated or cc_truncated or bcc_truncated,
    }


def _json_connector_result(envelope: dict[str, Any], *, is_error: bool = False) -> ConnectorCallResult:
    text = json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(text) <= MAX_CONNECTOR_RESULT_CHARS:
        return bounded_connector_result(text, is_error=is_error)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    compact = {
        "provider": "gmail",
        "operation": envelope.get("operation"),
        "binding_ref": envelope.get("binding_ref"),
        "result_status": "REVIEW_REQUIRED",
        "reason": "bounded Gmail projection exceeded the connector result envelope",
        "result_sha256": digest,
        "raw_credentials_present": False,
        "mail_content_trusted": False,
    }
    return bounded_connector_result(
        json.dumps(compact, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        is_error=is_error,
    )


class GmailReadTransport:
    """Readonly Gmail REST transport for B54 Business MVP."""

    list_needs_credential = False
    base_url = "https://gmail.googleapis.com/gmail/v1"
    required_scopes = (GMAIL_READONLY_SCOPE,)

    def __init__(self, http: AuthorizedGmailHttpPort) -> None:
        self._http = http

    def list_tools(self, connection: ConnectorConnection) -> tuple[ConnectorTool, ...]:
        if not isinstance(connection, ConnectorConnection):
            raise ContractError("connection must be ConnectorConnection")
        if connection.connector_id != "gmail":
            raise ContractError("Gmail transport requires gmail connection")
        return GMAIL_TOOLS

    def _json(
        self,
        connection: ConnectorConnection,
        path: str,
        query: dict[str, str],
        *,
        max_response_bytes: int,
    ) -> dict[str, Any]:
        return self._http.get_json(
            binding_ref=connection.binding_ref,
            actor_ref=connection.actor_ref,
            required_scopes=self.required_scopes,
            base_url=self.base_url,
            path=path,
            query=dict(query),
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            max_response_bytes=max_response_bytes,
        )

    def call_tool(
        self,
        connection: ConnectorConnection,
        tool_name: str,
        args: dict[str, Any],
    ) -> ConnectorCallResult:
        if not isinstance(connection, ConnectorConnection):
            raise ContractError("connection must be ConnectorConnection")
        if connection.connector_id != "gmail":
            raise ContractError("Gmail transport requires gmail connection")
        if not isinstance(args, dict):
            raise ContractError("Gmail args must be an object")

        try:
            if tool_name == "search_messages":
                query = _string_arg(args, "query", limit=MAX_SEARCH_QUERY_CHARS)
                if not query:
                    return bounded_connector_result("A Gmail search needs a query.", is_error=True)
                body = self._json(
                    connection,
                    "/users/me/messages",
                    {"q": query, "maxResults": str(SEARCH_RESULT_LIMIT)},
                    max_response_bytes=MAX_PROVIDER_SEARCH_BYTES,
                )
                messages = body.get("messages", [])
                if messages is None:
                    messages = []
                if not isinstance(messages, list):
                    return bounded_connector_result("Gmail returned an invalid message list.", is_error=True)
                refs: list[dict[str, str]] = []
                for item in messages[:SEARCH_RESULT_LIMIT]:
                    if not isinstance(item, dict):
                        continue
                    message_id = item.get("id")
                    thread_id = item.get("threadId")
                    if isinstance(message_id, str) and isinstance(thread_id, str):
                        refs.append({"message_id": message_id, "thread_id": thread_id})
                more = isinstance(body.get("nextPageToken"), str) and bool(body.get("nextPageToken"))
                status = "UNKNOWN" if not refs else ("REVIEW_REQUIRED" if more else "OK")
                return _json_connector_result(
                    {
                        "provider": "gmail",
                        "operation": "messages.list",
                        "binding_ref": connection.binding_ref,
                        "query": query,
                        "result_status": status,
                        "messages": refs,
                        "result_count": len(refs),
                        "more_results_available": more,
                        "page_followed": False,
                        "mail_content_trusted": False,
                        "raw_credentials_present": False,
                    }
                )

            if tool_name == "get_message":
                message_id = _string_arg(args, "messageId")
                if not message_id:
                    return bounded_connector_result("A Gmail message id is needed.", is_error=True)
                body = self._json(
                    connection,
                    f"/users/me/messages/{quote(message_id, safe='')}",
                    {"format": "full"},
                    max_response_bytes=MAX_PROVIDER_MESSAGE_BYTES,
                )
                projection, flags = _project_message(body, body_char_limit=MESSAGE_BODY_CONTEXT_CHARS)
                review_required = any(flags.values())
                return _json_connector_result(
                    {
                        "provider": "gmail",
                        "operation": "messages.get",
                        "binding_ref": connection.binding_ref,
                        "result_status": "REVIEW_REQUIRED" if review_required else "OK",
                        "projection": projection.safe_dict(),
                        **flags,
                        "raw_attachment_bytes_present": False,
                        "raw_credentials_present": False,
                    }
                )

            if tool_name == "get_thread":
                thread_id = _string_arg(args, "threadId")
                if not thread_id:
                    return bounded_connector_result("A Gmail thread id is needed.", is_error=True)
                body = self._json(
                    connection,
                    f"/users/me/threads/{quote(thread_id, safe='')}",
                    {"format": "full"},
                    max_response_bytes=MAX_PROVIDER_THREAD_BYTES,
                )
                provider_messages = body.get("messages", [])
                if not isinstance(provider_messages, list) or not provider_messages:
                    return _json_connector_result(
                        {
                            "provider": "gmail",
                            "operation": "threads.get",
                            "binding_ref": connection.binding_ref,
                            "thread_id": thread_id,
                            "result_status": "UNKNOWN",
                            "reason": "provider returned no thread messages",
                            "mail_content_trusted": False,
                            "raw_credentials_present": False,
                        }
                    )
                valid_messages = [item for item in provider_messages if isinstance(item, dict)]
                omitted = max(0, len(valid_messages) - MAX_THREAD_MESSAGES)
                selected = valid_messages[-MAX_THREAD_MESSAGES:]
                remaining = THREAD_BODY_CONTEXT_CHARS
                projections: list[GmailMessageProjection] = []
                body_truncated = False
                attachment_truncated = False
                address_truncated = False
                for item in selected:
                    projection, flags = _project_message(
                        item,
                        body_char_limit=min(MESSAGE_BODY_CONTEXT_CHARS, remaining),
                    )
                    projections.append(projection)
                    used = sum(len(segment.text) for segment in projection.body_segments)
                    remaining = max(0, remaining - used)
                    body_truncated = body_truncated or flags["body_truncated"]
                    attachment_truncated = attachment_truncated or flags[
                        "attachment_manifest_truncated"
                    ]
                    address_truncated = address_truncated or flags["address_headers_truncated"]
                thread = GmailThreadProjection(thread_id=thread_id, messages=tuple(projections))
                review_required = bool(
                    omitted or body_truncated or attachment_truncated or address_truncated
                )
                return _json_connector_result(
                    {
                        "provider": "gmail",
                        "operation": "threads.get",
                        "binding_ref": connection.binding_ref,
                        "result_status": "REVIEW_REQUIRED" if review_required else "OK",
                        "projection": thread.safe_dict(),
                        "provider_message_count": len(valid_messages),
                        "projected_message_count": len(projections),
                        "omitted_message_count": omitted,
                        "body_truncated": body_truncated,
                        "attachment_manifest_truncated": attachment_truncated,
                        "address_headers_truncated": address_truncated,
                        "raw_attachment_bytes_present": False,
                        "raw_credentials_present": False,
                    }
                )
        except ContractError as exc:
            return _json_connector_result(
                {
                    "provider": "gmail",
                    "operation": tool_name,
                    "binding_ref": connection.binding_ref,
                    "result_status": "REVIEW_REQUIRED",
                    "reason": str(exc),
                    "mail_content_trusted": False,
                    "raw_credentials_present": False,
                },
                is_error=True,
            )

        return bounded_connector_result(
            f"{tool_name} is not a tool this connector implements. The reviewed tool list is out of date.",
            is_error=True,
        )


REAL_GMAIL_CONNECTOR_CONFIGURED = False
GMAIL_READ_TRANSPORT_WRITE_SUPPORTED = False
GMAIL_RAW_CREDENTIAL_IN_B54 = False
