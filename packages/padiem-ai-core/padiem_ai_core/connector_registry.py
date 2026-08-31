"""Product-neutral Connector registry and opaque authorization references.

P01 owns only the reusable runtime primitive here. B49/B50 keep their
specialized connector specification/governance product boundaries. This module
therefore does not model source schemas, licences, transformation rules, OAuth
flows, tokens, refresh credentials, or private-data governance workflows.

A Connector may expose canonical Tool identities. Actual Tool execution still
passes through ToolRegistry/ToolRuntime, and an opaque authorization reference
never becomes a Tool permission grant by itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Iterable

from .tool_registry import ToolRegistrySnapshot


_CONNECTOR_ID_RE = re.compile(
    r"^connector:[a-z0-9][a-z0-9._-]{0,63}:[a-z0-9][a-z0-9._-]{0,63}@[1-9][0-9]*$"
)
_TOOL_ID_RE = re.compile(
    r"^tool:[a-z0-9][a-z0-9._-]{0,63}:[a-z0-9][a-z0-9._-]{0,63}@[1-9][0-9]*$"
)
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,255}$")
MAX_CONNECTOR_TOOLS = 128
MAX_REGISTERED_CONNECTORS = 512


class ConnectorRegistryError(ValueError):
    """Safe connector registry/auth-reference contract failure."""

    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or not _SAFE_ID_RE.fullmatch(code):
            raise ValueError("connector error code must be a safe identifier")
        self.code = code
        self.safe_message = safe_message


def _canonical_connector_id(value: str) -> str:
    if not isinstance(value, str) or not _CONNECTOR_ID_RE.fullmatch(value):
        raise ConnectorRegistryError(
            "invalid_connector_contract",
            "connector_id must match connector:<owner>:<id>@<major>",
        )
    return value


def _canonical_tool_ids(values: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise ConnectorRegistryError(
            "invalid_connector_contract",
            "canonical_tool_ids must be a tuple",
        )
    if not 1 <= len(values) <= MAX_CONNECTOR_TOOLS:
        raise ConnectorRegistryError(
            "connector_budget_exceeded",
            f"canonical_tool_ids must contain 1 to {MAX_CONNECTOR_TOOLS} items",
        )
    if len(set(values)) != len(values):
        raise ConnectorRegistryError(
            "invalid_connector_contract",
            "canonical_tool_ids must not contain duplicates",
        )
    if any(not isinstance(value, str) or not _TOOL_ID_RE.fullmatch(value) for value in values):
        raise ConnectorRegistryError(
            "invalid_connector_contract",
            "canonical_tool_ids contains an invalid versioned Tool id",
        )
    return values


def _safe_id(name: str, value: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise ConnectorRegistryError(
            "invalid_connector_contract",
            f"{name} must be a bounded safe identifier",
        )
    return value


def _safe_ref(value: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value):
        raise ConnectorRegistryError(
            "invalid_connector_authorization",
            "authorization_ref must be a bounded opaque reference",
        )
    return value


@dataclass(frozen=True, slots=True)
class ConnectorDescriptor:
    """Minimal runtime-facing Connector identity, not a B49/B50 source spec."""

    connector_id: str
    title: str
    canonical_tool_ids: tuple[str, ...]
    requires_authorization: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "connector_id",
            _canonical_connector_id(self.connector_id),
        )
        if not isinstance(self.title, str) or not self.title.strip():
            raise ConnectorRegistryError(
                "invalid_connector_contract",
                "title must be a non-empty string",
            )
        title = self.title.strip()
        if len(title) > 160:
            raise ConnectorRegistryError(
                "invalid_connector_contract",
                "title exceeds 160 characters",
            )
        object.__setattr__(self, "title", title)
        object.__setattr__(
            self,
            "canonical_tool_ids",
            _canonical_tool_ids(self.canonical_tool_ids),
        )
        if not isinstance(self.requires_authorization, bool):
            raise ConnectorRegistryError(
                "invalid_connector_contract",
                "requires_authorization must be boolean",
            )

    def to_public_dict(self) -> dict[str, object]:
        return {
            "connector_id": self.connector_id,
            "title": self.title,
            "canonical_tool_ids": list(self.canonical_tool_ids),
            "requires_authorization": self.requires_authorization,
        }


@dataclass(frozen=True, slots=True)
class ConnectorRegistrySnapshot:
    connectors: tuple[ConnectorDescriptor, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.connectors, tuple):
            raise ConnectorRegistryError(
                "invalid_connector_contract",
                "connectors must be a tuple",
            )
        if len(self.connectors) > MAX_REGISTERED_CONNECTORS:
            raise ConnectorRegistryError(
                "connector_budget_exceeded",
                "connector registry exceeds the bounded connector count",
            )
        if any(not isinstance(item, ConnectorDescriptor) for item in self.connectors):
            raise ConnectorRegistryError(
                "invalid_connector_contract",
                "connectors must contain ConnectorDescriptor values",
            )
        ids = tuple(item.connector_id for item in self.connectors)
        if len(set(ids)) != len(ids):
            raise ConnectorRegistryError(
                "duplicate_connector_id",
                "connector registry contains duplicate canonical ids",
            )
        if ids != tuple(sorted(ids)):
            raise ConnectorRegistryError(
                "invalid_connector_contract",
                "connectors must be sorted by canonical id",
            )

    @classmethod
    def from_connectors(
        cls,
        connectors: Iterable[ConnectorDescriptor],
    ) -> "ConnectorRegistrySnapshot":
        if isinstance(connectors, (str, bytes)):
            raise ConnectorRegistryError(
                "invalid_connector_contract",
                "connectors must be an iterable of ConnectorDescriptor values",
            )
        values = tuple(connectors)
        if any(not isinstance(item, ConnectorDescriptor) for item in values):
            raise ConnectorRegistryError(
                "invalid_connector_contract",
                "connectors must contain ConnectorDescriptor values",
            )
        return cls(connectors=tuple(sorted(values, key=lambda item: item.connector_id)))

    def get(self, connector_id: str) -> ConnectorDescriptor:
        target = _canonical_connector_id(connector_id)
        for descriptor in self.connectors:
            if descriptor.connector_id == target:
                return descriptor
        raise ConnectorRegistryError(
            "connector_not_registered",
            "requested Connector is not present in the registry",
        )


def validate_connector_tools(
    descriptor: ConnectorDescriptor,
    tool_registry: ToolRegistrySnapshot,
) -> ConnectorDescriptor:
    """Require every Connector Tool reference to resolve in the Tool registry."""

    if not isinstance(descriptor, ConnectorDescriptor):
        raise ConnectorRegistryError(
            "invalid_connector_contract",
            "descriptor must be ConnectorDescriptor",
        )
    if not isinstance(tool_registry, ToolRegistrySnapshot):
        raise ConnectorRegistryError(
            "invalid_connector_contract",
            "tool_registry must be ToolRegistrySnapshot",
        )
    for canonical_tool_id in descriptor.canonical_tool_ids:
        try:
            tool_registry.get(canonical_tool_id)
        except Exception as exc:
            raise ConnectorRegistryError(
                "connector_tool_not_registered",
                "Connector references a canonical Tool absent from the Tool registry",
            ) from exc
    return descriptor


class ConnectorAuthorizationStatus(str, Enum):
    AUTHORIZED = "authorized"
    REVOKED = "revoked"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ConnectorAuthorizationReference:
    """Opaque trusted reference to external connector authorization state.

    `authorization_ref` is server-only and never included in public projection.
    It points at whichever product/control-plane/private connector system owns
    credentials; P01 Core does not receive the credential value itself.
    """

    connector_id: str
    app_id: str
    subject_id: str
    authorization_ref: str
    status: ConnectorAuthorizationStatus

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "connector_id",
            _canonical_connector_id(self.connector_id),
        )
        object.__setattr__(self, "app_id", _safe_id("app_id", self.app_id))
        object.__setattr__(self, "subject_id", _safe_id("subject_id", self.subject_id))
        object.__setattr__(self, "authorization_ref", _safe_ref(self.authorization_ref))
        if not isinstance(self.status, ConnectorAuthorizationStatus):
            raise ConnectorRegistryError(
                "invalid_connector_authorization",
                "status must be ConnectorAuthorizationStatus",
            )

    def to_public_dict(self) -> dict[str, str]:
        return {
            "connector_id": self.connector_id,
            "app_id": self.app_id,
            "subject_id": self.subject_id,
            "status": self.status.value,
        }


@dataclass(frozen=True, slots=True)
class ConnectorAccess:
    """Resolved availability evidence, still not a Tool authorization grant."""

    connector_id: str
    app_id: str
    subject_id: str
    authorization_ref: str | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "connector_id",
            _canonical_connector_id(self.connector_id),
        )
        object.__setattr__(self, "app_id", _safe_id("app_id", self.app_id))
        object.__setattr__(self, "subject_id", _safe_id("subject_id", self.subject_id))
        if self.authorization_ref is not None:
            object.__setattr__(self, "authorization_ref", _safe_ref(self.authorization_ref))

    def to_public_dict(self) -> dict[str, str]:
        return {
            "connector_id": self.connector_id,
            "app_id": self.app_id,
            "subject_id": self.subject_id,
        }


def resolve_connector_access(
    *,
    descriptor: ConnectorDescriptor,
    app_id: str,
    subject_id: str,
    authorization: ConnectorAuthorizationReference | None = None,
) -> ConnectorAccess:
    """Resolve Connector availability without minting ToolRuntime authority."""

    if not isinstance(descriptor, ConnectorDescriptor):
        raise ConnectorRegistryError(
            "invalid_connector_contract",
            "descriptor must be ConnectorDescriptor",
        )
    checked_app_id = _safe_id("app_id", app_id)
    checked_subject_id = _safe_id("subject_id", subject_id)

    if not descriptor.requires_authorization:
        if authorization is not None:
            if not isinstance(authorization, ConnectorAuthorizationReference):
                raise ConnectorRegistryError(
                    "invalid_connector_authorization",
                    "authorization must be ConnectorAuthorizationReference or None",
                )
            if (
                authorization.connector_id != descriptor.connector_id
                or authorization.app_id != checked_app_id
                or authorization.subject_id != checked_subject_id
            ):
                raise ConnectorRegistryError(
                    "connector_authorization_mismatch",
                    "Connector authorization does not match requested connector context",
                )
        return ConnectorAccess(
            connector_id=descriptor.connector_id,
            app_id=checked_app_id,
            subject_id=checked_subject_id,
            authorization_ref=None,
        )

    if not isinstance(authorization, ConnectorAuthorizationReference):
        raise ConnectorRegistryError(
            "connector_authorization_required",
            "Connector requires an opaque trusted authorization reference",
        )
    if (
        authorization.connector_id != descriptor.connector_id
        or authorization.app_id != checked_app_id
        or authorization.subject_id != checked_subject_id
    ):
        raise ConnectorRegistryError(
            "connector_authorization_mismatch",
            "Connector authorization does not match requested connector context",
        )
    if authorization.status is not ConnectorAuthorizationStatus.AUTHORIZED:
        raise ConnectorRegistryError(
            "connector_not_authorized",
            "Connector authorization is revoked or unavailable",
        )
    return ConnectorAccess(
        connector_id=descriptor.connector_id,
        app_id=checked_app_id,
        subject_id=checked_subject_id,
        authorization_ref=authorization.authorization_ref,
    )
