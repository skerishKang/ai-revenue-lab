from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "b67-drive-case-folder-d1-readonly-gate.yml"
BINDING_SOURCE = ROOT / "apps" / "padiem-ai-engine" / "app" / "drive_case_folder_binding.py"
DOCUMENT_REFERENCE = ROOT / "apps" / "padiem-ai-engine" / "app" / "document_reference.py"


def test_d1_readonly_gate_is_manual_for_live_and_source_only_on_pr() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "\n  push:\n    branches:\n      - main\n" in workflow
    assert "github.event_name == 'workflow_dispatch'" in workflow
    assert "RUN_B67_D1_READONLY_ONCE" in workflow
    assert "environment: production" in workflow
    assert "expected_main_sha" in workflow
    assert "phase:" in workflow
    assert "select_a" in workflow
    assert "replace_b" in workflow
    assert "clear" in workflow


def test_d1_readonly_gate_reuses_existing_engine_store_and_table() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    binding = BINDING_SOURCE.read_text(encoding="utf-8")
    document_reference = DOCUMENT_REFERENCE.read_text(encoding="utf-8")
    assert 'BINDING_TABLE_NAME = "padiem_engine_drive_case_folder_bindings"' in binding
    assert 'DOCUMENT_STORE_BINDING_NAME = "ENGINE_DOCUMENT_STORE"' in document_reference
    assert "padiem_engine_drive_case_folder_bindings" in workflow
    assert "ENGINE_DOCUMENT_STORE" in workflow
    assert "padiem-ai-engine" in workflow


def test_live_query_region_is_select_only_and_identifier_blind() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    live_region = workflow.split("Read bounded case-folder D1 phase state", 1)[-1]
    upper = live_region.upper()
    forbidden_sql = (
        "INSERT " + "INTO",
        "UP" + "DATE ",
        "DE" + "LETE FROM",
        "RE" + "PLACE INTO",
        "DR" + "OP TABLE",
        "AL" + "TER TABLE",
        "CREATE " + "TABLE",
        "CREATE " + "INDEX",
    )
    for token in forbidden_sql:
        assert token not in upper

    for sensitive_column in (
        "workspace_ref",
        "project_id",
        "drive_binding_ref",
        "selected_folder_id",
        "shared_drive_id",
    ):
        assert sensitive_column not in live_region

    assert "COUNT(*) AS total_rows" in live_region
    assert "active_count" in live_region
    assert "canonical_connector_count" in live_region
    assert "created_equals_updated_count" not in live_region
    assert "updated_after_created_count" not in live_region


def test_phase_expectations_and_privacy_markers_are_pinned() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    required = (
        '"select_a": (1, 1, 1)',
        '"replace_b": (1, 1, 1)',
        '"clear": (1, 0, 1)',
        "D1_QUERY_MODE=READ_ONLY",
        "D1_MUTATION=0",
        "PRODUCTION_MUTATION=0",
        "PRODUCTION_DEPLOY=0",
        "GOOGLE_PROVIDER_CALLS=0",
        "RAW_PROJECT_ID_OUTPUT=0",
        "RAW_FOLDER_ID_OUTPUT=0",
        "RAW_FOLDER_NAME_OUTPUT=0",
        "RAW_WORKSPACE_REF_OUTPUT=0",
        "RAW_DRIVE_BINDING_REF_OUTPUT=0",
        "D1_IDENTIFIER_OUTPUT=0",
        "SECRET_VALUE_OUTPUT=0",
        "ROW_VALUE_OUTPUT=AGGREGATES_ONLY",
    )
    for marker in required:
        assert marker in workflow
