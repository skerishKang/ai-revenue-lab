#!/usr/bin/env python3
"""Static contract tests for the GCP Seoul N2 source-only live gate."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/b54-gcp-seoul-n2-live-probe-gate.yml"
MODULE = ROOT / "apps/korean-ai-code-agent/src/kagent/gcp_seoul_n2_live_gate.py"
TEST = ROOT / "apps/korean-ai-code-agent/tests/test_gcp_seoul_n2_live_gate.py"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_pull_request_is_source_only_and_push_is_absent() -> None:
    workflow = text(WORKFLOW)
    trigger = workflow.split("\non:\n", 1)[1].split("\npermissions:\n", 1)[0]
    assert "pull_request:" in trigger
    assert "push:" not in trigger
    source = workflow.split("\n  source-contract:\n", 1)[1].split("\n  future-live-probe:\n", 1)[0]
    assert "test_gcp_seoul_n2_live_gate.py" in source
    assert "PROVIDER_CALLS=0" in source
    assert "WORKFLOW_DISPATCH=0" in source


def test_live_job_is_dispatch_only_and_not_implemented() -> None:
    workflow = text(WORKFLOW)
    live = workflow.split("\n  future-live-probe:\n", 1)[1]
    assert "github.event_name == 'workflow_dispatch'" in live
    assert "LIVE_PROVIDER_CALL=BLOCKED_NOT_IMPLEMENTED" in live
    assert "GCP_VM_CREATE=0" in live
    assert "GCP_DISK_CREATE=0" in live
    assert "GCP_VPC_CREATE=0" in live
    assert "GCP_SERVICE_ACCOUNT_CREATE=0" in live
    assert "gh workflow run" not in workflow
    assert "gcloud" not in workflow


def test_exact_main_confirmation_zone_ttl_and_delete_guards_are_present() -> None:
    workflow = text(WORKFLOW)
    for marker in (
        "EXACT_MAIN_GUARD=PASS",
        "CENTRAL_CONFIRMATION=PASS",
        "SEOUL_ZONE_BOUND=PASS",
        "TTL_DELETE_GUARD=PASS",
        "CENTRAL_GCP_N2_LIVE_PROBE=YES",
        "git rev-parse origin/main",
        "asia-northeast3-a|asia-northeast3-b|asia-northeast3-c",
        "test \"${TTL_SECONDS}\" -le 900",
    ):
        assert marker in workflow, marker
    assert 'max_run_duration_action="DELETE"' in text(MODULE)


def test_source_module_has_no_provider_transport_or_secret_material() -> None:
    module = text(MODULE)
    forbidden = (
        "google.auth",
        "googleapiclient",
        "requests.get",
        "requests.post",
        "subprocess",
        "os.environ",
        "credential_value",
        "service_account_key",
        "project_id",
        "raw_provider_payload",
    )
    for token in forbidden:
        assert token not in module, token
    assert "GCP_N2_PROVIDER_CALLS = 0" in module
    assert "GCP_N2_LIVE_DISPATCH_TRIGGERED = False" in module


def test_runtime_controls_remain_explicit_and_unproven() -> None:
    module = text(MODULE)
    for token in (
        "metadata_negative_test_required",
        "process_tree_death_required",
        "non_resurrection_required",
        "single_fresh_resource_lineage",
        "cleanup_mandatory",
        "validate_gcp_seoul_n2_request_shape",
    ):
        assert token in module, token


def test_workflow_does_not_expose_secrets_or_authorities() -> None:
    workflow = text(WORKFLOW)
    assert "secrets." not in workflow
    assert "GCP_SERVICE_ACCOUNT_CREATE=0" in workflow
    assert "CREDENTIAL_VALUE" not in workflow
    assert "actions: write" not in workflow
    assert "contents: write" not in workflow


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"{len(tests)} static GCP gate contract tests passed")
