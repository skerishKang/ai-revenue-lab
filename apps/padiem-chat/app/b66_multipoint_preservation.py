"""TEST-ONLY READ-ONLY inventory for B66 #3839 (LOCAL2 data-path).

DO NOT import this module from production routes, workers, or renderers.
It creates no runtime authority, no PDF rendering, no model/provider call,
no D1 mutation, and no LOCAL1 Sol change. Tests import it only to pin the
already-enforced cutoffs and to document where 4+ rows fail closed.

Python-owned cutoffs are mirrored here for readability, but every value is
pinned by tests against its owning source module. A drift in any owner
must fail tests instead of silently forking a parallel policy source.
JS-owned cutoffs are documented with exact file/line provenance and pinned
by tests that read those JS sources.
"""

from __future__ import annotations

from dataclasses import dataclass


# Values below are expected current-source truth. Python values owned by
# apps/padiem-chat are pinned by tests against their owning modules; the
# standalone apps/b66-pdf-renderer bundle rule is pinned by a test that
# reads that exact file. JS values are pinned by tests that read the exact
# owning JS sources. Never edit production behavior by changing this
# inventory: change the owning source and let tests expose the drift.
EXPECTED_EXTRACTION_MAX_ITEMS = 100
EXPECTED_SAVED_SKILL_SEMANTIC_MAX_ITEMS = 100
EXPECTED_SERVER_CONVERSATION_MAX_ITEMS = 100
EXPECTED_SERVER_HISTORY_MAX_ITEMS = 200
EXPECTED_SERVER_HISTORY_SNAPSHOT_BYTES = 128 * 1024
EXPECTED_SAVED_SKILL_ENVELOPE_BYTES = 96 * 1024
EXPECTED_CERTIFIED_PDF_REQUEST_BYTES = 32 * 1024
EXPECTED_CERTIFIED_PDF_RESPONSE_BYTES = 32 * 1024 * 1024
EXPECTED_CERTIFIED_SOL_MAX_ITEM_ROWS = 3
EXPECTED_BUNDLE_SUPPORTED_SCOPE_MAX_ITEM_ROWS = 100

# Backwards-compatible aliases for the first review round. New callers
# should prefer the EXPECTED_* names so a parallel-policy fork is obvious.
EXTRACTION_MAX_ITEMS = EXPECTED_EXTRACTION_MAX_ITEMS
SAVED_SKILL_SEMANTIC_MAX_ITEMS = EXPECTED_SAVED_SKILL_SEMANTIC_MAX_ITEMS
SERVER_CONVERSATION_MAX_ITEMS = EXPECTED_SERVER_CONVERSATION_MAX_ITEMS
SERVER_HISTORY_MAX_ITEMS = EXPECTED_SERVER_HISTORY_MAX_ITEMS
SERVER_HISTORY_SNAPSHOT_BYTES = EXPECTED_SERVER_HISTORY_SNAPSHOT_BYTES
SAVED_SKILL_ENVELOPE_BYTES = EXPECTED_SAVED_SKILL_ENVELOPE_BYTES
CERTIFIED_PDF_REQUEST_BYTES = EXPECTED_CERTIFIED_PDF_REQUEST_BYTES
CERTIFIED_PDF_RESPONSE_BYTES = EXPECTED_CERTIFIED_PDF_RESPONSE_BYTES
CERTIFIED_SOL_MAX_ITEM_ROWS = EXPECTED_CERTIFIED_SOL_MAX_ITEM_ROWS
BUNDLE_SUPPORTED_SCOPE_MAX_ITEM_ROWS = (
    EXPECTED_BUNDLE_SUPPORTED_SCOPE_MAX_ITEM_ROWS
)
PROBE_ITEM_COUNTS = (1, 3, 4, 10, 25, 100, 101)
# 101 is intentionally an isolated-history probe only. Full-pipeline input
# remains eligible only through 100 because extraction/skill/intake reject
# 101 before history is reached.
FULL_PIPELINE_ELIGIBLE_MAX_ITEMS = 100
ISOLATED_HISTORY_ONLY_COUNTS = (101,)


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
    """Classify one probe count against current data-path truth.

    The returned object is a test-only inventory verdict, not live routing.
    ``history_snapshot_accepts_isolated`` deliberately differs from
    ``full_pipeline_input_eligible`` at 101: history alone can persist 101,
    while full-pipeline input is rejected upstream at 100.
    """
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise ValueError("probe count must be a positive integer")
    return {
        "extraction_accepts": count <= EXPECTED_EXTRACTION_MAX_ITEMS,
        "skill_semantics_accepts": (
            count <= EXPECTED_SAVED_SKILL_SEMANTIC_MAX_ITEMS
        ),
        "server_intake_accepts": (
            count <= EXPECTED_SERVER_CONVERSATION_MAX_ITEMS
        ),
        "history_items_accept": count <= EXPECTED_SERVER_HISTORY_MAX_ITEMS,
        "full_pipeline_input_eligible": (
            count <= FULL_PIPELINE_ELIGIBLE_MAX_ITEMS
        ),
        "isolated_history_only": count in ISOLATED_HISTORY_ONLY_COUNTS,
        "sol_certified_accepts": (
            count <= EXPECTED_CERTIFIED_SOL_MAX_ITEM_ROWS
        ),
        "requires_sol_extension": (
            count > EXPECTED_CERTIFIED_SOL_MAX_ITEM_ROWS
        ),
        "requires_glm_or_html_fallback": False,
    }


def sol_input_output_contract() -> dict[str, object]:
    """Return a DESIGN/INTERFACE manifest for the LOCAL1 Sol handoff.

    This only declares fields; it does not execute QuoteCore, Saved Skill,
    or Sol integration. Actual 4+ row Sol PDF behavior stays LOCAL1-owned
    and unverified here.
    """
    return {
        "kind": "design_interface_manifest_only",
        "implemented_sol_integration": False,
        "verified_sol_multipage_pdf": False,
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
    "EXPECTED_BUNDLE_SUPPORTED_SCOPE_MAX_ITEM_ROWS",
    "EXPECTED_CERTIFIED_PDF_REQUEST_BYTES",
    "EXPECTED_CERTIFIED_PDF_RESPONSE_BYTES",
    "EXPECTED_CERTIFIED_SOL_MAX_ITEM_ROWS",
    "EXPECTED_EXTRACTION_MAX_ITEMS",
    "EXPECTED_SAVED_SKILL_ENVELOPE_BYTES",
    "EXPECTED_SAVED_SKILL_SEMANTIC_MAX_ITEMS",
    "EXPECTED_SERVER_CONVERSATION_MAX_ITEMS",
    "EXPECTED_SERVER_HISTORY_MAX_ITEMS",
    "EXPECTED_SERVER_HISTORY_SNAPSHOT_BYTES",
    "EXTRACTION_MAX_ITEMS",
    "FULL_PIPELINE_ELIGIBLE_MAX_ITEMS",
    "ISOLATED_HISTORY_ONLY_COUNTS",
    "PROBE_ITEM_COUNTS",
    "SAVED_SKILL_ENVELOPE_BYTES",
    "SAVED_SKILL_SEMANTIC_MAX_ITEMS",
    "SERVER_CONVERSATION_MAX_ITEMS",
    "SERVER_HISTORY_MAX_ITEMS",
    "SERVER_HISTORY_SNAPSHOT_BYTES",
    "classify_probe_count",
    "sol_input_output_contract",
]

