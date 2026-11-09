"""#6828 2-2 — the registry switch: off keeps today's behavior, on uses the file.

Contract tests, no provider call: the switch is one environment variable, and a
document that cannot be used installs nothing instead of the repository values.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
for _package in ("packages/padiem-control-plane", "packages/padiem-ai-core"):
    _path = str(_REPO / _package)
    if _path not in sys.path:
        sys.path.insert(0, _path)

from app.pilot import model_registry_file as registry_file
from app.pilot import tier_fallback
from app.pilot.catalog import CATALOG_BY_ID, CATALOG_MODELS

from _registry_values import process_catalog_restored

SWITCH = "PADIEM_MODELS_REGISTRY"
OVERRIDE = "PADIEM_MODELS_REGISTRY_OVERRIDE"
MODEL_A = "example-provider/example-model-1"
MODEL_B = "example-provider/example-model-2"


def _document() -> dict:
    def row(model_id: str, upstream: str, caps: list[str]) -> dict:
        return {
            "id": model_id,
            "provider_id": "example-provider",
            "upstream_model": upstream,
            "capabilities": caps,
            "enabled": True,
            "display_name": upstream.replace("-", " ").title(),
            "provider_name": "Example Provider",
            "context_window": 128000,
            "input_price_usd_per_1m": 0.0,
            "output_price_usd_per_1m": 0.0,
            "source": "fixture",
            "source_checked_at": "2026-11-09",
        }

    return {
        "version": "padiem.models.private.v1",
        "providers": {
            "example-provider": {
                "base_origin": "https://api.example.invalid/v1",
                "allowed_hosts": ["api.example.invalid"],
                "credential_binding": "PADIEM_B14_CREDENTIAL_99",
            }
        },
        "models": [
            row(MODEL_A, "example-model-1", ["chat"]),
            row(MODEL_B, "example-model-2", ["chat", "tools"]),
        ],
        "tiers": {
            "free": {"primary": MODEL_A, "fallback": [MODEL_B]},
            "plus": {"primary": MODEL_B, "fallback": [MODEL_A]},
            "pro": {"primary": MODEL_B, "fallback": []},
            "max": {"primary": MODEL_B, "fallback": []},
        },
    }


@pytest.fixture
def restore():
    """Put the process registry back: these tests mutate process-wide state.

    The switch this process started with is restored verbatim (#7241 3단계): it
    is no longer optional, so clearing it would leave every later suite with no
    catalog at all.
    """
    saved = {name: os.environ.get(name) for name in (SWITCH, OVERRIDE)}
    with process_catalog_restored():
        try:
            yield
        finally:
            for name, value in saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
            registry_file._PRIVATE_SNAPSHOT = None
            registry_file.install_models()


def _private(tmp_path: Path, document: dict | None = None) -> Path:
    target = tmp_path / "models-private.json"
    target.write_text(json.dumps(document or _document()), encoding="utf-8")
    os.chmod(target, 0o600)
    return target


def test_switch_off_serves_no_catalog(restore, monkeypatch):
    """#7241 3단계: without the switch the repository answers nothing at all.

    The shipped document is a schema-shaped placeholder, so "no switch" is a
    fail-closed state, not a working mode: no catalog, no tier, and a reason
    code on the health surface.
    """
    for name in (SWITCH, OVERRIDE):
        monkeypatch.delenv(name, raising=False)
    registry_file._PRIVATE_SNAPSHOT = None
    assert registry_file.private_registry_enabled() is False
    assert tier_fallback.effective_tier_default() == ""
    assert tier_fallback.effective_tier_fallback() == {}
    with pytest.raises(registry_file.ModelRegistryError):
        registry_file.read_registry()
    registry_file.install_models()
    assert CATALOG_BY_ID == {}
    assert registry_file.private_registry_state() == {
        "enabled": False, "ok": False, "models": 0,
        "reason": registry_file.SWITCH_MISSING}


def test_switch_on_installs_the_private_catalog(restore, tmp_path, monkeypatch):
    monkeypatch.setenv(SWITCH, str(_private(tmp_path)))
    registry_file._PRIVATE_SNAPSHOT = None

    registry_file.install_models()

    assert set(CATALOG_BY_ID) == {MODEL_A, MODEL_B}
    assert tier_fallback.effective_tier_default() == MODEL_A
    rosters = tier_fallback.effective_tier_fallback()
    assert rosters["free"] == (MODEL_B,)
    assert rosters["plus"] == (MODEL_B, MODEL_A)
    assert registry_file.private_registry_state() == {
        "enabled": True, "ok": True, "models": 2, "reason": None}
    converted = registry_file.read_registry()
    assert [row["id"] for row in converted["models"]] == [MODEL_A, MODEL_B]
    assert converted["providers"]["example-provider"]["credential_binding_name"] == (
        "PADIEM_B14_CREDENTIAL_99")


@pytest.mark.parametrize("case,expected", [
    ("missing", "registry_file_missing"),
    ("version", "registry_version_unsupported"),
    ("evidence", "registry_model_install_fields"),
])
def test_switch_on_with_an_unusable_document_fails_closed(
        restore, tmp_path, monkeypatch, case, expected):
    if case == "missing":
        path = tmp_path / "absent.json"
    else:
        document = _document()
        if case == "version":
            document["version"] = "padiem.models.private.v2"
        else:
            document["models"][0].pop("input_price_usd_per_1m")
        path = _private(tmp_path, document)
    monkeypatch.setenv(SWITCH, str(path))
    registry_file._PRIVATE_SNAPSHOT = None

    registry_file.install_models()

    assert CATALOG_BY_ID == {}
    assert tier_fallback.effective_tier_default() == ""
    assert tier_fallback.effective_tier_fallback() == {}
    state = registry_file.private_registry_state()
    assert state["enabled"] is True
    assert state["ok"] is False
    assert state["reason"] == expected
    with pytest.raises(registry_file.ModelRegistryError):
        registry_file.read_registry()
