"""Bounded retrieval ranking and long-context assembly for P01 Memory/RAG.

The module consumes the existing provider-ranked ``RetrievedItem`` contract and
Core ``ContextPolicy``. It never invents relevance scores and never promotes
retrieved memory beyond ``UNTRUSTED_REFERENCE``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .context_policy import ContextPolicy, ContextPolicyError, PreparedContext, prepare_context
from .retrieval import (
    RetrievedItem,
    RetrievalContractError,
    RetrievalPolicy,
    RetrievalRequest,
    prepare_retrieval_context,
)

MAX_RANK_SCORE = 1.0


@dataclass(frozen=True, slots=True)
class RetrievalScore:
    """Optional relevance metadata; ``None`` means the provider did not score it."""

    item_id: str
    score: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.item_id, str) or not self.item_id:
            raise RetrievalContractError("invalid_retrieval_score", "item_id must be non-empty")
        if self.score is None:
            return
        if isinstance(self.score, bool) or not isinstance(self.score, (int, float)):
            raise RetrievalContractError("invalid_retrieval_score", "score must be numeric or None")
        value = float(self.score)
        if value != value or value < 0.0 or value > MAX_RANK_SCORE:
            raise RetrievalContractError("invalid_retrieval_score", "score must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class RankedMemoryItem:
    item: RetrievedItem
    score: float | None
    original_rank: int

    def __post_init__(self) -> None:
        if not isinstance(self.item, RetrievedItem):
            raise RetrievalContractError("invalid_ranked_memory", "item must be RetrievedItem")
        if isinstance(self.original_rank, bool) or not isinstance(self.original_rank, int) or self.original_rank < 0:
            raise RetrievalContractError("invalid_ranked_memory", "original_rank must be a non-negative integer")
        if self.score is not None:
            if isinstance(self.score, bool) or not isinstance(self.score, (int, float)):
                raise RetrievalContractError("invalid_ranked_memory", "score must be numeric or None")
            value = float(self.score)
            if value != value or value < 0 or value > MAX_RANK_SCORE:
                raise RetrievalContractError("invalid_ranked_memory", "score must be between 0 and 1")

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.item.id,
            "namespace": self.item.namespace,
            "score": self.score,
            "original_rank": self.original_rank,
        }


def rank_retrieval_results(
    items: Sequence[RetrievedItem],
    scores: Mapping[str, float | None] | Sequence[RetrievalScore] | None = None,
) -> tuple[RankedMemoryItem, ...]:
    """Attach provider scores without inventing missing values.

    Known scores are sorted descending. Items with unknown scores preserve their
    provider order and remain behind known scores. Ties preserve provider order.
    """
    candidates = tuple(items)
    if isinstance(candidates, (str, bytes)) or any(not isinstance(item, RetrievedItem) for item in candidates):
        raise RetrievalContractError("invalid_retrieval_contract", "items must contain RetrievedItem values")

    score_map: dict[str, float | None] = {}
    if scores is None:
        pass
    elif isinstance(scores, Mapping):
        score_map = dict(scores)
    else:
        for entry in scores:
            if not isinstance(entry, RetrievalScore):
                raise RetrievalContractError("invalid_retrieval_score", "scores must contain RetrievalScore values")
            if entry.item_id in score_map:
                raise RetrievalContractError("duplicate_retrieval_score", "scores must not contain duplicate item ids")
            score_map[entry.item_id] = entry.score

    ids = tuple(item.id for item in candidates)
    if len(set(ids)) != len(ids):
        raise RetrievalContractError("duplicate_retrieval_item", "retrieval item ids must be unique")
    unknown_score_ids = set(score_map) - set(ids)
    if unknown_score_ids:
        raise RetrievalContractError("unknown_retrieval_score", "score references an unknown retrieval item")

    ranked = [
        RankedMemoryItem(item=item, score=score_map.get(item.id), original_rank=index)
        for index, item in enumerate(candidates)
    ]
    ranked.sort(key=lambda value: (value.score is None, -(value.score or 0.0), value.original_rank))
    return tuple(ranked)


def assemble_long_context(
    ranked_items: Sequence[RankedMemoryItem],
    *,
    context_policy: ContextPolicy | None = None,
    max_items: int = 12,
    max_content_chars: int = 12_000,
) -> PreparedContext:
    """Select ranked memory within explicit budgets and assemble via ContextPolicy."""
    if isinstance(ranked_items, (str, bytes)):
        raise RetrievalContractError("invalid_long_context", "ranked_items must be a sequence")
    values = tuple(ranked_items)
    if any(not isinstance(item, RankedMemoryItem) for item in values):
        raise RetrievalContractError("invalid_long_context", "ranked_items must contain RankedMemoryItem values")
    if isinstance(max_items, bool) or not isinstance(max_items, int) or not 1 <= max_items <= 24:
        raise RetrievalContractError("invalid_long_context", "max_items must be between 1 and 24")
    if isinstance(max_content_chars, bool) or not isinstance(max_content_chars, int) or not 1 <= max_content_chars <= 16_000:
        raise RetrievalContractError("invalid_long_context", "max_content_chars must be between 1 and 16000")

    selected: list[RetrievedItem] = []
    used = 0
    for ranked in values[:max_items]:
        content = ranked.item.content
        if used + len(content) > max_content_chars:
            continue
        selected.append(ranked.item)
        used += len(content)

    if not selected:
        raise RetrievalContractError("no_long_context", "no ranked memory item fits the context budget")

    try:
        prepared = prepare_retrieval_context(
            RetrievalRequest(query="long-context", namespaces=tuple(dict.fromkeys(item.namespace for item in selected)), max_results=min(len(selected), 12)),
            selected,
            policy=RetrievalPolicy(
                max_results=min(len(selected), 12),
                max_item_chars=6_000,
                max_total_content_chars=max_content_chars,
            ),
            context_policy=context_policy,
        )
    except ContextPolicyError as exc:
        raise RetrievalContractError("long_context_rejected", exc.safe_message) from exc
    return prepared.context
