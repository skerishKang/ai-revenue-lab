"""B66 #3839 multi-item preservation contract (LOCAL2 data-path only).

This module does NOT render PDF, select models, call providers, mutate D1
history authority, or modify the LOCAL1-owned Sol renderer. It records the
exact resource-based cutoffs already enforced on the B66 input path so Sol
multi-page work can prove in-scope item arrays are preserved verbatim.
"""

from __future__ import annotations

from dataclasses import dataclass


EXTRACTION_MAX_ITEMS = 100
SAVED_SKILL_SEMANTIC_MAX_ITEMS = 100
SERVER_CONVERSATION_MAX_ITEMS = 100
SERVER_HISTORY_MAX_ITEMS = 200
SERVER_HISTORY_SNAPSHOT_BYTES = 128 * 1024
SAVED_SKILL_ENVELOPE_BYTES = 96 * 1024
CERTIFIED_PDF_REQUEST_BYTES = 32 * 1024
CERTIFIED_PDF_RESPONSE_BYTES = 32 * 1024 * 1024
CERTIFIED_SOL_MAX_ITEM_ROWS = 3
BUNDLE_SUPPORTED_SCOPE_MAX_ITEM_ROWS = 100
PROBE_ITEM_COUNTS = (1, 3, 4, 10, 25, 100, 101)


@dataclass(frozen=True, slots=True)
class B66MultiItemCutoff:
    stage: str
    max_items: int | None
    max_bytes: int | None
    overflow_code: str
    owner: str
    mutable_by_local2: bool


B66_MULTI_ITEM_CUTOFFS: tuple[B66MultiItemCutoff, ...] = (
    B66MultiItemCutoff("quote_extraction", 100, None,
                        "too_many_items",
                        "reference/.../quote-extraction.js", True),
    B66MultiItemCutoff("saved_skill_semantics", 100, None,
                        "invalid_structured_input",
                        "reference/.../quote-skill.js", True),
    B66MultiItemCutoff("server_conversation_intake", 100, None,
                        "invalid_items",
                        "apps/padiem-chat/app/b66_quote_conversation.py",
                        True),
    B66MultiItemCutoff("quote_core_calculation", None, None,
                        "none",
                        "reference/.../quote-core.js", False),
    B66MultiItemCutoff("server_history_snapshot", 200, 131072,
                        "snapshot.items is too large",
                        "apps/padiem-chat/app/b66_quote_history_store.py",
                        False),
    B66MultiItemCutoff("saved_skill_envelope", None, 98304,
                        "skill_json is too large",
                        "apps/padiem-chat/app/b66_saved_quote_skill_store.py",
                        False),
    B66MultiItemCutoff("certified_pdf_request", None, 32768,
                        "request_too_large",
                        "apps/padiem-chat/app/b66_certified_pdf_routes.py",
                        False),
    B66MultiItemCutoff("certified_sol_slots", 3, None,
                        "REJECT_ITEM_OVERFLOW",
                        "LOCAL1 Sol renderer", False),
)


def classify_probe_count(count: int) -> dict[str, bool]:
    """Classify one probe count against current data-path truth."""
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise ValueError("probe count must be a positive integer")
    return {
        "extraction_accepts": count <= EXTRACTION_MAX_ITEMS,
        "skill_semantics_accepts": count <= SAVED_SKILL_SEMANTIC_MAX_ITEMS,
        "server_intake_accepts": count <= SERVER_CONVERSATION_MAX_ITEMS,
        "history_items_accept": count <= SERVER_HISTORY_MAX_ITEMS,
        "sol_certified_accepts": count <= CERTIFIED_SOL_MAX_ITEM_ROWS,
        "requires_sol_extension": count > CERTIFIED_SOL_MAX_ITEM_ROWS,
        "requires_glm_or_html_fallback": False,
    }


def sol_input_output_contract() -> dict[str, object]:
    """Return the LOCAL1-ready Sol input/output contract for #3839."""
    return {
        "input": {
            "structured_quote_draft": True,
            "quote_core_effective_items": True,
            "quote_core_amounts": True,
            "quote_core_totals": ["supply", "vat", "grand"],
            "item_rows_in_order": True,
            "detail_groups": "unsupported_by_certified_sol_slots",
        },
        "output": {
            "sol_renderer_owner": "LOCAL1",
            "renderer_contract": "quote-template-renderer.v1",
            "calculation_authority": "quote-core",
            "render_model_calls": 0,
            "provider_calls": 0,
            "alternate_renderer_fallback": False,
        },
        "cutoffs": [
            {
                "stage": cutoff.stage,
                "max_items": cutoff.max_items,
                "max_bytes": cutoff.max_bytes,
                "overflow_code": cutoff.overflow_code,
                "owner": cutoff.owner,
                "mutable_by_local2": cutoff.mutable_by_local2,
            }
            for cutoff in B66_MULTI_ITEM_CUTOFFS
        ],
    }


__all__ = [
    "B66_MULTI_ITEM_CUTOFFS",
    "B66MultiItemCutoff",
    "BUNDLE_SUPPORTED_SCOPE_MAX_ITEM_ROWS",
    "CERTIFIED_PDF_REQUEST_BYTES",
    "CERTIFIED_PDF_RESPONSE_BYTES",
    "CERTIFIED_SOL_MAX_ITEM_ROWS",
    "EXTRACTION_MAX_ITEMS",
    "PROBE_ITEM_COUNTS",
    "SAVED_SKILL_ENVELOPE_BYTES",
    "SAVED_SKILL_SEMANTIC_MAX_ITEMS",
    "SERVER_CONVERSATION_MAX_ITEMS",
    "SERVER_HISTORY_MAX_ITEMS",
    "SERVER_HISTORY_SNAPSHOT_BYTES",
    "classify_probe_count",
    "sol_input_output_contract",
]

