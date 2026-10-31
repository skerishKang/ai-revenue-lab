"""The B71 ERP-side adapter delegates to the ERP item-master app."""

from __future__ import annotations

import csv
from pathlib import Path

from erp_item_master_adapter import (
    ERROR_MISSING_ARGUMENT,
    ERROR_OK,
    ERROR_SOURCE_UNREADABLE,
    ERROR_UNKNOWN_WORKFLOW_KIND,
    ERROR_UNSUPPORTED_ACTION,
    ERP_ITEM_MASTER_ACTION,
    ERP_ITEM_MASTER_WORKFLOW_KIND,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_REJECTED,
    job_contract_summary,
    run_erp_item_master_job,
)

import pytest

SOURCE_HEADERS = "품목코드,상품명,매입가,판매가,단위\n"
SOURCE_ROWS = (
    "BRG-1,볼 베어링,8500,12000,EA\n"
    "BRG-2,유압호스,32000,45000,본\n"
)


@pytest.fixture()
def catalog(tmp_path) -> Path:
    path = tmp_path / "source.csv"
    path.write_text(SOURCE_HEADERS + SOURCE_ROWS, encoding="utf-8-sig")
    return path


def _run(catalog: Path, output_root: Path, **overrides):
    payload = {
        "workspace_id": "ws-1",
        "job_id": "job-1",
        "workflow_kind": ERP_ITEM_MASTER_WORKFLOW_KIND,
        "source_ref": str(catalog),
        "requested_action": ERP_ITEM_MASTER_ACTION,
        "output_dir": str(output_root),
    }
    payload.update(overrides)
    return run_erp_item_master_job(**payload)


def test_a_completed_job_returns_the_b71_result_fields(catalog, tmp_path) -> None:
    result = _run(catalog, tmp_path / "out")

    assert result["status"] == STATUS_COMPLETED
    assert result["error_code"] == ERROR_OK
    assert result["output_refs"]
    assert result["validation_findings"]
    assert result["human_review_needed"] is False
    assert Path(result["execution_evidence_ref"]).is_file()


def test_the_job_writes_the_real_import_file(catalog, tmp_path) -> None:
    result = _run(catalog, tmp_path / "out")

    import_files = [Path(path) for path in result["output_refs"] if path.endswith(".csv")]
    assert import_files
    for path in import_files:
        assert path.is_file()


def test_a_job_writes_only_inside_its_own_output_directory(catalog, tmp_path) -> None:
    root = tmp_path / "out"
    result = _run(catalog, root, job_id="job-a")

    for path in result["output_refs"]:
        assert Path(path).is_relative_to(root.resolve())
    assert (root / "ws-1-job-a").is_dir()


def test_two_jobs_for_two_workspaces_do_not_share_an_output_directory(catalog, tmp_path) -> None:
    root = tmp_path / "out"
    first = _run(catalog, root, workspace_id="ws-a", job_id="job-1")
    second = _run(catalog, root, workspace_id="ws-b", job_id="job-1")

    first_root = Path(first["execution_evidence_ref"]).parent
    second_root = Path(second["execution_evidence_ref"]).parent
    assert first_root != second_root


def test_an_unknown_workflow_kind_is_rejected(catalog, tmp_path) -> None:
    result = _run(catalog, tmp_path / "out", workflow_kind="something_else")

    assert result["status"] == STATUS_REJECTED
    assert result["error_code"] == ERROR_UNKNOWN_WORKFLOW_KIND
    assert result["output_refs"] == []


def test_an_unsupported_action_is_rejected(catalog, tmp_path) -> None:
    result = _run(catalog, tmp_path / "out", requested_action="delete_everything")

    assert result["status"] == STATUS_REJECTED
    assert result["error_code"] == ERROR_UNSUPPORTED_ACTION


def test_a_missing_argument_is_rejected(catalog, tmp_path) -> None:
    result = _run(catalog, tmp_path / "out", workspace_id="")

    assert result["status"] == STATUS_REJECTED
    assert result["error_code"] == ERROR_MISSING_ARGUMENT


def test_an_unreadable_source_is_reported_as_a_failure(tmp_path) -> None:
    result = _run(tmp_path / "없음.csv", tmp_path / "out")

    assert result["status"] == STATUS_FAILED
    assert result["error_code"] == ERROR_SOURCE_UNREADABLE


def test_the_adapter_delegates_to_the_existing_erp_item_master_app() -> None:
    summary = job_contract_summary()

    assert summary["delegates_to"] == "apps/erp-item-master"
    assert summary["workflow_kind"] == ERP_ITEM_MASTER_WORKFLOW_KIND


def test_the_adapter_does_not_reimplement_the_pipeline() -> None:
    """The adapter must not own a second normalization or export path."""

    source = (
        Path(__file__).resolve().parents[1] / "erp_item_master_adapter.py"
    ).read_text(encoding="utf-8")

    for forbidden in ("def normalize_", "def parse_price", "def detect_duplicates", "openpyxl"):
        assert forbidden not in source
