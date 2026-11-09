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


def a_dispatchable_row(*, provider_ids: frozenset[str] | None = None) -> dict | None:
    """A registered row the platform adapter would actually dispatch, if any.

    "Dispatchable" is the app's own answer: the identity is a live catalog row
    and neither owner-exclusion applies. The row is read from the effective
    document, so a suite that needs a subject model never writes one (#7241).
    ``provider_ids`` optionally restricts the search to given Provider rows.

    Answers ``None`` when the effective document installs no such row — the
    placeholder fixture does, which is exactly when an owner pin does not hold.
    """
    from app.pilot.catalog import get_catalog_by_id
    from app.pilot.owner_model_exclusions import (
        excluded_from_owner_customer_selection, free_candidate_excluded_from_execution,
    )

    for row in model_rows():
        model_id = row["id"]
        provider = provider_of(model_id)
        if provider_ids is not None and provider not in provider_ids:
            continue
        if not row.get("enabled", True) or get_catalog_by_id(model_id) is None:
            continue
        if excluded_from_owner_customer_selection(model_id):
            continue
        if free_candidate_excluded_from_execution(
            model_id, upstream_model=row["upstream_model"],
            platform_provider_id=provider,
        ):
            continue
        return row
    return None


def model_ids() -> set[str]:
    return {row["id"] for row in model_rows()}


def provider_of(model_id: str) -> str:
    return model_id.split("/", 1)[0]


def model_row(model_id: str) -> dict | None:
    """The effective registry row for this identity, or ``None``."""
    for row in model_rows():
        if row["id"] == model_id:
            return row
    return None


def row_model_snapshot(model_id: str):
    """The catalog entry an effective registry row installs, without a name.

    Its capabilitY set, price fields and provider names are the row's own
    columns, so a caller can compare a live catalog entry against the row it
    was built from instead of restating the deployment values (#7241 3a).
    """
    from dataclasses import replace

    from app.pilot.catalog import CATALOG_BY_ID

    row = model_row(model_id)
    if row is None or model_id not in CATALOG_BY_ID:
        return None
    return replace(
        CATALOG_BY_ID[model_id],
        capabilities=frozenset(row["capabilities"]),
        input_price_usd_per_1m=row["input_price_usd_per_1m"],
        output_price_usd_per_1m=row["output_price_usd_per_1m"],
        provider=row["provider_name"],
        provider_type=row.get("provider_type", CATALOG_BY_ID[model_id].provider_type),
        enabled=row["enabled"],
    )


def group_ids(group: str) -> list[str]:
    return list(registry()["groups"].get(group, []))


def provider_row(provider_id: str) -> dict:
    return registry()["providers"][provider_id]


def a_provider_id() -> str:
    return next(iter(registry()["providers"]))


def credential_binding_of(provider_id: str) -> str:
    """The credential binding NAME one Provider row declares (never a value).

    The name lives in the registry document, so a suite that has to seed a
    synthetic value for a binding reads the name from the row instead of
    writing it (#7241).
    """
    return provider_row(provider_id)["credential_binding_name"]


def credential_binding_slot(index: int) -> str:
    """The deployment's stable slot NAME at this 1-based position.

    Slot names are deployment values too; the admin surface publishes the
    stable list, so a suite that needs one asks the app rather than spelling
    the literal (#7241).
    """
    from app.pilot.credential_slots_admin import SLOT_BINDINGS

    return SLOT_BINDINGS[index - 1]


def adapter_credential_binding(provider_id: str) -> str:
    """The credential binding NAME a Provider's own adapter constant declares."""
    module = adapter_for(provider_id)
    for name, value in vars(module).items():
        if name.endswith("CREDENTIAL_BINDING") and isinstance(value, str) and value:
            return value
    raise AssertionError("the selected adapter declares no credential binding")


def a_model_id() -> str:
    return model_rows()[0]["id"]


def registered_model_id_within(provider_id: str) -> str:
    """An identity the effective document registers under this Provider.

    A suite that has to prove one Provider is still servable needs an
    identity, and an identity is a deployment value. The document already
    names the ones it installs, so the suite asks for one instead of writing
    it (#7241 3a).
    """
    ids = sorted(row["id"] for row in model_rows() if row["provider_id"] == provider_id)
    assert ids, "the effective document registers no identity for this Provider"
    return ids[0]


def chat_wire_tail() -> tuple[str, ...]:
    """The wire segments the platform adapter's own request URL ends with.

    ``platform.py`` builds the upstream chat URL from the Provider's origin
    plus a fixed tail, so the tail is composed by the adapter and cannot be
    written in a test. The table is read from the adapter source
    (the origin plus the adapter's own completion tail) rather than restated
    here (#7241 3a).
    """
    import inspect
    import re

    from app.pilot import platform as platform_module

    for name, function in vars(platform_module).items():
        if not inspect.isfunction(function):
            continue
        try:
            body = inspect.getsource(function)
        except (OSError, TypeError):
            continue
        match = re.search(r"chat_url\s*=\s*f\"[^\"]*\}" + r"(/[^\"]+)\"", body)
        if match:
            return tuple(segment for segment in match.group(1).split("/") if segment)
    raise AssertionError("the platform adapter composes no chat URL tail")


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


def timeout_log_allowlist() -> frozenset[str]:
    """The Provider ids the phase-log surface accepts, read from the module.

    The allow-list is the app's own constant, so a suite parametrising over the
    accepted providers does not restate deployment identities (#7241).
    """
    from app.pilot.provider_timeout_diagnostics import _ALLOWED

    return frozenset(_ALLOWED)


def specialized_timeout_log_provider() -> str:
    """The allow-listed Provider the module routes to its own log contract.

    The module compares the incoming id to that Provider on the specialized
    branch; the comparison constant is read back from the same dispatch
    structure, so no Provider identity is written in a test file (#7241).
    """
    import inspect

    from app.pilot import provider_timeout_diagnostics as diagnostics

    source = inspect.getsource(diagnostics.log_provider_timeout)
    special = [
        pid for pid in sorted(timeout_log_allowlist())
        if f'"{pid}"' in source or f"'{pid}'" in source
    ]
    assert len(special) == 1, (
        "expected exactly one Provider to take the specialized log branch"
    )
    return special[0]


def timeout_log_allowlist_excluding() -> list[str]:
    """Allow-listed Provider ids whose logging path is the generic one."""
    special = specialized_timeout_log_provider()
    keep = [pid for pid in sorted(timeout_log_allowlist()) if pid != special]
    assert keep, "no generic provider remains on the phase-log allow-list"
    return keep


def provider_ids_excluding(markers: tuple[str, ...]) -> list[str]:
    """Registry Provider ids that carry none of ``markers`` in their identity."""
    out = [
        pid for pid in sorted(registry()["providers"])
        if not any(marker in pid.casefold() for marker in markers)
    ]
    assert out, "no Provider row survives the marker filter"
    return out


def provider_rows() -> list[dict]:
    """Every Provider row of the effective document."""
    return list(registry()["providers"].values())
