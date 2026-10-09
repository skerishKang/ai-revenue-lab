"""Protected Owner D1 apply/rollback gate: no real Cloudflare mutation in tests."""
from __future__ import annotations

import base64
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
    assert_exact_worker_code,
    main,
    prepare,
    validate_patch_settings,
    verify,
    verify_patch_response,
    verify_rollback_target,
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


def _module_response(version_id: str, *, body: bytes = b"unchanged python source") -> dict:
    return {"success": True, "result": {
        "id": version_id,
        "modules": [
            {"name": "main.py", "content_type": "text/x-python",
             "content_base64": base64.b64encode(body).decode("ascii")},
            {"name": "entry.mjs", "content_type": "application/javascript+module",
             "content_base64": base64.b64encode(b"export default {};").decode("ascii")},
        ],
    }}


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
        args[4]["result"]["bindings"][0]["service"] = "foreign"
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
    assert verify(
        version, post, fixture._deploy("new-live-version"), settings,
        OWNER, anchor, _module_response(version["result"]["id"]),
        _module_response("new-live-version"),
    ) == "new-live-version"


@pytest.mark.parametrize("change", [
    "unchanged_active", "wrong_version_id", "changed_handler", "dropped_secret",
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
    elif change == "changed_handler":
        post["result"]["resources"]["script"]["handlers"] = ["changed"]
    elif change == "dropped_secret":
        post["result"]["resources"]["bindings"].pop(10)
    elif change == "changed_annotations":
        post["result"]["annotations"]["workers/tag"] = "new"
    elif change == "wrong_settings":
        settings["result"]["bindings"][0]["service"] = "changed"
    elif change == "wrong_owner_id":
        owner = fixture.ENGINE_DB
    with pytest.raises(TransactionError):
        verify(
            pre, post, served, settings, owner, anchor,
            _module_response(pre["result"]["id"]),
            _module_response("new-live-version"),
        )


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
    emitted = json.loads(patch.read_text(encoding="utf-8"))
    # This EXACT file is used as the multipart form part named 'settings'.
    # Cloudflare requires its JSON to contain bindings directly, not a nested
    # {"settings": {...}} wrapper. Reinstating the original bug fails here.
    assert set(emitted) == {"bindings", "annotations"}
    assert "settings" not in emitted
    assert len(emitted["bindings"]) == 19
    assert emitted["bindings"][-1] == {
        "type": "d1", "name": OWNER_BINDING, "database_id": OWNER
    }
    assert all(x["type"] == "inherit" and x["version_id"] == "engine-version"
               for x in emitted["bindings"][:-1])
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
    for job in wf["jobs"].values():
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


def test_cloudflare_official_rollback_deployment_schema(tmp_path, capsys):
    """POST /deployments requires strategy and a versions ARRAY (not flat fields)."""
    from b62_owner_d1_release_transaction import build_rollback_deployment

    version_id = "023e105f-2a42-4f8b-a1c1-73f6a2a30c0f"
    expected = {
        "strategy": "percentage",
        "versions": [{"version_id": version_id, "percentage": 100}],
    }
    assert build_rollback_deployment(version_id) == expected
    for bad in ("latest", "", "invalid", "../versions"):
        with pytest.raises(TransactionError):
            build_rollback_deployment(bad)

    output = tmp_path / "rollback-deployment.json"
    assert main(["build-rollback-deployment", "--version-id", version_id,
                 "--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8")) == expected
    assert "OWNER_D1_ROLLBACK_DEPLOYMENT_PAYLOAD=OFFICIAL_SCHEMA_PASS" in capsys.readouterr().out
    assert main(["build-rollback-deployment", "--version-id", version_id,
                 "--output", str(output)]) == 2
    assert "INVALID_RELEASE_EVIDENCE" in capsys.readouterr().err


def test_rollback_workflow_uses_verified_cloudflare_deployment_schema():
    text = WORKFLOW.read_text(encoding="utf-8")
    rollback_step = text.split(
        "      - name: Roll back to exact pinned original with one deployment POST", 1
    )[1].split("      - name: Verify 100-percent restored served version", 1)[0]
    assert "b62_owner_d1_release_transaction.py build-rollback-deployment" in rollback_step
    assert "--version-id" in rollback_step and "OWNER_D1_ROLLBACK_TARGET" in rollback_step
    assert '--data-binary "@${RUNNER_TEMP}/rollback-request.json"' in rollback_step
    assert '"strategy"' not in rollback_step  # JSON envelope comes from tested builder.
    assert '{{--"version_id":' not in rollback_step
    assert rollback_step.count("-X POST") == 1
    assert rollback_step.index("build-rollback-deployment") < rollback_step.index("OWNER_D1_ROLLBACK_ATTEMPTED=YES")
    assert rollback_step.index("OWNER_D1_ROLLBACK_ATTEMPTED=YES") < rollback_step.index("-X POST")


@pytest.mark.parametrize("worker,old_count", [("engine", 18), ("chat", 27)])
def test_final_multipart_settings_payload_is_direct_object(worker, old_count):
    args = _engine() if worker == "engine" else _chat()
    patch, anchor = _prepare(worker)
    old_version = args[3]
    assert validate_patch_settings(patch, old_version, OWNER) == OWNER
    assert set(patch) == {"bindings", "annotations"}
    assert len(patch["bindings"]) == old_count + 1
    assert all(item["version_id"] == anchor["rollback_version_id"]
               for item in patch["bindings"][:-1])


@pytest.mark.parametrize("mutation", [
    "double_wrapper", "missing_owner", "renamed_existing",
    "inherit_latest", "foreign_database", "extra_setting", "annotations_drift",
])
def test_final_multipart_payload_rejects_wrong_or_unexpected_fields(mutation):
    patch, _ = _prepare("engine")
    old_version = _engine()[3]
    bad = copy.deepcopy(patch)
    if mutation == "double_wrapper":
        bad = {"settings": bad}
    elif mutation == "missing_owner":
        bad["bindings"].pop()
    elif mutation == "renamed_existing":
        bad["bindings"][0]["name"] = "RENAMED"
    elif mutation == "inherit_latest":
        bad["bindings"][0]["version_id"] = "latest"
    elif mutation == "foreign_database":
        bad["bindings"][-1]["database_id"] = "INVALID"
    elif mutation == "extra_setting":
        bad["some-unrelated-setting"] = {}
    else:
        bad["annotations"]["workers/message"] = "unapproved"
    with pytest.raises(TransactionError):
        validate_patch_settings(bad, old_version, OWNER)


@pytest.mark.parametrize("worker", ["engine", "chat"])
def test_http_200_patch_response_requires_added_owner_binding(worker):
    args = _engine() if worker == "engine" else _chat()
    before = args[3]
    patch, _ = _prepare(worker)
    success = {"success": True, "result": {
        "bindings": copy.deepcopy(before["result"]["resources"]["bindings"]) + [
            {"type": "d1", "name": OWNER_BINDING, "database_id": OWNER}
        ]
    }}
    verify_patch_response(before, success, patch, OWNER)
    # Observed real Cloudflare 2026-10-09 behavior: HTTP 200, success true,
    # a new served version, but the response had NO Owner D1 binding.
    no_op = {"success": True, "result": {
        "bindings": copy.deepcopy(before["result"]["resources"]["bindings"])
    }}
    with pytest.raises(TransactionError, match="PATCH_RESPONSE_D1_NOT_APPLIED"):
        verify_patch_response(before, no_op, patch, OWNER)
    other_id = copy.deepcopy(success)
    other_id["result"]["bindings"][-1]["database_id"] = fixture.CHAT_DB
    with pytest.raises(TransactionError, match="PATCH_RESPONSE_D1_NOT_APPLIED"):
        verify_patch_response(before, other_id, patch, OWNER)
    missing_existing = copy.deepcopy(success)
    missing_existing["result"]["bindings"].pop(0)
    with pytest.raises(TransactionError, match="PATCH_RESPONSE_D1_NOT_APPLIED"):
        verify_patch_response(before, missing_existing, patch, OWNER)


def test_verify_patch_response_cli_uses_actual_file_and_safe_diagnostics(tmp_path, capsys):
    args = _engine()
    patch, _ = _prepare("engine")
    pre_path = tmp_path / "before.json"
    proposal_path = tmp_path / "settings.json"
    response_path = tmp_path / "cloudflare-response.json"
    pre_path.write_text(json.dumps(args[3]), encoding="utf-8")
    proposal_path.write_text(json.dumps(patch), encoding="utf-8")
    no_op = {"success": True, "result": {
        "bindings": copy.deepcopy(args[3]["result"]["resources"]["bindings"])
    }}
    response_path.write_text(json.dumps(no_op), encoding="utf-8")
    database_paths = []
    for label, name in (("owner", fixture.mod.OWNER_NAME),
                        ("chat", "padiem-chat-db"),
                        ("engine", "padiem-engine")):
        path = tmp_path / f"database-{label}.json"
        path.write_text(json.dumps(args[0][name]), encoding="utf-8")
        database_paths.extend([f"--d1-{label}", str(path)])
    command = ["verify-patch-response",
               "--before", str(pre_path),
               "--candidate", str(proposal_path),
               "--response", str(response_path), *database_paths]
    assert main(command) == 2
    stderr = capsys.readouterr().err
    assert "PATCH_RESPONSE_D1_NOT_APPLIED" in stderr
    assert OWNER not in stderr
    good = copy.deepcopy(no_op)
    good["result"]["bindings"].append(
        {"type": "d1", "name": OWNER_BINDING, "database_id": OWNER}
    )
    response_path.write_text(json.dumps(good), encoding="utf-8")
    assert main(command) == 0
    assert "OWNER_D1_PATCH_RESPONSE_D1_AUTHORITY=PASS" in capsys.readouterr().out
    # The original 200-success bug also fails at the final form-part file.
    proposal_path.write_text(json.dumps({"settings": patch}), encoding="utf-8")
    assert main(command) == 2
    assert "PATCH_SETTINGS_TOP_LEVEL_INVALID" in capsys.readouterr().err


def test_workflow_checks_actual_cloudflare_patch_response_binding():
    wf = WORKFLOW.read_text(encoding="utf-8")
    apply = wf.split("      - name: PATCH existing Worker settings ONE time", 1)[1]
    patch = apply.split("      - name: Verify new 100-percent served version", 1)[0]
    assert patch.count("-X PATCH") == 1
    assert '-F "settings=@${RUNNER_TEMP}/candidate.json;type=application/json"' in patch
    assert "verify-patch-response" in patch
    assert "--before" in patch and "--candidate" in patch and "--response" in patch
    assert all(f"--d1-{name}" in patch for name in ("owner", "chat", "engine"))
    assert patch.index("jq -e '.success == true'") < patch.index("verify-patch-response")
    assert patch.index("verify-patch-response") < patch.index(
        "OWNER_D1_PATCH_RESPONSE=OWNER_BINDING_ADDED_PENDING_SERVED_VERIFICATION"
    )


def test_final_json_rejects_substituted_other_canonical_d1_uuid():
    old_version = _engine()[3]
    patch, _ = _prepare("engine")
    patch["bindings"][-1]["database_id"] = fixture.CHAT_DB
    with pytest.raises(TransactionError, match="PATCH_SETTINGS_OWNER_D1_ID_MISMATCH"):
        validate_patch_settings(patch, old_version, OWNER)


@pytest.mark.parametrize("worker", ["engine", "chat"])
def test_real_api_changed_etag_and_upload_source_with_identical_bytes_is_accepted(worker):
    args = _engine() if worker == "engine" else _chat()
    original = args[3]
    _, anchor = _prepare(worker)
    original["result"]["resources"]["script"]["last_deployed_from"] = "wrangler"
    after = copy.deepcopy(original)
    after["result"]["id"] = "new-live-version"
    after["result"]["resources"]["bindings"].append(
        {"type": "d1", "name": OWNER_BINDING, "database_id": OWNER}
    )
    after["result"]["resources"]["script"]["etag"] = "cloudflare-reissued-etag"
    after["result"]["resources"]["script"]["last_deployed_from"] = "api"
    settings = {"success": True, "result": {
        "bindings": copy.deepcopy(after["result"]["resources"]["bindings"])
    }}
    old_code = _module_response(original["result"]["id"])
    new_code = _module_response(after["result"]["id"])
    assert assert_exact_worker_code(
        old_code, new_code, original["result"]["id"], after["result"]["id"]
    ) == 2
    assert verify(
        original, after, fixture._deploy("new-live-version"),
        settings, OWNER, anchor, old_code, new_code
    ) == "new-live-version"


@pytest.mark.parametrize("tamper", [
    "content", "new_module", "remove_module", "mime", "different_version",
    "empty_modules", "invalid_base64", "duplicate_name", "extra_field",
])
def test_exact_module_guard_rejects_all_code_and_evidence_drift(tamper):
    old_code = _module_response("original-version")
    new_code = _module_response("new-version")
    if tamper == "content":
        new_code["result"]["modules"][0]["content_base64"] = base64.b64encode(
            b"malicious-different-code"
        ).decode("ascii")
    elif tamper == "new_module":
        new_code["result"]["modules"].append({
            "name": "rogue.py", "content_type": "text/x-python",
            "content_base64": base64.b64encode(b"print(9)").decode("ascii"),
        })
    elif tamper == "remove_module":
        new_code["result"]["modules"].pop()
    elif tamper == "mime":
        new_code["result"]["modules"][0]["content_type"] = "text/plain"
    elif tamper == "different_version":
        new_code["result"]["id"] = "wrong-version"
    elif tamper == "empty_modules":
        new_code["result"]["modules"] = []
    elif tamper == "invalid_base64":
        new_code["result"]["modules"][0]["content_base64"] = "invalid%"
    elif tamper == "duplicate_name":
        new_code["result"]["modules"][1]["name"] = "main.py"
    else:
        new_code["result"]["modules"][0]["source_map"] = "unexpected"
    with pytest.raises(TransactionError):
        assert_exact_worker_code(old_code, new_code, "original-version", "new-version")


def test_changed_etag_with_changed_module_bytes_never_accepted():
    args = _engine()
    original = args[3]
    _, anchor = _prepare("engine")
    after = copy.deepcopy(original)
    after["result"]["id"] = "new-live-version"
    after["result"]["resources"]["bindings"].append(
        {"type": "d1", "name": OWNER_BINDING, "database_id": OWNER}
    )
    after["result"]["resources"]["script"]["etag"] = "different-hash"
    after["result"]["resources"]["script"]["last_deployed_from"] = "api"
    settings = {"success": True, "result": {
        "bindings": copy.deepcopy(after["result"]["resources"]["bindings"])
    }}
    with pytest.raises(TransactionError, match="CODE_MODULE_CONTENT_DRIFT"):
        verify(original, after, fixture._deploy("new-live-version"), settings,
               OWNER, anchor, _module_response(original["result"]["id"]),
               _module_response("new-live-version", body=b"changed code"))


def test_matching_modules_never_override_drift_in_other_script_metadata():
    args = _engine()
    original = args[3]
    _, anchor = _prepare("engine")
    after = copy.deepcopy(original)
    after["result"]["id"] = "new-live-version"
    after["result"]["resources"]["bindings"].append(
        {"type": "d1", "name": OWNER_BINDING, "database_id": OWNER}
    )
    after["result"]["resources"]["script"]["etag"] = "different"
    after["result"]["resources"]["script"]["handlers"] = ["other"]
    settings = {"success": True, "result": {
        "bindings": copy.deepcopy(after["result"]["resources"]["bindings"])
    }}
    with pytest.raises(TransactionError, match="CODE_SCRIPT_OTHER_METADATA_DRIFT"):
        verify(original, after, fixture._deploy("new-live-version"), settings,
               OWNER, anchor, _module_response(original["result"]["id"]),
               _module_response("new-live-version"))


def test_production_workflow_gets_explicit_version_modules_and_never_uses_mutable_content():
    text = WORKFLOW.read_text(encoding="utf-8")
    step = text.split("      - name: Verify new 100-percent served version and ALL existing resources", 1)[1]
    step = step.split("      - name: Fail closed on ambiguous or failed mutation", 1)[0]
    assert "/workers/workers/${OWNER_WORKER}/versions" in step
    assert "${OWNER_D1_PRE_VERSION}?include=modules" in step
    assert "${fresh}?include=modules" in step
    assert '--pre-modules "${RUNNER_TEMP}/version-modules-pre.json"' in step
    assert '--post-modules "${RUNNER_TEMP}/version-modules-post.json"' in step
    assert "rm -f" in step
    assert "/scripts/${OWNER_WORKER}/content" not in step
    assert "actions/upload-artifact" not in step

def test_zero_byte_module_is_hashed_and_compared_as_valid_content():
    before = _module_response("original-version")
    after = _module_response("new-version")
    before["result"]["modules"][0]["content_base64"] = ""
    after["result"]["modules"][0]["content_base64"] = ""
    assert assert_exact_worker_code(before, after, "original-version", "new-version") == 2
    after["result"]["modules"][0]["content_base64"] = base64.b64encode(b"now nonempty").decode()
    with pytest.raises(TransactionError, match="CODE_MODULE_CONTENT_DRIFT"):
        assert_exact_worker_code(before, after, "original-version", "new-version")
