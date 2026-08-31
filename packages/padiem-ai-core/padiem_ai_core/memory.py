"""Product-neutral memory namespace and fail-closed write policy for Padiem AI Core.

This module deliberately does not implement a database, vector store, embedding
provider, or product persistence layer. Products keep storage ownership and
supply a trusted adapter. Core only defines the bounded semantics required to
prevent a model or retrieval result from widening memory scope or silently
turning generated text into durable memory.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Protocol


MAX_MEMORY_CONTENT_CHARS = 12_000
MAX_MEMORY_SOURCE_REF_CHARS = 512
MAX_MEMORY_DERIVED_FROM = 16
MAX_MEMORY_AUTH_NAMESPACES = 32
MAX_MEMORY_APPROVED_PROPOSALS = 32

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHORT_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,47}$")


class MemoryContractError(ValueError):
    """Safe validation/policy failure at the Core memory boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        if not isinstance(code, str) or not _IDENTIFIER_RE.fullmatch(code):
            raise ValueError("memory error code must be a safe identifier")
        self.code = code
        self.safe_message = message


def _identifier(name: str, value: str, *, short: bool = False) -> str:
    pattern = _SHORT_IDENTIFIER_RE if short else _IDENTIFIER_RE
    if not isinstance(value, str) or not pattern.fullmatch(value):
        limit = 48 if short else 128
        raise MemoryContractError(
            "invalid_memory_contract",
            f"{name} must be a safe identifier of at most {limit} characters",
        )
    return value


def _bounded_text(name: str, value: str, *, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MemoryContractError(
            "invalid_memory_contract",
            f"{name} must be a non-empty string",
        )
    text = value.strip()
    if len(text) > limit:
        raise MemoryContractError(
            "memory_budget_exceeded",
            f"{name} exceeds the bounded memory limit",
        )
    return text


def _identifier_tuple(
    name: str,
    values: tuple[str, ...],
    *,
    max_items: int,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise MemoryContractError(
            "invalid_memory_contract",
            f"{name} must be a sequence of identifiers",
        )
    checked = tuple(_identifier(name, value) for value in values)
    if len(checked) > max_items:
        raise MemoryContractError(
            "memory_budget_exceeded",
            f"{name} exceeds the bounded item count",
        )
    if len(set(checked)) != len(checked):
        raise MemoryContractError(
            "invalid_memory_contract",
            f"{name} must not contain duplicates",
        )
    return checked


class MemoryScope(str, Enum):
    """A persistence scope inside one product/application authority."""

    PRODUCT = "product"
    USER = "user"
    PROJECT = "project"
    CONVERSATION = "conversation"


class MemoryWriteOrigin(str, Enum):
    """Trusted adapter classification of why a memory write exists."""

    USER_EXPLICIT = "user_explicit"
    PRODUCT_DERIVED = "product_derived"
    MODEL_PROPOSED = "model_proposed"
    IMPORTED = "imported"


@dataclass(frozen=True, slots=True)
class MemoryNamespace:
    """Canonical partition key for product-owned memory persistence.

    `app_id` always partitions a namespace by the owning/consuming product.
    Product-wide memory uses the app id itself as the subject so there is only
    one canonical product namespace rather than multiple aliases.
    """

    app_id: str
    scope: MemoryScope
    subject_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "app_id", _identifier("app_id", self.app_id, short=True))
        if not isinstance(self.scope, MemoryScope):
            raise MemoryContractError(
                "invalid_memory_contract",
                "scope must be MemoryScope",
            )
        object.__setattr__(
            self,
            "subject_id",
            _identifier("subject_id", self.subject_id, short=True),
        )
        if self.scope is MemoryScope.PRODUCT and self.subject_id != self.app_id:
            raise MemoryContractError(
                "invalid_memory_namespace",
                "product scope subject_id must equal app_id",
            )

    @property
    def key(self) -> str:
        """Stable retrieval/storage namespace identifier."""

        return f"memory:{self.scope.value}:{self.app_id}:{self.subject_id}"

    def to_public_dict(self) -> dict[str, str]:
        return {
            "app_id": self.app_id,
            "scope": self.scope.value,
            "namespace": self.key,
        }


@dataclass(frozen=True, slots=True)
class MemoryProvenance:
    """Bounded origin evidence for a durable memory candidate.

    `source_ref` stays adapter/internal-facing and is intentionally excluded
    from public projections because it may identify a private storage record.
    """

    source_type: str
    source_ref: str
    trace_id: str | None = None
    derived_from: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_type",
            _identifier("source_type", self.source_type),
        )
        object.__setattr__(
            self,
            "source_ref",
            _bounded_text(
                "source_ref",
                self.source_ref,
                limit=MAX_MEMORY_SOURCE_REF_CHARS,
            ),
        )
        if self.trace_id is not None:
            object.__setattr__(self, "trace_id", _identifier("trace_id", self.trace_id))
        object.__setattr__(
            self,
            "derived_from",
            _identifier_tuple(
                "derived_from",
                self.derived_from,
                max_items=MAX_MEMORY_DERIVED_FROM,
            ),
        )

    def to_public_dict(self) -> dict[str, object]:
        return {
            "source_type": self.source_type,
            "trace_id": self.trace_id,
            "derived_from_count": len(self.derived_from),
        }


@dataclass(frozen=True, slots=True)
class MemoryWriteRequest:
    """One bounded durable-memory candidate constructed by a trusted adapter."""

    memory_id: str
    namespace: MemoryNamespace
    content: str
    origin: MemoryWriteOrigin
    provenance: MemoryProvenance
    idempotency_key: str
    proposal_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "memory_id", _identifier("memory_id", self.memory_id))
        if not isinstance(self.namespace, MemoryNamespace):
            raise MemoryContractError(
                "invalid_memory_contract",
                "namespace must be MemoryNamespace",
            )
        object.__setattr__(
            self,
            "content",
            _bounded_text(
                "memory content",
                self.content,
                limit=MAX_MEMORY_CONTENT_CHARS,
            ),
        )
        if not isinstance(self.origin, MemoryWriteOrigin):
            raise MemoryContractError(
                "invalid_memory_contract",
                "origin must be MemoryWriteOrigin",
            )
        if not isinstance(self.provenance, MemoryProvenance):
            raise MemoryContractError(
                "invalid_memory_contract",
                "provenance must be MemoryProvenance",
            )
        object.__setattr__(
            self,
            "idempotency_key",
            _identifier("idempotency_key", self.idempotency_key),
        )
        if self.origin is MemoryWriteOrigin.MODEL_PROPOSED:
            if self.proposal_id is None:
                raise MemoryContractError(
                    "model_memory_requires_proposal_id",
                    "model-proposed memory requires an explicit proposal id",
                )
            object.__setattr__(
                self,
                "proposal_id",
                _identifier("proposal_id", self.proposal_id),
            )
        elif self.proposal_id is not None:
            raise MemoryContractError(
                "invalid_memory_contract",
                "proposal_id is only valid for model-proposed memory",
            )

    @property
    def idempotency_scope(self) -> str:
        """Adapter key for duplicate suppression inside one namespace."""

        return f"{self.namespace.key}:{self.idempotency_key}"


@dataclass(frozen=True, slots=True)
class MemoryWriteAuthorization:
    """Trusted server-side write grants, never model supplied."""

    app_id: str
    writable_namespaces: tuple[str, ...]
    approved_model_proposals: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "app_id", _identifier("app_id", self.app_id, short=True))
        namespaces = _identifier_tuple(
            "writable namespace",
            self.writable_namespaces,
            max_items=MAX_MEMORY_AUTH_NAMESPACES,
        )
        if not namespaces:
            raise MemoryContractError(
                "invalid_memory_authorization",
                "at least one writable namespace is required",
            )
        if any(not namespace.startswith("memory:") for namespace in namespaces):
            raise MemoryContractError(
                "invalid_memory_authorization",
                "writable namespaces must use canonical memory namespace keys",
            )
        object.__setattr__(self, "writable_namespaces", namespaces)
        object.__setattr__(
            self,
            "approved_model_proposals",
            _identifier_tuple(
                "approved model proposal",
                self.approved_model_proposals,
                max_items=MAX_MEMORY_APPROVED_PROPOSALS,
            ),
        )


@dataclass(frozen=True, slots=True)
class MemoryWritePolicy:
    """Server-owned bounds applied after authorization."""

    allowed_scopes: tuple[MemoryScope, ...] = (
        MemoryScope.PRODUCT,
        MemoryScope.USER,
        MemoryScope.PROJECT,
        MemoryScope.CONVERSATION,
    )
    allowed_origins: tuple[MemoryWriteOrigin, ...] = (
        MemoryWriteOrigin.USER_EXPLICIT,
        MemoryWriteOrigin.PRODUCT_DERIVED,
        MemoryWriteOrigin.MODEL_PROPOSED,
        MemoryWriteOrigin.IMPORTED,
    )
    max_content_chars: int = MAX_MEMORY_CONTENT_CHARS

    def __post_init__(self) -> None:
        if not self.allowed_scopes or any(
            not isinstance(scope, MemoryScope) for scope in self.allowed_scopes
        ):
            raise MemoryContractError(
                "invalid_memory_policy",
                "allowed_scopes must contain MemoryScope values",
            )
        if len(set(self.allowed_scopes)) != len(self.allowed_scopes):
            raise MemoryContractError(
                "invalid_memory_policy",
                "allowed_scopes must not contain duplicates",
            )
        if not self.allowed_origins or any(
            not isinstance(origin, MemoryWriteOrigin) for origin in self.allowed_origins
        ):
            raise MemoryContractError(
                "invalid_memory_policy",
                "allowed_origins must contain MemoryWriteOrigin values",
            )
        if len(set(self.allowed_origins)) != len(self.allowed_origins):
            raise MemoryContractError(
                "invalid_memory_policy",
                "allowed_origins must not contain duplicates",
            )
        if (
            isinstance(self.max_content_chars, bool)
            or not isinstance(self.max_content_chars, int)
            or not 1 <= self.max_content_chars <= MAX_MEMORY_CONTENT_CHARS
        ):
            raise MemoryContractError(
                "invalid_memory_policy",
                f"max_content_chars must be between 1 and {MAX_MEMORY_CONTENT_CHARS}",
            )


@dataclass(frozen=True, slots=True)
class PreparedMemoryWrite:
    """Authorized storage-adapter input with a safe public projection."""

    request: MemoryWriteRequest

    def __post_init__(self) -> None:
        if not isinstance(self.request, MemoryWriteRequest):
            raise MemoryContractError(
                "invalid_memory_contract",
                "request must be MemoryWriteRequest",
            )

    def to_public_dict(self) -> dict[str, object]:
        return {
            "memory_id": self.request.memory_id,
            "namespace": self.request.namespace.to_public_dict(),
            "origin": self.request.origin.value,
            "content_chars": len(self.request.content),
            "provenance": self.request.provenance.to_public_dict(),
        }


class MemoryWriteAdapter(Protocol):
    """Product/storage-owned persistence boundary; Core provides no backend."""

    async def write(self, request: PreparedMemoryWrite) -> None: ...


def authorize_memory_write(
    request: MemoryWriteRequest,
    authorization: MemoryWriteAuthorization,
    *,
    policy: MemoryWritePolicy | None = None,
) -> PreparedMemoryWrite:
    """Apply trusted namespace/policy gates before any persistence adapter call.

    A model-proposed candidate always needs an independently supplied proposal
    approval in `MemoryWriteAuthorization`. There is intentionally no policy
    switch that turns model proposals into automatic writes.
    """

    if not isinstance(request, MemoryWriteRequest):
        raise MemoryContractError(
            "invalid_memory_contract",
            "request must be MemoryWriteRequest",
        )
    if not isinstance(authorization, MemoryWriteAuthorization):
        raise MemoryContractError(
            "invalid_memory_authorization",
            "authorization must be MemoryWriteAuthorization",
        )
    active_policy = policy or MemoryWritePolicy()
    if not isinstance(active_policy, MemoryWritePolicy):
        raise MemoryContractError(
            "invalid_memory_policy",
            "policy must be MemoryWritePolicy",
        )

    if request.namespace.app_id != authorization.app_id:
        raise MemoryContractError(
            "memory_app_mismatch",
            "memory namespace does not belong to the authorized app",
        )
    if request.namespace.key not in authorization.writable_namespaces:
        raise MemoryContractError(
            "memory_namespace_not_authorized",
            "memory namespace is not authorized for writing",
        )
    if request.namespace.scope not in active_policy.allowed_scopes:
        raise MemoryContractError(
            "memory_scope_not_allowed",
            "memory scope is not allowed by the active write policy",
        )
    if request.origin not in active_policy.allowed_origins:
        raise MemoryContractError(
            "memory_origin_not_allowed",
            "memory origin is not allowed by the active write policy",
        )
    if len(request.content) > active_policy.max_content_chars:
        raise MemoryContractError(
            "memory_budget_exceeded",
            "memory content exceeds the active write policy",
        )

    if request.origin is MemoryWriteOrigin.MODEL_PROPOSED:
        assert request.proposal_id is not None
        if request.proposal_id not in authorization.approved_model_proposals:
            raise MemoryContractError(
                "model_memory_approval_required",
                "model-proposed memory requires independent trusted approval",
            )

    return PreparedMemoryWrite(request=request)
