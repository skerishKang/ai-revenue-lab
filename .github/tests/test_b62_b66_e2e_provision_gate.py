from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / ".github/scripts/b62_b66_e2e_provision.py"
FIXTURE = ROOT / ".github/scripts/b62_b66_e2e_skill_fixture.cjs"
WORKFLOW = ROOT / ".github/workflows/b62-b66-e2e-skill-provision-gate.yml"
PROVISIONER = ROOT / "apps/padiem-chat/app/b66_quote_skill_provisioning.py"
STORE = ROOT / "apps/padiem-chat/app/b66_saved_quote_skill_store.py"

USER_ID = "usr_" + "a" * 32
WORKSPACE = "tenant_" + "b" * 32


def _load():
    spec = importlib.util.spec_from_file_location("b62_b66_e2e_provision", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _d1(rows, *, changes=0):
    return {
        "success": True,
        "result": [{"success": True, "results": rows, "meta": {"changes": changes}}],
    }


def _artifact(tmp_path: Path):
    path = tmp_path / "skill.json"
    subprocess.run(["node", str(FIXTURE), str(path)], check=True, capture_output=True, text=True)
    return path


def _artifact_row(helper, artifact_path: Path, **overrides):
    artifact = helper.load_artifact(artifact_path)
    row = {
        "id": "b66skill_" + "d" * 32,
        "skill_id": artifact.skill_id,
        "skill_name": artifact.skill_name,
        "skill_fingerprint": artifact.fingerprint,
        "skill_version": artifact.version,
        "skill_json": artifact.serialized_json,
        "status": "approved",
    }
    row.update(overrides)
    return row


def test_fixture_uses_canonical_js_and_zero_repeat_calls(tmp_path: Path) -> None:
    helper = _load()
    artifact_path = _artifact(tmp_path)
    artifact = helper.load_artifact(artifact_path)
    payload = json.loads(artifact.serialized_json)
    assert artifact.skill_id == "b66-e2e-canonical-v1"
    assert payload["approval"]["status"] == "approved"
    assert payload["rendererContract"] == "quote-template-renderer.v1"
    assert payload["calculationAuthority"] == "quote-core"
    source = FIXTURE.read_text(encoding="utf-8")
    assert 'require(path.join(B66, "quote-skill.js"))' in source
    assert "structuredRepeatGenerationModelCalls" in source
    assert "sourceDocumentReanalysisPerRepeat" in source
    assert "fullDocumentAiRegenerationPerRepeat" in source


def test_target_user_is_protected_and_workspace_is_server_projection(tmp_path: Path, monkeypatch) -> None:
    helper = _load()
    monkeypatch.setenv(helper.TARGET_USER_ENV, USER_ID)
    query_path = tmp_path / "resolve-query.json"
    helper.build_resolution_query(query_path)
    query = json.loads(query_path.read_text(encoding="utf-8"))
    assert query["params"][:4] == [USER_ID, USER_ID, USER_ID, USER_ID]
    assert "claw_approved_memory" in query["sql"]
    assert "claw_run_history" in query["sql"]
    assert "control_plane_identity_shadow" in query["sql"]

    response = tmp_path / "resolve-response.json"
    response.write_text(
        json.dumps(
            _d1([{
                "user_count": 1,
                "shadow_active_count": 1,
                "workspace_count": 1,
                "workspace_id": WORKSPACE,
            }])
        ),
        encoding="utf-8",
    )
    workspace_file = tmp_path / "workspace.txt"
    helper.resolve_workspace(response, workspace_file)
    assert workspace_file.read_text(encoding="utf-8") == WORKSPACE


@pytest.mark.parametrize(
    "row",
    [
        {"user_count": 0, "shadow_active_count": 1, "workspace_count": 1, "workspace_id": WORKSPACE},
        {"user_count": 1, "shadow_active_count": 0, "workspace_count": 1, "workspace_id": WORKSPACE},
        {"user_count": 1, "shadow_active_count": 1, "workspace_count": 0, "workspace_id": None},
        {"user_count": 1, "shadow_active_count": 1, "workspace_count": 2, "workspace_id": WORKSPACE},
        {"user_count": 1, "shadow_active_count": 1, "workspace_count": 1, "workspace_id": "owner:" + USER_ID},
    ],
)
def test_workspace_resolution_fails_closed(row, tmp_path: Path) -> None:
    helper = _load()
    response = tmp_path / "bad.json"
    response.write_text(json.dumps(_d1([row])), encoding="utf-8")
    with pytest.raises(helper.ProvisionError):
        helper.resolve_workspace(response, tmp_path / "workspace.txt")


def test_existing_state_missing_exact_drift(tmp_path: Path) -> None:
    helper = _load()
    artifact_path = _artifact(tmp_path)
    missing = tmp_path / "missing.json"
    exact = tmp_path / "exact.json"
    drift = tmp_path / "drift.json"
    missing.write_text(json.dumps(_d1([])), encoding="utf-8")
    exact.write_text(json.dumps(_d1([_artifact_row(helper, artifact_path)])), encoding="utf-8")
    drift.write_text(
        json.dumps(_d1([_artifact_row(helper, artifact_path, skill_fingerprint="0" * 64)])),
        encoding="utf-8",
    )
    assert helper.classify_existing(missing, artifact_path) == "missing"
    assert helper.classify_existing(exact, artifact_path) == "exact"
    assert helper.classify_existing(drift, artifact_path) == "drift"


def test_insert_is_create_only_one_row_and_matches_store_insert_shape(tmp_path: Path, monkeypatch) -> None:
    helper = _load()
    monkeypatch.setenv(helper.TARGET_USER_ENV, USER_ID)
    artifact_path = _artifact(tmp_path)
    workspace_file = tmp_path / "workspace.txt"
    workspace_file.write_text(WORKSPACE, encoding="utf-8")
    row_file = tmp_path / "row.txt"
    query_file = tmp_path / "insert.json"
    helper.build_insert_query(workspace_file, artifact_path, row_file, query_file)
    query = json.loads(query_file.read_text(encoding="utf-8"))
    assert query["sql"].startswith("INSERT INTO b66_saved_quote_skill")
    assert "UPDATE " not in query["sql"].upper()
    assert len(query["params"]) == 10
    assert query["params"][1] == USER_ID
    assert query["params"][2] == WORKSPACE
    assert row_file.read_text(encoding="utf-8").startswith("b66skill_")

    store = STORE.read_text(encoding="utf-8")
    assert "INSERT INTO b66_saved_quote_skill" in store
    assert "skill_version, skill_json, status, created_at, updated_at" in store
    assert "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'approved', ?, ?)" in store


def test_mutation_and_readback_are_exact(tmp_path: Path) -> None:
    helper = _load()
    artifact_path = _artifact(tmp_path)
    response = tmp_path / "mutation.json"
    response.write_text(json.dumps(_d1([], changes=1)), encoding="utf-8")
    helper.verify_mutation(response)

    row_file = tmp_path / "row.txt"
    row_file.write_text("b66skill_" + "d" * 32, encoding="utf-8")
    readback = tmp_path / "readback.json"
    readback.write_text(
        json.dumps(_d1([_artifact_row(helper, artifact_path)])),
        encoding="utf-8",
    )
    helper.verify_readback(readback, artifact_path, row_file)

    absent = tmp_path / "absent.json"
    absent.write_text(json.dumps(_d1([])), encoding="utf-8")
    helper.verify_absent(absent)


def test_workflow_contract_is_bounded_and_no_public_provision_route() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    dispatch = workflow.split("workflow_dispatch:", 1)[1].split("permissions:", 1)[0]
    assert "B62_B66_E2E_TARGET_USER_ID" in workflow
    assert "target_user" not in dispatch
    assert "workspace_id" not in dispatch
    assert "CONFIRM_ASSIGN_B66_E2E_SKILL_FROM_EXACT_MAIN" in workflow
    assert "environment: production" in workflow
    assert 'test "$(git rev-parse origin/main)" = "${TARGET_SHA}"' in workflow
    assert "D1_MUTATION_MAX_ROWS=1" in workflow
    assert "B62_B66_E2E_POST_READBACK=EXACT" in workflow
    assert "B62_B66_E2E_ROLLBACK_READBACK=ABSENT" in workflow
    assert "WORKER_DEPLOY=0" in workflow
    assert "MODEL_CALLS=0" in workflow
    assert "SOURCE_PARSE_CALLS=0" in workflow
    assert "RAW_TARGET_USER_OUTPUT=0" in workflow
    assert "b62_b66_e2e_skill_fixture.cjs" in workflow
    assert "b62_b66_e2e_provision.py" in workflow
    for forbidden in ("wrangler deploy", "pywrangler deploy", "PADIEM_CHAT_B66_QUOTE_BASE_URL="):
        assert forbidden not in workflow

    provisioner = PROVISIONER.read_text(encoding="utf-8").lower()
    assert "@router" not in provisioner
    assert "request.json" not in provisioner
