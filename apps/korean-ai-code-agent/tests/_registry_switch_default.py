"""Shared test-time default for the mandatory model registry switch (#6828 3단계).

The repository ships no model or provider value, so a test process that never
sets ``PADIEM_MODELS_REGISTRY`` would fail closed everywhere. Unless a test
( or the operator) already chose a registry, every suite runs as a switched
host against the placeholder fixture: a private-v1 document with
``example-provider`` rows only. Tests that exercise the switch itself delete
or override the variable with monkeypatch, which wins over this default.
"""
from __future__ import annotations

import atexit
import json
import os
import tempfile
from pathlib import Path

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "models_private_fixture.json"


def ensure_default_registry_switch() -> str | None:
    """Point an unconfigured process at the placeholder fixture, once."""
    if (os.environ.get("PADIEM_MODELS_REGISTRY", "").strip()
            or os.environ.get("PADIEM_MODELS_REGISTRY_OVERRIDE", "").strip()):
        return None
    if not FIXTURE_PATH.is_file():
        return None
    document = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    handle = tempfile.NamedTemporaryFile(
        prefix="padiem-models-fixture-", suffix=".json", delete=False)
    handle.write(json.dumps(document).encode("utf-8"))
    handle.close()
    os.chmod(handle.name, 0o600)
    os.environ["PADIEM_MODELS_REGISTRY"] = handle.name
    atexit.register(os.unlink, handle.name)
    return handle.name
