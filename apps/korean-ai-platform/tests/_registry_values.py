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


def adapter_modules() -> dict[str, object]:
    """Every pilot adapter module, keyed by the Provider id it declares.

    A suite that drives one provider's own wire needs that adapter, but naming
    the module would restate a deployment identity, so the module is selected
    from the package by the constant it declares (#7241).
    """
    import importlib
    import pkgutil

    import app.pilot as pilot_package

    found: dict[str, object] = {}
    for info in pkgutil.iter_modules(pilot_package.__path__):
        module = importlib.import_module(f"{pilot_package.__name__}.{info.name}")
        for name, value in vars(module).items():
            if name.endswith("PROVIDER_ID") and isinstance(value, str) and value:
                found.setdefault(value, module)
                break
    return found


def adapter_for(provider_id: str):
    """The adapter module that declares this Provider id."""
    module = adapter_modules().get(provider_id)
    assert module is not None, "no pilot adapter declares the selected Provider"
    return module


def adapter_declaring_retired(marker: str = "RETIRED"):
    """The adapter that owns retirement metadata for identities it no longer serves.

    Returns ``(provider_id, module, retired_ids)``: the ids the adapter marks as
    retired plus every identity its own constants retain for that roster. The
    adapter is selected by that metadata rather than by name (#7241).
    """
    matches = []
    for provider_id, module in adapter_modules().items():
        declared: set[str] = set()
        retained: set[str] = set()
        has_marker = False
        for name, value in vars(module).items():
            if isinstance(value, frozenset) and marker in name:
                has_marker = True
                declared |= {item for item in value if isinstance(item, str)}
            if name.endswith("_MODEL_ID") and isinstance(value, str):
                retained.add(value)
        if has_marker and declared:
            matches.append((provider_id, module, frozenset(declared | retained)))
    assert len(matches) == 1, "expected exactly one adapter to own a retirement roster"
    return matches[0]
