"""Canonical per-model maximum output (completion) token caps (B14 #3553).

The previous blanket ``1..4096`` request ceiling starved reasoning models into
empty completions: every current free/route model spends completion budget on
hidden reasoning tokens *before* it emits ``message.content``, so a small
``max_tokens`` yields ``content=null`` with ``finish_reason=length`` rather than
a usable answer. This module replaces the flat ceiling with a model-specific
budget taken from each upstream's own model metadata (measured 2026-10-07).

Sources of the measured values:

* Kilo Gateway ``/models``      -> ``top_provider.max_completion_tokens``
* Experiential Labs ``/models`` -> ``maximum_output_tokens``
* Inception / SenseNova ``/models`` -> ``max_output_length``

A model that advertises no cap maps to ``None``: callers then omit ``max_tokens``
so the provider's own default (its real ceiling) applies. This module holds no
credentials and performs no network call.
"""

from __future__ import annotations

# Largest explicit request any registered B14 route may ask for. Derived from the
# measured caps below so the gateway/schema ceiling can never be smaller than a
# registered route's own capability.
MAX_REQUEST_TOKENS = 131072

# model_id -> maximum output tokens, or None when the provider advertises none.
MODEL_MAX_OUTPUT_TOKENS: dict[str, int | None] = {
    # Kilo Gateway free lanes (top_provider.max_completion_tokens).
    "kilo/nvidia-nemotron-3-ultra-550b-a55b-free": 65536,
    "kilo/poolside-laguna-s-2.1-free": 32768,
    "kilo/inclusionai-ling-3.1-flash": 32768,
    # Direct provider routes.
    "agnes-ai/agnes-3.0-flash": None,
    "sensenova/sensenova-6.8-flash-lite": 65536,
    "poolside/laguna-s-2.1": 32768,
    "infron/motif/motif-3": None,
    "inception/mercury-2.5": 65536,
    "atria/Atria-Dawn-Preview": None,
    "experiential/glm-5.3-flash-abliterated": 131072,
}


def max_output_tokens_for(model_id: str) -> int | None:
    """Return the model's maximum output tokens, or ``None`` when unadvertised.

    ``None`` is meaningful: the caller omits ``max_tokens`` and the provider
    applies its own default ceiling for that model.
    """

    return MODEL_MAX_OUTPUT_TOKENS.get(model_id)
