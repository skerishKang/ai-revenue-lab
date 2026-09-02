from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from .contracts import ContractError
from .ops_contracts import Money
from .security import redact_secrets


def _ref(value: str, field_name: str, *, limit: int = 256) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    value = value.strip()
    if not value or len(value) > limit or any(ord(ch) < 32 for ch in value):
        raise ContractError(f"{field_name} must be a bounded non-empty reference")
    if redact_secrets(value) != value:
        raise ContractError(f"{field_name} must not contain raw credential material")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _plain_date(value: date, field_name: str) -> date:
    if not isinstance(value, date) or isinstance(value, datetime):
        raise ContractError(f"{field_name} must be a date")
    return value


def _duration_minutes(start: datetime, end: datetime) -> Decimal:
    delta = end - start
    total_microseconds = (
        delta.days * 86_400_000_000
        + delta.seconds * 1_000_000
        + delta.microseconds
    )
    return Decimal(total_microseconds) / Decimal(60_000_000)


@dataclass(frozen=True, slots=True)
class SupplierResponseObservation:
    observation_id: str
    workspace_id: str
    supplier_id: str
    rfq_id: str
    sent_at: datetime
    received_at: datetime
    evidence_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "observation_id", _ref(self.observation_id, "observation_id"))
        object.__setattr__(self, "workspace_id", _ref(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "supplier_id", _ref(self.supplier_id, "supplier_id"))
        object.__setattr__(self, "rfq_id", _ref(self.rfq_id, "rfq_id"))
        sent_at = _aware(self.sent_at, "sent_at")
        received_at = _aware(self.received_at, "received_at")
        if received_at < sent_at:
            raise ContractError("received_at cannot precede sent_at")
        if received_at - sent_at > __import__("datetime").timedelta(days=365):
            raise ContractError("supplier response interval exceeds supported bound")
        object.__setattr__(self, "sent_at", sent_at)
        object.__setattr__(self, "received_at", received_at)
        object.__setattr__(self, "evidence_ref", _ref(self.evidence_ref, "evidence_ref", limit=512))

    @property
    def response_minutes(self) -> Decimal:
        return _duration_minutes(self.sent_at, self.received_at)


@dataclass(frozen=True, slots=True)
class SupplierDeliveryObservation:
    observation_id: str
    workspace_id: str
    supplier_id: str
    po_id: str
    promised_date: date
    actual_delivery_date: date
    evidence_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "observation_id", _ref(self.observation_id, "observation_id"))
        object.__setattr__(self, "workspace_id", _ref(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "supplier_id", _ref(self.supplier_id, "supplier_id"))
        object.__setattr__(self, "po_id", _ref(self.po_id, "po_id"))
        object.__setattr__(self, "promised_date", _plain_date(self.promised_date, "promised_date"))
        object.__setattr__(
            self,
            "actual_delivery_date",
            _plain_date(self.actual_delivery_date, "actual_delivery_date"),
        )
        object.__setattr__(self, "evidence_ref", _ref(self.evidence_ref, "evidence_ref", limit=512))

    @property
    def days_late(self) -> int:
        return max((self.actual_delivery_date - self.promised_date).days, 0)

    @property
    def on_time(self) -> bool:
        return self.actual_delivery_date <= self.promised_date


@dataclass(frozen=True, slots=True)
class SupplierPriceObservation:
    observation_id: str
    workspace_id: str
    supplier_id: str
    item_key: str
    quote_id: str
    captured_at: datetime
    unit_price: Money
    evidence_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "observation_id", _ref(self.observation_id, "observation_id"))
        object.__setattr__(self, "workspace_id", _ref(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "supplier_id", _ref(self.supplier_id, "supplier_id"))
        object.__setattr__(self, "item_key", _ref(self.item_key, "item_key", limit=128))
        object.__setattr__(self, "quote_id", _ref(self.quote_id, "quote_id"))
        object.__setattr__(self, "captured_at", _aware(self.captured_at, "captured_at"))
        if not isinstance(self.unit_price, Money):
            raise ContractError("unit_price must be Money")
        object.__setattr__(self, "evidence_ref", _ref(self.evidence_ref, "evidence_ref", limit=512))


@dataclass(frozen=True, slots=True)
class SupplierPriceSeriesSummary:
    item_key: str
    currency: str
    sample_count: int
    minimum_unit_price_minor: int
    maximum_unit_price_minor: int
    latest_unit_price_minor: int
    latest_captured_at: datetime
    evidence_refs: tuple[str, ...]

    def safe_dict(self) -> dict[str, Any]:
        return {
            "item_key": self.item_key,
            "currency": self.currency,
            "sample_count": self.sample_count,
            "minimum_unit_price_minor": self.minimum_unit_price_minor,
            "maximum_unit_price_minor": self.maximum_unit_price_minor,
            "latest_unit_price_minor": self.latest_unit_price_minor,
            "latest_captured_at": self.latest_captured_at.isoformat().replace("+00:00", "Z"),
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True, slots=True)
class SupplierPerformanceSummary:
    workspace_id: str
    supplier_id: str
    response_sample_count: int
    average_response_minutes: Decimal | None
    delivery_sample_count: int
    on_time_delivery_count: int
    on_time_rate_percent: Decimal | None
    average_days_late: Decimal | None
    price_series: tuple[SupplierPriceSeriesSummary, ...]
    evidence_refs: tuple[str, ...]

    def safe_dict(self) -> dict[str, Any]:
        def render(value: Decimal | None) -> str | None:
            return None if value is None else format(value, "f")

        return {
            "workspace_id": self.workspace_id,
            "supplier_id": self.supplier_id,
            "response_sample_count": self.response_sample_count,
            "average_response_minutes": render(self.average_response_minutes),
            "delivery_sample_count": self.delivery_sample_count,
            "on_time_delivery_count": self.on_time_delivery_count,
            "on_time_rate_percent": render(self.on_time_rate_percent),
            "average_days_late": render(self.average_days_late),
            "price_series": [item.safe_dict() for item in self.price_series],
            "evidence_refs": list(self.evidence_refs),
            "opaque_composite_score": None,
            "automatic_supplier_selection": False,
        }


class SupplierPerformanceLedger:
    """Evidence-first operational history, not a supplier-selection authority."""

    def __init__(self) -> None:
        self._responses: dict[str, SupplierResponseObservation] = {}
        self._deliveries: dict[str, SupplierDeliveryObservation] = {}
        self._prices: dict[str, SupplierPriceObservation] = {}
        self._observation_kinds: dict[str, str] = {}

    def _claim_id(self, observation_id: str, kind: str) -> None:
        existing = self._observation_kinds.get(observation_id)
        if existing is not None:
            raise ContractError(
                f"observation_id already exists as {existing}; history observations must be globally unique"
            )
        self._observation_kinds[observation_id] = kind

    def add_response(self, observation: SupplierResponseObservation) -> None:
        if not isinstance(observation, SupplierResponseObservation):
            raise ContractError("observation must be SupplierResponseObservation")
        self._claim_id(observation.observation_id, "response")
        self._responses[observation.observation_id] = observation

    def add_delivery(self, observation: SupplierDeliveryObservation) -> None:
        if not isinstance(observation, SupplierDeliveryObservation):
            raise ContractError("observation must be SupplierDeliveryObservation")
        self._claim_id(observation.observation_id, "delivery")
        self._deliveries[observation.observation_id] = observation

    def add_price(self, observation: SupplierPriceObservation) -> None:
        if not isinstance(observation, SupplierPriceObservation):
            raise ContractError("observation must be SupplierPriceObservation")
        self._claim_id(observation.observation_id, "price")
        self._prices[observation.observation_id] = observation

    def summarize(self, *, workspace_id: str, supplier_id: str) -> SupplierPerformanceSummary:
        workspace_id = _ref(workspace_id, "workspace_id")
        supplier_id = _ref(supplier_id, "supplier_id")
        responses = tuple(
            item
            for item in self._responses.values()
            if item.workspace_id == workspace_id and item.supplier_id == supplier_id
        )
        deliveries = tuple(
            item
            for item in self._deliveries.values()
            if item.workspace_id == workspace_id and item.supplier_id == supplier_id
        )
        prices = tuple(
            item
            for item in self._prices.values()
            if item.workspace_id == workspace_id and item.supplier_id == supplier_id
        )

        average_response: Decimal | None = None
        if responses:
            average_response = sum(
                (item.response_minutes for item in responses),
                Decimal(0),
            ) / Decimal(len(responses))

        on_time_count = sum(1 for item in deliveries if item.on_time)
        on_time_rate: Decimal | None = None
        average_days_late: Decimal | None = None
        if deliveries:
            on_time_rate = Decimal(on_time_count) * Decimal(100) / Decimal(len(deliveries))
            average_days_late = sum(
                (Decimal(item.days_late) for item in deliveries),
                Decimal(0),
            ) / Decimal(len(deliveries))

        series_by_key: dict[tuple[str, str], list[SupplierPriceObservation]] = {}
        for item in prices:
            series_by_key.setdefault((item.item_key, item.unit_price.currency), []).append(item)

        price_series: list[SupplierPriceSeriesSummary] = []
        for (item_key, currency), rows in sorted(series_by_key.items()):
            ordered = sorted(rows, key=lambda row: (row.captured_at, row.observation_id))
            values = [row.unit_price.amount_minor for row in ordered]
            price_series.append(
                SupplierPriceSeriesSummary(
                    item_key=item_key,
                    currency=currency,
                    sample_count=len(ordered),
                    minimum_unit_price_minor=min(values),
                    maximum_unit_price_minor=max(values),
                    latest_unit_price_minor=ordered[-1].unit_price.amount_minor,
                    latest_captured_at=ordered[-1].captured_at,
                    evidence_refs=tuple(dict.fromkeys(row.evidence_ref for row in ordered)),
                )
            )

        evidence_refs = tuple(
            dict.fromkeys(
                [item.evidence_ref for item in responses]
                + [item.evidence_ref for item in deliveries]
                + [item.evidence_ref for item in prices]
            )
        )
        return SupplierPerformanceSummary(
            workspace_id=workspace_id,
            supplier_id=supplier_id,
            response_sample_count=len(responses),
            average_response_minutes=average_response,
            delivery_sample_count=len(deliveries),
            on_time_delivery_count=on_time_count,
            on_time_rate_percent=on_time_rate,
            average_days_late=average_days_late,
            price_series=tuple(price_series),
            evidence_refs=evidence_refs,
        )


OPAQUE_SUPPLIER_COMPOSITE_SCORE_SUPPORTED = False
AUTOMATIC_SUPPLIER_SELECTION_SUPPORTED = False
