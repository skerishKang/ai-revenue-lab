"""Provider-native optional chat parameters — never invent a model default.

The exact served model ID is authoritative, not a guessed family/alias.
Each non-generic option below is based on the named serving-provider's
published OpenAI-compatible API or exact serving model documentation.
UNKNOWN support fails closed; no manufacturer defaults are injected.
#3977 / docs/architecture/B14_MODEL_PROVIDER_EXECUTION_AUTHORITY_2026-10-10.md
"""
from __future__ import annotations

import math
from typing import Any

# Only explicitly documented API parameters are offered for the exact served
# route. Provider ID must match the canonical model registry at dispatch.
# Values below describe ACCEPTED USER OVERRIDES, NOT DEFAULTS.
_SUPPORTED: dict[str, dict[str, Any]] = {
    "google/gemini-3.1-flash-lite": {
        "reasoning_effort": frozenset({"minimal", "low", "medium", "high"}),
    },
    "google/gemini-3.5-flash-lite": {
        "reasoning_effort": frozenset({"minimal", "low", "medium", "high"}),
    },
    "atria/Atria-Dawn-Preview": {
        "reasoning_effort": frozenset({"low", "medium", "high"}),
    },
    "sensenova/sensenova-6.8-flash-lite": {
        "top_p": "unit_interval",
        "top_k": "positive_integer",
        "min_p": "unit_interval",
        "presence_penalty": "signed_two",
        "repetition_penalty": "positive_number",
    },
}
# Official references for supported provider-native overrides:
# google: https://ai.google.dev/gemini-api/docs/openai
# sensenova: https://github.com/OpenSenseNova/SenseNova6.8/blob/main/API.md
# atria: https://huggingface.co/internlm/Atria-Dawn-Preview-FP8 (manufacturer)
#   + exact-serving-API low/medium/high evidence: B14_FINAL_ATRIA_DAWN_PREVIEW
# Do not infer original Qwen capabilities for ExLab's uncensored served variant.

OPTIONAL_FIELDS = frozenset({
    "reasoning_effort", "top_p", "top_k", "min_p",
    "presence_penalty", "repetition_penalty",
})


class UnsupportedModelParameter(ValueError):
    """A caller explicitly requested an unverified or invalid native option."""


def validate_native_parameters(model_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Preserve only explicit, documented options for the chosen exact B14 ID."""
    allowed = _SUPPORTED.get(model_id, {})
    result: dict[str, Any] = {}
    for name in OPTIONAL_FIELDS:
        if name not in raw or raw[name] is None:
            continue
        rule = allowed.get(name)
        if rule is None:
            raise UnsupportedModelParameter(
                f"{name} is not documented for serving model {model_id}"
            )
        value = raw[name]
        if isinstance(rule, frozenset):
            if not isinstance(value, str) or value not in rule:
                raise UnsupportedModelParameter(
                    f"{name} must be one of: {', '.join(sorted(rule))}"
                )
        elif rule == "positive_integer":
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise UnsupportedModelParameter(f"{name} must be a positive integer")
        else:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise UnsupportedModelParameter(f"{name} must be numeric")
            if not math.isfinite(float(value)):
                raise UnsupportedModelParameter(f"{name} must be finite")
            if rule == "unit_interval" and not 0 <= float(value) <= 1:
                raise UnsupportedModelParameter(f"{name} must be between 0 and 1")
            if rule == "signed_two" and not -2 <= float(value) <= 2:
                raise UnsupportedModelParameter(f"{name} must be between -2 and 2")
            if rule == "positive_number" and float(value) <= 0:
                raise UnsupportedModelParameter(f"{name} must be positive")
        result[name] = value
    return result
