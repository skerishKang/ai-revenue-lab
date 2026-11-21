"""The user-session helper readiness wire shared by the PC agent lane and the Mesh queue.

#7987: a linked PC can be connected while a user-mode command cannot run on it,
because the user-session helper is not installed, no one is signed in to
Windows, or the helper is not listening. The executor observes five facts
about that from inside the already authenticated Mesh agent and forwards them
on the existing channel. This module is the whole shape of what may travel.

The shape is closed on purpose. Four values are a boolean or ``None`` ("could
not be read"), and one is the first twelve hex digits of the installed helper
build's SHA-256 or ``None``. There is no free text, so a user name, a path, a
device identity or a secret has nowhere to ride. Optional #8192 fields carry the public artifact SHA-256, bounded release label and UTC Mesh build timestamp. Ownership and receipt time
are supplied by the queue, never here, and readiness is display evidence only:
it neither grants nor blocks a PC command.
"""
from __future__ import annotations

import re
from typing import Any

HELPER_READY_FLAGS = ("task_present", "install_dir_present", "pipe_open", "interactive_session")
HELPER_READY_KEYS = frozenset({*HELPER_READY_FLAGS, "helper_build"})
_BUILD = re.compile(r"[0-9a-f]{12}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_AGENT_VERSION = re.compile(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z")
_RELEASE = re.compile(r"[0-9][0-9A-Za-z._-]{0,63}")
HELPER_UPDATE_RESULTS = frozenset({"current", "pending", "success", "hash_mismatch", "signature_mismatch",
                                   "manifest_rejected", "download_failed", "deferred", "rollback", "registration_failed", "available"})
REGISTRATION_ERRORS = frozenset({"updater_running", "excluded_computer", "missing_fixed_source",
                                 "invalid_install_record", "installed_digest_mismatch", "task_registration_failed",
                                 "task_registration_timeout", "task_process_start_failed", "version_unavailable"})
HELPER_READY_OPTIONAL_KEYS = frozenset({"helper_sha256", "helper_version", "mesh_agent_version",
                                      "update_result", "update_registration_error", "auto_update", "update_target_sha256"})


class HelperReadyError(ValueError):
    """Malformed readiness; messages never contain a reported value."""


def validate_helper_ready(value: Any) -> dict[str, Any]:
    """Validate and return a fresh, stable observation suitable for comparison."""
    if (not isinstance(value, dict) or not HELPER_READY_KEYS <= set(value)
            or set(value) - HELPER_READY_KEYS - HELPER_READY_OPTIONAL_KEYS):
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
    if "helper_sha256" in value:
        sha = value["helper_sha256"]
        if sha is not None and (not isinstance(sha, str) or _SHA256.fullmatch(sha) is None
                                or sha[:12] != build):
            raise HelperReadyError("invalid helper digest")
        result["helper_sha256"] = sha
    if "helper_version" in value:
        release = value["helper_version"]
        if release is not None and (not isinstance(release, str) or _RELEASE.fullmatch(release) is None
                                    or result.get("helper_sha256") is None):
            raise HelperReadyError("invalid helper release")
        result["helper_version"] = release
    if "mesh_agent_version" in value:
        version = value["mesh_agent_version"]
        if version is not None and (not isinstance(version, str)
                                    or _AGENT_VERSION.fullmatch(version) is None):
            raise HelperReadyError("invalid Mesh Agent version")
        result["mesh_agent_version"] = version
    if "update_result" in value:
        update = value["update_result"]
        if not isinstance(update, str) or update not in HELPER_UPDATE_RESULTS:
            raise HelperReadyError("invalid helper update result")
        result["update_result"] = update
    if "update_target_sha256" in value:
        target = value["update_target_sha256"]
        if not isinstance(target, str) or _SHA256.fullmatch(target) is None:
            raise HelperReadyError("invalid target release digest")
        result["update_target_sha256"] = target
    if "auto_update" in value:
        if type(value["auto_update"]) is not bool:
            raise HelperReadyError("invalid helper update preference")
        result["auto_update"] = value["auto_update"]
    if "update_registration_error" in value:
        reason = value["update_registration_error"]
        if (result.get("update_result") != "registration_failed" or not isinstance(reason, str)
                or reason not in REGISTRATION_ERRORS):
            raise HelperReadyError("invalid helper updater registration error")
        result["update_registration_error"] = reason
    return result


__all__ = ["HELPER_READY_FLAGS", "HELPER_READY_KEYS", "HELPER_READY_OPTIONAL_KEYS",
           "HelperReadyError", "validate_helper_ready"]
