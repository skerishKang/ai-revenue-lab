"""Provider-neutral bounded retrieval seam for Padiem AI Core.

This module does not implement a vector database, memory store, web search, or
model execution. It defines the narrow contract between an external retrieval
provider and Core context preparation.

Security invariant: retrieved content is always untrusted reference data. A
retrieval provider cannot promote project files, memories, saved outputs, or
RAG chunks into trusted system context.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import json
import re
from typing import Protocol

from .context_policy import (
    ContextFragment,
    ContextPolicy,
    ContextPolicyError,
    ContextTrust,
    PreparedContext,
    prepare_context,
)


MAX_RETRIEVAL_QUERY_CHARS = 2_000
MAX_RETRIEVAL_NAMESPACES = 8
MAX_RETRIEVAL_RESULTS = 12
MAX_PROVIDER_RETRIEVAL_ITEMS = 48
MAX_RETRIEVAL_ITEM_CHARS = 6_000
MAX_RETRIEVAL_TOTAL_CONTENT_CHARS = 12_000
MAX_RETRIEVAL_TITLE_CHARS = 256

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class RetrievalContractError(ValueError):
    """Safe validation failure at the Core retrieval boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        if not isinstance(code, str) or not _IDENTIFIER_RE.fullmatch(code):
            raise ValueError("retrieval error code must be a safe identifier")
        self.code = code
        self.safe_message = message


def _identifier(name: str, value: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise RetrievalContractError(
            "invalid_retrieval_contract",
            f"{name} must be a bounded safe identifier",
        )
    return value


def _bounded_text(name: str, value: str, *, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RetrievalContractError(
            "invalid_retrieval_contract",
            f"{name} must be a non-empty string",
        )
    text = value.strip()
    if len(text) > limit:
        raise RetrievalContractError(
            "retrieval_budget_exceeded",
            f"{name} exceeds the bounded retrieval limit",
        )
    return text


@dataclass(frozen=True, slots=True)
class RetrievalRequest:
    """Explicit, bounded request sent to a product-owned retrieval provider.

    Namespaces are mandatory so Core never implies a global/private-data search.
    Their semantics remain provider-owned; Core only enforces the exact allowed
    namespace set on returned items.
    """

    query: str
    namespaces: tuple[str, ...]
    max_results: int = 8

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "query",
            _bounded_text(
                "retrieval query",
                self.query,
                limit=MAX_RETRIEVAL_QUERY_CHARS,
            ),
        )
        if isinstance(self.namespaces, (str, bytes)):
            raise RetrievalContractError(
                "invalid_retrieval_contract",
                "namespaces must be a sequence of identifiers",
            )
        namespaces = tuple(
            _identifier("retrieval namespace", value) for value in self.namespaces
        )
        if not 1 <= len(namespaces) <= MAX_RETRIEVAL_NAMESPACES:
            raise RetrievalContractError(
                "invalid_retrieval_contract",
                f"namespaces must contain 1 to {MAX_RETRIEVAL_NAMESPACES} items",
            )
        if len(set(namespaces)) != len(namespaces):
            raise RetrievalContractError(
                "invalid_retrieval_contract",
                "namespaces must not contain duplicates",
            )
        object.__setattr__(self, "namespaces", namespaces)
        if (
            isinstance(self.max_results, bool)
            or not isinstance(self.max_results, int)
            or not 1 <= self.max_results <= MAX_RETRIEVAL_RESULTS
        ):
            raise RetrievalContractError(
                "invalid_retrieval_contract",
                f"max_results must be between 1 and {MAX_RETRIEVAL_RESULTS}",
            )


@dataclass(frozen=True, slots=True)
class RetrievedItem:
    """One ranked retrieval result with bounded provenance and no arbitrary metadata."""

    id: str
    namespace: str
    source_type: str
    provider: str
    source_ref: str
    content: str
    title: str | None = None

    def __post_init__(self) -> None:
        for name in ("id", "namespace", "source_type", "provider", "source_ref"):
            object.__setattr__(self, name, _identifier(name, getattr(self, name)))
        object.__setattr__(
            self,
            "content",
            _bounded_text(
                "retrieved content",
                self.content,
                limit=MAX_RETRIEVAL_ITEM_CHARS,
            ),
        )
        if self.title is not None:
            object.__setattr__(
                self,
                "title",
                _bounded_text(
                    "retrieved title",
                    self.title,
                    limit=MAX_RETRIEVAL_TITLE_CHARS,
                ),
            )

    def to_public_dict(self) -> dict[str, str | int | None]:
        """Return provenance only; retrieved content is intentionally omitted."""

        return {
            "id": self.id,
            "namespace": self.namespace,
            "source_type": self.source_type,
            "provider": self.provider,
            "source_ref": self.source_ref,
            "title": self.title,
            "content_chars": len(self.content),
        }


class RetrievalProvider(Protocol):
    """Product/storage adapter boundary; implementations live outside this contract."""

    async def retrieve(self, request: RetrievalRequest) -> Sequence[RetrievedItem]: ...


@dataclass(frozen=True, slots=True)
class RetrievalPolicy:
    max_results: int = MAX_RETRIEVAL_RESULTS
    max_item_chars: int = MAX_RETRIEVAL_ITEM_CHARS
    max_total_content_chars: int = MAX_RETRIEVAL_TOTAL_CONTENT_CHARS

    def __post_init__(self) -> None:
        bounds = (
            ("max_results", self.max_results, 1, MAX_RETRIEVAL_RESULTS),
            ("max_item_chars", self.max_item_chars, 1, MAX_RETRIEVAL_ITEM_CHARS),
            (
                "max_total_content_chars",
                self.max_total_content_chars,
                1,
                MAX_RETRIEVAL_TOTAL_CONTENT_CHARS,
            ),
        )
        for name, value, low, high in bounds:
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not low <= value <= high
            ):
                raise RetrievalContractError(
                    "invalid_retrieval_policy",
                    f"{name} must be between {low} and {high}",
                )


@dataclass(frozen=True, slots=True)
class PreparedRetrieval:
    items: tuple[RetrievedItem, ...]
    context: PreparedContext

    def __post_init__(self) -> None:
        if not self.items or any(not isinstance(item, RetrievedItem) for item in self.items):
            raise RetrievalContractError(
                "invalid_retrieval_contract",
                "prepared retrieval must contain RetrievedItem values",
            )
        if not isinstance(self.context, PreparedContext):
            raise RetrievalContractError(
                "invalid_retrieval_contract",
                "context must be PreparedContext",
            )
        if self.context.trusted_system_context is not None:
            raise RetrievalContractError(
                "retrieval_trust_violation",
                "retrieval must never produce trusted system context",
            )
        if any(
            reference.trust is not ContextTrust.UNTRUSTED_REFERENCE
            for reference in self.context.references
        ):
            raise RetrievalContractError(
                "retrieval_trust_violation",
                "retrieval references must remain untrusted",
            )

    def to_public_dict(self) -> dict[str, object]:
        return {
            "item_count": len(self.items),
            "items": [item.to_public_dict() for item in self.items],
            "context": self.context.to_public_dict(),
        }


def _retrieval_fragment(item: RetrievedItem) -> ContextFragment:
    payload = json.dumps(
        {
            "namespace": item.namespace,
            "source_type": item.source_type,
            "provider": item.provider,
            "source_ref": item.source_ref,
            "title": item.title,
            "content": item.content,
        },
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    return ContextFragment(
        id=f"retrieval:{item.id}",
        source_type=item.source_type,
        content=payload,
        trust=ContextTrust.UNTRUSTED_REFERENCE,
    )


def prepare_retrieval_context(
    request: RetrievalRequest,
    items: Sequence[RetrievedItem],
    *,
    policy: RetrievalPolicy | None = None,
    context_policy: ContextPolicy | None = None,
) -> PreparedRetrieval:
    """Validate ranked retrieval results and prepare quoted untrusted context.

    Result order is provider rank order. Core does not invent or normalize a
    relevance score. Items beyond the configured count/character budget are
    omitted in order; individual oversized or out-of-scope items fail closed.
    """

    if not isinstance(request, RetrievalRequest):
        raise RetrievalContractError(
            "invalid_retrieval_contract",
            "request must be RetrievalRequest",
        )
    if isinstance(items, (str, bytes)):
        raise RetrievalContractError(
            "invalid_retrieval_contract",
            "items must be a sequence of RetrievedItem values",
        )
    candidates = tuple(items)
    if len(candidates) > MAX_PROVIDER_RETRIEVAL_ITEMS:
        raise RetrievalContractError(
            "retrieval_budget_exceeded",
            "provider returned too many retrieval items",
        )
    if any(not isinstance(item, RetrievedItem) for item in candidates):
        raise RetrievalContractError(
            "invalid_retrieval_contract",
            "items must contain only RetrievedItem values",
        )

    active_policy = policy or RetrievalPolicy()
    if request.max_results > active_policy.max_results:
        raise RetrievalContractError(
            "retrieval_budget_exceeded",
            "request max_results exceeds the active retrieval policy",
        )

    selected_candidates = candidates[: request.max_results]
    ids = tuple(item.id for item in selected_candidates)
    if len(set(ids)) != len(ids):
        raise RetrievalContractError(
            "duplicate_retrieval_item",
            "retrieval item ids must be unique",
        )

    allowed_namespaces = frozenset(request.namespaces)
    selected: list[RetrievedItem] = []
    content_chars = 0
    for item in selected_candidates:
        if item.namespace not in allowed_namespaces:
            raise RetrievalContractError(
                "retrieval_scope_violation",
                "retrieval provider returned an item outside the requested namespaces",
            )
        if len(item.content) > active_policy.max_item_chars:
            raise RetrievalContractError(
                "retrieval_budget_exceeded",
                "retrieved item exceeds the active per-item budget",
            )
        if content_chars + len(item.content) > active_policy.max_total_content_chars:
            break
        selected.append(item)
        content_chars += len(item.content)

    if not selected:
        raise RetrievalContractError(
            "no_retrieval_context",
            "no retrieval item fits the active context budget",
        )

    try:
        prepared = prepare_context(
            tuple(_retrieval_fragment(item) for item in selected),
            policy=context_policy,
        )
    except ContextPolicyError as exc:
        raise RetrievalContractError(
            "retrieval_context_rejected",
            exc.safe_message,
        ) from exc

    return PreparedRetrieval(items=tuple(selected), context=prepared)
