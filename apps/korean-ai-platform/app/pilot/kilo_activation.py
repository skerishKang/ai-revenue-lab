"""Network-free activation contract for volatile Kilo free routes (#1438).

This module deliberately does not fetch the network and does not mutate the B14
catalog. It evaluates a fresh OpenAI-compatible Kilo ``GET /models`` payload
against a Padiem-owned allow-list plus separately collected live-callability
evidence. Catalog presence and zero price are necessary but not sufficient for
activation.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


STATE_DISCOVERED = "DISCOVERED"
STATE_CONTRACT_VERIFIED = "CONTRACT_VERIFIED"
STATE_LIVE_CALLABLE = "LIVE_CALLABLE"
STATE_INACTIVE = "INACTIVE"


@dataclass(frozen=True, slots=True)
class KiloActivationDecision:
    model_id: str
    state: str
    catalog_present: bool
    zero_priced: bool
    live_callable: bool
    reason: str


def _is_zero_price(value: object) -> bool:
    """Return True only for an explicit numeric zero value.

    Missing, malformed, negative, boolean, or non-zero prices fail closed.
    """

    if isinstance(value, bool) or value is None:
        return False
    try:
        price = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return False
    return price == Decimal("0")


def _models_by_id(payload: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    data = payload.get("data")
    if not isinstance(data, list):
        return {}

    result: dict[str, Mapping[str, Any]] = {}
    for item in data:
        if not isinstance(item, Mapping):
            continue
        model_id = item.get("id")
        if isinstance(model_id, str) and model_id:
            result[model_id] = item
    return result


def evaluate_kilo_activation(
    *,
    models_payload: Mapping[str, Any],
    allowed_model_ids: tuple[str, ...],
    live_callability: Mapping[str, bool] | None = None,
) -> tuple[KiloActivationDecision, ...]:
    """Evaluate explicit Kilo candidates without auto-promoting them.

    ``live_callability`` is deliberately external evidence gathered by a bounded
    smoke/benchmark lane. Absence of positive live evidence fails closed.
    """

    catalog = _models_by_id(models_payload)
    live = live_callability or {}
    decisions: list[KiloActivationDecision] = []

    for model_id in allowed_model_ids:
        item = catalog.get(model_id)
        if item is None:
            decisions.append(
                KiloActivationDecision(
                    model_id=model_id,
                    state=STATE_INACTIVE,
                    catalog_present=False,
                    zero_priced=False,
                    live_callable=False,
                    reason="not_in_current_kilo_catalog",
                )
            )
            continue

        pricing = item.get("pricing")
        prompt_zero = False
        completion_zero = False
        if isinstance(pricing, Mapping):
            prompt_zero = _is_zero_price(pricing.get("prompt"))
            completion_zero = _is_zero_price(pricing.get("completion"))
        zero_priced = prompt_zero and completion_zero

        if not zero_priced:
            decisions.append(
                KiloActivationDecision(
                    model_id=model_id,
                    state=STATE_INACTIVE,
                    catalog_present=True,
                    zero_priced=False,
                    live_callable=False,
                    reason="current_pricing_is_not_explicitly_zero",
                )
            )
            continue

        callable_now = live.get(model_id) is True
        if not callable_now:
            decisions.append(
                KiloActivationDecision(
                    model_id=model_id,
                    state=STATE_CONTRACT_VERIFIED,
                    catalog_present=True,
                    zero_priced=True,
                    live_callable=False,
                    reason="zero_priced_but_live_callability_not_proven",
                )
            )
            continue

        decisions.append(
            KiloActivationDecision(
                model_id=model_id,
                state=STATE_LIVE_CALLABLE,
                catalog_present=True,
                zero_priced=True,
                live_callable=True,
                reason="current_catalog_zero_price_and_live_callability_proven",
            )
        )

    return tuple(decisions)
