"""#7241: the shared placeholder registry and the switch default.

Two things must stay true while the platform suites move off repository values:
the fixture is a valid private-v1 document that carries placeholders only, and
the conftest switch default never turns on while the shipped document is still
the one the app reads (that would answer rows nobody approved).
"""
from __future__ import annotations

import json
from pathlib import Path

import _registry_switch_default as switch_default
import _registry_values as registry_values
from padiem_control_plane import models_registry

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "models_private_fixture.json"


def test_fixture_is_a_valid_private_registry_document():
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    registry = models_registry.validate_document(document)
    assert document["version"] == models_registry.FORMAT_VERSION
    assert registry.models
    assert set(models_registry.REQUIRED_TIER_NAMES) <= set(registry.tiers)


def test_fixture_carries_placeholders_only():
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for provider_id in document["providers"]:
        assert provider_id.startswith(switch_default.PLACEHOLDER_PROVIDER_PREFIX)
    for row in document["models"]:
        assert row["id"].startswith(switch_default.PLACEHOLDER_PROVIDER_PREFIX)
        assert row["provider_id"] in document["providers"]


def test_switch_default_is_inert_while_the_shipped_document_holds_values():
    # The platform app still reads its shipped catalog in this stage, so the
    # switch must stay unset unless a process/operator already chose one.
    if switch_default.repository_document_holds_placeholder_values():
        return
    assert switch_default.ensure_default_registry_switch() is None


def test_placeholder_detection_matches_the_document_the_process_reads(monkeypatch):
    assert registry_values.placeholder_registry_active() is False or (
        switch_default.repository_document_holds_placeholder_values()
    )
    # Hermetic: compare bytes against the fixture without touching the process
    # switch (a world-readable document would only be refused by the loader).
    monkeypatch.setattr(registry_values, "_switch_path", lambda: FIXTURE)
    assert registry_values.placeholder_registry_active() is True
