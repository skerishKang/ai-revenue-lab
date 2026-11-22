"""#8060 61차: the b14 models registry read for connector tool-turn tests.

The registry path honours the same environment overrides the product reads
(`PADIEM_MODELS_REGISTRY_OVERRIDE` / `PADIEM_MODELS_REGISTRY`), falling back to
the korean-ai-platform pilot registry. The read lives here so the contract
tests receive parsed rows without opening the file themselves.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def registry_rows() -> list[dict]:
    """The registry's model rows (a bare list or a ``models`` mapping)."""
    raw = (os.environ.get("PADIEM_MODELS_REGISTRY_OVERRIDE", "").strip()
           or os.environ.get("PADIEM_MODELS_REGISTRY", "").strip())
    path = (Path(raw).expanduser() if raw else
            (Path(__file__).resolve().parents[4] / "apps" / "korean-ai-platform"
             / "app" / "pilot" / "b14_models.json"))
    registry = json.loads(path.read_text(encoding="utf-8"))
    return registry if isinstance(registry, list) else registry.get("models", [])
