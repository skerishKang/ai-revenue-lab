"""Closed PC delegation settings shared by storage, transport and execution.

These rules narrow when an already-authorized file action needs a question.
They cannot grant device access, bypass user-intent evidence, or authorize SEND.
"""
from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any


PC_DELEGATION_ACTIONS = frozenset({"write", "move", "delete"})
_RULE_KEYS = {"id", "device_id", "folder", "actions", "mode", "enabled"}


def normalize_pc_delegation_path(value: Any) -> str:
    """Normalize path spelling without resolving, widening or guessing a root."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("PC delegation folder is required")
    path = value.strip().replace("\\", "/")
    if any(ord(char) < 32 or ord(char) == 127 for char in path) or any(char in path for char in '*?"<>|'):
        raise ValueError("PC delegation folder is invalid")
    prefix = ""
    if re.match(r"^[A-Za-z]:", path):
        if len(path) > 2 and path[2] != "/":
            raise ValueError("Drive-relative delegation folders are ambiguous")
        prefix, path = path[0].upper() + ":/", path[2:].lstrip("/")
    elif path.startswith("//"):
        prefix, path = "//", path[2:]
    elif path.startswith("/"):
        prefix, path = "/", path[1:]
    if ":" in path:
        raise ValueError("PC delegation folder is invalid")
    parts = [part for part in path.split("/") if part not in {"", "."}]
    if ".." in parts:
        raise ValueError("PC delegation folder cannot traverse parents")
    if prefix == "//" and len(parts) < 2:
        raise ValueError("A network delegation folder needs a server and share")
    # Windows aliases with trailing spaces/dots would make lexical boundaries
    # disagree with the filesystem; ask for their unambiguous spelling instead.
    if any(part != part.rstrip(" .") for part in parts):
        raise ValueError("PC delegation folder spelling is ambiguous")
    return prefix + "/".join(parts) if prefix or parts else "."


def _identifier(value: Any) -> str:
    if not isinstance(value, str) or not value or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("PC delegation identity is invalid")
    return value


def parse_pc_delegation(value: Any) -> dict[str, Any] | None:
    """Validate a snapshot; ``available`` is reserved for the server loader.

    A missing snapshot or a real empty configuration retains the existing
    behavior. A failed store read is explicitly ``available=False`` and must
    never be converted into an empty/default configuration by a caller.
    """
    if value is None:
        return None
    if (not isinstance(value, Mapping) or not {"version", "rules"} <= set(value)
            or set(value) - {"version", "rules", "available"}
            or type(value["version"]) is not int or value["version"] != 1
            or not isinstance(value["rules"], (list, tuple))):
        raise ValueError("PC delegation snapshot is invalid")
    result: dict[str, Any] = {"version": 1, "rules": []}
    if "available" in value:
        if type(value["available"]) is not bool:
            raise ValueError("PC delegation availability is invalid")
        result["available"] = value["available"]
    seen = set()
    for rule in value["rules"]:
        if not isinstance(rule, Mapping) or set(rule) != _RULE_KEYS:
            raise ValueError("PC delegation rule is invalid")
        identifier = _identifier(rule["id"])
        if identifier in seen:
            raise ValueError("PC delegation rule identifiers must be unique")
        seen.add(identifier)
        actions = rule["actions"]
        if (not isinstance(actions, (list, tuple)) or not actions
                or any(not isinstance(action, str) or action not in PC_DELEGATION_ACTIONS for action in actions)
                or len(set(actions)) != len(actions)):
            raise ValueError("Only PC file actions can be delegated")
        if not isinstance(rule["mode"], str) or rule["mode"] not in {"allow", "ask"} or type(rule["enabled"]) is not bool:
            raise ValueError("PC delegation rule mode is invalid")
        result["rules"].append({
            "id": identifier, "device_id": _identifier(rule["device_id"]),
            "folder": normalize_pc_delegation_path(rule["folder"]),
            "actions": list(actions), "mode": rule["mode"], "enabled": rule["enabled"],
        })
    return result
