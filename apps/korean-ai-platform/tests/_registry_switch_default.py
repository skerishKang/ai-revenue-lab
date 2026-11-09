"""#7241 test default for the private model registry switch.

B14 serves no catalog of its own: the repository ships a schema-shaped
placeholder (``app/pilot/b14_models.json``) and the deployed document named by
``PADIEM_MODELS_REGISTRY`` is the single authority. A test process therefore has
to name a document before anything imports the app, or the app fails closed with
an empty catalog.

This module points an unconfigured process at a 0600 copy of
``tests/fixtures/models_private_fixture.json`` (the control-plane loader refuses
a world-readable document, and a checked-in file cannot carry the mode). It
fills the switch only when it is unset, so a suite or an operator that sets its
own document always wins; the copy is removed at exit.
"""
from __future__ import annotations

import atexit
import json
import os
import tempfile
from pathlib import Path

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "models_private_fixture.json"
_SWITCH_ENVS = ("PADIEM_MODELS_REGISTRY", "PADIEM_MODELS_REGISTRY_OVERRIDE")


def ensure_default_registry_switch() -> str | None:
    """Point an unconfigured process at the placeholder fixture, once."""
    if any(os.environ.get(name, "").strip() for name in _SWITCH_ENVS):
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
