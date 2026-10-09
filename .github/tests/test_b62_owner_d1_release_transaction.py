"""Protected Owner D1 apply/rollback gate: no real Cloudflare mutation in tests."""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".github/scripts"
TESTS = ROOT / ".github/tests"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from b62_owner_d1_release_preflight import OWNER_BINDING
from b62_owner_d1_release_transaction import (
    TransactionError,
    prepare,
    verify,
    verify_rollback_target,
    main,
)

s = importlib.util.spec_from_file_location("owner_fixture", TESTS / "test_b62_owner_d1_release_preflight.py")
assert s and s.loader
fixture = importlib.util.module_from_spec(s)
s.loader.exec_module(fixture)
OWNER = fixture.OWNER
MAIN = fixture.MAIN
WORKFLOW = ROOT / ".github/workflows/b54-owner-d1-controlled-connection.yml"


def _latest(version: str) -> dict:
    return {"success": True, "result": {"items": [{"id": version}]}}


def _engine():
    d, workers = fixture._all()
    before, after, version, settings = workers["padiem-ai-engine"]
    peer_before, _, peer_version, _ = workers["padiem-chat"]
    return d, before, after, version, settings, _latest("engine-version"), peer_before, peer_version


def _chat():
    d, workers = fixture._all()
    before, after, version, settings = workers["padiem-chat"]
    peer_before, _, peer_version, _ = workers["padiem-ai-engine"]
    # Engine Owner D1 must have been installed in its previous, verified transaction.
    peer_version["result"]["resources"]["bindings"].append(
        {"type": "d1", "name": OWNER_BINDING, "database_id": OWNER}
    )
    return d, before, after, version, settings, _latest("chat-version"), peer_before, peer_version


def _prepare(worker: str, args=None):
    return prepare(worker, MAIN, *(args or (_engine() if worker == "engine" else _chat())))


@pytest.mark.parametrize("worker,expected", [("engine", 18), ("chat", 27)])
def test_prepare_creates_exact_one_version_pinned_candidate_and_safe_anchor(worker, expected):
    patch, anchor = _prepare(worker)
    assert len(patch["bindings"]) == expected + 1
    assert all(b == {"type": "inherit", "name": b["name"],
                     "version_id": anchor["rollback_version_id"]}
               for b in patch["bindings"][:-1])
    assert patch["bindings"][-1] == {
        "type": "d1", "name": OWNER_BINDING, "database_id": OWNER,
    }
    assert anchor["original_binding_count"] == expected
    assert anchor["target_binding_count"] == expected + 1
    assert anchor["first_mutation_not_yet_attempted"]
    assert anchor["kind"] == "OWNER_P01_D1_FRESH_PREMUTATION_ROLLBACK_ANCHOR"
    assert anchor["prepared_for_publication_before_mutation"]
    safe = json.dumps(anchor)
    assert OWNER not in safe and "secret_text" not in safe
    assert "PADIEM_ENGINE_CALLER_REGISTRY_V1" not in safe
    assert "P01_ENGINE_CREDENTIAL" not in safe
    assert patch["annotations"] == (
        {} if worker == "engine" else {"workers/message": "existing-note",
                                        "workers/tag": "existing-tag"}
    )


@pytest.mark.parametrize("failure", [
    "latest_not_served", "peer_missing_for_chat", "peer_already_connected_for_engine",
    "wrong_main", "wrong_active_version", "wrong_binding_authority",
    "wrong_owner_inventory", "unsafe_worker",
])
def test_prepare_fails_closed_without_side_effect(failure):
    args = list(_engine())
    worker = "engine"
    source = MAIN
    if failure == "latest_not_served":
        args[5]["result"]["items"][0]["id"] = "some-unserved-version"
    elif failure == "peer_missing_for_chat":
        worker, args = "chat", list(_chat())
        args[7]["result"]["resources"]["bindings"].pop()
    elif failure == "peer_already_connected_for_engine":
        args[7]["result"]["resources"]["bindings"].append(
            {"type": "d1", "name": OWNER_BINDING, "database_id": OWNER}
        )
    elif failure == "wrong_main":
        source = "bad"
    elif failure == "wrong_active_version":
        args[1]["result"]["deployments"][0]["versions"][0]["version_id"] = "foreign"
    elif failure == "wrong_binding_authority":
        args[3]["result"]["bindings"][0]["service"] = "foreign"
    elif failure == "wrong_owner_inventory":
        args[0][fixture.mod.OWNER_NAME]["result"] = []
    elif failure == "unsafe_worker":
        worker = "foreign"
    with pytest.raises((TransactionError, fixture.mod.ReleasePreflightError)):
        prepare(worker, source, *args)


@pytest.mark.parametrize("worker", ["engine", "chat"])
def test_verify_real_served_post_is_only_owner_binding_plus_resource_parity(worker):
    args = _engine() if worker == "engine" else _chat()
    _, _, _, version, _, _, _, _ = args
    _, anchor = _prepare(worker)
    post = copy.deepcopy(version)
    post["result"]["id"] = "new-live-version"
    post["result"]["resources"]["bindings"].append(
        {"type": "d1", "name": OWNER_BINDING, "database_id": OWNER}
    )
    settings = {"success": True, "result": {
        "bindings": copy.deepcopy(post["result"]["resources"]["bindings"])
    }}
    assert verify(version, post, fixture._deploy("new-live-version"), settings,
                  OWNER, anchor) == "new-live-version"


@pytest.mark.parametrize("change", [
    "unchanged_active", "wrong_version_id", "changed_script", "dropped_secret",
    "changed_annotations", "wrong_settings", "wrong_owner_id",
])
def test_post_failures_cannot_report_connected(change):
    args = _engine()
    _, _, _, pre, _, _, _, _ = args
    _, anchor = _prepare("engine")
    post = copy.deepcopy(pre)
    post["result"]["id"] = "new-live-version"
    post["result"]["resources"]["bindings"].append(
        {"type": "d1", "name": OWNER_BINDING, "database_id": OWNER}
    )
    settings = {"success": True, "result": {
        "bindings": copy.deepcopy(post["result"]["resources"]["bindings"])
    }}
    served = fixture._deploy("new-live-version")
    owner = OWNER
    if change == "unchanged_active":
        served = fixture._deploy("engine-version")
    elif change == "wrong_version_id":
        post["result"]["id"] = "not-the-served-version"
    elif change == "changed_script":
        post["result"]["resources"]["script"]["etag"] = "unexpected"
    elif change == "dropped_secret":
        post["result"]["resources"]["bindings"].pop(10)
    elif change == "changed_annotations":
        post["result"]["annotations"]["workers/tag"] = "new"
    elif change == "wrong_settings":
        settings["result"]["bindings"][0]["service"] = "changed"
    elif change == "wrong_owner_id":
        owner = fixture.ENGINE_DB
    with pytest.raises(TransactionError):
        verify(pre, post, served, settings, owner, anchor)


@pytest.mark.parametrize("worker", ["engine", "chat"])
def test_rollback_target_bound_to_exact_anchor_hashes(worker):
    args = _engine() if worker == "engine" else _chat()
    original = args[3]
    _, anchor = _prepare(worker)
    assert verify_rollback_target(anchor, original, anchor["worker"]) == anchor["rollback_version_id"]
    bad_version = copy.deepcopy(original)
    bad_version["result"]["resources"]["script"]["etag"] = "drift"
    with pytest.raises(TransactionError):
        verify_rollback_target(anchor, bad_version, anchor["worker"])
    bad_anchor = copy.deepcopy(anchor)
    bad_anchor["worker"] = "wrong-worker"
    with pytest.raises(TransactionError):
        verify_rollback_target(bad_anchor, original, "padiem-ai-engine" if worker == "engine" else "padiem-chat")
    bad_anchor = copy.deepcopy(anchor)
    bad_anchor["rollback_version_id"] = "different"
    with pytest.raises(TransactionError):
        verify_rollback_target(bad_anchor, original, anchor["worker"])


def test_file_outputs_are_creation_only_and_refuse_collisions(tmp_path, capsys):
    d, before, after, version, settings, latest, peer, peer_version = _engine()
    payloads = {"d1-owner": d[fixture.mod.OWNER_NAME],
                "d1-chat": d["padiem-chat-db"],
                "d1-engine": d["padiem-engine"],
                "before": before, "after": after, "version": version, "settings": settings,
                "latest": latest, "peer-deployments": peer, "peer-version": peer_version}
    args = ["prepare", "--worker", "engine", "--main-sha", MAIN]
    for key, value in payloads.items():
        path = tmp_path / (key + ".json")
        path.write_text(json.dumps(value), encoding="utf-8")
        args += ["--" + key, str(path)]
    patch = tmp_path / "candidate.json"
    anchor = tmp_path / "anchor.json"
    args += ["--candidate", str(patch), "--anchor", str(anchor)]
    assert main(args) == 0
    captured = capsys.readouterr().out
    assert "FRESH_ROLLBACK_ANCHOR_READY_FOR_UPLOAD=YES" in captured
    assert OWNER not in captured
    assert OWNER in patch.read_text(encoding="utf-8")
    assert OWNER not in anchor.read_text(encoding="utf-8")
    assert main(args) == 2
    assert "OUTPUT_EXISTS" in capsys.readouterr().err


def test_operational_workflow_enforces_durable_anchor_before_any_patch():
    text = WORKFLOW.read_text(encoding="utf-8")
    wf = yaml.safe_load(text)
    triggers = wf.get("on", wf.get(True))
    assert list(triggers) == ["workflow_dispatch"]
    assert set(wf["jobs"]) == {"apply", "rollback"}
    assert wf["concurrency"]["cancel-in-progress"] is False
    for name, job in wf["jobs"].items():
        assert job["environment"] == "production"
        assert "inputs.confirmation" in job["if"]
        assert "inputs.mode" in job["if"]
        assert any("checkout@v4" in str(step.get("uses", "")) for step in job["steps"])
    apply = wf["jobs"]["apply"]["steps"]
    names = [step.get("name", "") for step in apply]
    upload = next(i for i, v in enumerate(names) if "Persist rollback anchor" in v)
    patch = next(i for i, v in enumerate(names) if "PATCH existing Worker" in v)
    assert upload < patch
    assert "actions/upload-artifact@v4" in apply[upload]["uses"]
    assert apply[upload]["with"]["if-no-files-found"] == "error"
    assert "owner-prewrite-rollback-anchor.json" in apply[upload]["with"]["path"]
    assert "b62_owner_d1_release_transaction.py prepare" in text
    assert "b62_owner_d1_release_transaction.py verify" in text
    assert text.count("-X PATCH") == 1
    assert text.count("-X POST") == 1
    assert "NO_AUTOMATIC_PATCH_RETRY=YES" in text
    assert "ROLLOUT" not in text
    rollback = wf["jobs"]["rollback"]["steps"]
    download = next(step for step in rollback if "Download original pre-mutation" in step.get("name", ""))
    assert download["uses"].startswith("actions/download-artifact@")
    assert "inputs.anchor_run_id" in download["with"]["run-id"]
    assert "verify-rollback-target" in text
    assert "OWNER_D1_ROLLBACK_TARGET" in text
    assert "github.event.inputs" not in text


def test_workflow_merge_never_auto_deploys_and_existing_gates_are_unchanged():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request:" not in text
    assert "push:" not in text
    assert "schedule:" not in text
    assert "OWNER_D1_PATCH_ATTEMPTED=YES" not in text  # one named attempt in command
    assert "owner-d1-rollback-anchor-" in text
    assert "old_name" not in text
