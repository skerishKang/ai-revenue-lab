"""Compare post-action PC filesystem measurements with the requested result.

The server-built PC command measures the filesystem after the mutation, under
the same signed dispatch. An account's ``ok`` or output-envelope digest alone
is never proof that the requested bytes, move or deletion actually happened.
"""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
import re
from typing import Any


def unavailable_action(operation: str, path: str, *, destination: str | None = None,
                       reason: str = "check_unavailable") -> dict[str, Any]:
    result = {"status": "unavailable", "operation": operation, "path": path,
              "reason": reason, "label": "확인하지 못함"}
    if destination is not None:
        result["destination"] = destination
    return result


def verify_pc_action(*, operation: str, path: str, extra: Mapping[str, str],
                     account: Mapping[str, Any] | None, state: str,
                     termination: Any, exit_code: Any) -> dict[str, Any]:
    """Return a factual observation, including when a check is unavailable."""
    result = unavailable_action(operation, path, destination=extra.get("destination"))

    def finish(status: str, reason: str):
        result.update(status=status, reason=reason,
                      label={"verified": "검증됨", "failed": "검증 실패", "unavailable": "확인하지 못함"}[status])
        return result

    if not isinstance(account, Mapping):
        return finish("unavailable", "evidence_missing")
    if account.get("op") != operation or type(account.get("ok")) is not bool:
        return finish("unavailable", "evidence_invalid")
    evidence = account.get("verification")
    if not isinstance(evidence, Mapping):
        return finish("unavailable", "evidence_missing")
    if type(evidence.get("version")) is not int or evidence["version"] != 1:
        return finish("unavailable", "evidence_invalid")
    if evidence.get("status") == "unavailable":
        return finish("unavailable", "check_unavailable")
    if evidence.get("status") != "observed":
        return finish("unavailable", "evidence_invalid")

    if type(evidence.get("source_exists")) is not bool:
        return finish("unavailable", "evidence_invalid")
    if operation in {"write", "move"}:
        if any(type(evidence.get(key)) is not bool for key in ("target_exists", "target_is_file")):
            return finish("unavailable", "evidence_invalid")
        result.update(source_exists=evidence["source_exists"], target_exists=evidence["target_exists"],
                      target_is_file=evidence["target_is_file"])
        if operation == "move" and evidence["source_exists"]:
            return finish("failed", "source_remaining")
        if not evidence["target_exists"]:
            return finish("failed", "target_missing")
        if not evidence["target_is_file"]:
            return finish("failed", "target_not_file")
    elif operation == "delete":
        result["source_exists"] = evidence["source_exists"]
        if evidence["source_exists"]:
            return finish("failed", "source_remaining")
        if type(evidence.get("backup_exists")) is not bool:
            return finish("unavailable", "evidence_invalid")
        result["backup_exists"] = evidence["backup_exists"]
        if not evidence["backup_exists"]:
            return finish("failed", "backup_missing")
        if type(evidence.get("backup_is_file")) is not bool:
            return finish("unavailable", "evidence_invalid")
        if not evidence["backup_is_file"]:
            return finish("failed", "backup_missing")
        if not isinstance(account.get("backup"), str) or not account["backup"].strip():
            return finish("unavailable", "evidence_invalid")
    else:
        return finish("unavailable", "evidence_invalid")

    if operation == "write":
        size, digest = evidence.get("target_bytes"), evidence.get("target_sha256")
        if (type(size) is not int or size < 0 or not isinstance(digest, str)
                or re.fullmatch(r"[a-fA-F0-9]{64}", digest) is None):
            return finish("unavailable", "evidence_invalid")
        content = extra.get("content")
        if not isinstance(content, str):
            return finish("unavailable", "evidence_invalid")
        encoded = content.encode("utf-8")
        expected_hash = hashlib.sha256(encoded).hexdigest()
        result.update(expected_bytes=len(encoded), actual_bytes=size,
                      expected_sha256=expected_hash, actual_sha256=digest.lower())
        if size != len(encoded) or digest.lower() != expected_hash:
            return finish("failed", "content_mismatch")

    # A matching state does not turn a refused/failed command into a completed
    # action (for example, a pre-existing identical file after backup failure).
    # Mesh command consoles may have no exit code. Preserve that transport
    # contract: the independently measured postconditions above are the proof.
    terminal_ok = (
        isinstance(termination, str) and termination in {"exited", "no_exit_code", "output_too_large"}
        and ((type(exit_code) is int and exit_code == 0)
             or (exit_code is None and termination in {"no_exit_code", "output_too_large"}))
    )
    if account["ok"] is not True or state != "done" or not terminal_ok:
        return finish("failed", "execution_failed")
    return finish("verified", "postconditions_match")


def mutation_observation(*, verification: Mapping[str, Any], account=None, final=None, dispatch_id=None):
    """Normal tool data, never a tool error/refusal or an automatic retry."""
    import json

    account = account if isinstance(account, Mapping) else {}
    final = final if isinstance(final, Mapping) else {}
    verified = verification["status"] == "verified"
    data = {"ok": verified, "op": verification["operation"], "target": account.get("target"),
            "backup": account.get("backup"), "bytes": account.get("bytes"),
            "action_verification": dict(verification)}
    output = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return {"ok": verified, "dispatch_id": dispatch_id, "output": output, "content": output,
            "content_bytes": len(output.encode("utf-8")), "execution_confirmed": verified,
            "action_verification": dict(verification), "termination": final.get("termination"),
            "exit_code": final.get("exit_code"), "result_sha256": final.get("result_sha256"),
            "content_sha256": final.get("content_sha256")}
