"""#7241: the shared placeholder registry and the switch default.

Two things must stay true while the platform suites move off repository values:
the fixture is a valid private-v1 document that carries placeholders only, and
the switch default never overrides a document the process (or an operator)
already chose.

#7241 3단계: the repository document is now a placeholder too, so the switch
default is *no longer inert*: it points an unconfigured process at the fixture
so `read_registry()` keeps working in tests. The placeholder spelling lives in
the *shipped* document, not in this file, so the placeholder prefix is read back
from it (and from the fixture, which uses the same shape).
"""
from __future__ import annotations

import json
from pathlib import Path

import _registry_switch_default as switch_default
import _registry_values as registry_values
from app.pilot import model_registry_file
from padiem_control_plane import models_registry

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "models_private_fixture.json"
SHIPPED = Path(model_registry_file.__file__).with_name("b14_models.json")


def _placeholder_prefix() -> str:
    """The placeholder family the fixture and the shipped document share.

    Derived: the one Provider id the shipped placeholder document declares,
    truncated at its last ``-`` so numbered placeholder Providers
    (``<prefix>-01``) match the same family.
    """
    shipped = json.loads(SHIPPED.read_text(encoding="utf-8"))
    assert shipped["providers"], "the shipped document must keep one placeholder Provider"
    provider_id = next(iter(shipped["providers"]))
    return provider_id.rsplit("-", 1)[0] + "-"


def test_fixture_is_a_valid_private_registry_document():
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    registry = models_registry.validate_document(document)
    assert document["version"] == models_registry.FORMAT_VERSION
    assert registry.models
    assert set(models_registry.REQUIRED_TIER_NAMES) <= set(registry.tiers)


def test_fixture_carries_placeholders_only():
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    prefix = _placeholder_prefix()
    for provider_id in document["providers"]:
        assert provider_id.startswith(prefix)
    for row in document["models"]:
        assert row["id"].startswith(prefix)
        assert row["provider_id"] in document["providers"]


def test_switch_default_never_overrides_a_chosen_document(monkeypatch):
    # A process (or operator) that already named a document always wins: the
    # default helper must answer without touching the environment.
    chosen = str(Path("chosen-by-the-process.json"))
    monkeypatch.setenv(switch_default._SWITCH_ENVS[0], chosen)
    assert switch_default.ensure_default_registry_switch() is None
    import os

    assert os.environ[switch_default._SWITCH_ENVS[0]] == chosen


def test_placeholder_detection_matches_the_document_the_process_reads(monkeypatch):
    # The process reads a document; detection must answer whether that document
    # is byte-identical to the fixture (either answer is possible here).
    assert isinstance(registry_values.placeholder_registry_active(), bool)
    # Hermetic: compare bytes against the fixture without touching the process
    # switch (a world-readable document would only be refused by the loader).
    monkeypatch.setattr(registry_values, "_switch_path", lambda: FIXTURE)
    assert registry_values.placeholder_registry_active() is True
