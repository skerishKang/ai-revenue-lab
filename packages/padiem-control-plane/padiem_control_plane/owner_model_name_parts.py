"""Owner-selected Google B14 name PARTS, 2026-10-08 (#3790 Slice A).

A bounded, read-only subset projection, NOT the full Padiem Plus model list.
The OWNER may have selected additional models. Do not infer a global default,
availability, paid entitlement, implicit provider fallback, or display separator.
It is intentionally independent of the product tier's executable/HOLD contract.

Registration is supplied only by trusted B14 registered-route evidence.
No platform secret is read, no provider model is called, and no image-generation
or product-activation entitlement follows from any row of this projection.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

PRODUCT_NAME_PREFIX_KO = "파디엠플러스"

# Owner decisions, exact merged B14 ids, not a new model recommendation.
# This is GOOGLE ONLY, NOT the full owner-approved Plus inventory.
_GOOGLE_NAME_PARTS: tuple[tuple[str, str, bool], ...] = (
    ("google/gemini-3.1-flash-lite", "Gemini 3.1 Flash Lite", True),
    ("google/gemini-3.5-flash-lite", "Gemini 3.5 Flash Lite", True),
    ("google/gemma-4-26b-a4b-it", "Gemma 4 26B", True),
    ("google/gemma-4-31b-it", "Gemma 4 31B", False),
)


@dataclass(frozen=True, slots=True)
class OwnerModelNameParts:
    model_id: str
    product_name_prefix: str
    individual_model_name: str
    owner_selected: bool
    source_registered_in_b14: bool
    live_provider_verified: bool
    customer_product_enabled: bool
    customer_selectable: bool
    is_automatic_default: bool
    image_input_proven_in_prior_fixture: bool
    image_generation_proven: bool


def google_owner_name_parts(
    trusted_b14_registered_ids: Iterable[str] = (),
) -> tuple[OwnerModelNameParts, ...]:
    """Project only source-proven Google IDs; NEVER authorize customer selection.

    A caller must supply actual B14 registered model identities, not request
    payload labels. The product remains held even if every exact ID is present.
    The caller is responsible for separately verifying credential/readiness,
    entitlement, deployment, and UI display wording.
    """
    registered = frozenset(trusted_b14_registered_ids)
    return tuple(
        OwnerModelNameParts(
            model_id=mid,
            product_name_prefix=PRODUCT_NAME_PREFIX_KO,
            individual_model_name=name,
            owner_selected=True,
            source_registered_in_b14=mid in registered,
            live_provider_verified=False,
            customer_product_enabled=False,
            customer_selectable=False,
            is_automatic_default=False,
            image_input_proven_in_prior_fixture=image_input_proven,
            image_generation_proven=False,
        )
        for mid, name, image_input_proven in _GOOGLE_NAME_PARTS
    )
