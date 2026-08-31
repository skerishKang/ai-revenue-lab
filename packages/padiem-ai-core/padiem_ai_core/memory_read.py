"""Authorized memory-read bridge into the bounded Core retrieval seam.

`retrieval.py` intentionally requires explicit namespaces but does not decide
whether a caller is entitled to read them. This module supplies the missing
memory-specific trust boundary: trusted product/server authorization is checked
before canonical memory namespaces are projected into `RetrievalRequest`.

No database, vector store, embedding provider, or retrieval implementation is
owned here.
"""

from __future__ import annotations

from dataclasses import dataclass

from .memory import MemoryContractError, MemoryNamespace, MemoryScope
from .retrieval import (
    MAX_RETRIEVAL_NAMESPACES,
    MAX_RETRIEVAL_RESULTS,
    RetrievalRequest,
)


@dataclass(frozen=True, slots=True)
class MemoryReadAuthorization:
    """Trusted server-side set of readable memory namespaces."""

    app_id: str
    readable_namespaces: tuple[MemoryNamespace, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.app_id, str) or not self.app_id:
            raise MemoryContractError(
                "invalid_memory_read_authorization",
                "app_id must be a non-empty string",
            )
        if isinstance(self.readable_namespaces, (str, bytes)):
            raise MemoryContractError(
                "invalid_memory_read_authorization",
                "readable_namespaces must contain MemoryNamespace values",
            )
        namespaces = tuple(self.readable_namespaces)
        if not 1 <= len(namespaces) <= MAX_RETRIEVAL_NAMESPACES:
            raise MemoryContractError(
                "invalid_memory_read_authorization",
                f"readable_namespaces must contain 1 to {MAX_RETRIEVAL_NAMESPACES} items",
            )
        if any(not isinstance(namespace, MemoryNamespace) for namespace in namespaces):
            raise MemoryContractError(
                "invalid_memory_read_authorization",
                "readable_namespaces must contain MemoryNamespace values",
            )
        if any(namespace.app_id != self.app_id for namespace in namespaces):
            raise MemoryContractError(
                "memory_app_mismatch",
                "every readable namespace must belong to the authorized app",
            )
        keys = tuple(namespace.key for namespace in namespaces)
        if len(set(keys)) != len(keys):
            raise MemoryContractError(
                "invalid_memory_read_authorization",
                "readable_namespaces must not contain duplicates",
            )
        object.__setattr__(self, "readable_namespaces", namespaces)

    @property
    def readable_namespace_keys(self) -> frozenset[str]:
        return frozenset(namespace.key for namespace in self.readable_namespaces)


@dataclass(frozen=True, slots=True)
class MemoryReadPolicy:
    """Server-owned bounds that may narrow an existing read authorization."""

    allowed_scopes: tuple[MemoryScope, ...] = (
        MemoryScope.PRODUCT,
        MemoryScope.USER,
        MemoryScope.PROJECT,
        MemoryScope.CONVERSATION,
    )
    max_namespaces: int = MAX_RETRIEVAL_NAMESPACES
    max_results: int = MAX_RETRIEVAL_RESULTS

    def __post_init__(self) -> None:
        if not self.allowed_scopes or any(
            not isinstance(scope, MemoryScope) for scope in self.allowed_scopes
        ):
            raise MemoryContractError(
                "invalid_memory_read_policy",
                "allowed_scopes must contain MemoryScope values",
            )
        if len(set(self.allowed_scopes)) != len(self.allowed_scopes):
            raise MemoryContractError(
                "invalid_memory_read_policy",
                "allowed_scopes must not contain duplicates",
            )
        bounds = (
            ("max_namespaces", self.max_namespaces, MAX_RETRIEVAL_NAMESPACES),
            ("max_results", self.max_results, MAX_RETRIEVAL_RESULTS),
        )
        for name, value, high in bounds:
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 1 <= value <= high
            ):
                raise MemoryContractError(
                    "invalid_memory_read_policy",
                    f"{name} must be between 1 and {high}",
                )


def authorize_memory_retrieval(
    *,
    query: str,
    namespaces: tuple[MemoryNamespace, ...],
    authorization: MemoryReadAuthorization,
    max_results: int = 8,
    policy: MemoryReadPolicy | None = None,
) -> RetrievalRequest:
    """Build a `RetrievalRequest` only from independently authorized namespaces.

    The returned request remains subject to the existing retrieval result gates;
    this function only proves that the requested memory namespaces are readable
    by the trusted caller context. It never turns retrieved data into trusted
    system instructions.
    """

    if not isinstance(authorization, MemoryReadAuthorization):
        raise MemoryContractError(
            "invalid_memory_read_authorization",
            "authorization must be MemoryReadAuthorization",
        )
    active_policy = policy or MemoryReadPolicy()
    if not isinstance(active_policy, MemoryReadPolicy):
        raise MemoryContractError(
            "invalid_memory_read_policy",
            "policy must be MemoryReadPolicy",
        )
    if isinstance(namespaces, (str, bytes)):
        raise MemoryContractError(
            "invalid_memory_read_request",
            "namespaces must contain MemoryNamespace values",
        )
    requested = tuple(namespaces)
    if not 1 <= len(requested) <= active_policy.max_namespaces:
        raise MemoryContractError(
            "memory_read_budget_exceeded",
            "requested namespaces exceed the active memory read policy",
        )
    if any(not isinstance(namespace, MemoryNamespace) for namespace in requested):
        raise MemoryContractError(
            "invalid_memory_read_request",
            "namespaces must contain MemoryNamespace values",
        )
    keys = tuple(namespace.key for namespace in requested)
    if len(set(keys)) != len(keys):
        raise MemoryContractError(
            "invalid_memory_read_request",
            "requested namespaces must not contain duplicates",
        )
    if any(namespace.app_id != authorization.app_id for namespace in requested):
        raise MemoryContractError(
            "memory_app_mismatch",
            "requested memory namespace does not belong to the authorized app",
        )
    if any(namespace.scope not in active_policy.allowed_scopes for namespace in requested):
        raise MemoryContractError(
            "memory_scope_not_allowed",
            "requested memory scope is not allowed by the active read policy",
        )
    readable = authorization.readable_namespace_keys
    if any(key not in readable for key in keys):
        raise MemoryContractError(
            "memory_namespace_not_authorized",
            "requested memory namespace is not authorized for reading",
        )
    if (
        isinstance(max_results, bool)
        or not isinstance(max_results, int)
        or not 1 <= max_results <= active_policy.max_results
    ):
        raise MemoryContractError(
            "memory_read_budget_exceeded",
            "max_results exceeds the active memory read policy",
        )

    return RetrievalRequest(
        query=query,
        namespaces=keys,
        max_results=max_results,
    )
