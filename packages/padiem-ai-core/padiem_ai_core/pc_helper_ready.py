"""The user-session helper readiness wire shared by the PC agent lane and the Mesh queue.

#7987: a linked PC can be connected while a user-mode command cannot run on it,
because the user-session helper is not installed, no one is signed in to
Windows, or the helper is not listening. The executor observes five facts
about that from inside the already authenticated Mesh agent and forwards them
on the existing channel. This module is the whole shape of what may travel.

The shape is closed on purpose. Four values are a boolean or ``None`` ("could
not be read"), and one is the first twelve hex digits of the installed helper
build's SHA-256 or ``None``. There is no free text, so a user name, a path, a
device identity or a secret has nowhere to ride. Ownership and receipt time
are supplied by the queue, never here, and readiness is display evidence only:
it neither grants nor blocks a PC command.
"""
from __future__ import annotations

import re
from typing import Any

HELPER_READY_FLAGS = ("task_present", "install_dir_present", "pipe_open", "interactive_session")
HELPER_READY_KEYS = frozenset({*HELPER_READY_FLAGS, "helper_build"})
_BUILD = re.compile(r"[0-9a-f]{12}")


class HelperReadyError(ValueError):
    """Malformed readiness; messages never contain a reported value."""


def validate_helper_ready(value: Any) -> dict[str, Any]:
    """Validate and return a fresh, stable observation suitable for comparison."""
    if not isinstance(value, dict) or set(value) != HELPER_READY_KEYS:
        raise HelperReadyError("invalid helper readiness fields")
    result: dict[str, Any] = {}
    for key in HELPER_READY_FLAGS:
        flag = value[key]
        if flag is not None and type(flag) is not bool:
            raise HelperReadyError("invalid helper readiness flag")
        result[key] = flag
    build = value["helper_build"]
    if build is not None and (not isinstance(build, str) or _BUILD.fullmatch(build) is None):
        raise HelperReadyError("invalid helper build")
    result["helper_build"] = build
    return result


__all__ = ["HELPER_READY_FLAGS", "HELPER_READY_KEYS", "HelperReadyError", "validate_helper_ready"]
