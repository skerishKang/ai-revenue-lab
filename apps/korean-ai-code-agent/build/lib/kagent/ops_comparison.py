from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any

from .contracts import ContractError
from .ops_contracts import Money, SupplierQuote


class ComparisonMode(str, Enum):
    LOWEST_PRICE = "lowest_price"
    FASTEST_DELIVERY = "fastest_delivery"
    BEST_CASHFLOW_FIT = "best_cashflow_fit"
    BALANCED = "balanced"


@dataclass(frozen=True, slots=True)
class ComparisonWeights:
    price: int = 50
    delivery: int = 25
    cashflow: int = 25

    def __post_init__(self) -> None:
        values = (self.price, self.delivery, self.cashflow)
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise ContractError("comparison weights must be integers")
        if any(value < 0 or value > 100 for value in values):
            raise ContractError("comparison weights must be between 0 and 100")
        if sum(values) != 100:
            raise ContractError("comparison weights must sum to 100")


@dataclass(frozen=True, slots=True)
class SupplierDecisionScore:
    supplier_id: str
    quote_id: str
    quote_version: int
    total: Money
    promised_delivery_date: date | None
    due_days: int | None
    prepaid: bool | None
    price_rank: int
    delivery_rank: int | None
    cashflow_rank: int | None
    score_basis_points: int
    unknown_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.supplier_id or not self.quote_id:
            raise ContractError("supplier_id and quote_id are required")
        if isinstance(self.quote_version, bool) or not isinstance(self.quote_version, int) or self.quote_version < 1:
            raise ContractError("quote_version must be a positive integer")
        if not isinstance(self.total, Money):
            raise ContractError("total must be Money")
        if isinstance(self.price_rank, bool) or not isinstance(self.price_rank, int) or self.price_rank < 1:
            raise ContractError("price_rank must be a positive integer")
        for value, name in ((self.delivery_rank, "delivery_rank"), (self.cashflow_rank, "cashflow_rank")):
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 1):
                raise ContractError(f"{name} must be a positive integer or None")
        if isinstance(self.score_basis_points, bool) or not isinstance(self.score_basis_points, int):
            raise ContractError("score_basis_points must be an integer")
        if not 0 <= self.score_basis_points <= 10000:
            raise ContractError("score_basis_points must be between 0 and 10000")
        if not isinstance(self.unknown_fields, tuple) or len(self.unknown_fields) > 8:
            raise ContractError("unknown_fields must be a bounded tuple")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "supplier_id": self.supplier_id,
            "quote_id": self.quote_id,
            "quote_version": self.quote_version,
            "total": self.total.safe_dict(),
            "promised_delivery_date": self.promised_delivery_date.isoformat() if self.promised_delivery_date else None,
            "due_days": self.due_days,
            "prepaid": self.prepaid,
            "price_rank": self.price_rank,
            "delivery_rank": self.delivery_rank,
            "cashflow_rank": self.cashflow_rank,
            "score_basis_points": self.score_basis_points,
            "unknown_fields": list(self.unknown_fields),
        }


@dataclass(frozen=True, slots=True)
class SupplierComparisonAnalysis:
    mode: ComparisonMode
    weights: ComparisonWeights
    scores: tuple[SupplierDecisionScore, ...]
    recommended_supplier_id: str
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.mode, ComparisonMode):
            raise ContractError("mode must be ComparisonMode")
        if not isinstance(self.weights, ComparisonWeights):
            raise ContractError("weights must be ComparisonWeights")
        if not isinstance(self.scores, tuple) or not self.scores:
            raise ContractError("scores must be a non-empty tuple")
        if self.recommended_supplier_id not in {score.supplier_id for score in self.scores}:
            raise ContractError("recommended_supplier_id must reference a score")
        if not isinstance(self.reason_codes, tuple) or not self.reason_codes:
            raise ContractError("reason_codes must be a non-empty tuple")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "weights": {
                "price": self.weights.price,
                "delivery": self.weights.delivery,
                "cashflow": self.weights.cashflow,
            },
            "scores": [score.safe_dict() for score in self.scores],
            "recommended_supplier_id": self.recommended_supplier_id,
            "reason_codes": list(self.reason_codes),
            "advisory_only": True,
        }


@dataclass(frozen=True, slots=True)
class NegotiationTarget:
    supplier_id: str
    quote_id: str
    quote_version: int
    current_total: Money
    target_total: Money
    basis: str

    def __post_init__(self) -> None:
        if not self.supplier_id or not self.quote_id:
            raise ContractError("supplier_id and quote_id are required")
        if isinstance(self.quote_version, bool) or not isinstance(self.quote_version, int) or self.quote_version < 1:
            raise ContractError("quote_version must be a positive integer")
        if not isinstance(self.current_total, Money) or not isinstance(self.target_total, Money):
            raise ContractError("current_total and target_total must be Money")
        if self.current_total.currency != self.target_total.currency:
            raise ContractError("negotiation target currency mismatch")
        if self.target_total.amount_minor <= 0:
            raise ContractError("negotiation target must be positive")
        if self.target_total.amount_minor > self.current_total.amount_minor:
            raise ContractError("negotiation target cannot exceed current supplier total")
        if not isinstance(self.basis, str) or not self.basis.strip() or len(self.basis) > 500:
            raise ContractError("basis must be a bounded non-empty string")


class SupplierComparisonEngine:
    """Deterministic comparison from captured quote fields only.

    No model output or hidden reasoning is used to calculate the recommendation.
    Missing delivery/payment fields are visible and penalized rather than guessed.
    """

    def evaluate(
        self,
        quotes: tuple[SupplierQuote, ...],
        *,
        mode: ComparisonMode = ComparisonMode.BALANCED,
        weights: ComparisonWeights | None = None,
    ) -> SupplierComparisonAnalysis:
        if not isinstance(quotes, tuple) or not quotes or len(quotes) > 100:
            raise ContractError("quotes must be a non-empty tuple with at most 100 entries")
        if not all(isinstance(quote, SupplierQuote) for quote in quotes):
            raise ContractError("quotes must contain SupplierQuote values")
        if len({quote.supplier_id for quote in quotes}) != len(quotes):
            raise ContractError("comparison accepts at most one active quote per supplier")
        if len({quote.total.currency for quote in quotes}) != 1:
            raise ContractError("comparison quotes must use one currency")
        if not isinstance(mode, ComparisonMode):
            try:
                mode = ComparisonMode(mode)
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid comparison mode") from exc
        weights = weights or ComparisonWeights()

        price_order = sorted(quotes, key=lambda quote: (quote.total.amount_minor, quote.supplier_id))
        price_ranks = {quote.supplier_id: index + 1 for index, quote in enumerate(price_order)}

        known_delivery = sorted(
            (quote for quote in quotes if quote.promised_delivery_date is not None),
            key=lambda quote: (quote.promised_delivery_date, quote.supplier_id),
        )
        delivery_ranks = {quote.supplier_id: index + 1 for index, quote in enumerate(known_delivery)}

        def cashflow_key(quote: SupplierQuote) -> tuple[int, str]:
            terms = quote.payment_terms
            if terms is None:
                raise AssertionError("cashflow_key called for unknown payment terms")
            effective_days = 0 if terms.prepaid else (terms.due_days if terms.due_days is not None else 0)
            return (-effective_days, quote.supplier_id)

        known_cashflow = sorted(
            (quote for quote in quotes if quote.payment_terms is not None and quote.payment_terms.due_days is not None),
            key=cashflow_key,
        )
        cashflow_ranks = {quote.supplier_id: index + 1 for index, quote in enumerate(known_cashflow)}

        count = len(quotes)
        missing_rank = count + 1

        def rank_points(rank: int) -> int:
            # 10,000 for first, linearly decreasing to 0 at the missing-data rank.
            return max(0, ((missing_rank - rank) * 10000) // count)

        scored: list[SupplierDecisionScore] = []
        for quote in quotes:
            unknowns: list[str] = []
            delivery_rank = delivery_ranks.get(quote.supplier_id)
            if delivery_rank is None:
                unknowns.append("promised_delivery_date")
            cashflow_rank = cashflow_ranks.get(quote.supplier_id)
            if cashflow_rank is None:
                unknowns.append("payment_terms")

            price_points = rank_points(price_ranks[quote.supplier_id])
            delivery_points = rank_points(delivery_rank or missing_rank)
            cashflow_points = rank_points(cashflow_rank or missing_rank)

            if mode is ComparisonMode.LOWEST_PRICE:
                score = price_points
            elif mode is ComparisonMode.FASTEST_DELIVERY:
                score = delivery_points
            elif mode is ComparisonMode.BEST_CASHFLOW_FIT:
                score = cashflow_points
            else:
                score = (
                    price_points * weights.price
                    + delivery_points * weights.delivery
                    + cashflow_points * weights.cashflow
                ) // 100

            terms = quote.payment_terms
            scored.append(
                SupplierDecisionScore(
                    supplier_id=quote.supplier_id,
                    quote_id=quote.quote_id,
                    quote_version=quote.version,
                    total=quote.total,
                    promised_delivery_date=quote.promised_delivery_date,
                    due_days=terms.due_days if terms else None,
                    prepaid=terms.prepaid if terms else None,
                    price_rank=price_ranks[quote.supplier_id],
                    delivery_rank=delivery_rank,
                    cashflow_rank=cashflow_rank,
                    score_basis_points=score,
                    unknown_fields=tuple(unknowns),
                )
            )

        ordered = tuple(
            sorted(
                scored,
                key=lambda item: (-item.score_basis_points, item.total.amount_minor, item.supplier_id),
            )
        )
        winner = ordered[0]
        reasons = [f"mode:{mode.value}", f"score:{winner.score_basis_points}"]
        if winner.unknown_fields:
            reasons.append("winner_has_unknown_fields")
        else:
            reasons.append("winner_fields_complete")
        return SupplierComparisonAnalysis(
            mode=mode,
            weights=weights,
            scores=ordered,
            recommended_supplier_id=winner.supplier_id,
            reason_codes=tuple(reasons),
        )

    def negotiation_target_from_competing_quote(
        self,
        *,
        target_quote: SupplierQuote,
        competing_quotes: tuple[SupplierQuote, ...],
    ) -> NegotiationTarget:
        if not isinstance(target_quote, SupplierQuote):
            raise ContractError("target_quote must be SupplierQuote")
        if not isinstance(competing_quotes, tuple) or not competing_quotes:
            raise ContractError("competing_quotes must be a non-empty tuple")
        if not all(isinstance(quote, SupplierQuote) for quote in competing_quotes):
            raise ContractError("competing_quotes must contain SupplierQuote values")
        candidates = tuple(
            quote
            for quote in competing_quotes
            if quote.supplier_id != target_quote.supplier_id
            and quote.total.currency == target_quote.total.currency
        )
        if not candidates:
            raise ContractError("no same-currency competing supplier quote is available")
        best = min(candidates, key=lambda quote: (quote.total.amount_minor, quote.supplier_id))
        target_amount = min(target_quote.total.amount_minor, best.total.amount_minor)
        if target_amount <= 0:
            raise ContractError("competing quote total must be positive")
        return NegotiationTarget(
            supplier_id=target_quote.supplier_id,
            quote_id=target_quote.quote_id,
            quote_version=target_quote.version,
            current_total=target_quote.total,
            target_total=Money(target_amount, target_quote.total.currency),
            basis=f"captured_competing_quote:{best.quote_id}:v{best.version}",
        )
