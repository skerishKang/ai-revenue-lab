"""#3933 proposal validation; no XLSX/Drive/Office execution authority."""
from __future__ import annotations

from dataclasses import replace
import copy
from pathlib import Path

import pytest

from kagent.artifact_registration import CanonicalArtifactRecord
from app.claw_document_edit_plan import (
    DocumentEditPlanRejected,
    DocumentEditProposal,
    validate_document_edit_proposal,
)

SHA = "c" * 64
MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MODEL = "provider/Owner-Selected-Model.v1"


def source() -> CanonicalArtifactRecord:
    return CanonicalArtifactRecord(
        artifact_id="xlsx_source_3933",
        artifact_kind="source.xlsx",
        filename="invoice.xlsx",
        media_type=MIME,
        size_bytes=350,
        integrity_ref=SHA,
        workspace_ref="workspace_3933",
        run_ref="run_3933",
    )


def proposal():
    return {
        "source_artifact_id": "xlsx_source_3933",
        "source_sha256": SHA,
        "model_id": MODEL,
        "requested_edits": [
            {"field": "institution_name", "value": "광주대학교"},
            {"field": "supply_amount", "value": 99200000},
        ],
        "output_formats": ["xlsx", "pdf"],
        "preserve_unrequested": True,
        "overwrite_original": False,
    }


def parse(payload=None, *, src=None, workspace_ref="workspace_3933", run_ref="run_3933",
          selected_model_id=MODEL):
    return validate_document_edit_proposal(
        proposal() if payload is None else payload,
        trusted_source=source() if src is None else src,
        workspace_ref=workspace_ref,
        run_ref=run_ref,
        selected_model_id=selected_model_id,
    )


def reject(changes=None, **kwargs):
    value = proposal()
    value.update(changes or {})
    with pytest.raises(DocumentEditPlanRejected):
        parse(value, **kwargs)


def test_bounded_hark_example_keeps_exact_two_edits_and_model():
    result = parse()
    assert isinstance(result, DocumentEditProposal)
    assert tuple(x.field for x in result.edits) == ("institution_name", "supply_amount")
    assert tuple(x.value for x in result.edits) == ("광주대학교", 99200000)
    assert result.output_formats == ("xlsx", "pdf")
    assert result.model_id == MODEL
    assert result.integrity_ref == SHA
    projection = result.public_projection()
    assert projection["file_modified"] is False
    assert projection["fidelity_verified"] is False
    assert projection["authorization_minted"] is False
    assert projection["overwrite_original"] is False
    assert projection["requested_edit_fields"] == ["institution_name", "supply_amount"]
    assert "광주대학교" not in str(projection)


def test_trusted_workspace_run_record_must_match_and_not_be_pdf_or_docx():
    for edit in (
        {"workspace_ref": "foreign_workspace"},
        {"run_ref": "old_run"},
        {"artifact_kind": "output.pdf"},
        {"media_type": "application/pdf"},
        {"filename": "quote.xls"},
    ):
        reject(src=replace(source(), **edit))
    reject(workspace_ref="foreign_workspace")
    reject(run_ref="run_not_current")


def test_model_cannot_auto_select_fallback_or_change_identity():
    reject({"model_id": "other-provider/model"})
    reject(selected_model_id="")
    reject({"fallback_model_id": "other"})
    reject({"model_id": None})
    reject({"model_id": "provider/model", "source_artifact_id": "another"})


def test_hash_drift_or_spoofed_source_rejected():
    reject({"source_sha256": "d" * 64})
    reject({"source_artifact_id": "another_artifact"})
    reject(src=replace(source(), integrity_ref="f" * 64))


def test_never_allow_inplace_overwrite_or_unknown_plan_fields():
    reject({"overwrite_original": True})
    reject({"preserve_unrequested": False})
    reject({"permission": "approve"})
    reject({"tool": "run"})
    reject({"recipient": "external@example.org"})


def test_reject_duplicate_unbounded_or_ambiguous_semantic_edit_fields():
    reject({"requested_edits": []})
    reject({"requested_edits": [
        {"field": "name", "value": "A"}, {"field": "name", "value": "B"}]})
    reject({"requested_edits": [{"field": "A1:B4", "value": "ABC"}]})
    reject({"requested_edits": [{"field": "../../docs", "value": "ABC"}]})
    reject({"requested_edits": [{"field": "school", "value": "ABC", "cell": "A1"}]})
    reject({"requested_edits": [{"field": "x"+str(i), "value": "z"} for i in range(17)]})


def test_formula_and_csv_injection_literals_fail_closed():
    for attack in ("=1+1", "  =HYPERLINK(1)", "+cmd", "-cmd", "@SUM(A1:A2)", "a\nb", ""):
        reject({"requested_edits": [{"field": "name", "value": attack}]})


def test_money_values_cannot_use_unbounded_or_imprecise_scalars():
    for number in (99.2, 1e99, True, None, -10**16, 10**16):
        reject({"requested_edits": [{"field": "supply_amount", "value": number}]})


def test_no_pdf_only_silent_xlsx_replacement_or_unapproved_output_type():
    for formats in ([], ["docx"], ["xls"], ["xlsx", "xlsx"], ["xlsx", "pdf", "txt"]):
        reject({"output_formats": formats})
    assert parse({**proposal(), "output_formats": ["pdf"]}).output_formats == ("pdf",)


def test_bounded_plan_does_not_execute_or_store_artifact():
    root = Path(__file__).resolve().parents[1] / "app"
    content = (root / "claw_document_edit_plan.py").read_text(encoding="utf-8")
    for forbidden in (
        "openpyxl", "requests.", "httpx.", "zipfile", "Workbooks.Open",
        "save_workbook", "put_generated_docx", "send_to", "DriveArtifact",
    ):
        assert forbidden not in content
    assert "authorization_minted" in content
    assert "file_modified" in content
    assert "kagent.artifact_registration" in content
