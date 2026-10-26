"""Binding declaration locks that outlive the per-binding activation gates (#5898 follow-up).

The single-binding attach/detach gates were retired because the repository
declaration is now the binding authority. What stays locked here is the
declaration topology and the one production config generator - neither is a
gate's YAML.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHAT_WANGLER = ROOT / "apps/padiem-chat" / "wrangler.toml"
ENGINE_D1_GATE = ROOT / ".github/workflows/b54-engine-d1-provision-gate.yml"


def test_b54_engine_d1_gate_0008_source_contract() -> None:
    gate = ENGINE_D1_GATE.read_text(encoding="utf-8")
    assert "D1_MIGRATION_0008=APPLIED_OR_REPLAY_SAFE" in gate
    assert "D1_DRIVE_CASE_FOLDER_TABLE_ASSERT=PASS" in gate
    assert "D1_DRIVE_CASE_FOLDER_INDEX_ASSERT=PASS" in gate
    assert "0008_engine_drive_case_folder_bindings.sql" in gate
    print("ENGINE_D1_GATE_0008_SOURCE_CONTRACT=PASS")


def test_no_second_production_config_generator() -> None:
    scripts = sorted((ROOT / ".github/scripts").glob("*production_deploy_config*.py"))
    assert [p.name for p in scripts] == ["b62_cloudflare_production_deploy_config.py"]
    print("SECOND_PRODUCTION_CONFIG_GENERATOR=0")


def test_chat_wrangler_declares_the_already_live_engine_target() -> None:
    services = tomllib.loads(CHAT_WANGLER.read_text(encoding="utf-8"))["services"]
    matches = [x for x in services if x["binding"] == "P01_ENGINE_SERVICE"]
    assert matches == [{"binding": "P01_ENGINE_SERVICE", "service": "padiem-ai-engine"}]
