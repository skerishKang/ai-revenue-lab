from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any, Protocol

from .contracts import ContractError
from .security import redact_secrets

MAX_CONNECTOR_RESULT_CHARS = 20_000
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")
_SAFE_TOOL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-/]{0,255}$")


def _safe_ref(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    normalized = value.strip()
    if not _SAFE_REF_RE.fullmatch(normalized):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    if redact_secrets(normalized) != normalized:
        raise ContractError(f"{field_name} must not contain credential material")
    return normalized


def _safe_tool(value: str, field_name: str = "tool_name") -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    normalized = value.strip()
    if not _SAFE_TOOL_RE.fullmatch(normalized):
        raise ContractError(f"{field_name} must be a bounded tool name")
    return normalized


def _bounded_text(value: str, field_name: str, limit: int) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    normalized = value.strip()
    if len(normalized) > limit:
        raise ContractError(f"{field_name} exceeds {limit} characters")
    if redact_secrets(normalized) != normalized:
        normalized = redact_secrets(normalized)
    return normalized


class ConnectorAuthKind(str, Enum):
    NONE = "none"
    USER_OAUTH = "user_oauth"
    DEPLOYMENT_BEARER = "deployment_bearer"
    BUILTIN = "builtin"


class ConnectorEffect(str, Enum):
    READ = "read"
    WRITE = "write"


@dataclass(frozen=True, slots=True)
class ConnectorTool:
    name: str
    description: str
    input_schema: dict[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _safe_tool(self.name))
        object.__setattr__(self, "description", _bounded_text(self.description, "description", 4_000))
        if not isinstance(self.input_schema, dict):
            raise ContractError("input_schema must be an object")


@dataclass(frozen=True, slots=True)
class ConnectorCatalogueEntry:
    connector_id: str
    title: str
    vendor: str
    host: str | None
    path: str
    auth_kind: ConnectorAuthKind
    transport_kind: str
    read_tools: tuple[str, ...] = ()
    write_tools: tuple[str, ...] = ()
    first_party: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "connector_id", _safe_ref(self.connector_id, "connector_id"))
        object.__setattr__(self, "title", _bounded_text(self.title, "title", 160))
        object.__setattr__(self, "vendor", _bounded_text(self.vendor, "vendor", 160))
        if self.host is not None:
            host = self.host.strip()
            if not host.startswith("https://") and not host.startswith("builtin://"):
                raise ContractError("connector host must be pinned https or builtin")
            if len(host) > 512 or redact_secrets(host) != host:
                raise ContractError("connector host must be bounded and secret-free")
            object.__setattr__(self, "host", host.rstrip("/"))
        if not isinstance(self.path, str) or not self.path.startswith("/"):
            raise ContractError("connector path must be absolute")
        if not isinstance(self.auth_kind, ConnectorAuthKind):
            try:
                object.__setattr__(self, "auth_kind", ConnectorAuthKind(self.auth_kind))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid connector auth kind") from exc
        object.__setattr__(self, "transport_kind", _safe_ref(self.transport_kind, "transport_kind"))
        read_tools = tuple(_safe_tool(item) for item in self.read_tools)
        write_tools = tuple(_safe_tool(item) for item in self.write_tools)
        if len(read_tools) != len(set(read_tools)) or len(write_tools) != len(set(write_tools)):
            raise ContractError("connector tool classifications must be unique")
        if set(read_tools) & set(write_tools):
            raise ContractError("a connector tool cannot be classified as both read and write")
        object.__setattr__(self, "read_tools", read_tools)
        object.__setattr__(self, "write_tools", write_tools)
        if not isinstance(self.first_party, bool):
            raise ContractError("first_party must be boolean")

    def classify(self, tool_name: str) -> ConnectorEffect:
        """Fail closed: only explicitly reviewed reads are reads.

        This intentionally strengthens the upstream OpenBot catalogue behavior. A
        newly-advertised or custom connector tool must not become a read merely
        because its name was absent from a write list.
        """
        tool_name = _safe_tool(tool_name)
        if not self.first_party:
            return ConnectorEffect.WRITE
        if tool_name in self.read_tools:
            return ConnectorEffect.READ
        return ConnectorEffect.WRITE

    def safe_dict(self) -> dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "title": self.title,
            "vendor": self.vendor,
            "host": self.host,
            "path": self.path,
            "auth_kind": self.auth_kind.value,
            "transport_kind": self.transport_kind,
            "read_tools": list(self.read_tools),
            "write_tools": list(self.write_tools),
            "first_party": self.first_party,
            "credential_fields": False,
        }


@dataclass(frozen=True, slots=True)
class ConnectorConnection:
    binding_ref: str
    actor_ref: str
    connector_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_ref", _safe_ref(self.binding_ref, "binding_ref"))
        object.__setattr__(self, "actor_ref", _safe_ref(self.actor_ref, "actor_ref"))
        object.__setattr__(self, "connector_id", _safe_ref(self.connector_id, "connector_id"))

    def safe_dict(self) -> dict[str, str | bool]:
        return {
            "binding_ref": self.binding_ref,
            "actor_ref": self.actor_ref,
            "connector_id": self.connector_id,
            "raw_access_token": False,
            "raw_refresh_token": False,
            "raw_api_key": False,
        }


@dataclass(frozen=True, slots=True)
class ConnectorCallResult:
    text: str
    is_error: bool = False
    truncated: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise ContractError("connector result text must be a string")
        if len(self.text) > MAX_CONNECTOR_RESULT_CHARS + 256:
            raise ContractError("connector result exceeds bounded result envelope")
        if not isinstance(self.is_error, bool) or not isinstance(self.truncated, bool):
            raise ContractError("connector result flags must be boolean")


def bounded_connector_result(text: str, *, is_error: bool = False) -> ConnectorCallResult:
    if not isinstance(text, str):
        raise ContractError("connector result text must be a string")
    normalized = redact_secrets(text)
    if normalized.strip() == "":
        normalized = "The connector returned no content. Nothing was found, so there is nothing here to answer from."
    if len(normalized) <= MAX_CONNECTOR_RESULT_CHARS:
        return ConnectorCallResult(text=normalized, is_error=is_error, truncated=False)
    return ConnectorCallResult(
        text=f"{normalized[:MAX_CONNECTOR_RESULT_CHARS]}\n\n[truncated: connector returned {len(normalized)} characters]",
        is_error=is_error,
        truncated=True,
    )


class ConnectorTransport(Protocol):
    list_needs_credential: bool

    def list_tools(self, connection: ConnectorConnection) -> tuple[ConnectorTool, ...]:
        ...

    def call_tool(
        self,
        connection: ConnectorConnection,
        tool_name: str,
        args: dict[str, Any],
    ) -> ConnectorCallResult:
        ...


@dataclass(frozen=True, slots=True)
class ConnectorGrant:
    agent_ref: str
    tool_ref: str
    granted_by_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "agent_ref", _safe_ref(self.agent_ref, "agent_ref"))
        object.__setattr__(self, "tool_ref", _safe_ref(self.tool_ref, "tool_ref"))
        object.__setattr__(self, "granted_by_ref", _safe_ref(self.granted_by_ref, "granted_by_ref"))


@dataclass(frozen=True, slots=True)
class ConnectorSkill:
    slug: str
    title: str
    instructions: str
    tool_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "slug", _safe_ref(self.slug, "slug"))
        object.__setattr__(self, "title", _bounded_text(self.title, "title", 160))
        object.__setattr__(self, "instructions", _bounded_text(self.instructions, "instructions", 12_000))
        refs = tuple(_safe_ref(item, "tool_ref") for item in self.tool_refs)
        if len(refs) != len(set(refs)):
            raise ContractError("skill tool refs must be unique")
        object.__setattr__(self, "tool_refs", refs)


@dataclass(frozen=True, slots=True)
class ConnectorPolicyDecision:
    allowed: bool
    rule_ref: str
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.allowed, bool):
            raise ContractError("policy decision allowed must be boolean")
        object.__setattr__(self, "rule_ref", _safe_ref(self.rule_ref, "rule_ref"))
        object.__setattr__(self, "reason", _bounded_text(self.reason, "reason", 1_000))


class ConnectorPolicyPort(Protocol):
    def evaluate(
        self,
        *,
        agent_ref: str,
        actor_ref: str,
        connector_id: str,
        tool_name: str,
        effect: ConnectorEffect,
        args: dict[str, Any],
    ) -> ConnectorPolicyDecision:
        ...


class DenyAllConnectorPolicy:
    def evaluate(self, **_: Any) -> ConnectorPolicyDecision:
        return ConnectorPolicyDecision(
            allowed=False,
            rule_ref="connector.default.deny",
            reason="Connector calls require an explicit trusted policy decision.",
        )


class AllowReadsConnectorPolicy:
    """Deterministic test policy; not a Production policy authority."""

    def evaluate(self, *, effect: ConnectorEffect, **_: Any) -> ConnectorPolicyDecision:
        if effect is ConnectorEffect.READ:
            return ConnectorPolicyDecision(True, "test.read.allow", "Reviewed read allowed for deterministic test.")
        return ConnectorPolicyDecision(False, "test.write.deny", "Write/material connector actions remain approval-gated.")


class DeterministicFakeConnectorTransport:
    list_needs_credential = False

    def __init__(self, tools: tuple[ConnectorTool, ...], replies: dict[str, str] | None = None) -> None:
        self._tools = tuple(tools)
        self._replies = dict(replies or {})
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def list_tools(self, connection: ConnectorConnection) -> tuple[ConnectorTool, ...]:
        if not isinstance(connection, ConnectorConnection):
            raise ContractError("connection must be ConnectorConnection")
        return self._tools

    def call_tool(
        self,
        connection: ConnectorConnection,
        tool_name: str,
        args: dict[str, Any],
    ) -> ConnectorCallResult:
        if not isinstance(connection, ConnectorConnection):
            raise ContractError("connection must be ConnectorConnection")
        tool_name = _safe_tool(tool_name)
        if not isinstance(args, dict):
            raise ContractError("connector args must be an object")
        self.calls.append((connection.connector_id, tool_name, dict(args)))
        return bounded_connector_result(self._replies.get(tool_name, f"fake:{tool_name}"))


class ConnectorRuntime:
    """B54 physical connector dispatcher.

    Grants and policy are separate checks. P01 remains the authority that issues
    or validates material approvals; this class does not create approvals.
    """

    def __init__(
        self,
        *,
        catalogue: dict[str, ConnectorCatalogueEntry],
        transports: dict[str, ConnectorTransport],
        policy: ConnectorPolicyPort,
        grants: tuple[ConnectorGrant, ...] = (),
        skills: tuple[ConnectorSkill, ...] = (),
    ) -> None:
        self._catalogue = dict(catalogue)
        self._transports = dict(transports)
        self._policy = policy
        self._grants = tuple(grants)
        self._skills = {skill.slug: skill for skill in skills}
        for connector_id, entry in self._catalogue.items():
            if connector_id != entry.connector_id:
                raise ContractError("catalogue key must match connector_id")
            if entry.transport_kind not in self._transports:
                raise ContractError("catalogue entry references an unconfigured transport")

    def granted_refs(self, agent_ref: str) -> set[str]:
        agent_ref = _safe_ref(agent_ref, "agent_ref")
        return {grant.tool_ref for grant in self._grants if grant.agent_ref == agent_ref}

    def offered_refs(self, agent_ref: str, selected_skill_slugs: tuple[str, ...] = ()) -> set[str]:
        granted = self.granted_refs(agent_ref)
        if not selected_skill_slugs:
            return granted
        selected: set[str] = set()
        claimed_by_any_skill = {ref for skill in self._skills.values() for ref in skill.tool_refs}
        for slug in selected_skill_slugs:
            slug = _safe_ref(slug, "skill_slug")
            try:
                skill = self._skills[slug]
            except KeyError as exc:
                raise ContractError("unknown connector skill") from exc
            selected.update(ref for ref in skill.tool_refs if ref in granted)
        selected.update(ref for ref in granted if ref not in claimed_by_any_skill)
        return selected

    def call(
        self,
        *,
        connection: ConnectorConnection,
        agent_ref: str,
        tool_name: str,
        args: dict[str, Any],
    ) -> ConnectorCallResult:
        if not isinstance(connection, ConnectorConnection):
            raise ContractError("connection must be ConnectorConnection")
        agent_ref = _safe_ref(agent_ref, "agent_ref")
        tool_name = _safe_tool(tool_name)
        if not isinstance(args, dict):
            raise ContractError("connector args must be an object")
        try:
            entry = self._catalogue[connection.connector_id]
        except KeyError as exc:
            raise ContractError("connector is not in the reviewed catalogue") from exc
        tool_ref = f"{entry.connector_id}/{tool_name}"
        if tool_ref not in self.granted_refs(agent_ref):
            raise ContractError("connector tool is not granted to this agent")
        effect = entry.classify(tool_name)
        decision = self._policy.evaluate(
            agent_ref=agent_ref,
            actor_ref=connection.actor_ref,
            connector_id=entry.connector_id,
            tool_name=tool_name,
            effect=effect,
            args=dict(args),
        )
        if not isinstance(decision, ConnectorPolicyDecision):
            raise ContractError("connector policy returned an invalid decision")
        if not decision.allowed:
            raise ContractError(f"connector policy refused call: {decision.rule_ref}")
        transport = self._transports[entry.transport_kind]
        return transport.call_tool(connection, tool_name, dict(args))


GOOGLE_DRIVE_ENTRY = ConnectorCatalogueEntry(
    connector_id="google-drive",
    title="Google Drive",
    vendor="Google",
    host="https://www.googleapis.com",
    path="/drive/v3",
    auth_kind=ConnectorAuthKind.USER_OAUTH,
    transport_kind="google-drive-rest",
    read_tools=(
        "search_files",
        "list_recent_files",
        "get_file_metadata",
        "read_file_content",
    ),
    write_tools=("create_file", "copy_file"),
)

NOTION_ENTRY = ConnectorCatalogueEntry(
    connector_id="notion",
    title="Notion",
    vendor="Notion",
    host="https://mcp.notion.com",
    path="/mcp",
    auth_kind=ConnectorAuthKind.USER_OAUTH,
    transport_kind="mcp",
    # Deliberately no implicit read list. Until a live tool list is reconciled
    # against a reviewed classification, unknown Notion tools remain material.
    read_tools=(),
    write_tools=(
        "notion-create-attachment",
        "notion-create-comment",
        "notion-create-database",
        "notion-create-file-upload",
        "notion-create-folder",
        "notion-create-pages",
        "notion-create-view",
        "notion-duplicate-page",
        "notion-move-pages",
        "notion-update-data-source",
        "notion-update-folder",
        "notion-update-page",
        "notion-update-view",
    ),
)

OPENBOT_REUSE_CATALOGUE = {
    GOOGLE_DRIVE_ENTRY.connector_id: GOOGLE_DRIVE_ENTRY,
    NOTION_ENTRY.connector_id: NOTION_ENTRY,
}
