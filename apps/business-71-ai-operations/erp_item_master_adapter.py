"""B71 AI Operations — ERP item-master workstream adapter.

This is the ERP side of the B71 job contract. It owns no normalization, no
duplicate detection and no file writing of its own: every step is delegated to
the existing ``apps/erp-item-master`` implementation, so the B71 workspace and
the ERP workstream cannot drift apart.

The job contract is the one stated in the B71 workspace README
(``apps/business-71-ai-operations/README.md``):

    in : workspace_id, job_id, workflow_kind, source_ref, requested_action
    out: status, output_refs, validation_findings, human_review_needed,
         execution_evidence_ref, error_code

Two boundaries are enforced here rather than left to the caller:

* one job writes only inside the output directory it was given, so a job for
  one workspace can never touch another workspace's files;
* a workflow kind or an action this adapter does not implement is rejected
  with an error code instead of being approximated.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping

#: The repository root, derived from this file's location.
REPO_ROOT = Path(__file__).resolve().parents[2]

#: The ERP item-master app this adapter delegates to.
ERP_ITEM_MASTER_ROOT = REPO_ROOT / "apps" / "erp-item-master"

#: The workflow kind this adapter implements.
ERP_ITEM_MASTER_WORKFLOW_KIND = "erp_item_master_import_prepare"

#: The action this adapter implements.
ERP_ITEM_MASTER_ACTION = "normalize_and_prepare_import"

#: The import profiles this adapter may write.
SUPPORTED_PROFILE_IDS: tuple[str, ...] = ("generic", "ecount_api_candidate")

#: The job status values this adapter returns.
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_REJECTED = "rejected"

#: The error codes this adapter returns.
ERROR_OK = "ok"
ERROR_UNKNOWN_WORKFLOW_KIND = "unknown_workflow_kind"
ERROR_UNSUPPORTED_ACTION = "unsupported_requested_action"
ERROR_MISSING_ARGUMENT = "missing_argument"
ERROR_SOURCE_UNREADABLE = "source_unreadable"
ERROR_JOB_FAILED = "job_failed"

_LOADED_PACKAGE_NAME = "erp_item_master_app"


def _load_erp_item_master() -> ModuleType:
    """Load the ERP item-master package under a name of its own.

    The package is loaded from its path under a unique module name, so it can
    never collide with another app that also ships a top-level ``app``
    package. Its own relative imports keep working because the loaded package
    keeps its own search path.
    """

    existing = sys.modules.get(_LOADED_PACKAGE_NAME)
    if existing is not None:
        return existing

    package_dir = ERP_ITEM_MASTER_ROOT / "app"
    initializer = package_dir / "__init__.py"
    if not initializer.is_file():
        raise ModuleNotFoundError(
            f"The ERP item-master package was not found at {ERP_ITEM_MASTER_ROOT}."
        )

    spec = importlib.util.spec_from_file_location(
        _LOADED_PACKAGE_NAME,
        initializer,
        submodule_search_locations=[str(package_dir)],
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ModuleNotFoundError("The ERP item-master package could not be loaded.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_LOADED_PACKAGE_NAME] = module
    spec.loader.exec_module(module)
    return module


def _job_result(
    *,
    status: str,
    error_code: str,
    output_refs: list[str],
    validation_findings: list[dict[str, Any]],
    human_review_needed: bool,
    execution_evidence_ref: str | None,
    detail: str = "",
) -> dict[str, Any]:
    return {
        "status": status,
        "error_code": error_code,
        "output_refs": output_refs,
        "validation_findings": validation_findings,
        "human_review_needed": human_review_needed,
        "execution_evidence_ref": execution_evidence_ref,
        "detail": detail,
    }


def run_erp_item_master_job(
    *,
    workspace_id: str,
    job_id: str,
    workflow_kind: str,
    source_ref: str,
    requested_action: str,
    output_dir: str | Path,
    extraction_ref: str | Path | None = None,
    profile_ids: tuple[str, ...] = SUPPORTED_PROFILE_IDS,
) -> dict[str, Any]:
    """Run one ERP item-master job through the B71 job contract.

    The returned mapping carries the B71 result fields. Everything the job
    produces is written under ``output_dir``; nothing outside it is touched.
    """

    for name, value in (
        ("workspace_id", workspace_id),
        ("job_id", job_id),
        ("workflow_kind", workflow_kind),
        ("source_ref", source_ref),
        ("requested_action", requested_action),
    ):
        if not isinstance(value, str) or not value.strip():
            return _job_result(
                status=STATUS_REJECTED,
                error_code=ERROR_MISSING_ARGUMENT,
                output_refs=[],
                validation_findings=[],
                human_review_needed=False,
                execution_evidence_ref=None,
                detail=f"{name} is required",
            )

    if workflow_kind != ERP_ITEM_MASTER_WORKFLOW_KIND:
        return _job_result(
            status=STATUS_REJECTED,
            error_code=ERROR_UNKNOWN_WORKFLOW_KIND,
            output_refs=[],
            validation_findings=[],
            human_review_needed=False,
            execution_evidence_ref=None,
            detail=(
                f"{workflow_kind} is not implemented; "
                f"{ERP_ITEM_MASTER_WORKFLOW_KIND} is"
            ),
        )

    if requested_action != ERP_ITEM_MASTER_ACTION:
        return _job_result(
            status=STATUS_REJECTED,
            error_code=ERROR_UNSUPPORTED_ACTION,
            output_refs=[],
            validation_findings=[],
            human_review_needed=False,
            execution_evidence_ref=None,
            detail=(
                f"{requested_action} is not implemented; "
                f"{ERP_ITEM_MASTER_ACTION} is"
            ),
        )

    source_path = Path(source_ref)
    if not source_path.is_file():
        return _job_result(
            status=STATUS_FAILED,
            error_code=ERROR_SOURCE_UNREADABLE,
            output_refs=[],
            validation_findings=[],
            human_review_needed=False,
            execution_evidence_ref=None,
            detail=f"the source catalog was not found: {source_path.name}",
        )

    target_root = Path(output_dir).resolve()
    target_root.mkdir(parents=True, exist_ok=True)
    # One job writes only inside its own output directory, so a job for one
    # workspace can never touch another workspace's files.
    job_root = target_root / f"{workspace_id}-{job_id}"
    job_root.mkdir(parents=True, exist_ok=True)

    package = _load_erp_item_master()
    pipeline = importlib.import_module(f"{_LOADED_PACKAGE_NAME}.pipeline")

    try:
        report = pipeline.run_pipeline(
            source=source_path,
            output_dir=job_root,
            extraction_file=extraction_ref,
            profile_ids=profile_ids,
        )
    except Exception as exc:  # noqa: BLE001 - the contract reports the failure
        code = getattr(exc, "code", type(exc).__name__)
        return _job_result(
            status=STATUS_FAILED,
            error_code=ERROR_JOB_FAILED,
            output_refs=[],
            validation_findings=[
                {"kind": "job_failed", "detail": str(code), "count": 1}
            ],
            human_review_needed=False,
            execution_evidence_ref=None,
            detail="the ERP item-master pipeline failed",
        )

    findings: list[dict[str, Any]] = [
        {
            "kind": "row_count",
            "detail": str(report.row_count),
            "count": report.row_count,
        },
        {
            "kind": "auto_ok_rows",
            "detail": str(report.auto_ok_count),
            "count": report.auto_ok_count,
        },
        {
            "kind": "review_required_rows",
            "detail": str(report.review_required_count),
            "count": report.review_required_count,
        },
        {
            "kind": "duplicate_groups",
            "detail": str(report.duplicate_group_count),
            "count": report.duplicate_group_count,
        },
        {
            "kind": "record_errors",
            "detail": str(report.error_count),
            "count": report.error_count,
        },
    ]
    for record in report.records:
        for reason in record.review_reasons:
            findings.append(
                {
                    "kind": "review_reason",
                    "detail": f"row{record.source_row}:{reason}",
                    "count": 1,
                }
            )

    evidence = job_root / "pipeline_report.json"
    return _job_result(
        status=STATUS_COMPLETED,
        error_code=ERROR_OK,
        output_refs=[str(Path(path).resolve()) for path in report.outputs],
        validation_findings=findings,
        human_review_needed=report.review_required_count > 0,
        execution_evidence_ref=str(evidence.resolve()),
        detail=(
            f"{report.auto_ok_count} of {report.row_count} rows are import-ready, "
            f"{report.review_required_count} need a person"
        ),
    )


def job_contract_summary() -> Mapping[str, Any]:
    """The contract this adapter implements, for a workspace to read."""

    return {
        "workflow_kind": ERP_ITEM_MASTER_WORKFLOW_KIND,
        "requested_action": ERP_ITEM_MASTER_ACTION,
        "input_fields": (
            "workspace_id",
            "job_id",
            "workflow_kind",
            "source_ref",
            "requested_action",
        ),
        "result_fields": (
            "status",
            "output_refs",
            "validation_findings",
            "human_review_needed",
            "execution_evidence_ref",
            "error_code",
        ),
        "delegates_to": "apps/erp-item-master",
    }
