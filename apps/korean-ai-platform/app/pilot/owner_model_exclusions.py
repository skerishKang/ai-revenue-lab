"""Owner-excluded B14 customer model identities, 2026-10-08 (#3554).

Historical catalog/provider registration may remain while compatibility
dependencies are audited. Registration and free pricing never imply current
OWNER authorization for customer automatic model selection.

Do not add replacement models, alter credentials, activate Production or
infer image-generation support here.
"""
from __future__ import annotations

import re

# Owner decision 2026-10-21 (#2505): an OpenCode Go free model is never an
# execution candidate. The provider prefix plus the ``-free`` suffix marks the
# family; no other provider's free model is affected by this decision.
FREE_CANDIDATE_PROVIDER = "opencode-go"


def free_candidate_excluded_from_execution(
    model_id: str,
    *,
    upstream_model: str | None = None,
    platform_provider_id: str | None = None,
) -> bool:
    """Whether one model identity is an excluded free execution candidate.

    The candidate lists must never offer an excluded free model: the grade
    routes and the automatic recovery chains are owner-pinned choices, and a
    free lane is not one of them.

    The public model id carries the provider prefix, so the family is
    recognized from it. A caller that also knows the provider's own upstream
    name cannot disguise an excluded free upstream route behind a benign
    public id: the upstream of the excluded provider is checked as well, and
    another provider's free upstream name is never affected.
    """
    if not isinstance(model_id, str) or not model_id:
        return False
    provider, separator, tail = model_id.strip().casefold().partition("/")
    if separator and provider == FREE_CANDIDATE_PROVIDER and tail.endswith("-free"):
        return True
    return (
        isinstance(upstream_model, str)
        and platform_provider_id == FREE_CANDIDATE_PROVIDER
        and upstream_model.strip().casefold().endswith("-free")
    )


def excluded_from_owner_customer_selection(model_id: str) -> bool:
    """Match owner-excluded model families across their existing registered IDs.

    Families: Kilo Poolside Laguna, B.AI Qwen, Motif 3,
    GPT-5.6 Luna, NVIDIA Nemotron, StepFun Step 3.7 Flash, and
    Thinking Machines Inkling Small (owner-retired 2026-10-10).
    This excludes only Inkling Small, not other Small models from other vendors.
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
