"""PC model-context budget: a fixed share of the selected model's own window.

The catalogue is still the only source of a model's context window. This module
never guesses a window for a model that does not declare one; it only turns a
declared window into the threshold at which older PC context is compacted.

The ratio is a deployment setting, not a product-tier or model policy:
`PADIEM_PC_CONTEXT_RATIO` (default 0.6, allowed 0.2-0.9). A value outside that
range or a non-numeric value falls back to the default instead of widening the
threshold silently.
"""
from __future__ import annotations

import os

RATIO_ENV = "PADIEM_PC_CONTEXT_RATIO"
DEFAULT_RATIO = 0.60
MIN_RATIO = 0.20
MAX_RATIO = 0.90
# A very small model window still needs room for the step prompt itself.
MIN_BUDGET_TOKENS = 2048


def context_ratio(value: str | float | None = None) -> float:
    raw = os.environ.get(RATIO_ENV, "") if value is None else value
    try:
        ratio = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_RATIO
    if ratio != ratio or ratio < MIN_RATIO or ratio > MAX_RATIO:  # NaN-safe
        return DEFAULT_RATIO
    return ratio


def compaction_budget(context_window: object, ratio: str | float | None = None) -> int | None:
    """The token threshold for a declared window; None when it is unknown."""
    if isinstance(context_window, bool) or not isinstance(context_window, int):
        return None
    if context_window <= 0:
        return None
    return max(MIN_BUDGET_TOKENS, int(context_window * context_ratio(ratio)))


async def catalog_compaction_budget(catalog, model_id: str) -> int | None:
    """Read the selected model's declared window from the existing catalogue."""
    reader = getattr(catalog, "context_budget", None)
    if not callable(reader):
        return None
    return compaction_budget(await reader(model_id))
