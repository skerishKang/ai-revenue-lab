from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .contracts import ContractError
from .ops_comparison import SupplierComparisonAnalysis
from .ops_supplier_history import SupplierPerformanceSummary


@dataclass(frozen=True, slots=True)
class SupplierHistoryDecisionContext:
    supplier_id: str
    history_available: bool
    response_sample_count: int
    average_response_minutes: str | None
    delivery_sample_count: int
    on_time_rate_percent: str | None
    average_days_late: str | None
    price_series_count: int
    evidence_refs: tuple[str, ...]

    def safe_dict(self) -> dict[str, Any]:
        return {
            "supplier_id": self.supplier_id,
            "history_available": self.history_available,
            "response_sample_count": self.response_sample_count,
            "average_response_minutes": self.average_response_minutes,
            "delivery_sample_count": self.delivery_sample_count,
            "on_time_rate_percent": self.on_time_rate_percent,
            "average_days_late": self.average_days_late,
            "price_series_count": self.price_series_count,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True, slots=True)
class SupplierComparisonWithHistory:
    analysis: SupplierComparisonAnalysis
    history_contexts: tuple[SupplierHistoryDecisionContext, ...]
    history_influenced_recommendation: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.analysis, SupplierComparisonAnalysis):
            raise ContractError("analysis must be SupplierComparisonAnalysis")
        if not isinstance(self.history_contexts, tuple) or not all(
            isinstance(item, SupplierHistoryDecisionContext) for item in self.history_contexts
        ):
            raise ContractError("history_contexts must contain SupplierHistoryDecisionContext")
        score_ids = tuple(score.supplier_id for score in self.analysis.scores)
        context_ids = tuple(item.supplier_id for item in self.history_contexts)
        if context_ids != score_ids:
            raise ContractError("history contexts must preserve exact comparison score order")
        if self.history_influenced_recommendation is not False:
            raise ContractError("M1 supplier history must not silently change recommendation scoring")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "analysis": self.analysis.safe_dict(),
            "history_contexts": [item.safe_dict() for item in self.history_contexts],
            "history_influenced_recommendation": False,
            "recommended_supplier_id_unchanged": self.analysis.recommended_supplier_id,
        }


class SupplierHistoryContextProjector:
    """Attach factual history to a comparison without modifying its score or winner."""

    def project(
        self,
        analysis: SupplierComparisonAnalysis,
        *,
        workspace_id: str,
        histories: tuple[SupplierPerformanceSummary, ...],
    ) -> SupplierComparisonWithHistory:
        if not isinstance(analysis, SupplierComparisonAnalysis):
            raise ContractError("analysis must be SupplierComparisonAnalysis")
        if not isinstance(workspace_id, str) or not workspace_id.strip():
            raise ContractError("workspace_id is required")
        workspace_id = workspace_id.strip()
        if not isinstance(histories, tuple) or not all(
            isinstance(item, SupplierPerformanceSummary) for item in histories
        ):
            raise ContractError("histories must contain SupplierPerformanceSummary values")

        score_ids = {score.supplier_id for score in analysis.scores}
        by_supplier: dict[str, SupplierPerformanceSummary] = {}
        for summary in histories:
            if summary.workspace_id != workspace_id:
                raise ContractError("supplier history belongs to another workspace")
            if summary.supplier_id not in score_ids:
                raise ContractError("supplier history is unrelated to this comparison")
            if summary.supplier_id in by_supplier:
                raise ContractError("duplicate supplier history summary")
            by_supplier[summary.supplier_id] = summary

        contexts: list[SupplierHistoryDecisionContext] = []
        for score in analysis.scores:
            summary = by_supplier.get(score.supplier_id)
            if summary is None:
                contexts.append(
                    SupplierHistoryDecisionContext(
                        supplier_id=score.supplier_id,
                        history_available=False,
                        response_sample_count=0,
                        average_response_minutes=None,
                        delivery_sample_count=0,
                        on_time_rate_percent=None,
                        average_days_late=None,
                        price_series_count=0,
                        evidence_refs=(),
                    )
                )
                continue
            contexts.append(
                SupplierHistoryDecisionContext(
                    supplier_id=summary.supplier_id,
                    history_available=bool(
                        summary.response_sample_count
                        or summary.delivery_sample_count
                        or summary.price_series
                    ),
                    response_sample_count=summary.response_sample_count,
                    average_response_minutes=(
                        format(summary.average_response_minutes, "f")
                        if summary.average_response_minutes is not None
                        else None
                    ),
                    delivery_sample_count=summary.delivery_sample_count,
                    on_time_rate_percent=(
                        format(summary.on_time_rate_percent, "f")
                        if summary.on_time_rate_percent is not None
                        else None
                    ),
                    average_days_late=(
                        format(summary.average_days_late, "f")
                        if summary.average_days_late is not None
                        else None
                    ),
                    price_series_count=len(summary.price_series),
                    evidence_refs=summary.evidence_refs,
                )
            )

        return SupplierComparisonWithHistory(
            analysis=analysis,
            history_contexts=tuple(contexts),
        )


SUPPLIER_HISTORY_CHANGES_COMPARISON_SCORE = False
SUPPLIER_HISTORY_AUTHORIZES_SELECTION = False
