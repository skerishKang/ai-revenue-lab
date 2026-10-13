"""No-network immutable Worker comparison and read-only workflow contract."""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/b62_p01_postpatch_immutable_forensic.py"
WORKFLOW = ROOT / ".github/workflows/b62-p01-sse-immutable-forensic.yml"
spec = importlib.util.spec_from_file_location("sse_readonly_forensic", SCRIPT)
assert spec and spec.loader
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)


def version(id: str, flag: bool, code: str = "original", assets: str = "same"):
    bs = [
        {"name": "ASSETS", "type": "assets"},
        {"name": "P01_ENGINE_CREDENTIAL", "type": "secret_text", "secret": "do-not-log"},
        {"name": "PADIEM_CHAT_RUNTIME_MODE", "type": "plain_text", "text": "b14"},
    ]
    if flag:
        bs.append({"name": f.FLAG, "type": "plain_text", "text": "true"})
    return {"success": True, "result": {"id": id, "resources": {
        "script": {"etag": code}, "script_runtime": {"compatibility_date": "2026-01-01"},
        "assets": {"etag": assets}, "bindings": bs}}}


def fixture():
    return version(f.BEFORE, False), version(f.FAILED_PATCH, True)


def test_exact_flag_only_does_not_report_false_drift():
    result = f.compare(*fixture())
    assert result["flag_added_true"] is True
    assert result["old_bindings"] == 3
    assert result["new_bindings"] == 4
    assert result["other_binding_diff_count"] == 0
    assert result["nonbinding_changed_resource_keys"] == []
    assert result["script_changed_field_names"] == []
    assert result["script_etag_same"] is True


def test_script_assets_runtime_and_binding_changes_are_not_normalized_away():
    before, after = fixture()
    after["result"]["resources"]["script"]["etag"] = "different"
    after["result"]["resources"]["assets"]["etag"] = "different"
    after["result"]["resources"]["script_runtime"]["compatibility_date"] = "changed"
    after["result"]["resources"]["bindings"][2]["text"] = "unapproved-secret-token"
    result = f.compare(before, after)
    assert result["script_changed_field_names"] == ["etag"]
    assert result["script_etag_same"] is False
    assert result["assets_same"] is False
    assert result["script_runtime_same"] is False
    assert result["other_binding_diff_count"] == 1
    assert len(result["other_binding_diff_name_hashes"][0]) == 12
    assert "unapproved-secret-token" not in str(result)
    assert "secret" not in str(result["other_binding_diff_name_hashes"])


@pytest.mark.parametrize("mutation", [
    "wrong_old", "wrong_new", "duplicate", "bad_shape",
    "failed_response", "missing_etag"
])
def test_refuse_untrusted_metadata(mutation):
    before, after = copy.deepcopy(fixture())
    if mutation == "wrong_old":
        before["result"]["id"] = "not-the-old-version"
    elif mutation == "wrong_new":
        after["result"]["id"] = "not-the-failed-version"
    elif mutation == "duplicate":
        after["result"]["resources"]["bindings"].append(
            {"name": f.FLAG, "type": "plain_text", "text": "true"})
    elif mutation == "bad_shape":
        after["result"]["resources"]["bindings"] = "invalid"
    elif mutation == "failed_response":
        after["success"] = False
    else:
        after["result"]["resources"]["script"].pop("etag")
    with pytest.raises(f.ForensicRefused):
        f.compare(before, after)


def test_workflow_is_strictly_read_only_and_separate_from_activation():
    y = WORKFLOW.read_text(encoding="utf-8")
    job = y.split("\n  immutable-forensic:", 1)[1]
    assert "workflow_dispatch:" in y
    assert "pull_request:" in y
    assert "permissions:\n  contents: read" in y
    assert "b62_cloudflare_504_readonly_get.sh" in job
    assert "versions/181d637c-de84-4919-9d45-8e966a07f181" in job
    assert "versions/18ee50a1-ab64-4cc0-8fc2-2ed3234f63a5" in job
    assert "b62_p01_postpatch_immutable_forensic.py" in job
    assert "github.event_name == 'workflow_dispatch'" in job
    for forbidden in ("-X POST", "-X PATCH", "-X PUT", "-X DELETE", "wrangler deploy",
                      "required-reviewers", "reviewers:", "environment: production"):
        assert forbidden not in job, forbidden
    assert "PRODUCTION_MUTATION=0" in job
