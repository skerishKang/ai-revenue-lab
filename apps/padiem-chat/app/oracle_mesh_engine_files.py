"""Engine PC file operations: admission, dispatch and verification."""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from starlette.requests import Request
from starlette.responses import JSONResponse
from .pc_dispatch_ttl import chat_pc_dispatch_ttl
from .pc_share_timeout import share_command_prefix, share_roots_of
from .claw_pc_read_command import pc_read_chunk_command, pc_read_length, pc_read_offset
from .claw_pc_search_command import PC_SEARCH_MAX_LIMIT, pc_search_command, pc_search_mode, pc_search_query, pc_search_roots
from .claw_local_task_result_projection import result_message_id
from .history import HistoryForbidden, validate_conversation_id
from .oracle_mesh_http import _response, _error
from .oracle_mesh_dispatch import _dispatch_workspace_id, dispatch_oracle_mesh_command_intent, dispatch_oracle_mesh_file_read_intent
from .oracle_mesh_engine_auth import _verify_engine_proof, _engine_pc_scope_claim, _engine_pc_files_owner, _engine_pc_files_target
from .oracle_mesh_pc_paths import _PC_FILES_SAFE_REF, _pc_files_pick_root, _PC_FILES_OPS, _pc_files_read_only, _PC_WRITE_OPS, _pc_files_claim_op, _pc_files_search_roots
from .oracle_mesh_pc_write import _pc_backup_dir, _pc_write_command
from .oracle_mesh_pc_read import _pc_files_command
from .oracle_mesh_engine_output import _engine_pc_public_output, _engine_pc_job_response, _engine_pc_output_call, PC_IMAGE_ENVELOPE_PREFIX, _pc_image_projection


async def _engine_pc_files_call(request: Request, *, product: str) -> JSONResponse:
    """One signed Engine call for the PC file context/dispatch/status/result."""
    resp, bundle = await _engine_pc_files_call_verify(request, product=product)
    if resp is not None:
        return resp
    scope_claim = bundle["scope_claim"]
    payload = bundle["payload"]
    requested_mode = bundle["requested_mode"]
    mode = bundle["mode"]
    selected = bundle["selected"]
    uid = bundle["uid"]
    session = bundle["session"]
    history_store = bundle["history_store"]
    run_row = bundle["run_row"]
    new_mode = bundle["new_mode"]
    resolved = bundle["resolved"]
    target = bundle["target"]
    roots = bundle["roots"]
    device_id = bundle["device_id"]

    if mode in ("context", "dispatch") and scope_claim is not None:
        scope_pinner = getattr(history_store, "pin_pc_run_scope", None)
        if not callable(scope_pinner):
            return _error(503, "pc_scope_store_unavailable")
        try:
            await scope_pinner(user_id=uid, run_id=payload["run_id"], claim=scope_claim)
        except HistoryForbidden:
            return _error(403, "pc_scope_frozen")
        except Exception:
            return _error(503, "pc_scope_store_unavailable")

    if mode == "context":
        # (A): the model is shown the owner's own names for the approved
        # folders, never a real path. One folder keeps the single-folder shape
        # the tools already speak; several arrive as a label list, and a call
        # must then name which one it means.
        labels = [root["label"] for root in roots]
        return _response({
            "ok": True,
            "roots": [{"label": label} for label in labels],
            # Engine guard only. The model projection remains device/tools;
            # matching a saved absolute folder to a labeled relative tool path
            # must use these owner-verified roots, never guess a home directory.
            "delegation_roots": [{"label": root["label"], "path": root["path"]} for root in roots],
            "device": {
                "device_id": device_id,
                "status": "configured",
                "folder": {
                    "name": labels[0] if len(labels) == 1 else (target.get("label") or "PC"),
                    "relative_path": ".",
                },
                "online_verified": False,
            },
            "tools": [
                "claw.pc.list_files",
                "claw.pc.read_file",
                "claw.pc.search_files",
                "claw.pc.search_contents",
                "claw.pc.query_drives",
            ],
            "run_id": payload["run_id"],
        })

    if requested_mode in ("read_output", "search_output", "store_output"):
        return await _engine_pc_output_call(
            history_store, payload=payload, uid=uid, device_id=device_id,
        )

    # The Engine has reached a real PC step for this proof- and owner-verified
    # run, so the conversation's staged row moves pending -> running. Status
    # only: no result_summary is ever passed, so a step in flight cannot be
    # mistaken for the run's answer, and the guarded write leaves a completed
    # run untouched. A lost projection must not fail the step that is running.
    mark_running = getattr(history_store, "update_claw_run_status", None)
    if callable(mark_running):
        try:
            await mark_running(uid, payload["run_id"], "running")
        except Exception:
            pass

    resp, _bundle = await _engine_pc_files_call_dispatch(
        request, payload=payload, requested_mode=requested_mode, mode=mode,
        scope_claim=scope_claim, roots=roots, selected=selected,
        session=session, uid=uid, target=target,
    )
    if resp is not None:
        return resp

    dispatch_id = payload.get("dispatch_id")
    if not isinstance(dispatch_id, str) or not 0 < len(dispatch_id) <= 128:
        return _error(400, "claw_engine_files_invalid_body")
    reader = getattr(history_store, "get_oracle_mesh_dispatch_for_owner", None)
    if not callable(reader):
        return _error(503, "oracle_mesh_unconfigured")
    try:
        dispatch = await reader(user_id=uid, dispatch_id=dispatch_id)
    except Exception:
        return _error(503, "oracle_mesh_dispatch_unavailable")
    kind = dispatch.get("kind") if isinstance(dispatch, dict) else None
    if (
        not isinstance(dispatch, dict)
        or dispatch.get("run_id") != payload["run_id"]
        or kind not in ("command", "read")
    ):
        return _error(404, "oracle_mesh_run_unavailable")
    if scope_claim is not None and kind == "read" and "read" not in scope_claim["ops"]:
        return _error(403, "pc_scope_denied")
    if new_mode:
        # The public row carries no device binding; the owner-scoped private
        # read is where it lives.
        private_reader = getattr(history_store, "get_pc_output_dispatch_for_owner", None)
        private = await private_reader(user_id=uid, dispatch_id=dispatch_id) if callable(private_reader) else None
        bound = private.get("device_id") if isinstance(private, dict) else dispatch.get("device_id")
        if bound != device_id:
            return _error(404, "oracle_mesh_run_unavailable")
    state = dispatch.get("state")
    if state not in {"pending", "received", "store_failed", "done", "failed"}:
        return _error(503, "oracle_mesh_dispatch_unavailable")
    if requested_mode == "job_status":
        return _response({"ok": True, "result": {
            "job_id": dispatch_id,
            "state": "running" if state == "pending" and dispatch.get("claimed") is True else state,
            "kind": kind, "termination": dispatch.get("termination"), "exit_code": dispatch.get("exit_code"),
            **({"operation": dispatch["job_operation"]} if isinstance(dispatch.get("job_operation"), dict) else {}),
        }})
    if mode == "command_status":
        return _response({
            "ok": True,
            "dispatch": {
                "dispatch_id": dispatch["dispatch_id"],
                "run_id": payload["run_id"],
                "kind": kind,
                "state": state,
                "result_sha256": dispatch.get("result_sha256"),
                "termination": dispatch.get("termination"),
                "exit_code": dispatch.get("exit_code"),
                # The continuation leg projects the finished listing against the
                # folder it was asked about; the Engine sent this path and is the
                # only reader of this response.
                "file_path": dispatch.get("file_path"),
            },
        })
    # A command result is ready only after a clean terminal row. A read keeps
    # its verified body on a failed row too (the executor's bounded
    # PADIEM_PC_FILE_ERROR marker), so the Engine can surface the same error
    # mapping instead of losing it to an empty outcome.
    if kind == "read":
        if state not in ("done", "failed"):
            return _error(409, "oracle_mesh_result_not_ready")
    elif state != "done" and not (requested_mode == "job_output" and state == "failed"):
        return _error(409, "oracle_mesh_result_not_ready")
    termination = dispatch.get("termination")
    exit_code = dispatch.get("exit_code")
    if termination not in (
        "exited", "no_exit_code", "output_too_large", "not_executed",
        "timed_out", "cancelled", "no_reply", "bad_reply",
    ):
        return _error(503, "oracle_mesh_original_unavailable")
    if exit_code is None:
        if termination not in (
            "timed_out", "no_reply", "no_exit_code", "not_executed",
            "output_too_large", "cancelled", "bad_reply",
        ):
            return _error(503, "oracle_mesh_original_unavailable")
    elif isinstance(exit_code, bool) or not isinstance(exit_code, int):
        return _error(503, "oracle_mesh_original_unavailable")
    try:
        conversation_id = validate_conversation_id(
            (run_row or {}).get("conversation_id"),
        )
        if not conversation_id:
            return _error(404, "oracle_mesh_run_unavailable")
        message_id = result_message_id(
            conversation_id=conversation_id,
            command_id=dispatch["command_id"],
            revision_ref=dispatch["revision_ref"],
        )
        stored = await history_store.read_oracle_mesh_original(
            user_id=uid, dispatch_id=dispatch["dispatch_id"],
            conversation_id=conversation_id, message_id=message_id,
        )
    except Exception:
        return _error(503, "oracle_mesh_original_unavailable")
    if stored is None:
        return _error(404, "oracle_mesh_original_unavailable")
    content, digest = stored
    if (
        not isinstance(content, bytes)
        or hashlib.sha256(content).hexdigest() != digest
        or digest != dispatch.get("result_sha256")
    ):
        return _error(503, "oracle_mesh_original_unavailable")
    try:
        output = content.decode("utf-8")
    except UnicodeDecodeError:
        return _error(503, "oracle_mesh_original_unavailable")
    image_block = None
    if kind == "read" and output.startswith(PC_IMAGE_ENVELOPE_PREFIX):
        output, image_block = _pc_image_projection(output)
    output_ref = None
    if len(output) > 4096 or requested_mode == "job_output":
        public_output, output_error = await _engine_pc_public_output(
            history_store, payload=payload, uid=uid, dispatch=dispatch,
            output=output, device_id=device_id, force=True,
        )
        if output_error is not None:
            return output_error
        output_ref = public_output["output_ref"]
        if requested_mode == "job_output":
            page = await _engine_pc_output_call(
                history_store,
                payload={**payload, "mode": "read_output", "handle": output_ref["handle"]},
                uid=uid, device_id=device_id,
            )
            if page.status_code != 200:
                return page
            result = json.loads(page.body)["result"]
            # The projected image block rides beside the paged output: a
            # job_output re-read must answer with the same image the direct
            # result carried (#7447).
            return _response({"ok": True, "result": {
                **result, "job_id": dispatch_id, "state": state,
                "output_ref": output_ref, "termination": termination, "exit_code": exit_code,
                **({"operation": dispatch["job_operation"]} if isinstance(dispatch.get("job_operation"), dict) else {}),
                **({"_pc_image": image_block} if image_block else {}),
            }})
        output = public_output["output"]
    # #7447/#7473: only a projected image read answers with the note as
    # its body, so content length/digest must describe the note the Engine
    # validates against. The stored-output reference and the plain text
    # lane keep the stored original's values: the Engine pins
    # content_bytes to the reference size there (#7473 review).
    if image_block is not None and output_ref is None:
        content_sha256 = hashlib.sha256(output.encode("utf-8")).hexdigest()
        content_bytes = len(output.encode("utf-8"))
    else:
        content_sha256 = digest
        content_bytes = len(content)
    return _response({
        "ok": True,
        "dispatch": {
            "dispatch_id": dispatch["dispatch_id"],
            "run_id": payload["run_id"],
            "kind": kind,
            "state": state,
            "result_sha256": digest,
            # A continuation projects the finished listing against the folder it
            # was asked about; the Engine sent this path and is the only reader.
            "file_path": dispatch.get("file_path"),
            "content_sha256": content_sha256,
            "content_bytes": content_bytes,
            "output": output,
            **({"_pc_image": image_block} if image_block else {}),
            **({"output_ref": output_ref} if output_ref else {}),
            "termination": termination,
            "exit_code": exit_code,
        },
    })


async def _engine_pc_files_call_dispatch(
    request: Request, *, payload: dict, requested_mode: str, mode: str,
    scope_claim: dict | None, roots: list, selected: str | None,
    session: Any, uid: str, target: dict,
) -> tuple[JSONResponse | None, dict[str, object]]:
    """디스패치 분기 구간.

    본문은 리팩터 전 `_engine_pc_files_call`의 연속 구간을 글자 그대로 옮긴다.
    검사 순서·실패 응답·await 순서·디스패치 생성 인자를 그대로 지킨다.
    """
    if mode == "dispatch":
        op = payload.get("op")
        if op not in _PC_FILES_OPS:
            return _error(422, "oracle_mesh_file_op_invalid"), {}
        search_mode = None
        claim_op = op
        if op == "search":
            search_mode = pc_search_mode(payload.get("search_mode"))
            claim_op = _pc_files_claim_op(op, search_mode)
            if claim_op is None:
                return _error(422, "oracle_mesh_file_search_invalid"), {}
        # The independently signed ceiling is enforced before either dispatch
        # constructor. The existing owner/path/size/idempotency checks follow.
        if scope_claim is not None and claim_op not in scope_claim["ops"]:
            return _error(403, "pc_scope_denied"), {}
        search_roots = None
        if op == "search":
            # No folder named means every approved root, in order: the owner's
            # grant is the whole set, so a search never has to guess one and is
            # never refused for not naming one.
            search_roots = _pc_files_search_roots(roots, payload.get("path"))
            if search_roots is None:
                return _error(422, "oracle_mesh_file_path_invalid"), {}
            if pc_search_roots(search_roots) is None:
                return _error(503, "oracle_mesh_file_root_unavailable"), {}
            root = relative = None
        else:
            picked = _pc_files_pick_root(roots, payload.get("path"))
            if picked is None:
                return _error(422, "oracle_mesh_file_path_invalid"), {}
            root, relative = picked
            if op == "read" and not relative:
                return _error(422, "oracle_mesh_file_path_invalid"), {}
        tool_call_ref = payload.get("tool_call_ref")
        if (
            not isinstance(tool_call_ref, str)
            or _PC_FILES_SAFE_REF.fullmatch(tool_call_ref) is None
        ):
            return _error(422, "oracle_mesh_file_call_invalid"), {}
        command_workspace = await _dispatch_workspace_id(request, uid, session)
        if not command_workspace:
            return _error(503, "oracle_mesh_workspace_unavailable"), {}
        job_operation = {"op": op, "path": payload["path"]} if requested_mode == "job_start" else None
        if op in _PC_WRITE_OPS:
            # One write step, one account. The path the PC will change is built
            # the way the listing builds its folder - the root the server picked
            # plus the relative path the caller named - so a request never
            # carries an absolute target of its own.
            resolved = root.rstrip("/") + ("/" + relative if relative else "")
            content_b64 = None
            append = False
            if op == "write":
                content = payload.get("content")
                if not isinstance(content, str):
                    return _error(422, "oracle_mesh_file_content_invalid"), {}
                if "append" in payload and type(payload["append"]) is not bool:
                    return _error(422, "oracle_mesh_file_mode_invalid"), {}
                append = payload.get("append") is True
                content_b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
                if job_operation is not None:
                    job_operation.update(expected_bytes=len(content.encode("utf-8")),
                                         expected_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest())
                    if append:
                        job_operation["mode"] = "append"
            old_text_b64 = new_text_b64 = None
            if op == "edit":
                # #7065: the two byte sequences are carried the same way the
                # write carries its bytes, so no console code page or quoting
                # rule can change what is searched for or what is written.
                old_text, new_text = payload.get("old_text"), payload.get("new_text")
                if not isinstance(old_text, str) or not isinstance(new_text, str):
                    return _error(422, "oracle_mesh_file_edit_invalid"), {}
                if not old_text:
                    return _error(422, "oracle_mesh_file_edit_invalid"), {}
                replace_all = payload.get("replace_all")
                if replace_all is not None and not isinstance(replace_all, bool):
                    return _error(422, "oracle_mesh_file_edit_invalid"), {}
                if job_operation is not None:
                    job_operation["edit"] = True
                old_text_b64 = base64.b64encode(old_text.encode("utf-8")).decode("ascii")
                new_text_b64 = base64.b64encode(new_text.encode("utf-8")).decode("ascii")
            destination_path = None
            if op == "move":
                picked_destination = _pc_files_pick_root(roots, payload.get("destination"))
                if picked_destination is None:
                    return _error(422, "oracle_mesh_file_path_invalid"), {}
                destination_root, destination_relative = picked_destination
                if destination_root != root or not destination_relative:
                    # A move stays inside the folder this link was granted, and
                    # never onto the granted root itself: replacing a whole
                    # folder is not what moving one file means.
                    return _error(422, "oracle_mesh_file_path_invalid"), {}
                destination_path = destination_root.rstrip("/") + "/" + destination_relative
                if job_operation is not None:
                    job_operation["destination"] = payload["destination"]
            command = _pc_write_command(
                op=op,
                root=root,
                target=resolved,
                backup_dir=_pc_backup_dir(
                    root, datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                ),
                relative=relative,
                destination=destination_path,
                content_b64=content_b64,
                old_text_b64=old_text_b64,
                new_text_b64=new_text_b64,
                append=append,
                replace_all=bool(payload.get("replace_all")),
            )
            response = await dispatch_oracle_mesh_command_intent(
                request, command=command,
                wire={
                    "run_id": payload["run_id"],
                    "device_id": selected,
                    "confirmed": True,
                },
                trusted_owner=(session, uid, command_workspace),
                tool_call_ref=tool_call_ref,
                files_target=target,
                background=requested_mode == "job_start",
                job_operation=job_operation,
            )
            return _engine_pc_job_response(response, requested_mode), {}
        if op == "read":
            # #5015: the read reuses the existing kind="read" MeshCentral
            # download lane. No shell command is built for it.
            response = await dispatch_oracle_mesh_file_read_intent(
                request,
                wire={
                    "run_id": payload["run_id"],
                    "device_id": selected,
                    "confirmed": True,
                },
                trusted_owner=(session, uid, command_workspace),
                tool_call_ref=tool_call_ref,
                target=target,
                root=root,
                relative=relative,
                background=requested_mode == "job_start",
                job_operation=job_operation,
            )
            return _engine_pc_job_response(response, requested_mode), {}
        if op == "read_chunk":
            offset = pc_read_offset(payload.get("offset"))
            length = pc_read_length(payload.get("length"))
            if offset is None or length is None or not relative:
                return _error(422, "oracle_mesh_file_range_invalid"), {}
            command = pc_read_chunk_command(
                root=root, relative=relative, offset=offset, length=length,
            )
            return await dispatch_oracle_mesh_command_intent(
                request, command=share_command_prefix([root]) + command,
                wire={
                    "run_id": payload["run_id"],
                    "device_id": selected,
                    "confirmed": True,
                },
                trusted_owner=(session, uid, command_workspace),
                tool_call_ref=tool_call_ref,
                files_target=target,
                read_only=True,
                share_roots=share_roots_of([root]),
            ), {}
        if op == "search":
            query = pc_search_query(payload.get("query"))
            if query is None:
                return _error(422, "oracle_mesh_file_search_invalid"), {}
            command = pc_search_command(
                roots=search_roots, query=query, mode=search_mode,
                limit=PC_SEARCH_MAX_LIMIT,
            )
            return await dispatch_oracle_mesh_command_intent(
                request, command=share_command_prefix(search_roots) + command,
                wire={
                    "run_id": payload["run_id"],
                    "device_id": selected,
                    "confirmed": True,
                },
                trusted_owner=(session, uid, command_workspace),
                tool_call_ref=tool_call_ref,
                files_target=target,
                read_only=True,
                share_roots=share_roots_of(search_roots),
            ), {}
        depth = payload.get("depth")
        if "depth" in payload and (
            type(depth) is not int or isinstance(depth, bool) or not 1 <= depth <= 3
        ):
            return _error(422, "oracle_mesh_file_depth_invalid"), {}
        offset = payload.get("offset")
        if "offset" in payload and (
            type(offset) is not int or isinstance(offset, bool) or not 0 <= offset <= 10_000
        ):
            return _error(422, "oracle_mesh_file_offset_invalid"), {}
        if (depth or 1) > 1 and (offset or 0) != 0:
            return _error(422, "oracle_mesh_file_offset_invalid"), {}
        recursive = payload.get("recursive")
        if "recursive" in payload and type(recursive) is not bool:
            return _error(422, "oracle_mesh_file_recursive_invalid"), {}
        if recursive is True:
            # This leg carries no name fragment, and the recursive builder
            # refuses to walk without one. A recursive name search travels as
            # the search op instead, so the flag is refused here by name rather
            # than left to fail inside the builder.
            return _error(422, "oracle_mesh_file_recursive_unsupported"), {}
        command = _pc_files_command(
            op=op, root=root, relative=relative,
            depth=depth if depth is not None else 1,
            offset=offset if offset is not None else 0,
        )
        response = await dispatch_oracle_mesh_command_intent(
            request, command=share_command_prefix([root]) + command,
            wire={
                "run_id": payload["run_id"],
                "device_id": selected,
                "confirmed": True,
            },
            trusted_owner=(session, uid, command_workspace),
            tool_call_ref=tool_call_ref,
            files_target=target,
            # #7602: only a read is handed out again after a run-out lease.
            read_only=_pc_files_read_only(op),
            share_roots=share_roots_of([root]),
            background=requested_mode == "job_start",
                job_operation=job_operation,
        )
        return _engine_pc_job_response(response, requested_mode), {}
    return None, {}


async def _engine_pc_files_call_verify(
    request: Request, *, product: str,
) -> tuple[JSONResponse | None, dict[str, object]]:
    """서명·본문 파싱·모드 검증·소유자/대상 확인 구간.

    본문은 리팩터 전 `_engine_pc_files_call`의 연속 구간을 글자 그대로 옮긴다.
    검사 순서와 실패 응답, await 순서를 그대로 지킨다.
    """
    raw, proof_error = await _verify_engine_proof(request, max_body_bytes=None)
    if proof_error is not None or raw is None:
        return (proof_error if proof_error is not None else _error(
            401, "claw_engine_proof_required",
        )), {}
    scope_claim, scope_error = _engine_pc_scope_claim(request, raw, product=product)
    if scope_error is not None:
        return scope_error, {}
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return _error(400, "claw_engine_files_invalid_body"), {}
    if not isinstance(payload, dict):
        return _error(400, "claw_engine_files_invalid_body"), {}
    requested_mode = mode = payload.get("mode")
    # Only the dispatch leg has optional fields today; every other leg is exact.
    optional = set()
    if mode == "context":
        expected = {"subject_id", "run_id", "device_id", "mode"}
    elif mode == "dispatch":
        expected = {
            "subject_id", "run_id", "device_id", "op", "path",
            "tool_call_ref", "mode",
        }
        # A write names its bytes and a move names where the file lands. Nothing
        # else may add a field, and the operation itself is validated below.
        # A search names its query and which side of the file it looks at.
        extra_fields = {"write": {"content"}, "move": {"destination"},
                        "search": {"query", "search_mode"},
                        "read_chunk": {"offset", "length"}}
        # #7603: a write may name the append spelling. It is its own boolean
        # because `mode` in this body already names the transport leg.
        optional_fields = {"write": {"append"}}
        named = payload.get("op")
        if isinstance(named, str) and named in extra_fields:
            expected = expected | extra_fields[named]
        if isinstance(named, str) and named in optional_fields:
            optional = optional_fields[named]
        else:
            optional = set()
        if named == "list":
            # The widened read-only listing carries its depth and recursive
            # flag only when the caller named them; both are re-validated
            # (type and range) below before any command is built.
            for key in ("depth", "recursive"):
                if key in payload:
                    expected = expected | {key}
    elif mode == "job_start":
        expected = {"subject_id", "run_id", "device_id", "mode", "operation", "tool_call_ref"}
    elif mode == "job_status":
        expected = {"subject_id", "run_id", "device_id", "mode", "job_id"}
    elif mode == "job_output":
        expected = {"subject_id", "run_id", "device_id", "mode", "job_id", "offset", "length"}
    elif mode == "read_output":
        expected = {"subject_id", "run_id", "device_id", "mode", "handle", "offset", "length"}
    elif mode == "search_output":
        expected = {"subject_id", "run_id", "device_id", "mode", "handle", "query"}
    elif mode == "store_output":
        expected = {"subject_id", "run_id", "device_id", "mode", "output", "source", "tool_call_ref"}
    elif mode in ("command_status", "result"):
        expected = {"subject_id", "run_id", "dispatch_id", "mode"}
    else:
        return _error(400, "claw_engine_files_invalid_body"), {}
    if not (expected <= set(payload) <= expected | optional):
        return _error(400, "claw_engine_files_invalid_body"), {}
    if not all(
        isinstance(payload.get(name), str) and 0 < len(payload[name]) <= 512
        for name in ("subject_id", "run_id")
    ):
        return _error(400, "claw_engine_files_invalid_body"), {}
    if requested_mode == "job_start":
        operation = payload.get("operation")
        if not isinstance(operation, dict) or operation.get("op") not in _PC_FILES_OPS:
            return _error(422, "oracle_mesh_file_op_invalid"), {}
        op = operation["op"]
        operation_fields = ({"op", "path"}
                            | ({"content"} if op == "write" else
                               {"old_text", "new_text", "replace_all"} if op == "edit" else
                               {"destination"} if op == "move" else set()))
        operation_optional = {"mode"} if op == "write" else set()
        if not (operation_fields <= set(operation)
                <= operation_fields | operation_optional):
            return _error(400, "claw_engine_files_invalid_body"), {}
        # The operation's own `mode` is the write spelling (overwrite/append),
        # not this body's transport leg. It must never replace the leg name,
        # and an append must reach the dispatch below as the `append` boolean:
        # dropping it here would turn a requested append into an overwrite.
        operation = dict(operation)
        write_mode = operation.pop("mode", None)
        if write_mode not in (None, "overwrite", "append"):
            return _error(422, "oracle_mesh_file_mode_invalid"), {}
        payload = {**payload, **operation}
        if write_mode == "append":
            payload["append"] = True
        mode = "dispatch"
    elif requested_mode in ("job_status", "job_output"):
        payload["dispatch_id"] = payload["job_id"]
        mode = "command_status" if requested_mode == "job_status" else "result"
    new_mode = requested_mode in {"job_start", "job_status", "job_output", "read_output", "search_output", "store_output"}
    if new_mode and scope_claim is None:
        return _error(403, "pc_scope_required"), {}
    if new_mode and (not isinstance(payload.get("device_id"), str) or not payload["device_id"]):
        return _error(422, "oracle_mesh_device_invalid"), {}
    if requested_mode in ("job_output", "read_output") and (
        type(payload.get("offset")) is not int or payload["offset"] < 0
        or type(payload.get("length")) is not int or not 0 <= payload["length"] <= 65536
    ):
        return _error(422, "pc_output_range_invalid"), {}
    selected = payload.get("device_id")
    if selected is not None and (
        not isinstance(selected, str) or not 0 < len(selected) <= 128
    ):
        return _error(422, "oracle_mesh_device_invalid"), {}
    uid, session, owner_error = await _engine_pc_files_owner(
        request, product=product, subject_id=payload["subject_id"],
    )
    if owner_error is not None:
        return owner_error, {}
    history_store = getattr(request.app.state, "history_store", None)
    if history_store is None or not callable(
        getattr(history_store, "get_claw_run", None)
    ):
        return _error(503, "oracle_mesh_unconfigured"), {}
    try:
        run_row = await history_store.get_claw_run(uid, payload["run_id"])
        if run_row is None and product == "chat" and mode == "context" and scope_claim is not None:
            from .chat_pc_drive import promote_chat_pc_stream_run
            run_row = await promote_chat_pc_stream_run(
                request, uid=uid, run_id=payload["run_id"], device_id=selected,
                action="pc_files_query",
            )
    except Exception:
        return _error(503, "oracle_mesh_run_unavailable"), {}
    if (
        not isinstance(run_row, dict)
        or run_row.get("run_id") != payload["run_id"]
        or not isinstance(run_row.get("conversation_id"), str)
        or not run_row["conversation_id"]
    ):
        return _error(404, "oracle_mesh_run_unavailable"), {}

    scope_reader = getattr(history_store, "get_pc_run_scope", None)
    try:
        saved_scope = await scope_reader(user_id=uid, run_id=payload["run_id"]) if callable(scope_reader) else None
    except Exception:
        return _error(503, "pc_scope_store_unavailable"), {}
    if saved_scope is not None and scope_claim != saved_scope:
        return _error(403, "pc_scope_required" if scope_claim is None else "pc_scope_frozen"), {}

    # The status/result legs carry only the dispatch id; adding a device hint
    # is a malformed body by contract. The dispatch itself names the PC that
    # ran the step, so use that node for the target check. Re-resolving a
    # multi-link owner without it can only answer "ambiguous" and refuse a
    # step that already ran.
    if mode in ("command_status", "result") and selected is None:
        # The private owner-scoped reader is the dispatch authority that also
        # names its PC; the public read intentionally keeps the normal row's
        # shape. Neither leg accepts a device hint from the Engine.
        reader = getattr(history_store, "get_pc_output_dispatch_for_owner", None)
        if not callable(reader):
            reader = getattr(history_store, "get_oracle_mesh_dispatch_for_owner", None)
        if callable(reader) and isinstance(payload.get("dispatch_id"), str):
            try:
                status_dispatch = await reader(
                    user_id=uid, dispatch_id=payload["dispatch_id"],
                )
            except Exception:
                status_dispatch = None
            if isinstance(status_dispatch, dict):
                hint = status_dispatch.get("node_ref") or status_dispatch.get("device_id")
                if isinstance(hint, str) and hint:
                    selected = hint

    resolved, target_error = await _engine_pc_files_target(
        request, session=session, selected_device_id=selected, user_id=uid,
    )
    if target_error is not None:
        return target_error, {}
    if resolved is None:
        # No PC for this account: tool discovery answers honestly instead of
        # failing the turn, and only a call that needs a device is refused.
        if mode == "context":
            return _response({
                "ok": True,
                "roots": [],
                "device": {"device_id": selected, "status": "not_connected",
                           "online_verified": False},
                "tools": [],
                "run_id": payload["run_id"],
            }), {}
        return _error(403, "oracle_mesh_device_unverified"), {}
    target = resolved["target"]
    roots = resolved["roots"]
    device_id = target.get("device_id") or target["node_ref"]
    return None, {
        "scope_claim": scope_claim,
        "payload": payload,
        "requested_mode": requested_mode,
        "mode": mode,
        "selected": selected,
        "uid": uid,
        "session": session,
        "history_store": history_store,
        "run_row": run_row,
        "new_mode": new_mode,
        "resolved": resolved,
        "target": target,
        "roots": roots,
        "device_id": device_id,
    }


async def oracle_mesh_engine_claw_files_call(request: Request) -> JSONResponse:
    return await _engine_pc_files_call(request, product="claw")


@chat_pc_dispatch_ttl
async def oracle_mesh_engine_chat_files_call(request: Request) -> JSONResponse:
    return await _engine_pc_files_call(request, product="chat")
