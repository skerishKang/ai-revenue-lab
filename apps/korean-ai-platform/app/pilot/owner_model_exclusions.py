"""Owner-excluded B14 customer model identities, 2026-10-08 (#3554).

Historical catalog/provider registration may remain while compatibility
dependencies are audited. Registration and free pricing never imply current
OWNER authorization for customer automatic model selection.

Do not add replacement models, alter credentials, activate Production or
infer image-generation support here.
"""
from __future__ import annotations

import re


def excluded_from_owner_customer_selection(model_id: str) -> bool:
    """Match owner-excluded model families across their existing registered IDs.

    Families: Kilo Poolside Laguna, B.AI Qwen, Motif 3,
    GPT-5.6 Luna, NVIDIA Nemotron, StepFun Step 3.7 Flash, and
    Thinking Machines Inkling Small (owner-retired 2026-10-10).
    This excludes only Inkling Small, not other Small models from other vendors.
    StepFun Step 5 Preview Free is a separate candidate and stays unblocked.
    """
    normalized = model_id.strip().casefold()
    return (
        "nemotron" in normalized
        or (normalized.startswith("kilo/") and "poolside" in normalized and "laguna" in normalized)
        or (normalized.startswith("b-ai/") and "qwen" in normalized)
        or "motif-3" in normalized
        or "gpt-5.6-luna" in normalized
        or re.search(r"(?:^|[/\-])stepfun[/\-]step-3[.]7-flash(?=$|[:/\-])", normalized) is not None
        or re.search(r"(?:^|/)thinkingmachines(?:/|-)inkling-small(?=$|[:/\-])", normalized) is not None
    )
