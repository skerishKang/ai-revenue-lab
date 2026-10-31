"""#3782 GET-only Owner D1 release preparation: fail-closed contract tests.

#5223: the live binding set is compared with the reviewed name+type baseline
(``.github/binding_baselines/<worker>.json``) instead of a magic binding count.
These fixtures therefore build the synthetic Worker evidence FROM that
baseline, so a baseline change is exercised here and the fixtures cannot
silently drift away from the reviewed expectation.
"""
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

baseline_spec = importlib.util.spec_from_file_location(
    "b62_binding_baseline", SCRIPT_DIR / "b62_binding_baseline.py"
)
assert baseline_spec is not None and baseline_spec.loader is not None
baseline_mod = importlib.util.module_from_spec(baseline_spec)
baseline_spec.loader.exec_module(baseline_mod)

OWNER = "01d0560b-58f4-4052-991d-dc935f5ecca0"
CHAT_DB = "702bb62b-36f5-41a0-973f-c4f663ee01e6"
ENGINE_DB = "6b77ad02-bc27-488f-bb97-6325f6750cba"
MAIN = "a" * 40

# The authority each synthetic binding carries.  A name absent from this map
# keeps the shape its type requires and nothing else.
SERVICE_TARGETS = {
    "P01_ENGINE_SERVICE": "padiem-ai-engine",
    "IDENTITY_AUTHORITY_SERVICE": "padiem-control-plane-identity",
    "CONTROL_PLANE_IDENTITY": "padiem-control-plane-identity",
}
# The Engine D1 that must point at the expected Engine database.  The other
# Engine D1 bindings and the separate B62 web-xlsx database keep their own
# identity: one database for every Engine D1 was never the real invariant.
ENGINE_CONTINUATION_DB = ENGINE_DB
OTHER_D1_DB = "11111111-2222-3333-4444-555555555555"


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


def _synthetic_binding(name: str, kind: str) -> dict:
    """Build one synthetic binding in the same shape the live API returns."""
    binding = {"name": name, "type": kind}
    if kind == "service":
        binding["service"] = SERVICE_TARGETS.get(name, "other-service")
        binding["environment"] = "production"
    elif kind == "d1":
        # The live API returns both aliases with the same identity.
        database = CHAT_DB if name == "PADIEM_CHAT_DB" else (
            ENGINE_CONTINUATION_DB if name == "ENGINE_CONTINUATION" else OTHER_D1_DB
        )
        binding["database_id"] = database
        binding["id"] = database
    elif kind == "r2_bucket":
        binding["bucket_name"] = "test-files"
    elif kind == "plain_text":
        binding["text"] = f"value-of-{name}"
    elif kind == "secrets_store_secret":
        binding["store_id"] = f"store-of-{name}"
        binding["secret_name"] = f"secret-of-{name}"
    return binding



def _version(worker, version_id):
    # The synthetic evidence is the reviewed baseline, so the test proves the
    # real comparison and not a hand-counted fixture.
    expected = baseline_mod.load_baseline(worker)
    bindings = [
        _synthetic_binding(name, kind) for name, kind in sorted(expected.items())
    ]
    if worker == "padiem-ai-engine":
        annotations = {"workers/triggered_by": "api"}
        runtime = {"compatibility_date": "2026-08-25",
                   "compatibility_flags": ["python_workers"], "usage_model": "standard"}
    else:
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


def _bindings_of(payload) -> list:
    result = payload["result"]
    if "resources" in result:
        return result["resources"]["bindings"]
    return result["bindings"]


def _find(payload, name):
    for item in _bindings_of(payload):
        if item.get("name") == name:
            return item
    raise AssertionError(f"fixture has no binding named {name!r}")


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


def test_the_baseline_evidence_creates_only_a_safe_manifest():
    inventories, workers = _all()
    result = mod.prepare_release(inventories, workers, MAIN)
    assert result["mode"] == "OWNER_D1_GET_ONLY_PREPARATION"
    assert not result["production_mutation"]
    assert not result["pre_mutation_release_anchor"]
    expected_counts = {
        "padiem-ai-engine": len(baseline_mod.load_baseline("padiem-ai-engine")),
        "padiem-chat": len(baseline_mod.load_baseline("padiem-chat")),
    }
    assert {x["worker"]: x["existing_bindings"] for x in result["workers"]} == expected_counts
    assert {x["worker"]: x["planned_bindings"] for x in result["workers"]} == {
        worker: count + 1 for worker, count in expected_counts.items()
    }
    assert {x["worker"]: x["pinned_inherit_count"] for x in result["workers"]} == expected_counts
    assert result["workers"][0]["annotations_carried"] == []
    assert result["workers"][1]["annotations_carried"] == ["workers/message", "workers/tag"]
    output = json.dumps(result, sort_keys=True)
    assert OWNER not in output and CHAT_DB not in output and ENGINE_DB not in output
    assert "value-of-" not in output
    for name in baseline_mod.load_baseline("padiem-chat"):
        # The manifest carries a digest of the names, not the names themselves.
        assert name not in output


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
    "owner_db_aliased", "wrong_main_sha", "missing_caller_secret",
    "wrong_primary_d1_id", "wrong_engine_continuation_d1",
    "unexpected_binding", "missing_approved_binding", "retyped_binding",
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
        # The served version and the live settings disagree about one service
        # target: the served version is proven, the settings plane drifted.
        _find(workers["padiem-chat"][3], "P01_ENGINE_SERVICE")["service"] = "foreign"
    elif tamper == "missing_secret":
        workers["padiem-chat"][2]["result"]["resources"]["bindings"].pop()
        workers["padiem-chat"][3]["result"]["bindings"].pop()
    elif tamper == "duplicate_binding":
        _find(workers["padiem-chat"][2], "P01_ENGINE_SERVICE")["name"] = "ASSETS"
    elif tamper == "wrong_engine_identity":
        _find(workers["padiem-ai-engine"][2], "CONTROL_PLANE_IDENTITY")["service"] = "foreign"
        _find(workers["padiem-ai-engine"][3], "CONTROL_PLANE_IDENTITY")["service"] = "foreign"
    elif tamper == "unexpected_annotation":
        workers["padiem-chat"][2]["result"]["annotations"]["unknown"] = "unreviewed"
    elif tamper == "missing_script":
        del workers["padiem-ai-engine"][2]["result"]["resources"]["script"]
    elif tamper == "missing_compatibility":
        del workers["padiem-ai-engine"][2]["result"]["resources"]["script_runtime"]["compatibility_date"]
    elif tamper == "owner_present":
        workers["padiem-chat"][2]["result"]["resources"]["bindings"][-1]["name"] = mod.OWNER_BINDING
        workers["padiem-chat"][3]["result"]["bindings"][-1]["name"] = mod.OWNER_BINDING
    elif tamper == "bad_db_list":
        inventories[mod.OWNER_NAME]["result"] = []
    elif tamper == "owner_db_aliased":
        inventories["padiem-engine"]["result"][0]["uuid"] = OWNER
    elif tamper == "missing_caller_secret":
        _find(workers["padiem-chat"][2], "P01_ENGINE_CREDENTIAL")["name"] = "REPLACED"
        # Keep settings equal to version so the missing secret identity, not
        # the settings drift check, is the fail-closed mechanism.
        _find(workers["padiem-chat"][3], "P01_ENGINE_CREDENTIAL")["name"] = "REPLACED"
    elif tamper == "wrong_primary_d1_id":
        _find(workers["padiem-chat"][2], "PADIEM_CHAT_DB")["database_id"] = OWNER
        _find(workers["padiem-chat"][2], "PADIEM_CHAT_DB")["id"] = OWNER
        _find(workers["padiem-chat"][3], "PADIEM_CHAT_DB")["database_id"] = OWNER
        _find(workers["padiem-chat"][3], "PADIEM_CHAT_DB")["id"] = OWNER
    elif tamper == "wrong_engine_continuation_d1":
        _find(workers["padiem-ai-engine"][2], "ENGINE_CONTINUATION")["database_id"] = OWNER
        _find(workers["padiem-ai-engine"][2], "ENGINE_CONTINUATION")["id"] = OWNER
        _find(workers["padiem-ai-engine"][3], "ENGINE_CONTINUATION")["database_id"] = OWNER
        _find(workers["padiem-ai-engine"][3], "ENGINE_CONTINUATION")["id"] = OWNER
    elif tamper == "unexpected_binding":
        # A binding the baseline does not approve is a drift, even though the
        # count alone would not notice it.
        extra = {"name": "UNAPPROVED_EXTRA_BINDING", "type": "plain_text", "text": "x"}
        workers["padiem-chat"][2]["result"]["resources"]["bindings"].append(extra)
        workers["padiem-chat"][3]["result"]["bindings"].append(copy.deepcopy(extra))
    elif tamper == "missing_approved_binding":
        removed = None
        for item in workers["padiem-chat"][2]["result"]["resources"]["bindings"]:
            if item["name"] != "P01_ENGINE_CREDENTIAL" and item["type"] == "plain_text":
                removed = item["name"]
                break
        workers["padiem-chat"][2]["result"]["resources"]["bindings"] = [
            b for b in workers["padiem-chat"][2]["result"]["resources"]["bindings"]
            if b["name"] != removed
        ]
        workers["padiem-chat"][3]["result"]["bindings"] = [
            b for b in workers["padiem-chat"][3]["result"]["bindings"]
            if b["name"] != removed
        ]
    elif tamper == "retyped_binding":
        for payload in (workers["padiem-chat"][2], workers["padiem-chat"][3]):
            _find(payload, "PADIEM_CHAT_DB")["type"] = "plain_text"
    with pytest.raises(mod.ReleasePreflightError):
        mod.prepare_release(inventories, workers, MAIN if tamper != "wrong_main_sha" else "wrong")


def test_the_binding_set_drift_is_reported_as_its_own_code():
    """A drift is a named, actionable code, not an opaque count mismatch."""
    inventories, workers = _all()
    workers["padiem-chat"][2]["result"]["resources"]["bindings"].append(
        {"name": "UNAPPROVED", "type": "plain_text", "text": "x"}
    )
    with pytest.raises(mod.ReleasePreflightError) as excinfo:
        mod.prepare_release(inventories, workers, MAIN)
    assert "BINDING_SET_DRIFT" in str(excinfo.value)


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
    assert "OWNER_D1_PREFLIGHT=PASS" in out
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


def test_the_read_only_gate_proves_the_live_binding_set_against_the_baseline():
    """#5223: the expectation cannot rot unnoticed again.

    The read-only gate runs before any deploy mutation, so a Worker that grew
    a binding nobody reviewed fails closed there instead of blocking the D1
    release path later with an opaque count mismatch.
    """
    text = (ROOT / ".github/workflows/b62-production-code-deploy-gate.yml").read_text(
        encoding="utf-8"
    )
    readonly_job = text.split("\n  cloudflare-readonly:\n", 1)[1]
    readonly_job = readonly_job.split("\n  deploy-production-code:\n", 1)[0]
    assert "b62_binding_baseline.py" in readonly_job
    assert "B62_BINDING_BASELINE=PASS" in readonly_job
    assert "B62_BINDING_BASELINE_VALUES_EMITTED=0" in readonly_job
    # This gate's credential is deliberately locked to the B62 Worker
    # (#3930), so it proves the B62 baseline only and must not reach for the
    # Engine Worker through that helper.
    assert "${P01_ENGINE_WORKER}/settings" not in readonly_job
    assert "B62_BINDING_BASELINE_WORKERS=${B62_WORKER}" in readonly_job
    # The read-only gate runs before the deploy job, so a drifted binding set
    # fails closed before any deploy mutation.
    assert text.index("\n  cloudflare-readonly:") < text.index("\n  deploy-production-code:")
    assert "needs: [source-contract, cloudflare-readonly]" in text
    # The baseline and its test are part of the trigger scope.
    assert ".github/binding_baselines/**" in text
    assert ".github/scripts/b62_binding_baseline.py" in text
    assert ".github/tests/test_b62_binding_baseline.py" in text
    # The source-contract CI runs the baseline contract.
    assert ".github/tests/test_b62_binding_baseline.py" in text
