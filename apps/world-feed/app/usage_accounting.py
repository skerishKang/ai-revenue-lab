"""Token usage normalization and aggregation for generation runs."""

from __future__ import annotations

from app.domain.models import ProviderUsage
from app.errors import UsageAccountingError


def normalize_usage(usage: ProviderUsage) -> ProviderUsage:
    """Normalize partial provider usage under a documented contract.

    Rules:
    - negative values are rejected;
    - when ``total_tokens`` is omitted but input and output are present,
      total becomes ``input + output``;
    - when all three are present and ``total != input + output``, fail closed;
    - omitted fields stay ``None`` (not coerced to 0) until aggregation.
    """
    it = usage.input_tokens
    ot = usage.output_tokens
    tt = usage.total_tokens
    for label, value in (("input_tokens", it), ("output_tokens", ot), ("total_tokens", tt)):
        if value is not None and value < 0:
            raise UsageAccountingError(f"{label} must not be negative")
    if tt is None and it is not None and ot is not None:
        tt = it + ot
    elif tt is not None and it is not None and ot is not None and tt != it + ot:
        raise UsageAccountingError(
            f"inconsistent usage: total_tokens={tt} != "
            f"input_tokens({it})+output_tokens({ot})"
        )
    return ProviderUsage(input_tokens=it, output_tokens=ot, total_tokens=tt)


def aggregate_usage(parts: list[ProviderUsage]) -> ProviderUsage:
    """Sum normalized attempt usage; missing fields contribute 0 to the sum."""
    total_input = 0
    total_output = 0
    total_tokens = 0
    for part in parts:
        total_input += part.input_tokens or 0
        total_output += part.output_tokens or 0
        total_tokens += part.total_tokens or 0
    return ProviderUsage(
        input_tokens=total_input,
        output_tokens=total_output,
        total_tokens=total_tokens,
    )
