"""Phase 3 structured generation pipeline.

This package implements the provider-neutral pipeline that converts persisted
participant input into a validated editorial plan and a ``pending_review``
edition draft, including the feedback-responsive second-edition loop.

Design boundaries (see docs/product/PERSONAL_EDITION_MVP_CONTRACT.md and
docs/architecture/PERSONAL_EDITION_MVP_ARCHITECTURE.md):

- ``segmentation``: deterministic input normalization and segmentation with
  stable identifiers and exact offsets.
- ``markup``: recursive rejection of unsafe markup in visible output fields.
- ``grounding``: deterministic prohibited-fact checks (no semantic guarantee).
- ``validators``: deterministic plan and draft reference/structure validation.
- ``prompts``: versioned editorial-plan and edition-draft prompt contracts.
- ``fixtures``: synthetic, repository-safe Korean/English fixture families.
- ``service``: provider-neutral ``GenerationService`` orchestrating the stages
  with bounded retry, normalized provider-error handling, generation-run
  accounting, and durable ``pending_review`` persistence.

No module in this package imports a concrete external provider client. All
provider access flows through the ``AIProvider`` protocol in ``app.ai.base``.
"""

__all__ = [
    "errors",
    "segmentation",
    "markup",
    "grounding",
    "validators",
    "prompts",
    "fixtures",
    "service",
]
