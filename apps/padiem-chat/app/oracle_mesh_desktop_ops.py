"""Oracle Mesh desktop input grammar."""
from __future__ import annotations

import re
from typing import Any

from .oracle_mesh_contract import _DESKTOP_COMMAND_PREFIX, _DESKTOP_OPS


#: #6460 step 2 — the combo vocabulary the executor also enforces. What is
#: closed is the *names*: one reviewed key name with up to three distinct
#: modifiers, and never the secure attention sequence. The executor re-checks
#: before the PC acts and stays the authority.
_DESKTOP_KEY_NAMES = frozenset({
    "enter", "esc", "escape", "tab", "backspace", "delete", "space",
    "insert", "home", "end", "pageup", "pagedown", "left", "up", "right", "down",
    "win", "meta",
}) | frozenset(chr(code) for code in range(ord("a"), ord("z") + 1)) \
  | frozenset(str(digit) for digit in range(10)) \
  | frozenset("f%d" % n for n in range(1, 13))
_DESKTOP_KEY_MODIFIER_CODES = {
    "ctrl": 17, "control": 17, "alt": 18, "shift": 16, "win": 91, "meta": 91,
}
_DESKTOP_RESERVED_KEY_COMBOS = frozenset({
    "ctrl+alt+del", "ctrl+alt+delete",
})


def _desktop_key_combo_is_valid(arg: str) -> bool:
    if not isinstance(arg, str) or not arg or len(arg) > 64:
        return False
    parts = [part.strip().lower() for part in arg.split("+")]
    if any(not part for part in parts) or len(parts) > 4:
        return False
    key, modifiers = parts[-1], parts[:-1]
    if key not in _DESKTOP_KEY_NAMES:
        return False
    if key in ("win", "meta") and modifiers:
        # A lone Win key is a real press; as a combo member it is a modifier.
        return False
    canonical_modifiers: list[str] = []
    seen: set[int] = set()
    for modifier in modifiers:
        code = _DESKTOP_KEY_MODIFIER_CODES.get(modifier)
        if code is None or code in seen:
            return False
        seen.add(code)
        canonical_modifiers.append(
            "ctrl" if modifier in ("ctrl", "control")
            else "win" if modifier in ("win", "meta") else modifier
        )
    canonical = "+".join(canonical_modifiers + [key])
    return canonical not in _DESKTOP_RESERVED_KEY_COMBOS


def _parse_desktop_op_text(value: Any) -> tuple[str, str | None] | None:
    """Split one ``desktop:`` op body into (op, arg), or None when malformed.

    #4139 desktop lane. This mirrors the executor's grammar so a malformed
    op is refused here with 422 instead of burning a PC turn; the executor
    still re-verifies before the PC acts and never trusts this check.
    """
    if not isinstance(value, str):
        return None
    if not value.startswith(_DESKTOP_COMMAND_PREFIX):
        return None
    rest = value[len(_DESKTOP_COMMAND_PREFIX):]
    if "\x00" in rest or "\r" in rest:
        return None
    head, _, tail = rest.partition("\n")
    op = head.strip().lower()
    if op not in _DESKTOP_OPS:
        return None
    if op == "capture":
        if tail.strip():
            return None
        return op, None
    arg = tail.strip(" \t\n")
    if not arg:
        return None
    if op == "type":
        if any(ord(ch) < 32 and ch not in "\t\n" for ch in arg) or "\x7f" in arg:
            return None
        return op, arg
    if op == "keys":
        if not _desktop_key_combo_is_valid(arg):
            return None
        return op, arg.strip().lower()
    match = re.fullmatch(r"(\d{1,5}),(\d{1,5})", arg)
    if match is None:
        return None
    if int(match.group(1)) > 65535 or int(match.group(2)) > 65535:
        return None
    return op, f"{int(match.group(1))},{int(match.group(2))}"

#: #6460 step 2 — the audit row names a typed value only by length, digest
#: prefix and an unguessable reference; the value itself is taken once here.
_DESKTOP_TYPE_MARKER = re.compile(r"\Adesktop:type\n#\d{1,6}:[0-9a-f]{8}:([0-9a-f]{32})\Z")


def _desktop_text_ref(command_text: Any) -> str | None:
    if not isinstance(command_text, str):
        return None
    match = _DESKTOP_TYPE_MARKER.fullmatch(command_text)
    return match.group(1) if match else None
