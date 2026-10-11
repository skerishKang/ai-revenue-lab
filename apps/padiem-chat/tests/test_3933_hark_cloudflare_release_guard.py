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
