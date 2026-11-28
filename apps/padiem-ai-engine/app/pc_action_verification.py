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
                     termination: Any, exit_code: Any,
                     expected_content: Mapping[str, Any] | None = None) -> dict[str, Any]:
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
    # The PC's exact refusal must never be projected as a completed edit.
    if operation == "edit" and account.get("ok") is False:
        refused = account.get("reason")
        return finish("failed", refused if refused in {
            "edit_not_found", "edit_not_unique", "edit_conflict",
            "edit_encoding_unsupported", "edit_verification_failed",
            "backup_failed", "path_invalid",
        } else "execution_failed")
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
    # #7603: which postcondition an append must meet is decided by the request
    # the caller approved, never by a field the PC reported about itself.
    appending = extra.get("append") is True or (
        isinstance(expected_content, Mapping) and expected_content.get("mode") == "append")
    if operation in {"write", "edit", "move"}:
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
    elif operation == "mkdir":
        # #7603: a folder exists and is not a file. An existing folder is the
        # success path, so only a missing target or a same-name file fails.
        if any(type(evidence.get(key)) is not bool
               for key in ("target_exists", "target_is_file")):
            return finish("unavailable", "evidence_invalid")
        result.update(target_exists=evidence["target_exists"],
                      target_is_file=evidence["target_is_file"])
        if not evidence["target_exists"]:
            return finish("failed", "target_missing")
        if evidence["target_is_file"]:
            return finish("failed", "target_exists")
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

    if operation == "edit":
        expected_digest = account.get("edit_expected_sha256")
        actual_digest = evidence.get("target_sha256")
        count = account.get("replacement_count")
        before_preview = account.get("before_context")
        after_preview = account.get("after_context")
        first_line, last_line = account.get("line_start"), account.get("line_end")
        if (evidence.get("edit_verified") is not True
                or type(count) is not int or count < 1
                or type(first_line) is not int or first_line < 1
                or type(last_line) is not int or last_line < first_line
                or type(account.get("newline_converted")) is not bool
                or type(account.get("truncated")) is not bool
                or not isinstance(before_preview, str) or not isinstance(after_preview, str)
                or len(before_preview.encode("utf-8")) + len(after_preview.encode("utf-8")) > 4096
                or type(evidence.get("target_bytes")) is not int
                or evidence["target_bytes"] != account.get("bytes")
                or not isinstance(expected_digest, str)
                or re.fullmatch("[a-f0-9]{64}", expected_digest) is None
                or not isinstance(actual_digest, str)
                or re.fullmatch("[a-fA-F0-9]{64}", actual_digest) is None):
            return finish("unavailable", "evidence_invalid")
        if actual_digest.lower() != expected_digest:
            return finish("failed", "content_mismatch")
        if not isinstance(account.get("backup"), str) or not account["backup"].strip():
            return finish("unavailable", "evidence_invalid")
        if evidence.get("backup_exists") is not True or evidence.get("backup_is_file") is not True:
            return finish("failed", "backup_missing")

    if operation == "write":
        if expected_content is None:
            content = extra.get("content")
            if not isinstance(content, str):
                return finish("unavailable", "evidence_invalid")
            encoded = content.encode("utf-8")
            expected_size, expected_hash = len(encoded), hashlib.sha256(encoded).hexdigest()
        else:
            # Only the authenticated queue's original job metadata supplies this
            # projection; no model argument schema accepts these fields.
            expected_size = expected_content.get("expected_bytes")
            expected_hash = expected_content.get("expected_sha256")
            if (type(expected_size) is not int or expected_size < 0
                    or not isinstance(expected_hash, str)
                    or re.fullmatch(r"[a-f0-9]{64}", expected_hash) is None):
                return finish("unavailable", "evidence_invalid")
        if appending:
            # #7603: an append is measured where it lands, not over the whole
            # file: the target must now end with exactly the bytes that were
            # added, and the tail the command read back is that length. The
            # whole-file digest answers a different question and is not
            # compared with the added bytes here.
            tail_size = evidence.get("append_bytes")
            tail_digest = evidence.get("append_sha256")
            size = evidence.get("target_bytes")
            if (type(size) is not int or size < expected_size
                    or type(tail_size) is not int or tail_size != expected_size
                    or not isinstance(tail_digest, str)
                    or re.fullmatch(r"[a-fA-F0-9]{64}", tail_digest) is None):
                return finish("unavailable", "evidence_invalid")
            result.update(expected_bytes=expected_size, actual_bytes=tail_size,
                          expected_sha256=expected_hash, actual_sha256=tail_digest.lower())
            if tail_digest.lower() != expected_hash:
                return finish("failed", "content_mismatch")
        else:
            size, digest = evidence.get("target_bytes"), evidence.get("target_sha256")
            if (type(size) is not int or size < 0 or not isinstance(digest, str)
                    or re.fullmatch(r"[a-fA-F0-9]{64}", digest) is None):
                return finish("unavailable", "evidence_invalid")
            result.update(expected_bytes=expected_size, actual_bytes=size,
                          expected_sha256=expected_hash, actual_sha256=digest.lower())
            if size != expected_size or digest.lower() != expected_hash:
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
    # Only a verified edit may expose the bounded, two-sided preview to the
    # caller. It is tool output, never a new audit argument or trace entry.
    preview_keys = ("line_start", "line_end", "before_context", "after_context",
                    "replacement_count", "truncated", "newline_converted", "backup")
    if verified and verification["operation"] == "edit":
        data.update({key: account[key] for key in preview_keys if key in account})
    output = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return {"ok": verified, "dispatch_id": dispatch_id, "output": output, "content": output,
            **({key: data[key] for key in preview_keys if key in data}
               if verified and verification["operation"] == "edit" else {}),
            "content_bytes": len(output.encode("utf-8")), "execution_confirmed": verified,
            "action_verification": dict(verification), "termination": final.get("termination"),
            "exit_code": final.get("exit_code"), "result_sha256": final.get("result_sha256"),
            "content_sha256": final.get("content_sha256")}
