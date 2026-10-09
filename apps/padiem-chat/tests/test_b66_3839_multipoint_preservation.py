"""Offline B66 #3839 multi-item preservation contract tests (LOCAL2 only).

No browser, D1, PDF rendering, model call, or LOCAL1 renderer change.
"""

from __future__ import annotations

import json

import pytest

from app.b66_multipoint_preservation import (
    B66_MULTI_ITEM_CUTOFFS,
    CERTIFIED_PDF_REQUEST_BYTES,
    CERTIFIED_SOL_MAX_ITEM_ROWS,
    PROBE_ITEM_COUNTS,
    SAVED_SKILL_ENVELOPE_BYTES,
    SERVER_HISTORY_SNAPSHOT_BYTES,
    classify_probe_count,
    sol_input_output_contract,
)
from app.b66_quote_conversation import MAX_ITEMS as SERVER_INTAKE_MAX
from app.b66_quote_history_store import (
    MAX_ITEMS as HISTORY_MAX,
    MAX_SNAPSHOT_JSON_BYTES,
    normalize_quote_draft_snapshot,
)


def _items(count: int) -> list[dict[str, object]]:
    return [
        {"name": "품목%03d" % (i + 1), "qty": 2, "unitPrice": 15000}
        for i in range(count)
    ]


def test_probe_matrix_matches_source_cutoffs():
    assert PROBE_ITEM_COUNTS == (1, 3, 4, 10, 25, 100, 101)
    assert SERVER_INTAKE_MAX == 100
    assert HISTORY_MAX == 200
    assert MAX_SNAPSHOT_JSON_BYTES == SERVER_HISTORY_SNAPSHOT_BYTES
    for count in PROBE_ITEM_COUNTS:
        verdict = classify_probe_count(count)
        assert verdict["extraction_accepts"] == (count <= 100)
        assert verdict["server_intake_accepts"] == (count <= 100)
        assert verdict["history_items_accept"] == (count <= 200)
        assert verdict["sol_certified_accepts"] == (count <= 3)
        assert verdict["requires_sol_extension"] == (count > 3)
        assert verdict["requires_glm_or_html_fallback"] is False


def test_history_snapshot_preserves_all_in_scope_items_offline():
    for count in PROBE_ITEM_COUNTS:
        payload = {"recipient": {"company": "B"}, "items": _items(count)}
        snapshot = normalize_quote_draft_snapshot(payload)
        body = json.loads(snapshot.serialized_json)
        assert len(body["items"]) == count
        assert [row["name"] for row in body["items"]] == [
            "품목%03d" % (i + 1) for i in range(count)
        ]
        assert len(snapshot.serialized_json.encode("utf-8")) <= (
            SERVER_HISTORY_SNAPSHOT_BYTES
        )


def test_pdf_request_and_skill_envelopes_fit_probe_payloads():
    for count in PROBE_ITEM_COUNTS:
        minimal = {
            "saved_skill_id": "b66skill_" + "a" * 32,
            "render_model": {"items": _items(count)},
        }
        size = len(json.dumps(minimal, ensure_ascii=False).encode("utf-8"))
        assert size < CERTIFIED_PDF_REQUEST_BYTES
        assert size < SAVED_SKILL_ENVELOPE_BYTES


def test_sol_contract_never_selects_alternate_renderer():
    contract = sol_input_output_contract()
    assert contract["output"]["sol_renderer_owner"] == "LOCAL1"
    assert contract["output"]["render_model_calls"] == 0
    assert contract["output"]["provider_calls"] == 0
    assert contract["output"]["alternate_renderer_fallback"] is False
    assert CERTIFIED_SOL_MAX_ITEM_ROWS == 3
    assert B66_MULTI_ITEM_CUTOFFS[0].max_items == 100


def test_invalid_probe_count_rejected():
    for bad in (0, -1, True, "4", None):
        with pytest.raises(ValueError):
            classify_probe_count(bad)  # type: ignore[arg-type]
