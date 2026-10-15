"""Actual installed Connector -> existing Agent source selection regression.

Runs a fresh Python interpreter for each isolated, synthetic Agent. This
catches cases where the developer checkout masks a broken Windows shortcut.
No external network, registry, DPAPI mutation or real secret is used.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

from claw_connect.resident_path import write_resident_config

CONNECTOR_SRC = Path(__file__).resolve().parents[1]
_AGENT_FILES = (
    "kagent/__init__.py",
    "kagent/local_agent_resident_process.py",
    "kagent/local_agent_secure_transport.py",
    "kagent/local_agent_pairing.py",
    "kagent/local_agent_broker_production_entry.py",
)

_RUN = """
import os
from pathlib import Path
from claw_connect.operator_wss_enrollment import _admit_existing_agent_package
state = Path(os.environ['PIN_STATE'])
if os.environ.get('PIN_PRELOAD_FOREIGN') == '1':
    # Already-loaded code must not be shadowed by the installer pin.
    import kagent
try:
    _admit_existing_agent_package(state_dir=state)
except Exception as exc:
    print('DENIED ' + type(exc).__name__ + ' ' + str(exc))
else:
    import kagent
    expected = (Path(os.environ['PIN_SOURCE']) / 'kagent').resolve()
    actual = Path(kagent.__file__).parent.resolve()
    print('PINNED_AGENT_OK' if actual == expected else 'WRONG_AGENT_IMPORTED')
"""


def _agent(tmp_path: Path, name: str) -> Path:
    root = tmp_path / name
    for item in _AGENT_FILES:
        candidate = root / item
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text("# synthetic Agent package, shape only\n", encoding="utf-8")
    return root


def _probe(
    tmp_path: Path, root: Path, *, conflicting_root: Path | None = None,
    preload_foreign: bool = False,
) -> str:
    state = tmp_path / "installed-padiem-connector"
    write_resident_config(state, str(root))
    env = os.environ.copy()
    for var in ("PADIEM_AGENT_SRC", "CLAW_RESIDENT_SRC"):
        env.pop(var, None)
    # An already installed unrelated kagent may exist in the system
    # interpreter on the developer PC. The success fixture must model the
    # installer-pinned Agent as the first import candidate, not accidentally
    # exercise an ambient installation. The conflicting case still puts a
    # foreign Agent before the pin and must fail closed.
    env["PYTHONPATH"] = os.pathsep.join(
        (str(root), str(CONNECTOR_SRC)) if conflicting_root is None
        else (str(conflicting_root), str(root), str(CONNECTOR_SRC))
    )
    env["PIN_SOURCE"] = str(root)
    env["PIN_STATE"] = str(state)
    if preload_foreign:
        env["PIN_PRELOAD_FOREIGN"] = "1"
    else:
        env.pop("PIN_PRELOAD_FOREIGN", None)
    result = subprocess.run(
        [sys.executable, "-c", _RUN],
        cwd=state, env=env, text=True, capture_output=True, timeout=15,
        check=True,
    )
    return result.stdout.strip()


def test_fresh_installed_interpreter_imports_the_exact_pinned_agent(tmp_path):
    source = _agent(tmp_path, "reviewed-canonical-agent")
    assert _probe(tmp_path, source) == "PINNED_AGENT_OK"


def test_foreign_python_agent_does_not_replace_the_installer_pin(tmp_path):
    source = _agent(tmp_path, "reviewed-canonical-agent")
    foreign = _agent(tmp_path, "ambient-foreign-agent")
    # Fresh process: the installer-pinned verified path outranks an unrelated
    # package already present in the global Python installation.
    assert _probe(tmp_path, source, conflicting_root=foreign) == "PINNED_AGENT_OK"


def test_preloaded_foreign_agent_remains_fail_closed(tmp_path):
    source = _agent(tmp_path, "reviewed-canonical-agent")
    foreign = _agent(tmp_path, "ambient-foreign-agent")
    # A foreign module already imported in-process cannot be replaced.
    assert _probe(
        tmp_path, source, conflicting_root=foreign, preload_foreign=True,
    ) == "DENIED DeviceSessionRefused canonical_agent_source_unavailable"


def test_corrupt_or_absent_source_never_falls_back_to_any_agent(tmp_path):
    missing = tmp_path / "not-an-agent"
    assert _probe(tmp_path, missing) == (
        "DENIED DeviceSessionRefused canonical_agent_source_unavailable"
    )
