from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Protocol

from .connector_platform import (
    ConnectorCallResult,
    ConnectorCatalogueEntry,
    ConnectorConnection,
    ConnectorTool,
    bounded_connector_result,
)
from .contracts import ContractError

MAX_MCP_TOOLS = 128
REQUEST_TIMEOUT_SECONDS = 30
_TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-/]{0,255}$")


def _safe_tool_name(value: str) -> str:
    if not isinstance(value, str):
        raise ContractError("tool_name must be a string")
    normalized = value.strip()
    if not _TOOL_NAME_RE.fullmatch(normalized):
        raise ContractError("tool_name must be a bounded safe tool name")
    return normalized


@dataclass(frozen=True, slots=True)
class TrustedMcpCallResponse:
    text: str
    is_error: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise ContractError("trusted MCP call text must be a string")
        if not isinstance(self.is_error, bool):
            raise ContractError("trusted MCP call is_error must be boolean")


class TrustedMcpAuthority(Protocol):
    """Credential-resolving MCP boundary owned outside B54.

    The implementation is responsible for resolving/refreshing the credential
    identified by binding_ref + actor_ref. B54 never passes or receives raw
    access tokens, refresh tokens, client secrets, API keys or cookies.
    """

    def list_tools(
        self,
        *,
        binding_ref: str,
        actor_ref: str,
        connector_id: str,
        endpoint: str,
        timeout_seconds: int,
    ) -> tuple[dict[str, Any], ...]:
        ...

    def call_tool(
        self,
        *,
        binding_ref: str,
        actor_ref: str,
        connector_id: str,
        endpoint: str,
        tool_name: str,
        args: dict[str, Any],
        timeout_seconds: int,
    ) -> TrustedMcpCallResponse:
        ...


class TrustedMcpTransport:
    list_needs_credential = True

    def __init__(
        self,
        *,
        catalogue: dict[str, ConnectorCatalogueEntry],
        authority: TrustedMcpAuthority,
    ) -> None:
        self._catalogue = dict(catalogue)
        self._authority = authority
        for connector_id, entry in self._catalogue.items():
            if connector_id != entry.connector_id:
                raise ContractError("MCP catalogue key must match connector_id")

    def _entry(self, connection: ConnectorConnection) -> ConnectorCatalogueEntry:
        if not isinstance(connection, ConnectorConnection):
            raise ContractError("connection must be ConnectorConnection")
        try:
            entry = self._catalogue[connection.connector_id]
        except KeyError as exc:
            raise ContractError("connector is not configured for trusted MCP transport") from exc
        if entry.transport_kind != "mcp":
            raise ContractError("connector is not configured for MCP transport")
        if entry.host is None:
            raise ContractError("MCP source contract requires a pinned host")
        if not entry.host.startswith("https://"):
            raise ContractError("MCP source contract requires pinned https host")
        return entry

    @staticmethod
    def _endpoint(entry: ConnectorCatalogueEntry) -> str:
        path = "" if entry.path == "/" else entry.path
        return f"{entry.host}{path}"

    def list_tools(self, connection: ConnectorConnection) -> tuple[ConnectorTool, ...]:
        entry = self._entry(connection)
        records = self._authority.list_tools(
            binding_ref=connection.binding_ref,
            actor_ref=connection.actor_ref,
            connector_id=entry.connector_id,
            endpoint=self._endpoint(entry),
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
        )
        if not isinstance(records, tuple):
            raise ContractError("trusted MCP authority must return a tuple of tool records")
        if len(records) > MAX_MCP_TOOLS:
            raise ContractError("trusted MCP tool list exceeds bounded maximum")
        tools: list[ConnectorTool] = []
        seen: set[str] = set()
        for record in records:
            if not isinstance(record, dict):
                raise ContractError("trusted MCP tool record must be an object")
            name = record.get("name")
            description = record.get("description", "")
            input_schema = record.get("inputSchema", record.get("input_schema", {"type": "object"}))
            if not isinstance(name, str):
                raise ContractError("trusted MCP tool record is missing name")
            name = _safe_tool_name(name)
            if name in seen:
                raise ContractError("trusted MCP tool list contains duplicate names")
            seen.add(name)
            if not isinstance(description, str):
                raise ContractError("trusted MCP tool description must be a string")
            if not isinstance(input_schema, dict):
                raise ContractError("trusted MCP tool input schema must be an object")
            tools.append(ConnectorTool(name=name, description=description, input_schema=input_schema))
        return tuple(tools)

    def call_tool(
        self,
        connection: ConnectorConnection,
        tool_name: str,
        args: dict[str, Any],
    ) -> ConnectorCallResult:
        entry = self._entry(connection)
        tool_name = _safe_tool_name(tool_name)
        if not isinstance(args, dict):
            raise ContractError("MCP args must be an object")
        response = self._authority.call_tool(
            binding_ref=connection.binding_ref,
            actor_ref=connection.actor_ref,
            connector_id=entry.connector_id,
            endpoint=self._endpoint(entry),
            tool_name=tool_name,
            args=dict(args),
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
        )
        if not isinstance(response, TrustedMcpCallResponse):
            raise ContractError("trusted MCP authority returned an invalid call response")
        return bounded_connector_result(response.text, is_error=response.is_error)


class DeterministicTrustedMcpAuthority:
    """Network-free fake for repository conformance only."""

    def __init__(
        self,
        *,
        tools: tuple[dict[str, Any], ...] = (),
        replies: dict[str, TrustedMcpCallResponse] | None = None,
    ) -> None:
        self._tools = tuple(dict(item) for item in tools)
        self._replies = dict(replies or {})
        self.list_calls: list[dict[str, Any]] = []
        self.tool_calls: list[dict[str, Any]] = []

    def list_tools(self, **kwargs: Any) -> tuple[dict[str, Any], ...]:
        self.list_calls.append(dict(kwargs))
        return self._tools

    def call_tool(self, *, tool_name: str, args: dict[str, Any], **kwargs: Any) -> TrustedMcpCallResponse:
        call = dict(kwargs)
        call["tool_name"] = tool_name
        call["args"] = dict(args)
        self.tool_calls.append(call)
        return self._replies.get(tool_name, TrustedMcpCallResponse(text=f"fake:{tool_name}"))


REAL_TRUSTED_MCP_AUTHORITY_CONFIGURED = False
RAW_MCP_ACCESS_TOKEN_IN_B54 = False
RAW_MCP_REFRESH_TOKEN_IN_B54 = False
RAW_MCP_CLIENT_SECRET_IN_B54 = False
