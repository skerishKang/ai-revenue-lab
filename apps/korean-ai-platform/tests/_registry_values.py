"""#7241 helpers: expected registry values for the platform suites.

Every value a suite asserts comes from the *effective* registry — the shipped
document today, the private registry once this host is switched — so no
provider, host, model or credential value is written in a test file. Owner
decision pins (a specific provider's host, a specific binding slot, a fixed
roster) only make sense on a host that reads the owner's document; they are
skipped while the placeholder fixture is the authority.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "models_private_fixture.json"


def _switch_path() -> Path | None:
    raw = (os.environ.get("PADIEM_MODELS_REGISTRY_OVERRIDE", "").strip()
           or os.environ.get("PADIEM_MODELS_REGISTRY", "").strip())
    return Path(raw).expanduser() if raw else None


def placeholder_registry_active() -> bool:
    """Whether this process runs against the placeholder fixture document."""
    path = _switch_path()
    if path is None or not FIXTURE_PATH.is_file():
        return False
    try:
        return path.read_bytes() == FIXTURE_PATH.read_bytes()
    except OSError:
        return False


requires_owner_document = pytest.mark.skipif(
    placeholder_registry_active(),
    reason="owner decision pin: only a host reading the owner's registry document",
)


def registry() -> dict:
    """The effective registry document (shipped or private)."""
    from app.pilot.model_registry_file import read_registry

    return read_registry()


def model_rows() -> list[dict]:
    return list(registry()["models"])


def model_ids() -> set[str]:
    return {row["id"] for row in model_rows()}


def provider_of(model_id: str) -> str:
    return model_id.split("/", 1)[0]


def group_ids(group: str) -> list[str]:
    return list(registry()["groups"].get(group, []))


def provider_row(provider_id: str) -> dict:
    return registry()["providers"][provider_id]


def a_provider_id() -> str:
    return next(iter(registry()["providers"]))


def a_model_id() -> str:
    return model_rows()[0]["id"]
