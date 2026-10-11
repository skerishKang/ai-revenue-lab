"""#3934 version cards: canonical lineage only, no false original-preserved claim."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
from pathlib import Path

import pytest
from kagent.artifact_lineage import ArtifactLineage, LineageArtifactRef
from kagent.artifact_registration import (
    ArtifactLocation, ArtifactLifecycle, CanonicalArtifactRecord,
)
from app.claw_artifact_lineage_display import (
    LineageDisplayDenied, build_authorized_lineage_display,
)

SOURCE_BYTES = b"original verified workbook bytes"
SOURCE_SHA = hashlib.sha256(SOURCE_BYTES).hexdigest()
SHA_WORK = "b" * 64
SHA_PDF = "c" * 64
SCOPE = "workspace_hark"
RUN = "run_hark"
NOW = datetime(2026, 10, 10, 0, 0, tzinfo=timezone.utc)


def record(artifact_id, sha, name, kind, *, mime="application/pdf",
           workspace=SCOPE, run=RUN, size=21):
    return CanonicalArtifactRecord(
        artifact_id=artifact_id,
        artifact_kind=kind,
        filename=name,
        media_type=mime,
        size_bytes=size,
        integrity_ref=sha,
        workspace_ref=workspace,
        run_ref=run,
    )


def fixture(working=True, *, duplicates=False):
    orig = record("source_original", SOURCE_SHA, "quote.xlsx", "source.xlsx",
                  mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                  size=len(SOURCE_BYTES))
    edited = record("working_copy", SHA_WORK, "quote-updated.xlsx", "working.xlsx",
                    mime=orig.media_type)
    pdf = record("output_pdf", SHA_PDF, "quote.pdf", "output.pdf")
    if duplicates:
        pdf = replace(pdf, filename="QUOTE.XLSX")
    kwargs = dict(lineage_id="lineage_hark", source=orig,
                  transformation_kind="xlsx.office_pdf",
                  workspace_ref=SCOPE, run_ref=RUN, created_at=NOW,
                  outputs=(pdf,))
    if working:
        kwargs["working"] = edited
    relation = ArtifactLineage(**kwargs)
    records = {orig.artifact_id: orig, pdf.artifact_id: pdf}
    if working:
        records[edited.artifact_id] = edited
    return relation, records


def display(relation=None, records=None, proof=None, **kwargs):
    lin, rows = fixture()
    return build_authorized_lineage_display(
        lineage=lin if relation is None else relation,
        owner_resolved_records=rows if records is None else records,
        authorized_workspace_ref=kwargs.get("workspace_ref", SCOPE),
        authorized_run_ref=kwargs.get("run_ref", RUN),
        verified_source_bytes=proof,
    )


def test_source_working_pdf_versions_shown_without_false_preservation():
    result = display()
    assert [x["role"] for x in result["cards"]] == [
        "original", "working_copy", "output",
    ]
    assert [x["filename"] for x in result["cards"]] == [
        "quote.xlsx", "quote-updated.xlsx", "quote.pdf",
    ]
    assert result["source_integrity_verified_now"] is False
    assert result["original_preserved_claim_allowed"] is False
    assert result["all_open_download_restore_actions_disabled"] is True
    for card in result["cards"]:
        assert card["open_available"] is False
        assert card["download_available"] is False
        assert card["restore_available"] is False
        assert "location_ref" not in card


def test_real_same_original_bytes_enable_only_integrity_claim():
    result = display(proof=SOURCE_BYTES)
    assert result["source_integrity_verified_now"] is True
    assert result["original_preserved_claim_allowed"] is True
    assert result["all_open_download_restore_actions_disabled"] is True
    assert result["source_content_exposed"] is False
    assert str(SOURCE_BYTES) not in str(result)


def test_modified_original_fails_closed_instead_of_claiming_preserved():
    with pytest.raises(LineageDisplayDenied, match="source content proof mismatch"):
        display(proof=b"changed source")


def test_missing_record_extra_record_and_malformed_ref_are_denied():
    lineage, rows = fixture()
    with pytest.raises(LineageDisplayDenied):
        display(relation=lineage, records={lineage.source.artifact_id: rows[lineage.source.artifact_id]})
    with pytest.raises(LineageDisplayDenied):
        display(relation=lineage, records={**rows, "unexpected": rows["output_pdf"]})
    with pytest.raises(LineageDisplayDenied):
        display(relation=lineage, records={**rows, "output_pdf": rows["working_copy"]})


def test_cross_workspace_and_run_are_rejected_before_projection():
    relation, rows = fixture()
    with pytest.raises(LineageDisplayDenied):
        display(relation=relation, records=rows, workspace_ref="workspace_elsewhere")
    with pytest.raises(LineageDisplayDenied):
        display(relation=relation, records=rows, run_ref="other_run")
    with pytest.raises(LineageDisplayDenied):
        display(relation=relation, records={
            **rows, "output_pdf": replace(rows["output_pdf"], workspace_ref="foreign")
        })
    with pytest.raises(LineageDisplayDenied):
        display(relation=relation, records={
            **rows, "working_copy": replace(rows["working_copy"], run_ref="foreign_run")
        })


def test_duplicate_filename_requires_explicit_target_selection():
    relation, rows = fixture(duplicates=True)
    result = display(relation=relation, records=rows)
    assert result["duplicate_name_needs_selection"] is True
    assert len(result["ambiguous_filenames"]) == 2


def test_direct_source_to_pdf_valid_without_fake_working_copy():
    relation, rows = fixture(working=False)
    result = display(relation=relation, records=rows)
    assert [x["role"] for x in result["cards"]] == ["original", "output"]
    assert result["has_registered_working_copy"] is False


def test_ephemeral_working_ref_never_exposed():
    relation, rows = fixture(working=False)
    relation = replace(relation, working_representation_ref="opaque_hark_888")
    result = display(relation=relation, records=rows)
    assert result["has_ephemeral_working_representation"] is True
    assert "opaque_hark_888" not in str(result)


def test_durable_location_kind_never_grants_download_and_raw_ref_hidden():
    relation, rows = fixture()
    rows["output_pdf"] = replace(rows["output_pdf"], lifecycle=ArtifactLifecycle.DURABLE,
                                 durable_location=ArtifactLocation(
                                     location_kind="google_drive", location_ref="drive-private-opaque-ref"))
    result = display(relation=relation, records=rows)
    assert "drive-private-opaque-ref" not in str(result)
    assert result["cards"][-1]["lifecycle"] == "durable"
    assert result["cards"][-1]["download_available"] is False


def test_pure_projection_no_side_effects():
    source = (Path(__file__).resolve().parents[1] / "app" / "claw_artifact_lineage_display.py").read_text(encoding="utf-8")
    for disallowed in ("open(", "fetch(", "requests.", "httpx.", "r2_bucket",
                       "googleapiclient", "os.environ", "chmod", "permission_grant",
                       "set_cookie"):
        assert disallowed not in source
    assert "kagent.artifact_lineage" in source
    assert "kagent.artifact_registration" in source
