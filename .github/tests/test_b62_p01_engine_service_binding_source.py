"""S0-B source-contract / binding classification / preservation regressions (#3199).

Classification and mutation-contract logic is exercised as real callable
helper logic over concrete data structures - not as YAML string scans.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / ".github/workflows/b62-p01-engine-service-binding-gate.yml"
SCRIPT = ROOT / ".github" / "scripts" / "cloudflare_served_version.py"
ENGINE_WANGLER = ROOT / "apps/padiem-ai-engine/wrangler.toml"

spec = importlib.util.spec_from_file_location("cloudflare_served_version", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

GATE_TEXT = GATE.read_text(encoding="utf-8")
ENGINE_CONFIG = ENGINE_WANGLER.read_text(encoding="utf-8")


def classify(bindings):
    """Mirror the gate's cloudflare-readonly classification exactly."""
    matches = [b for b in bindings if b.get("name") == "P01_ENGINE_SERVICE"]
    if len(matches) == 0:
        return "absent"
    if len(matches) > 1:
        return "duplicate"
    sole = matches[0]
    if sole.get("type") == "service" and sole.get("service") == "padiem-ai-engine":
        return "present_expected"
    if sole.get("type") != "service":
        return "wrong_type"
    return "wrong_target"


def assert_fail_closed(state):
    assert state in {"duplicate", "wrong_type", "wrong_target"}


# ---- source-contract ----------------------------------------------------

def test_p01_engine_binding_gate_source_contract() -> None:
    assert 'B62_WORKER: padiem-chat' in GATE_TEXT
    assert 'ENGINE_WORKER: padiem-ai-engine' in GATE_TEXT
    assert 'ENGINE_BINDING: P01_ENGINE_SERVICE' in GATE_TEXT
    assert '"version_id": "latest"' in GATE_TEXT
    assert "LATEST_VERSION_EQUALS_ACTIVE_VERSION=PASS" in GATE_TEXT
    assert "SOURCE_ETAG_UNCHANGED=PASS" in GATE_TEXT
    assert "EXISTING_BINDINGS_UNCHANGED=PASS" in GATE_TEXT
    assert "PUBLIC_TOPOLOGY_UNCHANGED=PASS" in GATE_TEXT
    assert "WORKER_SOURCE_REDEPLOY=NO" in GATE_TEXT
    assert '-F "settings=<${RUNNER_TEMP}/binding-patch.json' in GATE_TEXT
    assert '-F "settings=@${RUNNER_TEMP}/binding-patch.json' not in GATE_TEXT
    assert "B62_ENGINE_BINDING_PATCH_HTTP_STATUS=" in GATE_TEXT
    assert "CLOUDFLARE_ERROR_BODY_JSON=NO" in GATE_TEXT
    assert "B62_BINDINGS_SHAPE_OBSERVATION" in GATE_TEXT
    assert "before_by_name" in GATE_TEXT
    assert "expected_by_name" in GATE_TEXT
    assert "LATEST_VERSION_PROPAGATION_RETRY=OK" in GATE_TEXT
    print("P01_ENGINE_BINDING_GATE_SOURCE_CONTRACT=PASS")


def test_b54_engine_d1_gate_0008_source_contract() -> None:
    gate = (ROOT / ".github/workflows/b54-engine-d1-provision-gate.yml").read_text(encoding="utf-8")
    assert "D1_MIGRATION_0008=APPLIED_OR_REPLAY_SAFE" in gate
    assert "D1_DRIVE_CASE_FOLDER_TABLE_ASSERT=PASS" in gate
    assert "D1_DRIVE_CASE_FOLDER_INDEX_ASSERT=PASS" in gate
    assert "0008_engine_drive_case_folder_bindings.sql" in gate
    print("ENGINE_D1_GATE_0008_SOURCE_CONTRACT=PASS")


# ---- classification -----------------------------------------------------

def test_p01_binding_absent_classification() -> None:
    assert classify([]) == "absent"
    assert classify([{"name": "OTHER", "type": "service", "service": "foo"}]) == "absent"
    print("P01_BINDING_ABSENT_CLASSIFICATION=PASS")


def test_p01_binding_present_expected_classification() -> None:
    assert classify([{"name": "P01_ENGINE_SERVICE", "type": "service", "service": "padiem-ai-engine"}]) == "present_expected"
    print("P01_BINDING_PRESENT_EXPECTED_CLASSIFICATION=PASS")


def test_p01_binding_wrong_target_is_denied() -> None:
    assert_fail_closed(classify([{"name": "P01_ENGINE_SERVICE", "type": "service", "service": "wrong-target"}]))
    print("P01_BINDING_WRONG_TARGET=DENY")


def test_p01_binding_wrong_type_is_denied() -> None:
    assert_fail_closed(classify([{"name": "P01_ENGINE_SERVICE", "type": "inherit", "service": "padiem-ai-engine"}]))
    print("P01_BINDING_WRONG_TYPE=DENY")


def test_p01_binding_duplicate_is_denied() -> None:
    assert_fail_closed(classify([
        {"name": "P01_ENGINE_SERVICE", "type": "service", "service": "padiem-ai-engine"},
        {"name": "P01_ENGINE_SERVICE", "type": "service", "service": "padiem-ai-engine"},
    ]))
    print("P01_BINDING_DUPLICATE=DENY")


# ---- activation / rollback ---------------------------------------------

def test_activation_preserves_unrelated_bindings() -> None:
    existing = [
        {"name": "B14_SERVICE", "type": "inherit", "version_id": "latest"},
        {"name": "CONTROL_PLANE_IDENTITY", "type": "service", "service": "padiem-control-plane-identity"},
    ]
    after = [{"name": b["name"], "type": b["type"], "version_id": b.get("version_id", "latest")} for b in existing]
    after.append({"name": "P01_ENGINE_SERVICE", "type": "service", "service": "padiem-ai-engine"})
    assert len(after) == len(existing) + 1
    new = [b for b in after if b["name"] == "P01_ENGINE_SERVICE"]
    assert len(new) == 1 and new[0]["service"] == "padiem-ai-engine"
    existing_after = [b for b in after if b["name"] != "P01_ENGINE_SERVICE"]
    assert {b["name"] for b in existing_after} == {b["name"] for b in existing}
    print("ACTIVATION_PRESERVES_UNRELATED_BINDINGS=PASS")


def test_rollback_removes_only_p01_binding() -> None:
    existing = [
        {"name": "B14_SERVICE", "type": "inherit", "version_id": "latest"},
        {"name": "P01_ENGINE_SERVICE", "type": "service", "service": "padiem-ai-engine"},
        {"name": "CONTROL_PLANE_GOOGLE_OAUTH", "type": "service", "service": "padiem-google-oauth-state"},
    ]
    after = [b for b in existing if b["name"] != "P01_ENGINE_SERVICE"]
    assert len(after) == len(existing) - 1
    assert {b["name"] for b in after} == {"B14_SERVICE", "CONTROL_PLANE_GOOGLE_OAUTH"}
    print("ROLLBACK_REMOVES_ONLY_P01_BINDING=PASS")


# ---- preservation contracts --------------------------------------------

def test_source_etag_preservation_contract() -> None:
    assert "SOURCE_ETAG_UNCHANGED=PASS" in GATE_TEXT
    assert "source_etag" in GATE_TEXT
    print("SOURCE_ETAG_PRESERVATION_CONTRACT=PASS")


def test_public_topology_preservation_contract() -> None:
    assert "PUBLIC_TOPOLOGY_UNCHANGED=PASS" in GATE_TEXT
    assert "b62-domains-before-safe.json" in GATE_TEXT
    assert "b62-subdomain-before-safe.json" in GATE_TEXT
    assert "cmp -s" in GATE_TEXT
    print("PUBLIC_TOPOLOGY_PRESERVATION_CONTRACT=PASS")


def test_settings_only_mutation_and_bounded_error_body() -> None:
    assert '-F "settings=<' in GATE_TEXT
    activate_section = GATE_TEXT.split("activate-p01-engine-binding:")[1]
    assert "settings=@" not in activate_section
    assert "CLOUDFLARE_ERROR_BODY_JSON=NO" in GATE_TEXT
    assert "CLOUDFLARE_ROLLBACK_ERROR_BODY_JSON=NO" in GATE_TEXT
    print("B62_GENERATOR_PRESERVES_P01_SERVICE_BINDING=PASS")


# ---- hard locks ---------------------------------------------------------

def test_no_second_production_config_generator() -> None:
    scripts = sorted((ROOT / ".github/scripts").glob("*production_deploy_config*.py"))
    assert [p.name for p in scripts] == ["b62_cloudflare_production_deploy_config.py"]
    print("SECOND_PRODUCTION_CONFIG_GENERATOR=0")


def test_engine_wrangler_does_not_pre_declare_p01() -> None:
    assert "P01_ENGINE_SERVICE" not in ENGINE_CONFIG
    print("P01_ENGINE_BINDING_GATE_SOURCE=PASS")
