"""Read-only, fail-closed PADIEM Agent source preflight for a PC.

No Agent execution, credential readback, Broker call or device identity write.
An explicit source root must contain the SAME existing canonical modules;
we never substitute a second local AI engine or silently search the PC.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from .resident_path import resident_src_root

_REQUIRED = (
    "kagent/__init__.py",
    "kagent/local_agent_resident_process.py",
    "kagent/local_agent_secure_transport.py",
    "kagent/local_agent_pairing.py",
    "kagent/local_agent_broker_production_entry.py",
)


def _canonical_source(root: str | os.PathLike[str]) -> bool:
    """Check source shape without importing/executing any supplied code."""
    try:
        path = Path(root).expanduser()
        if not path.is_absolute() or not path.is_dir():
            return False
        base = path.resolve(strict=True)
        for relative in _REQUIRED:
            item = base / relative
            if not item.is_file() or not item.resolve(strict=True).is_relative_to(base):
                return False
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def agent_preflight(*, state_dir: str | os.PathLike[str] | None = None) -> dict[str, object]:
    """Return only bounded diagnostic facts; never print source paths or tokens.

    If an explicitly pinned source is corrupt, do NOT silently fall back to an
    unrelated ambient kagent package. An unpinned setup may use the already
    installed canonical interpreter package if it has the reviewed source files.
    """
    method = "unconfigured"
    reason = "agent_source_not_configured"
    ready = False
    try:
        source = resident_src_root(state_dir=state_dir)
    except ValueError as exc:
        source = None
        if str(exc) == "agent_source_config_invalid":
            method = "invalid_configuration"
            reason = "agent_source_config_invalid"
        else:
            method = "conflicting_environment"
            reason = "agent_source_conflict"
    else:
        if source is not None:
            method = "configured"
            ready = _canonical_source(source)
            reason = "ok" if ready else "agent_source_invalid"
        else:
            method = "interpreter"
            try:
                spec = importlib.util.find_spec("kagent")
                if spec is not None and spec.submodule_search_locations:
                    # Python's module search locations point at /src/kagent,
                    # whereas canonical source validation expects /src.
                    ready = any(
                        _canonical_source(Path(package_dir).parent)
                        for package_dir in spec.submodule_search_locations
                    )
            except (ImportError, ValueError, OSError, AttributeError):
                ready = False
            reason = "ok" if ready else "agent_source_not_configured"
    return {
        "product": "PADIEM Agent",
        "agent_ready": ready,
        "agent_status": reason,
        "source_kind": method,
        "production_gateway_enabled": False,
        "agent_started": False,
        "device_enrollment_changed": False,
    }
