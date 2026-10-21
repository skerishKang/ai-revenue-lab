"""#5023 — the Calendar timezone contract must work in the deployed runtime.

The Calendar routes validate the explicit timezone against the real IANA
database. The Worker runtime ships no system tz database (Pyodide has no
`/usr/share/zoneinfo`), so `zoneinfo` raises `ZoneInfoNotFoundError` for every
real zone there — and every Calendar read then answers HTTP 400
`invalid_timezone`.

The database therefore has to be part of the Worker's **vendored dependency
set** (`pylock.toml`), not only the dev/test one. This file pins that, and
pins the real-runtime probe that would have caught the gap before a release.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from app.calendar_contracts import CalendarContractError, validate_timezone

APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_ROOT.parents[1]

#: The package that ships the IANA database to a runtime without a system one.
TIMEZONE_DATABASE_PACKAGE = "tzdata"


def _worker_lock() -> dict:
    return tomllib.loads((APP_ROOT / "pylock.toml").read_text(encoding="utf-8"))


def _project_metadata() -> dict:
    return tomllib.loads((APP_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_the_worker_lock_ships_the_iana_timezone_database():
    """The Worker's vendored set must carry the database, with a pinned wheel."""
    packages = {
        package.get("name"): package
        for package in _worker_lock().get("packages", [])
        if isinstance(package, dict)
    }
    entry = packages.get(TIMEZONE_DATABASE_PACKAGE)
    assert entry is not None, (
        "the Worker dependency lock must ship the IANA timezone database; "
        "without it every Calendar read answers HTTP 400 invalid_timezone"
    )
    assert isinstance(entry.get("version"), str) and entry["version"]
    wheels = entry.get("wheels") or []
    assert wheels, "the timezone database needs a pinned wheel"
    for wheel in wheels:
        assert isinstance(wheel.get("url"), str) and wheel["url"].startswith("https://")
        hashes = wheel.get("hashes") or {}
        assert isinstance(hashes.get("sha256"), str) and len(hashes["sha256"]) == 64


def test_the_timezone_database_is_a_runtime_dependency():
    """A dev-only declaration would leave the deployed Worker without it."""
    metadata = _project_metadata()
    runtime = metadata["project"]["dependencies"]
    dev = metadata["project"].get("optional-dependencies", {}).get("dev", [])
    assert any(
        requirement.startswith(TIMEZONE_DATABASE_PACKAGE) for requirement in runtime
    ), "the IANA timezone database must be a runtime dependency of the Worker"
    assert not any(
        requirement.startswith(TIMEZONE_DATABASE_PACKAGE) for requirement in dev
    ), "the timezone database must not be declared for the dev environment only"


def test_the_calendar_contract_accepts_a_real_zone_and_refuses_a_fake_one():
    """The contract itself stays strict: a real zone works, a fake one is refused."""
    assert validate_timezone("Asia/Seoul") is not None
    with pytest.raises(CalendarContractError) as exc:
        validate_timezone("Mars/Olympus")
    assert exc.value.code == "invalid_timezone"


def test_the_real_runtime_probe_asserts_the_timezone_database():
    """The real Workerd/Pyodide lane must fail when the database is missing."""
    probe = (APP_ROOT / "worker_runtime_combined_probe.py").read_text(encoding="utf-8")
    assert "_timezone_database_state" in probe
    assert "tz=" in probe
    assert "validate_timezone" in probe
    script = (REPO_ROOT / ".github/scripts/b62_worker_probe_shared_runtime.sh").read_text(
        encoding="utf-8"
    )
    assert "B62_WORKER_TIMEZONE_DATABASE" in script
    assert "tz=ok" in script
