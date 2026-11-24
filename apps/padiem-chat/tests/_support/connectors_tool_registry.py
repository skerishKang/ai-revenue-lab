"""Parsed view of the B14 model registry for connector-tool contracts.

Raw ``read_text`` stays here; the contract test asserts on parsed model rows.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_REGISTRY = (Path(__file__).resolve().parents[4]
                    / "apps/korean-ai-platform/app/pilot/b14_models.json")


def registry_path() -> Path:
    raw = (os.environ.get("PADIEM_MODELS_REGISTRY_OVERRIDE", "").strip()
           or os.environ.get("PADIEM_MODELS_REGISTRY", "").strip())
    return Path(raw).expanduser() if raw else DEFAULT_REGISTRY


def registry_rows() -> list[dict]:
    data = json.loads(registry_path().read_text(encoding="utf-8"))
    return data if isinstance(data, list) else data.get("models", [])