"""The read-only drive inventory wire shared by the PC agent and Mesh queue.

An inventory is a complete snapshot, not a permission grant. In particular an
empty list means every drive disappeared; an unavailable probe must not report
an empty list. Ownership and receipt time are supplied by the queue, never here.
"""
from __future__ import annotations

import re
from typing import Any

DRIVE_KINDS = frozenset({"fixed", "removable", "network", "cdrom", "ramdisk", "unknown"})
DRIVE_KEYS = frozenset({"path", "name", "kind", "free_bytes", "total_bytes"})


class DriveInventoryError(ValueError):
    """Malformed inventory; messages never contain reported paths or labels."""


def _text(value: Any, *, empty: bool = False) -> str:
    if (not isinstance(value, str) or (not empty and not value)
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)):
        raise DriveInventoryError("invalid drive text")
    return value


def _path(value: Any) -> str:
    value = _text(value).replace("\\", "/")
    if re.fullmatch(r"[A-Za-z]:/?", value):
        return value[0].upper() + ":/"
    # Unix mount points and network share roots are display metadata too.
    # No relative path or traversal is accepted as a drive.
    if not value.startswith("/") or any(part in {".", ".."} for part in value.split("/")):
        raise DriveInventoryError("invalid drive path")
    return value.rstrip("/") or "/"


def _bytes(value: Any) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise DriveInventoryError("invalid drive capacity")
    return value


def validate_drive_inventory(value: Any) -> list[dict[str, Any]]:
    """Validate and return a fresh, stable snapshot suitable for comparison."""
    if not isinstance(value, list):
        raise DriveInventoryError("drive inventory must be a list")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in value:
        if not isinstance(entry, dict) or set(entry) != DRIVE_KEYS:
            raise DriveInventoryError("invalid drive fields")
        path = _path(entry["path"])
        if path in seen:
            raise DriveInventoryError("duplicate drive")
        seen.add(path)
        kind = entry["kind"]
        if not isinstance(kind, str) or kind not in DRIVE_KINDS:
            raise DriveInventoryError("invalid drive kind")
        free, total = _bytes(entry["free_bytes"]), _bytes(entry["total_bytes"])
        if free is not None and total is not None and free > total:
            raise DriveInventoryError("invalid drive capacity")
        result.append({"path": path, "name": _text(entry["name"], empty=True),
                       "kind": kind, "free_bytes": free, "total_bytes": total})
    return sorted(result, key=lambda row: row["path"])


__all__ = ["DRIVE_KINDS", "DriveInventoryError", "validate_drive_inventory"]
