"""Folder rules narrow confirmation after the PC user-evidence check.

This is not device/tool authorization. SEND and external writes never become
delegated file actions; their existing Core confirmation boundary stays separate.
"""
from __future__ import annotations

from collections.abc import Mapping
import re

from padiem_ai_core.pc_delegation import normalize_pc_delegation_path, parse_pc_delegation


_OPS = {"claw.pc.write_file": "write", "claw.pc.move_file": "move", "claw.pc.delete_file": "delete"}
_PREFIXES = (
    "위임 범위 밖의 작업입니다.",
    "항상 확인하도록 정한 작업입니다.",
    "위임 설정을 확인하지 못했습니다.",
)
_YES = re.compile(r"^\s*(?:네|예|응|그래|맞아|진행해|해줘|확인|yes|ok|okay|go ahead)[.!。]?\s*$", re.I)


def _question(prefix, operation, arguments):
    path = arguments.get("path", "")
    if operation == "move":
        action = f"`{path}` 파일을 `{arguments.get('destination', '')}`로 옮길까요?"
    else:
        verb = "저장할까요" if operation == "write" else "지울까요"
        action = f"`{path}` 파일을 {verb}?"
    return prefix + " " + action


def confirmed_delegation_action(tool_id, arguments, records) -> bool:
    """An owner's next affirmative turn confirms exactly the shown action.

    There is no pause/resume token or browser-supplied approval bit. Callers
    must still run the first-stage evidence check, including current tool data.
    """
    operation = _OPS.get(tool_id)
    if operation is None:
        return False
    last_user = next((i for i in range(len(records) - 1, -1, -1) if records[i].get("role") == "user"), None)
    if last_user is None or not _YES.fullmatch(records[last_user].get("content", "")):
        return False
    before = records[:last_user]
    if not before or before[-1].get("role") != "assistant":
        return False
    shown = before[-1].get("content", "").strip()
    return any(shown == question or shown.startswith(question + "\n\n")
               for prefix in _PREFIXES if (question := _question(prefix, operation, arguments)))


def _absolute(path):
    return path.startswith("/") or bool(re.match(r"^[A-Z]:/", path, re.I))


def _resolve(path, context, *, folder=False):
    """Use the signed server's root labels, never an inferred home directory."""
    path = normalize_pc_delegation_path(path)
    if _absolute(path):
        return path
    roots = context.get("delegation_roots") if isinstance(context, Mapping) else None
    if not isinstance(roots, list) or not roots:
        return path
    if any(not isinstance(root, Mapping) or not isinstance(root.get("label"), str)
           or not isinstance(root.get("path"), str) for root in roots):
        raise ValueError("Invalid verified roots")
    label, separator, remainder = path.partition("/")
    named_folder = [root for root in roots if root["label"] == path]
    if folder and len(named_folder) == 1:
        return normalize_pc_delegation_path(named_folder[0]["path"])
    if len(roots) == 1:
        root = roots[0]
        relative = remainder if separator and label == root["label"] else path
    else:
        named = [root for root in roots if root["label"] == label]
        if not separator or len(named) != 1:
            raise ValueError("A folder label is required")
        root, relative = named[0], remainder
    return normalize_pc_delegation_path(root["path"].rstrip("/") + "/" + relative)


def _within(folder, path):
    # Windows paths are case-insensitive. POSIX/unspecified relative paths keep
    # case so one folder cannot silently stand in for a different one.
    if re.match(r"^[A-Z]:/", folder, re.I) or folder.startswith("//"):
        folder, path = folder.casefold(), path.casefold()
    if folder == ".":
        return not _absolute(path)
    return path == folder or path.startswith(folder.rstrip("/") + "/")


class PcActionDelegation:
    def __init__(self, policy=None):
        self.policy = parse_pc_delegation(policy)

    def question(self, tool_id, arguments, *, records, device_id, context=None):
        operation = _OPS.get(tool_id)
        if operation is None:
            return None  # Only the closed local-file actions can be delegated.
        policy = self.policy
        if policy is None or (policy.get("available", True) and not policy["rules"]):
            return None  # Unconfigured accounts keep the first-stage behavior.
        if confirmed_delegation_action(tool_id, arguments, records):
            return None
        if policy.get("available", True) is False:
            return _question(_PREFIXES[2], operation, arguments)
        context = context or {}
        reported = context.get("device", {}).get("device_id") if isinstance(context.get("device"), Mapping) else None
        if device_id is not None and reported is not None and device_id != reported:
            return _question(_PREFIXES[2], operation, arguments)
        device_id = device_id or reported
        try:
            targets = [_resolve(arguments["path"], context)]
            if operation == "move":
                targets.append(_resolve(arguments["destination"], context))
            matches = []
            for rule in policy["rules"]:
                if rule["enabled"] and rule["device_id"] == device_id and operation in rule["actions"]:
                    matches.append((rule["mode"], _resolve(rule["folder"], context, folder=True)))
        except (KeyError, TypeError, ValueError):
            return _question(_PREFIXES[0], operation, arguments)
        if any(mode == "ask" and _within(folder, target) for mode, folder in matches for target in targets):
            return _question(_PREFIXES[1], operation, arguments)
        if all(any(mode == "allow" and _within(folder, target) for mode, folder in matches) for target in targets):
            return None
        return _question(_PREFIXES[0], operation, arguments)
