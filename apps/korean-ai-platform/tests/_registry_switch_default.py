"""#7241 shared test default for the private model registry switch.

The repository must not ship model, provider, host or credential values, so a
test process has to run against the placeholder fixture instead of the shipped
document. This module points ``PADIEM_MODELS_REGISTRY`` at a 0600 copy of
``tests/fixtures/models_private_fixture.json`` (the control-plane loader
refuses a world-readable document, and the checked-in file cannot carry the
mode).

Sequencing (#7241 1단계): the platform app still reads its shipped document
while the repository carries values — switching a test process now would make
the app answer placeholder rows that the not-yet-converted suites pin as
owner decisions. The switch therefore engages as soon as the shipped document
is itself a placeholder (the app then has to read the private registry, 3단계).
Until then the fixture is inert for this app, while the shared helpers and the
converted suites below already derive every expected value from the effective
registry, so they read the same source in both modes.

A test's own ``monkeypatch.setenv``/``setenv`` always wins: this only fills an
unset switch, exactly once per process.
"""
from __future__ import annotations

import atexit
import json
import os
import tempfile
from pathlib import Path

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "models_private_fixture.json"
SHIPPED_DOCUMENT = Path(__file__).resolve().parents[1] / "app" / "pilot" / "b14_models.json"
PLACEHOLDER_PROVIDER_PREFIX = "example-provider"


def repository_document_holds_placeholder_values() -> bool:
    """Whether the shipped catalog is already value-free (3단계 done)."""
    try:
        document = json.loads(SHIPPED_DOCUMENT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    providers = document.get("providers")
    if not isinstance(providers, dict) or not providers:
        return False
    return all(str(name).startswith(PLACEHOLDER_PROVIDER_PREFIX) for name in providers)


def ensure_default_registry_switch() -> str | None:
    """Point an unconfigured process at the placeholder fixture, once."""
    if (os.environ.get("PADIEM_MODELS_REGISTRY", "").strip()
            or os.environ.get("PADIEM_MODELS_REGISTRY_OVERRIDE", "").strip()):
        return None
    if not repository_document_holds_placeholder_values():
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
