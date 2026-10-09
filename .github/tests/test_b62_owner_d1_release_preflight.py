"""#3782 GET-only Owner D1 release preparation: fail-closed contract tests."""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / ".github/scripts"
sys.path.insert(0, str(SCRIPT_DIR))
spec = importlib.util.spec_from_file_location(
    "b62_owner_d1_release_preflight", SCRIPT_DIR / "b62_owner_d1_release_preflight.py"
)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

OWNER = "01d0560b-58f4-4052-991d-dc935f5ecca0"
CHAT_DB = "702bb62b-36f5-41a0-973f-c4f663ee01e6"
ENGINE_DB = "6b77ad02-bc27-488f-bb97-6325f6750cba"
MAIN = "a" * 40


def _d1():
    return {name: {"success": True, "result": [{"name": name, "uuid": identity}]}
            for name, identity in (
                (mod.OWNER_NAME, OWNER), ("padiem-chat-db", CHAT_DB),
                ("padiem-engine", ENGINE_DB),
            )}


def _deploy(version_id):
    return {"success": True, "result": {"deployments": [
        {"versions": [{"version_id": version_id, "percentage": 100}]},
    ]}}


def _version(worker, version_id):
    if worker == "padiem-ai-engine":
        bindings = [
            {"name": "CONTROL_PLANE_IDENTITY", "type": "service",
             "service": "padiem-control-plane-identity"},
            *({"name": f"ENGINE_SERVICE_{i}", "type": "service",
               "service": f"other-{i}"} for i in range(3)),
            *({"name": f"ENGINE_D1_{i}", "type": "d1", "database_id": ENGINE_DB}
              for i in range(6)),
            *({"name": f"ENGINE_SECRET_{i}", "type": "secret_text"}
              for i in range(8)),
        ]
        annotations = {"workers/triggered_by": "api"}
        runtime = {"compatibility_date": "2026-08-25",
                   "compatibility_flags": ["python_workers"], "usage_model": "standard"}
    else:
        bindings = [
            {"name": "P01_ENGINE_SERVICE", "type": "service", "service": "padiem-ai-engine"},
            {"name": "IDENTITY_AUTHORITY_SERVICE", "type": "service",
             "service": "padiem-control-plane-identity"},
            *({"name": f"CHAT_SERVICE_{i}", "type": "service", "service": f"other-{i}"}
              for i in range(3)),
            {"name": "PADIEM_CHAT_DB", "type": "d1", "database_id": CHAT_DB},
            {"name": "ASSETS", "type": "assets"},
            {"name": "WORKSPACE_R2", "type": "r2_bucket", "bucket_name": "test-files"},
            *({"name": f"PLAIN_{i}", "type": "plain_text", "text": f"value-{i}"}
              for i in range(15)),
            *({"name": f"CHAT_SECRET_{i}", "type": "secret_text"} for i in range(4)),
        ]
        annotations = {"workers/message": "existing-note",
                       "workers/tag": "existing-tag", "workers/triggered_by": "wrangler"}
        runtime = {"compatibility_date": "2026-08-25",
                   "compatibility_flags": ["python_workers"], "usage_model": "standard",
                   "assets": {"jwt": "unchanged-assets"}}
    return {"success": True, "result": {"id": version_id,
        "annotations": annotations,
        "resources": {"bindings": bindings,
                      "script": {"etag": f"unchanged-{worker}", "handlers": ["fetch"]},
                      "script_runtime": runtime}}}


def _all():
    version_ids = {"padiem-ai-engine": "engine-version", "padiem-chat": "chat-version"}
    workers = {}
    for name, version in version_ids.items():
        detail = _version(name, version)
        settings = {"success": True, "result": {
            "bindings": copy.deepcopy(detail["result"]["resources"]["bindings"])
        }}
        workers[name] = (_deploy(version), _deploy(version), detail, settings)
    return _d1(), workers


def test_realistic_18_27_resource_evidence_creates_only_safe_manifest():
    inventories, workers = _all()
    result = mod.prepare_release(inventories, workers, MAIN)
    assert result["mode"] == "OWNER_D1_GET_ONLY_PREPARATION"
    assert not result["production_mutation"]
    assert not result["pre_mutation_release_anchor"]
    assert [(x["existing_bindings"], x["planned_bindings"]) for x in result["workers"]] == [
        (18, 19), (27, 28),
    ]
    assert [x["pinned_inherit_count"] for x in result["workers"]] == [18, 27]
    assert result["workers"][0]["annotations_carried"] == []
    assert result["workers"][1]["annotations_carried"] == ["workers/message", "workers/tag"]
    output = json.dumps(result, sort_keys=True)
    assert OWNER not in output and CHAT_DB not in output and ENGINE_DB not in output
    assert "value-0" not in output and "CHAT_SECRET_0" not in output


@pytest.mark.parametrize("worker", ["padiem-ai-engine", "padiem-chat"])
def test_pinned_inherit_candidate_uses_only_explicit_version_ids(worker):
    _, workers = _all()
    version = workers[worker][2]["result"]
    old = version["resources"]["bindings"]
    payload = mod.build_candidate(old, version["id"], OWNER, {
        "workers/message": "keep-existing" if worker == "padiem-chat" else ""
    })
    assert payload["bindings"][:-1] == [
        {"type": "inherit", "name": b["name"], "version_id": version["id"]}
        for b in old
    ]
    assert payload["bindings"][-1] == {
        "type": "d1", "name": mod.OWNER_BINDING, "database_id": OWNER
    }
    assert not any(b.get("old_name") or b.get("version_id") == "latest"
                   for b in payload["bindings"])


@pytest.mark.parametrize("tamper", [
    "ambiguous_deployment", "changed_active_version", "wrong_version_detail",
    "settings_drift", "missing_secret", "duplicate_binding",
    "wrong_engine_identity", "unexpected_annotation", "missing_script",
    "missing_compatibility", "owner_present", "bad_db_list",
    "owner_db_aliased", "wrong_main_sha",
])
def test_fail_closed_on_changed_trust_or_resource_authority(tamper):
    inventories, workers = _all()
    if tamper == "ambiguous_deployment":
        workers["padiem-ai-engine"][0]["result"]["deployments"][0]["versions"].append(
            {"version_id": "other", "percentage": 0})
    elif tamper == "changed_active_version":
        workers["padiem-chat"][1]["result"]["deployments"][0]["versions"][0]["version_id"] = "new"
    elif tamper == "wrong_version_detail":
        workers["padiem-ai-engine"][2]["result"]["id"] = "unexpected"
    elif tamper == "settings_drift":
        workers["padiem-chat"][3]["result"]["bindings"][0]["service"] = "foreign"
    elif tamper == "missing_secret":
        workers["padiem-chat"][2]["result"]["resources"]["bindings"].pop()
    elif tamper == "duplicate_binding":
        workers["padiem-chat"][2]["result"]["resources"]["bindings"][1]["name"] = "P01_ENGINE_SERVICE"
    elif tamper == "wrong_engine_identity":
        workers["padiem-ai-engine"][2]["result"]["resources"]["bindings"][0]["service"] = "foreign"
        workers["padiem-ai-engine"][3]["result"]["bindings"][0]["service"] = "foreign"
    elif tamper == "unexpected_annotation":
        workers["padiem-chat"][2]["result"]["annotations"]["unknown"] = "unreviewed"
    elif tamper == "missing_script":
        del workers["padiem-ai-engine"][2]["result"]["resources"]["script"]
    elif tamper == "missing_compatibility":
        del workers["padiem-ai-engine"][2]["result"]["resources"]["script_runtime"]["compatibility_date"]
    elif tamper == "owner_present":
        workers["padiem-chat"][2]["result"]["resources"]["bindings"][-1]["name"] = mod.OWNER_BINDING
    elif tamper == "bad_db_list":
        inventories[mod.OWNER_NAME]["result"] = []
    elif tamper == "owner_db_aliased":
        inventories["padiem-engine"]["result"][0]["uuid"] = OWNER
    with pytest.raises(mod.ReleasePreflightError):
        mod.prepare_release(inventories, workers, MAIN if tamper != "wrong_main_sha" else "wrong")


@pytest.mark.parametrize("bad", ["latest", "", "inv alid", None])
def test_inherit_refuses_unsafe_version_names(bad):
    _, workers = _all()
    old = workers["padiem-chat"][2]["result"]["resources"]["bindings"]
    with pytest.raises(mod.ReleasePreflightError):
        mod.build_candidate(old, bad, OWNER, {})


def test_preparation_cli_writes_only_bounded_file_and_refuses_overwrite(tmp_path, capsys):
    inventories, workers = _all()
    paths = {}
    for label, name in (("owner", mod.OWNER_NAME), ("chat", "padiem-chat-db"),
                        ("engine", "padiem-engine")):
        path = tmp_path / f"database-{label}.json"
        path.write_text(json.dumps(inventories[name]), encoding="utf-8")
        paths[f"--d1-{label}"] = path
    for label, worker in (("engine", "padiem-ai-engine"), ("chat", "padiem-chat")):
        for part, payload in zip(("before", "after", "version", "settings"), workers[worker]):
            path = tmp_path / f"{label}-{part}.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            paths[f"--{label}-{part}"] = path
    outfile = tmp_path / "safe.json"
    cli = ["--main-sha", MAIN, "--output", str(outfile)]
    for flag, path in paths.items():
        cli.extend([flag, str(path)])
    assert mod.main(cli) == 0
    out = capsys.readouterr().out
    assert "PRODUCTION_MUTATION=0" in out
    assert OWNER not in out
    result = json.loads(outfile.read_text(encoding="utf-8"))
    assert result["source_main"] == MAIN
    assert result["pre_mutation_release_anchor"] is False
    assert mod.main(cli) == 2
    assert "OUTPUT_ALREADY_EXISTS" in capsys.readouterr().err


def test_existing_b62_workflow_is_read_only_for_new_mode():
    text = (ROOT / ".github/workflows/b62-production-code-deploy-gate.yml").read_text(
        encoding="utf-8"
    )
    assert "owner_d1_release_preflight" in text
    assert '.github/scripts/b62_owner_d1_release_preflight.py' in text
    assert '.github/tests/test_b62_owner_d1_release_preflight.py' in text
    new_job = text.split("\n  owner-d1-release-preflight:\n", 1)[1]
    assert "needs: [source-contract, cloudflare-readonly]" in new_job
    assert "github.event_name == 'workflow_dispatch'" in new_job
    assert "actions/checkout@v4" in new_job
    assert "git fetch --no-tags --depth=1 origin main" in new_job
    assert "cloudflare_served_version_cli.py resolve-active" in new_job
    assert "b62_owner_d1_release_preflight.py" in new_job
    assert "actions/upload-artifact@v4" in new_job
    assert "if-no-files-found: error" in new_job
    assert "DURABLE_PREMUTATION_RELEASE_ANCHOR=NO" in (
        (SCRIPT_DIR / "b62_owner_d1_release_preflight.py").read_text(encoding="utf-8")
    )
    assert new_job.index("b62_owner_d1_release_preflight.py") < new_job.index(
        "actions/upload-artifact@v4"
    )
    assert new_job.index("actions/upload-artifact@v4") < new_job.index(
        "Stop without any Worker release or settings mutation"
    )
    assert "environment: production" not in new_job
    assert "pywrangler deploy" not in new_job
    assert "curl -X PATCH" not in new_job and "curl -X POST" not in new_job
    assert "LIVE_OWNER_D1_BINDINGS_ADDED=NO" in new_job
