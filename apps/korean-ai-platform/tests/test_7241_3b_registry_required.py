"""#7241 3단계: B14 has no catalog in the repository, and the switch is required.

Two properties are pinned here, both without a single deployment value:

``test_resolution_table_*``
    Under the conditions this deployment runs in — switch on, a private document
    of the production shape (28 models, five graded tiers) — the per-grade
    primary, ordered fallback and admin resolution are answered *by that
    document* and by nothing else. The expected row of every case is computed
    from the document itself, so the table proves the resolution is a function of
    the owner document: identical for the same document, on either side of the
    3단계 change, and empty for a document that cannot be read.

``test_fail_closed_*``
    Switch absent, document absent, document unreadable: an empty catalog and a
    reason code. Never the repository values, and never an exception escaping
    into a dispatch path.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.pilot import model_registry_file
from app.pilot.catalog import CATALOG_BY_ID, CATALOG_MODELS
from app.pilot.tier_fallback import effective_tier_default, effective_tier_fallback

from _registry_values import registry

SWITCH_ENVS = ("PADIEM_MODELS_REGISTRY", "PADIEM_MODELS_REGISTRY_OVERRIDE")
GRADES = ("free", "plus", "pro", "max")
#: Grades the resolution table reports, admin included: its route is declared
#: per document and may be absent (item 2).
TABLE_GRADES = (*GRADES, "admin")
#: The production document's shape: the row count a populated deployment reads.
PRODUCTION_MODEL_COUNT = 28
#: The reason code every fail-closed path logs and reports (no value logged).
SWITCH_MISSING = "registry_switch_missing"


@pytest.fixture()
def clear_switch(monkeypatch):
    for name in SWITCH_ENVS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def _reset_snapshot():
    """Drop the cached snapshot so the next read sees the current environment."""
    model_registry_file._PRIVATE_SNAPSHOT = None


@pytest.fixture(autouse=True)
def restore_installed_catalog():
    """Reinstall the process catalog after a case that had to empty it."""
    yield
    _reset_snapshot()
    model_registry_file.install_models()


def _private_document() -> dict:
    """The document this process reads, or skip when it is not a private one."""
    path = (os.environ.get(SWITCH_ENVS[0], "").strip()
            or os.environ.get(SWITCH_ENVS[1], "").strip())
    if not path:
        pytest.skip("no registry switch in this process")
    registry_document = registry()
    if not registry_document.get("models"):
        pytest.skip("the effective document registers no model")
    return registry_document


# ---------------------------------------------------------------------------
# Item 3a: the resolution table, under production conditions.
# ---------------------------------------------------------------------------
def _expected_rows(document: dict) -> list[tuple[str, str, tuple[str, ...]]]:
    """(grade, primary, ordered fallback) exactly as the document declares them."""
    tiers = getattr(document, "tiers", None)
    rows = []
    if tiers is not None:
        for grade in TABLE_GRADES:
            tier = tiers.get(grade)
            if tier is None:
                continue
            rows.append((grade, tier["primary"], tuple(tier["fallback"])))
        return rows
    # The install document keeps no grade block: the tier authority answers.
    from padiem_control_plane import models_registry

    private = models_registry.load_snapshot()
    assert private.ready, private.code
    for grade in TABLE_GRADES:
        tier = private.registry.tiers.get(grade)
        if tier is None:
            continue
        rows.append((grade, tier["primary"], tuple(tier["fallback"])))
    return rows


def test_resolution_table_matches_the_document():
    """Per-grade resolution is the document's answer, row by row."""
    document = _private_document()
    rows = _expected_rows(document)
    assert rows, "the document declares no graded tier"

    rosters = effective_tier_fallback()
    for grade, primary, fallback in rows:
        roster = rosters.get(grade)
        assert roster is not None, grade
        if grade == "free":
            # Free's roster is compared to its default first, so it lists the
            # recovery models without repeating the primary.
            assert effective_tier_default() == primary
            assert tuple(roster) == fallback
            continue
        assert tuple(roster) == (primary, *fallback)


def test_resolution_table_admin_prefers_declared_route_then_paid_primary():
    """Admin resolves to its own grade, or to the paid primary when absent."""
    from padiem_control_plane.product_tier_routes import ProductTierLabel
    from padiem_control_plane.product_tier_routes_private import (
        effective_active_route_for,
        paid_primary_model_id,
    )

    document = _private_document()
    rows = {grade: (primary, fallback) for grade, primary, fallback in _expected_rows(document)}
    route = effective_active_route_for(ProductTierLabel.ADMIN)
    resolved = route.model_id if route is not None and route.model_id else ""
    if "admin" in rows:
        assert resolved == rows["admin"][0]
        assert effective_tier_fallback().get("admin") == (rows["admin"][0], *rows["admin"][1])
        return
    # No admin grade in this document: the paid primary is the fallback that
    # keeps the lane provisioned (#7238 residual risk).
    assert resolved == ""
    assert paid_primary_model_id() == rows["plus"][0]


def test_admin_fallback_source_without_an_admin_grade(clear_switch, tmp_path):
    """A document with no admin grade still names a provisioned fallback.

    #7238's residual risk: the admin lane must not stay on an unresolvable
    marker. With no admin grade the shared paid primary is the fallback the
    chat policy passes for that lane.
    """
    from padiem_control_plane.product_tier_routes import ProductTierLabel
    from padiem_control_plane.product_tier_routes_private import (
        effective_active_route_for,
        paid_primary_model_id,
    )

    fixture = json.loads(
        (Path(__file__).resolve().parent / "fixtures" / "models_private_fixture.json")
        .read_text(encoding="utf-8")
    )
    tiers = dict(fixture["tiers"])
    assert "admin" in tiers, "the fixture declares an admin grade"
    plus_tier = tiers.pop("admin")
    del plus_tier
    fixture["tiers"] = tiers
    document = tmp_path / "no-admin.json"
    document.write_text(json.dumps(fixture), encoding="utf-8")
    document.chmod(0o600)

    previous = {name: os.environ.get(name) for name in SWITCH_ENVS}
    for name in SWITCH_ENVS:
        clear_switch.delenv(name, raising=False)
    clear_switch.setenv(SWITCH_ENVS[0], str(document))
    _reset_snapshot()
    try:
        assert effective_active_route_for(ProductTierLabel.ADMIN) is None
        paid = paid_primary_model_id()
        assert paid, "the document still declares the paid grades"
        assert paid == tiers["plus"]["primary"]
    finally:
        for name, value in previous.items():
            if value is None:
                clear_switch.delenv(name, raising=False)
            else:
                clear_switch.setenv(name, value)
        _reset_snapshot()


def test_resolution_table_covers_the_production_shape():
    """The populated deployment shape the table is meant to run on."""
    from padiem_control_plane import models_registry

    private = models_registry.load_snapshot()
    if not private.ready or len(private.registry.models) != PRODUCTION_MODEL_COUNT:
        pytest.skip("this process does not read the populated deployment document")
    grades = {grade for grade, _primary, _fallback in _expected_rows(registry())}
    assert {"free", "plus", "pro", "max"} <= grades


def test_repository_document_carries_no_model_or_provider_identity():
    """The shipped document is a placeholder: schema only, no deployment value."""
    shipped = json.loads(
        (Path(model_registry_file.__file__).with_name("b14_models.json")).read_text(encoding="utf-8")
    )
    assert shipped["models"] == []
    assert shipped["groups"] == {"plus": [], "pro": [], "max": []}
    assert shipped["retired_models"] == []
    assert all(name.startswith("example-provider") for name in shipped["providers"])
    assert all(entry["enabled"] is False for entry in shipped["providers"].values())


# ---------------------------------------------------------------------------
# Item 3b: fail-closed, with a reason code and an empty catalog.
# ---------------------------------------------------------------------------
def test_fail_closed_switch_absent(clear_switch):
    _reset_snapshot()
    try:
        state = model_registry_file.private_registry_state()
        assert state["enabled"] is False
        assert state["ok"] is False
        assert state["models"] == 0
        assert state["reason"] == SWITCH_MISSING
        model_registry_file.install_models()
        assert CATALOG_MODELS == [] and CATALOG_BY_ID == {}
        assert effective_tier_default() == ""
        assert effective_tier_fallback() == {}
        with pytest.raises(model_registry_file.ModelRegistryError) as raised:
            model_registry_file.read_registry()
        assert SWITCH_MISSING in str(raised.value)
    finally:
        clear_switch.undo()
        _reset_snapshot()


def test_fail_closed_document_absent(clear_switch, tmp_path):
    clear_switch.setenv(SWITCH_ENVS[0], str(tmp_path / "absent.json"))
    _reset_snapshot()
    try:
        state = model_registry_file.private_registry_state()
        assert state["ok"] is False and state["models"] == 0
        assert state["reason"] and state["reason"] != SWITCH_MISSING
        model_registry_file.install_models()
        assert CATALOG_MODELS == [] and CATALOG_BY_ID == {}
        assert effective_tier_fallback() == {}
        with pytest.raises(model_registry_file.ModelRegistryError):
            model_registry_file.read_registry()
    finally:
        clear_switch.undo()
        _reset_snapshot()


def test_fail_closed_document_unreadable(clear_switch, tmp_path):
    document = tmp_path / "unreadable.json"
    document.write_text('{"schema_version": 1, "providers": {}, "models": []}', encoding="utf-8")
    document.chmod(0o000)
    clear_switch.setenv(SWITCH_ENVS[0], str(document))
    _reset_snapshot()
    try:
        state = model_registry_file.private_registry_state()
        assert state["ok"] is False and state["models"] == 0
        assert state["reason"]
        model_registry_file.install_models()
        assert CATALOG_MODELS == [] and CATALOG_BY_ID == {}
        with pytest.raises(model_registry_file.ModelRegistryError):
            model_registry_file.read_registry()
    finally:
        document.chmod(0o600)
        clear_switch.undo()
        _reset_snapshot()


def test_fail_closed_document_world_readable(clear_switch, tmp_path):
    """The loader's mode rule is part of the fail-closed contract."""
    source = json.loads(
        (Path(__file__).resolve().parent / "fixtures" / "models_private_fixture.json")
        .read_text(encoding="utf-8")
    )
    document = tmp_path / "world-readable.json"
    document.write_text(json.dumps(source), encoding="utf-8")
    document.chmod(0o644)
    clear_switch.setenv(SWITCH_ENVS[0], str(document))
    _reset_snapshot()
    try:
        state = model_registry_file.private_registry_state()
        if os.name == "nt":
            pytest.skip("POSIX document modes are not enforced on this host")
        assert state["ok"] is False
        assert state["reason"]
        model_registry_file.install_models()
        assert CATALOG_BY_ID == {}
    finally:
        clear_switch.undo()
        _reset_snapshot()
