"""Engine-side E7 usage lifecycle projection.

The Engine does not own a billing ledger, pricing, provider route, or cost.
This module turns trusted Control Plane reservation evidence plus server-observed
terminal execution evidence into one deterministic UsageReceipt identity.
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
from typing import Any

from app.execution_admission_resume import OriginalAdmissionBinding
from app.tenant_auth import UsageReceipt


def is_idempotency_replay(result: Any) -> bool:
    for event in getattr(result, "events", ()) or ():
        metadata = getattr(event, "metadata", None)
        if isinstance(metadata, Mapping) and metadata.get("replay") is True:
            return True
    return False


def build_terminal_usage_receipt(
    original: OriginalAdmissionBinding,
    *,
    outcome: str,
    result: Any | None = None,
) -> UsageReceipt:
    if not isinstance(original, OriginalAdmissionBinding) or original.usage_reservation is None:
        raise ValueError("typed original usage reservation evidence is required")
    reservation = original.usage_reservation
    material = "|".join(
        ("engine-usage-event-v1", reservation.reservation_ref, reservation.idempotency_key, reservation.request_fingerprint)
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()

    input_tokens = output_tokens = total_tokens = None
    if result is not None:
        execution_result = getattr(result, "execution_result", None)
        metadata = getattr(execution_result, "metadata", None)
        usage = getattr(metadata, "usage", None)
        if usage is not None:
            input_tokens = getattr(usage, "input_tokens", None)
            output_tokens = getattr(usage, "output_tokens", None)
            total_tokens = getattr(usage, "total_tokens", None)

    # E7 source activation is shadow usage only. Commercial chargeability remains
    # Control Plane/product policy and live billing is still explicitly disabled,
    # so Engine receipts must never activate a billable disposition.
    disposition = "non_billable"
    return UsageReceipt(
        event_id=f"eng-use-{digest[:32]}",
        idempotency_key=f"use-{digest}",
        billing_semantic_id=reservation.billing_semantic_id,
        product_id=reservation.product_id,
        subject={"subject_type": reservation.subject_type, "subject_id": reservation.subject_id},
        execution_id=f"eng-exec-{reservation.request_fingerprint[:32]}",
        outcome=outcome,
        billing_disposition=disposition,
        # Stable across receipt retry after a lost acknowledgement.
        occurred_at=reservation.reserved_at,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


ENGINE_BILLING_LEDGER = False
B14_PROVIDER_AUTHORITY_WIDENED = False
