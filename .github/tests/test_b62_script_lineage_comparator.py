"""B62 script lineage comparator contract tests (#2541, SOURCE-ONLY)."""
from __future__ import annotations

import importlib.util
import io
import json
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / ".github" / "scripts" / "b62_script_lineage_comparator.py"
WORKFLOW = ROOT / ".github" / "workflows" / "b62-script-lineage-comparator.yml"

ACTIVE = "c2468c5d-73e1-41fb-9408-565f871a4ad8"
REFERENCE = "cc9f8601-d3ab-4e48-ae4d-249f4d6f090c"
INTERMEDIATE = "4fa6eee9-b47a-4ad0-a73a-ad391a33ee6c"
SECRET_ETAG = "etag-value-must-never-be-printed-1234"
OTHER_ETAG = "another-etag-value-5678"


def _load_helper():
    spec = importlib.util.spec_from_file_location("b62_script_lineage_comparator", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _deployments(version_id=ACTIVE, percentage=100, count=1):
    versions = [{"version_id": version_id, "percentage": percentage}]
    if count > 1:
        versions.append({"version_id": REFERENCE, "percentage": 100 - percentage})
    return {"success": True, "result": {"deployments": [{"versions": versions}]}}


def _detail(etag=SECRET_ETAG):
    return {"success": True, "result": {"resources": {"script": {"etag": etag}}}}


def test_match_yields_exact_closed_vocabulary():
    helper = _load_helper()
    buf = io.StringIO()
    with redirect_stdout(buf):
        verdict = helper.compare_lineage(
            deployments_payload=_deployments(),
            expected_active_version=ACTIVE,
            active_detail_payload=_detail(SECRET_ETAG),
            reference_detail_payload=_detail(SECRET_ETAG),
        )
    out = buf.getvalue()
    assert out == "", out  # compare_lineage never prints
    assert verdict == {
        "ACTIVE_VERSION": ACTIVE,
        "EXPECTED_ACTIVE_VERSION_MATCH": "PASS",
        "ACTIVE_SCRIPT_IDENTITY_PRESENT": "PASS",
        "REFERENCE_SCRIPT_IDENTITY_PRESENT": "PASS",
        "SCRIPT_IDENTITY_EQUAL": "YES",
        "INTERMEDIATE_SCRIPT_IDENTITY_EQUAL": "NOT_CHECKED",
        "B62_SCRIPT_LINEAGE": "MATCH",
    }
    assert SECRET_ETAG not in json.dumps(verdict)


def test_mismatch_yields_no_without_leaking_values():
    helper = _load_helper()
    verdict = helper.compare_lineage(
        deployments_payload=_deployments(),
        expected_active_version=ACTIVE,
        active_detail_payload=_detail(SECRET_ETAG),
        reference_detail_payload=_detail(OTHER_ETAG),
    )
    assert verdict["SCRIPT_IDENTITY_EQUAL"] == "NO"
    assert verdict["B62_SCRIPT_LINEAGE"] == "MISMATCH"
    text = json.dumps(verdict)
    assert SECRET_ETAG not in text and OTHER_ETAG not in text


def test_intermediate_checked_yes_and_no():
    helper = _load_helper()
    verdict = helper.compare_lineage(
        deployments_payload=_deployments(),
        expected_active_version=ACTIVE,
        active_detail_payload=_detail(SECRET_ETAG),
        reference_detail_payload=_detail(OTHER_ETAG),
        intermediate_detail_payload=_detail(SECRET_ETAG),
    )
    assert verdict["INTERMEDIATE_SCRIPT_IDENTITY_EQUAL"] == "YES"
    verdict = helper.compare_lineage(
        deployments_payload=_deployments(),
        expected_active_version=ACTIVE,
        active_detail_payload=_detail(SECRET_ETAG),
        reference_detail_payload=_detail(OTHER_ETAG),
        intermediate_detail_payload=_detail("third-etag-9"),
    )
    assert verdict["INTERMEDIATE_SCRIPT_IDENTITY_EQUAL"] == "NO"


def test_active_drift_and_structural_ambiguity_fail_closed():
    helper = _load_helper()
    with pytest.raises(helper.LineageError):
        helper.compare_lineage(
            deployments_payload=_deployments(version_id=REFERENCE),
            expected_active_version=ACTIVE,
            active_detail_payload=_detail(),
            reference_detail_payload=_detail(),
        )
    with pytest.raises(helper.LineageError):
        helper.compare_lineage(
            deployments_payload=_deployments(percentage=50, count=2),
            expected_active_version=ACTIVE,
            active_detail_payload=_detail(),
            reference_detail_payload=_detail(),
        )
    with pytest.raises(helper.LineageError):
        helper.compare_lineage(
            deployments_payload={"success": False, "result": None},
            expected_active_version=ACTIVE,
            active_detail_payload=_detail(),
            reference_detail_payload=_detail(),
        )
    with pytest.raises(helper.LineageError):
        helper.compare_lineage(
            deployments_payload=_deployments(),
            expected_active_version="not-a-uuid",
            active_detail_payload=_detail(),
            reference_detail_payload=_detail(),
        )


def test_missing_or_empty_script_identity_fails_closed():
    helper = _load_helper()
    for bad in (
        {"success": True, "result": {"resources": {}}},
        {"success": True, "result": {"resources": {"script": {"etag": ""}}}},
        {"success": True, "result": {}},
        {"success": True, "result": None},
    ):
        with pytest.raises(helper.LineageError):
            helper.compare_lineage(
                deployments_payload=_deployments(),
                expected_active_version=ACTIVE,
                active_detail_payload=bad,
                reference_detail_payload=_detail(),
            )
        with pytest.raises(helper.LineageError):
            helper.compare_lineage(
                deployments_payload=_deployments(),
                expected_active_version=ACTIVE,
                active_detail_payload=_detail(),
                reference_detail_payload=bad,
            )


def test_cli_success_prints_exact_vocabulary_and_no_etag(tmp_path):
    helper = _load_helper()
    dep = tmp_path / "deployments.json"
    act = tmp_path / "active.json"
    ref = tmp_path / "reference.json"
    dep.write_text(json.dumps(_deployments()), encoding="utf-8")
    act.write_text(json.dumps(_detail(SECRET_ETAG)), encoding="utf-8")
    ref.write_text(json.dumps(_detail(SECRET_ETAG)), encoding="utf-8")
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = helper.main([
            "--deployments", str(dep),
            "--expected-active-version", ACTIVE,
            "--active-detail", str(act),
            "--reference-detail", str(ref),
        ])
    assert rc == 0
    lines = out.getvalue().splitlines()
    assert lines == [
        f"ACTIVE_VERSION={ACTIVE}",
        "EXPECTED_ACTIVE_VERSION_MATCH=PASS",
        "ACTIVE_SCRIPT_IDENTITY_PRESENT=PASS",
        "REFERENCE_SCRIPT_IDENTITY_PRESENT=PASS",
        "SCRIPT_IDENTITY_EQUAL=YES",
        "INTERMEDIATE_SCRIPT_IDENTITY_EQUAL=NOT_CHECKED",
        "B62_SCRIPT_LINEAGE=MATCH",
        "RAW_SCRIPT_ETAG_OUTPUT=0",
        "RAW_VERSION_DETAIL_OUTPUT=0",
        "SECRET_VALUE_OUTPUT=0",
        "PRODUCTION_MUTATION=0",
    ]
    combined = out.getvalue() + err.getvalue()
    assert SECRET_ETAG not in combined
    assert "etag" not in combined.lower().replace("raw_script_etag_output", "")


def test_cli_failure_is_value_free(tmp_path):
    helper = _load_helper()
    dep = tmp_path / "deployments.json"
    act = tmp_path / "active.json"
    ref = tmp_path / "reference.json"
    dep.write_text(json.dumps(_deployments(version_id=REFERENCE)), encoding="utf-8")
    act.write_text(json.dumps(_detail(SECRET_ETAG)), encoding="utf-8")
    ref.write_text(json.dumps(_detail(SECRET_ETAG)), encoding="utf-8")
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = helper.main([
            "--deployments", str(dep),
            "--expected-active-version", ACTIVE,
            "--active-detail", str(act),
            "--reference-detail", str(ref),
        ])
    assert rc == 1
    assert out.getvalue() == ""
    assert "B62_SCRIPT_LINEAGE=FAIL" in err.getvalue()
    assert "PRODUCTION_MUTATION=0" in err.getvalue()
    assert SECRET_ETAG not in err.getvalue()


def test_helper_performs_no_network_io():
    source = HELPER.read_text(encoding="utf-8")
    for token in ("urllib", "http.client", "requests", "socket", "subprocess",
                  "httpx", "curl", "Authorization"):
        assert token not in source, token


def test_workflow_is_get_only_and_exact_main_guarded():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "EXACT_MAIN=PASS" in workflow
    assert 'test "${GITHUB_REF}" = "refs/heads/main"' in workflow
    assert 'test "$(git rev-parse HEAD)" = "${TARGET_SHA}"' in workflow
    assert 'test "$(git rev-parse origin/main)" = "${TARGET_SHA}"' in workflow
    assert 'test "${active}" = "${EXPECTED_ACTIVE_VERSION}"' in workflow
    assert "percentage == 100" in workflow
    assert "b62_script_lineage_comparator.py" in workflow
    assert "RAW_SCRIPT_ETAG_OUTPUT=0" in workflow
    assert "PRODUCTION_MUTATION=0" in workflow
    assert "permissions:\n  contents: read" in workflow
    for verb in ("-X PATCH", "-X PUT", "-X POST", "-X DELETE", "--data",
                 "wrangler", "rollback", "provider", "/stream"):
        assert verb not in workflow, verb
    # the token is only ever used as a bearer header for GET reads
    assert workflow.count("CLOUDFLARE_API_TOKEN") <= 4
    assert "resources.script.etag" not in workflow
    assert "jq -r" not in workflow or ".version_id" in workflow


def test_workflow_never_prints_payloads():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    readonly = workflow.split("lineage-readonly:", 1)[1]
    for token in ("cat ", "jq .", "jq -c", "echo \"${active_detail}", "head ",
                  "upload-artifact", "FULL_SETTINGS", "/settings"):
        assert token not in readonly, token
    assert "SETTINGS_PAYLOAD_READ=0" in readonly
