"""#2831 Claw supplier quote comparison UI contracts.

The backend comparison route is covered by ``test_claw_quote_compare_http``.
This file guards the static UI wiring and the product-safety boundary around
that existing route: captured facts only, at least two suppliers, draft-only
negotiation, and the existing artifact download endpoint.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
MODULE = (STATIC / "claw-quote-compare.js").read_text(encoding="utf-8")
CSS = (STATIC / "claw-quote-compare.css").read_text(encoding="utf-8")
LOCALE = (STATIC / "locale.js").read_text(encoding="utf-8")


def test_compare_surface_is_wired_as_a_separate_claw_static_module() -> None:
    assert 'id="clawQuoteCompare"' in INDEX
    assert 'id="clawQuoteCompareForm"' in INDEX
    assert 'id="clawQcSuppliers"' in INDEX
    assert 'id="clawQcCompareBtn"' in INDEX
    assert 'id="clawQcDocxBtn"' in INDEX
    assert 'id="clawQcDownloadBtn"' in INDEX
    assert '<link rel="stylesheet" href="./claw-quote-compare.css" />' in INDEX
    assert '<script src="./claw-quote-compare.js"></script>' in INDEX
    assert INDEX.count('id="clawQuoteCompare"') == 1
    assert INDEX.count('id="clawQuoteCompareForm"') == 1


def test_supplier_inputs_have_explicit_labels_and_captured_date_field() -> None:
    for field in (
        "claw-qc-field-name", "claw-qc-field-item", "claw-qc-field-unit",
        "claw-qc-field-quantity", "claw-qc-field-total", "claw-qc-field-delivery",
        "claw-qc-field-payment", "claw-qc-field-due", "claw-qc-field-prepaid",
        "claw-qc-field-evidence",
    ):
        assert field in MODULE
    assert 'node.type = type' in MODULE
    assert 'input("date", "claw-qc-delivery"' in MODULE
    assert 'promised_delivery_date = row.delivery.value' in MODULE
    assert "Lead-time text is never converted" in MODULE
    assert "리드타임" in INDEX


def test_client_requires_two_suppliers_and_preserves_missing_values() -> None:
    assert "const MIN_SUPPLIERS = 2" in MODULE
    assert "const MAX_SUPPLIERS = 10" in MODULE
    assert "entries.length < MIN_SUPPLIERS" in MODULE
    assert "supplier_price_missing" in MODULE
    assert "if (unit) entry.unit_price_minor" in MODULE
    assert "if (total) entry.total_minor" in MODULE
    assert "if (row.delivery.value) entry.promised_delivery_date" in MODULE
    assert "row.delivery.value ||" not in MODULE
    assert "new Date" not in MODULE


def test_comparison_uses_existing_backend_and_artifact_download_contract() -> None:
    assert 'const ROUTE = "/api/claw/manual-intake/quote-compare"' in MODULE
    assert 'const ARTIFACT_ROUTE = "/api/claw/manual-intake/artifact/"' in MODULE
    assert 'artifact: "docx"' in MODULE
    assert 'DOCUMENT_ID = /^doc_[A-Za-z0-9]{32}$/' in MODULE
    assert 'fetch(`${ARTIFACT_ROUTE}${encodeURIComponent(artifact.document_id)}`' in MODULE
    assert 'anchor.download = artifact.filename' in MODULE
    assert "workspace_document_store" not in MODULE
    assert "createClawRun" not in MODULE


def test_negotiation_is_explicitly_draft_only_without_external_actions() -> None:
    assert 'negotiation.status === "draft_only"' in MODULE
    assert 'text("claw-qc-draft")' in MODULE
    assert 'text("claw-qc-no-external")' in MODULE
    assert 'id="clawQcCompareBtn"' in INDEX
    assert 'id="clawQcDocxBtn"' in INDEX
    # No actionable send, order-submit, or purchase control is present.
    assert not re.search(r'<button[^>]+>(?:[^<]*(?:send|purchase|order submit)[^<]*)</button>', INDEX, re.I)


def test_result_projection_is_text_only_and_mobile_focus_tokens_exist() -> None:
    assert "textContent" in MODULE
    assert "innerHTML" not in MODULE
    assert "replaceChildren" in MODULE
    for token in ("focus-visible", "min-height: 2.75rem", "@media (max-width: 920px)", "@media (max-width: 560px)"):
        assert token in CSS
    assert ".app-shell:not([data-state=\"claw\"]) .claw-quote-compare" in CSS


def test_new_locale_keys_exist_in_both_languages() -> None:
    keys = set(re.findall(r'"(claw-qc-[^"]+)"\s*:', MODULE))
    assert keys
    ko, en = LOCALE.split("    en: {", 1)
    for key in keys:
        assert f'"{key}"' in ko, key
        assert f'"{key}"' in en, key
