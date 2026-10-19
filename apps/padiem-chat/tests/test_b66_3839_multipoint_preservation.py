"""Offline B66 #3839 source-local preservation tests (LOCAL2 only).

No browser, D1, PDF rendering, model call, or LOCAL1 renderer change.
History assertions are source-local: 101 proves isolated history capacity
only, not full-pipeline eligibility. Size probes below the PDF route use a
synthetic lower-bound payload and never claim real PDF acceptance.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.b66_multipoint_preservation import (
    B66_MULTI_ITEM_CUTOFFS,
    EXPECTED_BUNDLE_SUPPORTED_SCOPE_MAX_ITEM_ROWS,
    EXPECTED_CERTIFIED_PDF_REQUEST_BYTES,
    EXPECTED_CERTIFIED_PDF_RESPONSE_BYTES,
    EXPECTED_CERTIFIED_SOL_MAX_ITEM_ROWS,
    EXPECTED_EXTRACTION_MAX_ITEMS,
    EXPECTED_SAVED_SKILL_ENVELOPE_BYTES,
    EXPECTED_SAVED_SKILL_SEMANTIC_MAX_ITEMS,
    EXPECTED_SERVER_CONVERSATION_MAX_ITEMS,
    EXPECTED_SERVER_HISTORY_MAX_ITEMS,
    EXPECTED_SERVER_HISTORY_SNAPSHOT_BYTES,
    FULL_PIPELINE_ELIGIBLE_MAX_ITEMS,
    ISOLATED_HISTORY_ONLY_COUNTS,
    PROBE_ITEM_COUNTS,
    classify_probe_count,
    sol_input_output_contract,
)
from app import b66_certified_pdf_routes as pdf_routes
from app import b66_quote_conversation as conversation
from app import b66_saved_quote_skill_store as skill_store
from app.b66_quote_conversation import (
    B66QuoteConversationError,
    normalize_conversation_output,
)
from app.b66_quote_history_store import (
    MAX_ITEMS as HISTORY_MAX,
    MAX_SNAPSHOT_JSON_BYTES,
    QuoteHistoryStoreError,
    normalize_quote_draft_snapshot,
)

REFERENCE_DIR = (
    Path(__file__).resolve().parents[3]
    / "reference"
    / "business-66-padiem-quote-v1"
)
RENDERER_DIR = Path(__file__).resolve().parents[3] / "apps" / "b66-pdf-renderer"


def _items(count: int) -> list[dict[str, object]]:
    return [
        {"name": "품목%03d" % (i + 1), "qty": 2, "unitPrice": 15000}
        for i in range(count)
    ]


def _read_js_int(path: str, pattern: str) -> int:
    text = (REFERENCE_DIR / path).read_text(encoding="utf-8")
    match = re.search(pattern, text)
    assert match is not None, path + " owner cutoff not found"
    return int(match.group(1))


def test_python_cutoffs_pin_owning_sources_no_parallel_policy():
    assert conversation.MAX_ITEMS == EXPECTED_SERVER_CONVERSATION_MAX_ITEMS
    assert HISTORY_MAX == EXPECTED_SERVER_HISTORY_MAX_ITEMS
    assert MAX_SNAPSHOT_JSON_BYTES == EXPECTED_SERVER_HISTORY_SNAPSHOT_BYTES
    assert (
        skill_store.MAX_SKILL_JSON_BYTES == EXPECTED_SAVED_SKILL_ENVELOPE_BYTES
    )
    assert (
        pdf_routes.MAX_PDF_REQUEST_BYTES
        == EXPECTED_CERTIFIED_PDF_REQUEST_BYTES
    )
    assert (
        pdf_routes.MAX_PDF_RESPONSE_BYTES
        == EXPECTED_CERTIFIED_PDF_RESPONSE_BYTES
    )


def test_js_cutoffs_read_from_owning_sources():
    assert (
        _read_js_int("quote-extraction.js", r"var MAX_ITEMS = (\d+);")
        == EXPECTED_EXTRACTION_MAX_ITEMS
    )
    assert (
        _read_js_int("quote-skill.js", r"var MAX_ITEMS = (\d+);")
        == EXPECTED_SAVED_SKILL_SEMANTIC_MAX_ITEMS
    )
    renderer = (REFERENCE_DIR / "quote-template-renderer.js").read_text(
        encoding="utf-8"
    )
    assert "var CGI_ROW_BASELINES = Object.freeze([353.61, 375.31, 397.13]);" in (
        renderer
    )
    assert "CGI_MAX_ITEM_ROWS: CGI_ROW_BASELINES.length," in renderer
    assert EXPECTED_CERTIFIED_SOL_MAX_ITEM_ROWS == 3
    bundle = (REFERENCE_DIR / "quote-browser-pdf.js").read_text(
        encoding="utf-8"
    )
    assert "var MAX_ITEM_ROWS = Renderer.CGI_MAX_ITEM_ROWS;" in bundle
    assert EXPECTED_BUNDLE_SUPPORTED_SCOPE_MAX_ITEM_ROWS == 100



def test_standalone_bundle_scope_pins_owner_file_not_inventory():
    text = (RENDERER_DIR / "bundle.py").read_text(encoding="utf-8")
    # apps/b66-pdf-renderer/bundle.py:180-181 owns the real bundle rule.
    # Extract its literal upper bound so a future owner edit fails this test.
    match = re.search(
        r'or type\(scope\.get\("max_item_rows"\)\) is not int\s*\n'
        r'\s+or not 1 <= scope\["max_item_rows"\] <= (\d+)',
        text,
    )
    assert match is not None, "bundle.py owner rule not found at lines 180-181"
    assert int(match.group(1)) == EXPECTED_BUNDLE_SUPPORTED_SCOPE_MAX_ITEM_ROWS
    assert EXPECTED_BUNDLE_SUPPORTED_SCOPE_MAX_ITEM_ROWS == 100
    assert EXPECTED_BUNDLE_SUPPORTED_SCOPE_MAX_ITEM_ROWS <= (
        FULL_PIPELINE_ELIGIBLE_MAX_ITEMS
    )


def test_probe_matrix_marks_101_as_history_only_not_full_pipeline():
    assert PROBE_ITEM_COUNTS == (1, 3, 4, 10, 25, 100, 101)
    assert FULL_PIPELINE_ELIGIBLE_MAX_ITEMS == 100
    assert ISOLATED_HISTORY_ONLY_COUNTS == (101,)
    for count in PROBE_ITEM_COUNTS:
        verdict = classify_probe_count(count)
        assert verdict["extraction_accepts"] == (count <= 100)
        assert verdict["server_intake_accepts"] == (count <= 100)
        assert verdict["history_items_accept"] == (count <= 200)
        assert verdict["full_pipeline_input_eligible"] == (count <= 100)
        assert verdict["isolated_history_only"] == (count == 101)
        assert verdict["sol_certified_accepts"] == (count <= 3)
        assert verdict["requires_sol_extension"] == (count > 3)
        assert verdict["requires_glm_or_html_fallback"] is False


def test_history_snapshot_source_local_includes_101_but_pipeline_rejects_it():
    for count in PROBE_ITEM_COUNTS:
        payload = {"recipient": {"company": "B"}, "items": _items(count)}
        snapshot = normalize_quote_draft_snapshot(payload)
        body = json.loads(snapshot.serialized_json)
        assert len(body["items"]) == count
        assert [row["name"] for row in body["items"]] == [
            "품목%03d" % (i + 1) for i in range(count)
        ]
        assert len(snapshot.serialized_json.encode("utf-8")) <= (
            EXPECTED_SERVER_HISTORY_SNAPSHOT_BYTES
        )
    too_many = {"items": _items(201)}
    with pytest.raises(QuoteHistoryStoreError):
        normalize_quote_draft_snapshot(too_many)
    upstream_rejection = {
        "items": [
            {
                "name": "품목%03d" % (i + 1),
                "qty": 2,
                "unitPrice": 15000,
            }
            for i in range(101)
        ]
    }
    with pytest.raises(B66QuoteConversationError):
        normalize_conversation_output(upstream_rejection)


def test_synthetic_size_lower_bound_is_not_a_real_pdf_request():
    for count in PROBE_ITEM_COUNTS:
        synthetic_minimal = {
            "saved_skill_id": "b66skill_" + "a" * 32,
            "render_model": {"items": _items(count)},
        }
        size = len(
            json.dumps(synthetic_minimal, ensure_ascii=False).encode("utf-8")
        )
        assert size < EXPECTED_CERTIFIED_PDF_REQUEST_BYTES
        assert size < EXPECTED_SAVED_SKILL_ENVELOPE_BYTES
    # Explicit NON_E2E marker: this synthetic dict omits approved Skill,
    # QuoteCore totals, fingerprints, signatures, and route guards, so it
    # cannot prove real 101-item PDF acceptance or readiness.


def test_sol_manifest_declares_fields_without_claiming_integration():
    contract = sol_input_output_contract()
    assert contract["kind"] == "design_interface_manifest_only"
    assert contract["implemented_sol_integration"] is False
    assert contract["verified_sol_multipage_pdf"] is False
    assert contract["output"]["sol_renderer_owner"] == "LOCAL1"
    assert contract["output"]["render_model_calls"] == 0
    assert contract["output"]["provider_calls"] == 0
    assert contract["output"]["alternate_renderer_fallback"] is False
    assert EXPECTED_CERTIFIED_SOL_MAX_ITEM_ROWS == 3
    assert B66_MULTI_ITEM_CUTOFFS[0].max_items == 100


def test_invalid_probe_count_rejected():
    for bad in (0, -1, True, "4", None):
        with pytest.raises(ValueError):
            classify_probe_count(bad)  # type: ignore[arg-type]
