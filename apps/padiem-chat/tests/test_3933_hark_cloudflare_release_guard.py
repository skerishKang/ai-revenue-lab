"""Release-level fail-closed parity guards, no Cloudflare API calls."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "hark_cloudflare_release_guard.py"
spec = importlib.util.spec_from_file_location("hark_release_guard", SCRIPT)
assert spec and spec.loader
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
REPO = ROOT.parents[1]
CHAT = ROOT / "wrangler.toml"
ENGINE = REPO / "apps" / "padiem-ai-engine" / "wrangler.toml"


def test_source_bindings_match_live_provenance_and_never_activate_hark():
    guard.assert_configured_source(CHAT, ENGINE)
    config = guard._load_toml(CHAT)
    assert "PADIEM_WEB_XLSX_QUOTE_PDF_ENABLED" not in config.get("vars", {})
    assert config["compatibility_date"] >= "2026-03-24"


def test_source_toml_must_not_replace_live_service_inventory():
    chat = guard._load_toml(CHAT)
    # Source defaults are intentionally incomplete for managed Production.
    assert chat["vars"]["PADIEM_CHAT_RUNTIME_MODE"] == "mock"
    assert guard.B62_ADDED_BINDING == "BROWSER"
    baseline = {
        "PADIEM_CHAT_DB": "d1",
        "P01_ENGINE_SERVICE": "service",
        "PADIEM_WORKSPACE_FILES": "r2_bucket",
        "PADIEM_CHAT_SESSION_SECRET": "secret_text",
        "PADIEM_CHAT_DAUM_REST_API_KEY": "secrets_store_secret",
        "B14_SERVICE": "service",
    }
    candidate = {"ASSETS": "assets", "B14_SERVICE": "service",
                 "BROWSER": "browser"}
    engine_baseline = {
        "ENGINE_CONTINUATION": "d1",
        "CONTROL_PLANE_IDENTITY": "service",
    }
    engine_candidate = {
        "ENGINE_CONTINUATION": "d1",
        guard.ENGINE_ADDED_BINDING: "d1",
    }
    errors = guard.audit_replacement(
        baseline, engine_baseline, candidate, engine_candidate)
    assert any("DROP bindings" in x and "PADIEM_CHAT_DB" in x for x in errors)
    assert any("P01_ENGINE_SERVICE" in x for x in errors)
    assert any("PADIEM_WORKSPACE_FILES" in x for x in errors)
    assert any("PADIEM_CHAT_SESSION_SECRET" in x for x in errors)
    assert any("CONTROL_PLANE_IDENTITY" in x for x in errors)


def test_full_compatible_candidate_names_types_must_keep_all_existing_bindings():
    baseline_b62 = {"A": "assets", "D1": "d1", "SECRET": "secret_text",
                    "P01": "service", "R2": "r2_bucket"}
    baseline_engine = {"EXISTING_D1": "d1", "CP": "service"}
    valid_b62 = {**baseline_b62, guard.B62_ADDED_BINDING: "browser"}
    valid_engine = {**baseline_engine, guard.ENGINE_ADDED_BINDING: "d1"}
    assert guard.audit_replacement(
        baseline_b62, baseline_engine, valid_b62, valid_engine) == []
    bad_b62 = {**valid_b62, "D1": "kv_namespace"}
    errors = guard.audit_replacement(
        baseline_b62, baseline_engine, bad_b62, valid_engine)
    assert any("RETYPE" in x and "D1" in x for x in errors)
    errors = guard.audit_replacement(
        baseline_b62, baseline_engine,
        {k: v for k, v in valid_b62.items() if k != "SECRET"},
        valid_engine)
    assert any("DROP" in x and "SECRET" in x for x in errors)


def test_version_binding_parser_refuses_invalid_or_duplicate_input(tmp_path):
    filename = tmp_path / "version.json"
    filename.write_text(json.dumps({
        "resources": {"bindings": [
            {"name": "PADIEM_CHAT_DB", "type": "d1", "database_id": "fake"},
            {"name": "BROWSER", "type": "browser"},
        ]},
    }), encoding="utf-8")
    assert guard.read_version_bindings(filename) == {
        "PADIEM_CHAT_DB": "d1", "BROWSER": "browser"}
    filename.write_text(json.dumps({
        "resources": {"bindings": [
            {"name": "BROWSER", "type": "browser"},
            {"name": "BROWSER", "type": "kv_namespace"},
        ]},
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        guard.read_version_bindings(filename)
    filename.write_text('{"resources":{"bindings":{"BROWSER":"browser"}}}')
    with pytest.raises(ValueError, match="resources.bindings"):
        guard.read_version_bindings(filename)


def test_release_guard_blocks_without_real_candidate_and_never_deploys(
    tmp_path, capsys,
):
    b = tmp_path / "b62.json"
    e = tmp_path / "engine.json"
    for path in (b, e):
        path.write_text('{"resources":{"bindings":[]}}', encoding="utf-8")
    assert guard.main([
        "--chat-toml", str(CHAT), "--engine-toml", str(ENGINE),
        "--live-b62-version", str(b), "--live-engine-version", str(e),
    ]) == 2
    captured = capsys.readouterr().out
    assert "BLOCKED candidate version manifests absent" in captured
    assert "never deploys" not in captured  # no operation performed

def test_live_resource_identifiers_cannot_be_rebound_even_with_same_name_type():
    live_b62 = {
        "PADIEM_CHAT_DB": {"database_id": guard.ENGINE_PRIVATE_DB_ID},
        "P01_ENGINE_SERVICE": {"service": "padiem-ai-engine",
                               "environment": "production"},
        "PADIEM_WORKSPACE_FILES": {"bucket_name": "padiem-workspace-files"},
    }
    live_engine = {"ENGINE_CONTINUATION": {
        "database_id": "6b77ad02-bc27-488f-bb97-6325f6750cba"}}
    updated_engine = {
        **live_engine,
        guard.ENGINE_ADDED_BINDING: {"database_id": guard.ENGINE_PRIVATE_DB_ID},
    }
    assert guard.audit_resource_identity(
        live_b62, live_engine, live_b62, updated_engine) == []
    wrong_db = {
        **updated_engine,
        guard.ENGINE_ADDED_BINDING: {"database_id": "other-db"},
    }
    assert any("private D1 target" in x for x in guard.audit_resource_identity(
        live_b62, live_engine, live_b62, wrong_db))
    wrong_service = {
        **live_b62, "P01_ENGINE_SERVICE": {"service": "attacker",
                                         "environment": "production"},
    }
    assert any("REBIND P01_ENGINE_SERVICE" in x for x in
        guard.audit_resource_identity(live_b62, live_engine,
                                      wrong_service, updated_engine))
    wrong_r2 = {
        **live_b62, "PADIEM_WORKSPACE_FILES": {"bucket_name": "foreign"},
    }
    assert any("REBIND PADIEM_WORKSPACE_FILES" in x for x in
        guard.audit_resource_identity(live_b62, live_engine,
                                      wrong_r2, updated_engine))


def test_hark_release_blocks_unapproved_additions_even_when_expected_two_present():
    old_b62 = {"ASSETS": "assets", "PADIEM_CHAT_DB": "d1"}
    old_engine = {"ENGINE_CONTINUATION": "d1", "CP": "service"}
    next_b62 = {**old_b62, "BROWSER": "browser"}
    next_engine = {**old_engine, "WEB_XLSX_PRIVATE_B62_D1": "d1"}
    assert guard.audit_replacement(old_b62, old_engine, next_b62, next_engine) == []

    wrong_b62 = {**next_b62, "OTHER_TOKEN": "secret_text"}
    errors = guard.audit_replacement(old_b62, old_engine, wrong_b62, next_engine)
    assert any("padiem-chat would ADD unapproved" in item
               and "OTHER_TOKEN" in item for item in errors)

    wrong_engine = {**next_engine, "UNREVIEWED_SERVICE": "service"}
    errors = guard.audit_replacement(old_b62, old_engine, next_b62, wrong_engine)
    assert any("padiem-ai-engine would ADD unapproved" in item
               and "UNREVIEWED_SERVICE" in item for item in errors)

    # Already commissioned expected names are valid; adding an unrelated
    # authority is not excused by an otherwise identical prior binding.
    assert guard.audit_replacement(
        next_b62, next_engine, next_b62,
        {**next_engine, "UNREVIEWED": "r2_bucket"},
    )


def _version_export(version_id: str, bindings: list[dict]) -> dict:
    return {
        "id": version_id,
        "resources": {
            "script": {"etag": "script-proof"},
            "script_runtime": {"compatibility_date": "2026-09-01"},
            "bindings": bindings,
        },
    }


def test_immutable_cloudflare_version_shape_required(tmp_path):
    p = tmp_path / "version.json"
    valid = _version_export(
        "50cd1dc1-c0da-4963-abbe-b235a950c9b1",
        [{"name": "PADIEM_CHAT_DB", "type": "d1"}],
    )
    p.write_text(json.dumps(valid), encoding="utf-8")
    assert guard.read_immutable_version_proof(p) == valid["id"]
    for bad in (
        {"resources": valid["resources"]},
        {"id": "fake", "resources": valid["resources"]},
        {**valid, "resources": {"bindings": valid["resources"]["bindings"]}},
        {**valid, "resources": {**valid["resources"], "script": {}}},
        {**valid, "resources": {**valid["resources"], "bindings": {}}},
    ):
        p.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ValueError, match="immutable Cloudflare"):
            guard.read_immutable_version_proof(p)


def test_release_cli_only_accepts_distinct_real_shaped_candidates(tmp_path, capsys):
    ids = {
        "b62_old": "50cd1dc1-c0da-4963-abbe-b235a950c9b1",
        "engine_old": "3c4cde93-195e-4e3d-a857-b2bb0575f9fd",
        "b62_new": "5ac1c513-f3e8-43e0-aea6-95cb66889aad",
        "engine_new": "28c53e10-b8cc-4bad-8107-469132a284e4",
    }
    chat_old = [
        {"name": "PADIEM_CHAT_DB", "type": "d1",
         "database_id": guard.ENGINE_PRIVATE_DB_ID},
        {"name": "ASSETS", "type": "assets"},
        {"name": "PADIEM_CHAT_SESSION_SECRET", "type": "secret_text"},
    ]
    engine_old = [
        {"name": "ENGINE_CONTINUATION", "type": "d1",
         "database_id": "6b77ad02-bc27-488f-bb97-6325f6750cba"},
        {"name": "CP", "type": "service", "service": "padiem-control-plane-identity"},
    ]
    payloads = {
        "b62_old": chat_old,
        "engine_old": engine_old,
        "b62_new": [*chat_old, {"name": "BROWSER", "type": "browser"}],
        "engine_new": [*engine_old, {
            "name": "WEB_XLSX_PRIVATE_B62_D1", "type": "d1",
            "database_id": guard.ENGINE_PRIVATE_DB_ID,
        }],
    }
    paths = {}
    for key, bindings in payloads.items():
        p = tmp_path / (key + ".json")
        p.write_text(json.dumps(_version_export(ids[key], bindings)), encoding="utf-8")
        paths[key] = p

    args = [
        "--chat-toml", str(CHAT), "--engine-toml", str(ENGINE),
        "--live-b62-version", str(paths["b62_old"]),
        "--live-engine-version", str(paths["engine_old"]),
        "--candidate-b62-version", str(paths["b62_new"]),
        "--candidate-engine-version", str(paths["engine_new"]),
    ]
    assert guard.main(args) == 0
    assert "IMMUTABLE_VERSION_SHAPE_AND_DISTINCT_ID=PASS" in capsys.readouterr().out

    # A fake version that simply reuses the served version is NOT a candidate.
    ids["b62_new"] = ids["b62_old"]
    paths["b62_new"].write_text(
        json.dumps(_version_export(ids["b62_new"], payloads["b62_new"])),
        encoding="utf-8",
    )
    assert guard.main(args) == 2
    assert "distinct immutable" in capsys.readouterr().out

    # Even with both exact desired bindings, an unrelated added service
    # must never be approved for Hark release.
    ids["b62_new"] = "5ac1c513-f3e8-43e0-aea6-95cb66889aad"
    extra = payloads["engine_new"] + [
        {"name": "FOREIGN", "type": "service", "service": "other-worker"},
    ]
    paths["b62_new"].write_text(
        json.dumps(_version_export(ids["b62_new"], payloads["b62_new"])),
        encoding="utf-8",
    )
    paths["engine_new"].write_text(
        json.dumps(_version_export(ids["engine_new"], extra)),
        encoding="utf-8",
    )
    assert guard.main(args) == 2
    assert "ADD unapproved bindings" in capsys.readouterr().out
