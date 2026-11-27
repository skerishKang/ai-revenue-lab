"""Oracle Mesh result receipt, persistence and original retrieval."""
from __future__ import annotations

from typing import Any
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .auth_routes import current_user_id
from .claw_local_task_result_projection import result_message_id
from .history import HistoryError, HistoryForbidden, is_multi_command_action, validate_conversation_id
from .history_append_reason import last_append_reason
from .oracle_mesh_contract import (
    _DESKTOP_SCREENSHOT_MAGIC, _DESKTOP_SCREENSHOT_MEDIA_TYPE,
    _EXECUTOR, _MAX_COMMAND_MESSAGE_PARTS,
)
from .oracle_mesh_http import _NO_STORE, _error, _ref, _response
from .oracle_mesh_log import (
    _PC_RESULT_ACTION_WORDS, _PC_RESULT_STATUS_WORDS, _pc_result_word,
    ensure_result_log_host_visible, log_pc_result_store_stage,
)
from .oracle_mesh_result_projection import (
    _command_head, _command_original_stored_content, _command_output_parts,
    _command_output_withheld_content, _command_part_budget, _command_part_messages,
    _desktop_act_content, _desktop_capture_content, _desktop_failed_content,
    _file_read_part_messages, _file_read_stored_content,
    _oracle_mesh_read_result_outcome, _oracle_mesh_read_result_verify,
)


async def _store_oracle_mesh_read_original(
    history_store: Any, *, dispatch: dict[str, Any],
    conversation_id: str, message_id: str, raw: str,
    expected_sha256: str, expected_bytes: int,
) -> None:
    """Store one verified read body through the existing command-result store.

    The raw bytes (file text or a bounded ``PADIEM_PC_FILE_ERROR`` marker) are
    keyed by the same deterministic result message id the command result mode
    already uses. No new store or DB row is introduced. The small-output method
    is preferred because the over-budget method skips short texts; both apply
    the same owner and dispatch-pin checks.
    """
    store = getattr(history_store, "store_oracle_mesh_command_result", None)
    if not callable(store):
        store = getattr(history_store, "store_oracle_mesh_original", None)
    if not callable(store):
        raise HistoryError("oracle mesh result store is unavailable")
    await store(
        user_id=dispatch["user_id"], dispatch_id=dispatch["dispatch_id"],
        conversation_id=conversation_id, message_id=message_id,
        raw=raw, expected_sha256=expected_sha256,
        expected_bytes=expected_bytes,
    )


async def oracle_mesh_read_result(request: Request) -> JSONResponse:
    """Executor submit: secret + single-use nonce, verified, appended once."""
    ensure_result_log_host_visible()
    resp, bundle = await _oracle_mesh_read_result_verify(request)
    if resp is not None:
        return resp
    wire = bundle["wire"]
    result_blob_raw = bundle["result_blob_raw"]
    result_log = bundle["result_log"]
    result_run_hash = bundle["result_run_hash"]
    result_dispatch_id = bundle["result_dispatch_id"]
    history_store = bundle["history_store"]
    dispatch = bundle["dispatch"]
    claim = bundle["claim"]

    resp, bundle = await _oracle_mesh_read_result_outcome(
        dispatch, result_blob_raw, wire,
    )
    if resp is not None:
        return resp
    outcome = bundle["outcome"]
    content = bundle["content"]
    summary = bundle["summary"]
    status = bundle["status"]
    command_output = bundle["command_output"]
    read_output = bundle["read_output"]
    read_stored_output = bundle["read_stored_output"]
    desktop_note = bundle["desktop_note"]
    desktop_blob = bundle["desktop_blob"]
    desktop_op = bundle["desktop_op"]
    desktop_arg = bundle["desktop_arg"]
    result_digest = bundle["result_digest"]
    result_size = bundle["result_size"]
    # Every stored message is now bounded by the splitter, so the former
    # 1 000-character refusal has no case left to serve.

    # Pin the first accepted result. A resend after a transient store failure
    # must be the identical bytes: the executor holds them and never re-reads
    # the PC file, and a differing resend is refused rather than appended.
    try:
        try:
            same_result = await history_store.record_oracle_mesh_first_result(
                dispatch_id=wire["dispatch_id"],
                content_sha256=result_digest,
                content_bytes=result_size,
                termination=wire.get("termination") if isinstance(wire.get("termination"), str) else None,
                exit_code=wire.get("exit_code"),
            )
        except TypeError:
            same_result = await history_store.record_oracle_mesh_first_result(
                dispatch_id=wire["dispatch_id"],
                content_sha256=result_digest,
                content_bytes=result_size,
            )
    except Exception:
        # A pin failure must stay retryable: park the received row so the
        # identical resend is accepted as claim="retry" instead of dying
        # on 409. Pin comparison and idempotent append still prevent any
        # second delivery.
        try:
            await history_store.mark_oracle_mesh_store_failed(
                dispatch_id=wire["dispatch_id"],
            )
        except Exception:
            pass
        return _error(503, "oracle_mesh_dispatch_unavailable")
    if same_result is not True:
        # Park the claim again: a rejected resend must not burn the retry the
        # executor still legitimately owns for its identical bytes.
        try:
            await history_store.mark_oracle_mesh_store_failed(
                dispatch_id=wire["dispatch_id"],
            )
        except Exception:
            pass
        return _error(409, "oracle_mesh_result_fingerprint_mismatch")

    run_row = None
    try:
        run_row = await history_store.get_claw_run(
            dispatch["user_id"], dispatch["run_id"],
        )
    except Exception:
        run_row = None
    conversation_id = (
        validate_conversation_id((run_row or {}).get("conversation_id"))
        if isinstance(run_row, dict) else None
    )
    if not conversation_id:
        try:
            await history_store.finish_oracle_mesh_dispatch(
                dispatch_id=wire["dispatch_id"], outcome="failed",
            )
        except Exception:
            pass
        return _error(404, "oracle_mesh_run_unavailable")

    base_message_id = result_message_id(
        conversation_id=conversation_id,
        command_id=dispatch["command_id"],
        revision_ref=dispatch["revision_ref"],
    )
    from .chat_pc_session import project_history_result, is_session_dispatch
    session_messages = project_history_result(run_row, dispatch, command_output)
    if read_stored_output is not None:
        # #5015: the Engine read lane retrieves the exact verified body from
        # this existing store. Storing before the conversation projection
        # keeps a store failure retryable with the same bytes; the executor
        # is never asked to read the PC file again.
        try:
            await _store_oracle_mesh_read_original(
                history_store, dispatch=dispatch,
                conversation_id=conversation_id, message_id=base_message_id,
                raw=read_stored_output,
                expected_sha256=result_digest,
                expected_bytes=result_size,
            )
        except HistoryForbidden:
            try:
                await history_store.finish_oracle_mesh_dispatch(
                    dispatch_id=wire["dispatch_id"], outcome="failed",
                )
            except Exception:
                pass
            return _error(403, "oracle_mesh_conversation_forbidden")
        except Exception:
            try:
                await history_store.mark_oracle_mesh_store_failed(
                    dispatch_id=wire["dispatch_id"],
                )
            except Exception:
                pass
            return _error(503, "oracle_mesh_original_unavailable")
    resp, bundle = await _oracle_mesh_read_result_store(
        base_message_id=base_message_id,
        command_output=command_output,
        content=content,
        conversation_id=conversation_id,
        desktop_arg=desktop_arg,
        desktop_blob=desktop_blob,
        desktop_note=desktop_note,
        desktop_op=desktop_op,
        dispatch=dispatch,
        history_store=history_store,
        is_session_dispatch=is_session_dispatch,
        read_output=read_output,
        result_digest=result_digest,
        result_size=result_size,
        summary=summary,
        wire=wire,
    )
    if resp is not None:
        return resp
    messages = bundle["messages"]
    if session_messages is not None:
        messages = session_messages
    appended = False
    # #5015: a run that may hold more than one PC tool call stores each
    # command's own result beside the others and never seals the run row, so
    # one command's completion is never read as the whole work's completion.
    command_scope = None
    if is_multi_command_action((run_row or {}).get("action")):
        command_scope = dispatch.get("command_id")
    # #6460 step 3: a model-driven desktop loop stages one dispatch per step.
    # Each step's message is evidence of that step alone, so it never writes
    # the run's terminal result; the verified final answer owns that.
    step_message_only = (
        command_scope is None
        and dispatch.get("kind") == "desktop"
        and isinstance(dispatch.get("tool_call_ref"), str)
        and bool(dispatch["tool_call_ref"])
        and len(messages) == 1
    )
    append_step = getattr(history_store, "append_step_result_message", None)
    if step_message_only and not callable(append_step):
        step_message_only = False
    try:
        for index, part in enumerate(messages):
            message_id = base_message_id if len(messages) == 1 else (
                base_message_id + "_p" + str(index)
            )
            if step_message_only:
                appended = await append_step(
                    user_id=dispatch["user_id"],
                    run_id=dispatch["run_id"],
                    message_id=message_id,
                    content=part,
                ) or appended
                continue
            appended = await history_store.append_local_task_result(
                user_id=dispatch["user_id"],
                run_id=dispatch["run_id"],
                message_id=message_id,
                summary=summary,
                content=part,
                status=("failed" if command_scope is not None and outcome == "failed" else status),
                # A terminal result is the only caller that opts out of the
                # shared edge trim; every other message keeps today's behavior.
                preserve_edges=(dispatch.get("kind") == "command"),
                command_scope=command_scope,
            ) or appended
        if command_scope is not None and outcome == "failed":
            # Seal before acknowledging the queue result: an unavailable Chat
            # store leaves the dispatch retryable with the same pinned result.
            await history_store.seal_run_terminal(
                user_id=dispatch["user_id"], run_id=dispatch["run_id"],
                summary="pc_read_failed", status="failed",
            )
    except HistoryForbidden:
        # Ownership refusal is final: retrying cannot change it.
        try:
            await history_store.finish_oracle_mesh_dispatch(
                dispatch_id=wire["dispatch_id"], outcome="failed",
            )
        except Exception:
            pass
        return _error(403, "oracle_mesh_conversation_forbidden")
    except Exception:
        # Transient conversation-store failure. The verified result is parked
        # (claim and expiry intact) so the executor can resend the SAME result
        # — the PC file is not read again, and the stable message id keeps the
        # eventual append exactly-once.
        try:
            await history_store.mark_oracle_mesh_store_failed(
                dispatch_id=wire["dispatch_id"],
            )
        except Exception:
            pass
        return _error(503, "oracle_mesh_append_unavailable")
    store_stage = "stored" if appended else "not_appended"
    # #7841 instrumentation: a refused append names the guard that refused it
    # and the run row it saw before the write. Values only; the stored line is
    # unchanged, and nothing here changes a return value or a write.
    log_pc_result_store_stage(
        result_log, stage=store_stage, run_hash=result_run_hash,
        dispatch_id=result_dispatch_id,
        reason=last_append_reason() if not appended else None,
        run_action=_pc_result_word(
            (run_row or {}).get("action"), _PC_RESULT_ACTION_WORDS,
        ),
        run_status_before=_pc_result_word(
            (run_row or {}).get("status"), _PC_RESULT_STATUS_WORDS,
        ),
        scoped=command_scope is not None,
    )
    try:
        finished = await history_store.finish_oracle_mesh_dispatch(
            dispatch_id=wire["dispatch_id"], outcome=outcome,
        )
    except Exception:
        result_log.info("pc_result stage=queue_finish_error run_hash=%s dispatch_id=%s", result_run_hash, result_dispatch_id)
    else:
        stage = "queue_finished" if finished else "queue_not_finished"
        result_log.info("pc_result stage=%s run_hash=%s dispatch_id=%s", stage, result_run_hash, result_dispatch_id)
    return _response({
        "ok": True,
        "runId": dispatch["run_id"],
        "commandId": dispatch["command_id"],
        "appended": bool(appended),
        "status": status,
        "claim": claim,
        "executor": _EXECUTOR,
        "brokerAcknowledged": False,
    })


async def _oracle_mesh_read_result_store(
    *, base_message_id, command_output, content, conversation_id,
    desktop_arg,
    desktop_blob,
    desktop_note,
    desktop_op,
    dispatch,
    history_store,
    is_session_dispatch,
    read_output,
    result_digest,
    result_size,
    summary,
    wire,
) -> tuple[JSONResponse | None, dict[str, object]]:
    """메시지 조립·원본 저장 구간 (본문 글자 그대로)."""
    if command_output is not None:
        # #5015: the Engine model lane re-feeds exact bytes, including small
        # drive inventories that never needed the over-budget original store.
        # Errors are never promoted by storing: this only preserves bytes, the
        # outcome below stays as verified. Withheld bodies (empty) are owned
        # by the non-delivery notice and store nothing, so no result is lost.
        # no_reply: the console's bounded message (for example a client-side
        # refusal) is the only account of why no exit code exists; keep it as
        # the original so the MCP output read can show it instead of a generic
        # "output not verified".
        if command_output and (is_session_dispatch(dispatch) or (
                len(command_output) <= 65536 and wire["termination"] in ("exited", "no_exit_code", "no_reply"))):
            try:
                store_small = getattr(history_store, "store_oracle_mesh_command_result", None)
                if not callable(store_small):
                    store_small = history_store.store_oracle_mesh_original
                await store_small(
                    user_id=dispatch["user_id"], dispatch_id=wire["dispatch_id"],
                    conversation_id=conversation_id, message_id=base_message_id,
                    raw=command_output, expected_sha256=result_digest,
                    expected_bytes=result_size,
                )
            except HistoryForbidden:
                try:
                    await history_store.finish_oracle_mesh_dispatch(
                        dispatch_id=wire["dispatch_id"], outcome="failed",
                    )
                except Exception:
                    pass
                return _error(403, "oracle_mesh_conversation_forbidden"), {}
            except Exception:
                try:
                    await history_store.mark_oracle_mesh_store_failed(
                        dispatch_id=wire["dispatch_id"],
                    )
                except Exception:
                    pass
                return _error(503, "oracle_mesh_original_unavailable"), {}
        if wire["termination"] == "output_too_large" and not command_output:
            # The executor withheld the body at the wire envelope, so there
            # is no original to store and nothing to split: the observed
            # exit code is delivered with an explicit non-delivery notice.
            messages = [_command_output_withheld_content(dispatch, wire)]
        else:
            head = _command_head(dispatch, wire)
            output_parts = _command_output_parts(
                command_output, _command_part_budget(head),
            )
            if len(output_parts) > _MAX_COMMAND_MESSAGE_PARTS:
                # Over the per-run message-row guard: the verified original is
                # kept in the private store first. The conversation carries a
                # head preview plus the owner-scoped retrieval reference;
                # "stored" is claimed only after the put succeeds, never before.
                try:
                    await history_store.store_oracle_mesh_original(
                        user_id=dispatch["user_id"],
                        dispatch_id=wire["dispatch_id"],
                        conversation_id=conversation_id,
                        message_id=base_message_id,
                        raw=command_output,
                        expected_sha256=result_digest,
                        expected_bytes=result_size,
                    )
                except HistoryForbidden:
                    # Ownership refusal is final: retrying cannot change it.
                    try:
                        await history_store.finish_oracle_mesh_dispatch(
                            dispatch_id=wire["dispatch_id"], outcome="failed",
                        )
                    except Exception:
                        pass
                    return _error(403, "oracle_mesh_conversation_forbidden"), {}
                except Exception:
                    # Storage failed: park the row so the executor resends
                    # the SAME bytes. No completion is reported, and the PC
                    # command is never re-run for a store failure.
                    try:
                        await history_store.mark_oracle_mesh_store_failed(
                            dispatch_id=wire["dispatch_id"],
                        )
                    except Exception:
                        pass
                    return _error(503, "oracle_mesh_original_unavailable"), {}
                messages = [_command_original_stored_content(
                    dispatch, wire, command_output,
                )]
            else:
                messages = _command_part_messages(head, output_parts)
    elif read_output is not None:
        head = ["PC 파일 읽기 결과"]
        output_parts = _command_output_parts(
            read_output, _command_part_budget(head),
        )
        if len(output_parts) > _MAX_COMMAND_MESSAGE_PARTS:
            # The read lane carries the same guard as the command lane. The
            # verified file body is stored whole first, so a large document
            # becomes a preview plus a retrieval reference instead of either
            # hundreds of messages or a silent refusal.
            try:
                await history_store.store_oracle_mesh_original(
                    user_id=dispatch["user_id"],
                    dispatch_id=wire["dispatch_id"],
                    conversation_id=conversation_id,
                    message_id=base_message_id,
                    raw=read_output,
                    expected_sha256=result_digest,
                    expected_bytes=result_size,
                )
            except HistoryForbidden:
                try:
                    await history_store.finish_oracle_mesh_dispatch(
                        dispatch_id=wire["dispatch_id"], outcome="failed",
                    )
                except Exception:
                    pass
                return _error(403, "oracle_mesh_conversation_forbidden"), {}
            except Exception:
                try:
                    await history_store.mark_oracle_mesh_store_failed(
                        dispatch_id=wire["dispatch_id"],
                    )
                except Exception:
                    pass
                return _error(503, "oracle_mesh_original_unavailable"), {}
            messages = [_file_read_stored_content(dispatch, wire, read_output)]
        else:
            messages = _file_read_part_messages(output_parts)
    elif desktop_note is not None and desktop_op is not None:
        # #4139 desktop lane. A capture stores its screenshot bytes first:
        # "stored" is claimed only after the put succeeds, never before. An
        # input or failed turn carries its note directly; notes are short by
        # construction (executor observations, never file bodies).
        if desktop_blob is not None:
            if not callable(getattr(
                history_store, "store_oracle_mesh_original_bytes", None
            )):
                return _error(503, "oracle_mesh_unconfigured"), {}
            try:
                await history_store.store_oracle_mesh_original_bytes(
                    user_id=dispatch["user_id"],
                    dispatch_id=wire["dispatch_id"],
                    conversation_id=conversation_id,
                    message_id=base_message_id,
                    raw=desktop_blob,
                    media_type=_DESKTOP_SCREENSHOT_MEDIA_TYPE,
                    expected_sha256=result_digest,
                    expected_bytes=result_size,
                )
            except HistoryForbidden:
                try:
                    await history_store.finish_oracle_mesh_dispatch(
                        dispatch_id=wire["dispatch_id"], outcome="failed",
                    )
                except Exception:
                    pass
                return _error(403, "oracle_mesh_conversation_forbidden"), {}
            except Exception:
                try:
                    await history_store.mark_oracle_mesh_store_failed(
                        dispatch_id=wire["dispatch_id"],
                    )
                except Exception:
                    pass
                return _error(503, "oracle_mesh_original_unavailable"), {}
            messages = [_desktop_capture_content(
                dispatch, wire, desktop_op, desktop_arg,
                desktop_note, result_digest,
            )]
        elif summary in ("acted",):
            messages = [_desktop_act_content(
                dispatch, wire, desktop_op, desktop_arg, desktop_note,
            )]
        else:
            messages = [_desktop_failed_content(
                dispatch, wire, desktop_op, desktop_arg, desktop_note,
            )]
    else:
        messages = [content]
    return None, {"messages": messages}


async def oracle_mesh_read_original(request: Request) -> Response:
    """Owner-scoped read of one stored over-budget command original.

    Only the dispatch id comes from the browser. The dispatch row (owner,
    run, correlation), the originating conversation and the deterministic
    result id are all re-derived server-side, so no browser-chosen object
    key or foreign-account result is addressable. Unknown ids, foreign
    accounts and missing objects all answer 404 without disclosing which
    part failed; a stored object that disagrees with the dispatch pin is a
    503, never served bytes.
    """
    uid = current_user_id(request)
    if not isinstance(uid, str) or not uid:
        return _error(401, "canonical_session_required")
    params = getattr(request, "path_params", None) or {}
    dispatch_id = _ref(params.get("dispatch_id"), 128)
    if dispatch_id is None:
        return _error(404, "oracle_mesh_original_unavailable")
    history_store = getattr(request.app.state, "history_store", None)
    for method in ("get_oracle_mesh_dispatch_for_owner", "get_claw_run",
                   "read_oracle_mesh_original"):
        if not callable(getattr(history_store, method, None)):
            return _error(503, "oracle_mesh_unconfigured")
    try:
        dispatch = await history_store.get_oracle_mesh_dispatch_for_owner(
            user_id=uid, dispatch_id=dispatch_id,
        )
    except Exception:
        return _error(503, "oracle_mesh_unconfigured")
    if not isinstance(dispatch, dict):
        return _error(404, "oracle_mesh_original_unavailable")
    try:
        run_row = await history_store.get_claw_run(uid, dispatch.get("run_id"))
    except Exception:
        run_row = None
    conversation_id = (
        validate_conversation_id((run_row or {}).get("conversation_id"))
        if isinstance(run_row, dict) else None
    )
    if not conversation_id:
        return _error(404, "oracle_mesh_original_unavailable")
    try:
        message_id = result_message_id(
            conversation_id=conversation_id,
            command_id=dispatch.get("command_id"),
            revision_ref=dispatch.get("revision_ref"),
        )
    except Exception:
        return _error(404, "oracle_mesh_original_unavailable")
    try:
        stored = await history_store.read_oracle_mesh_original(
            user_id=uid, dispatch_id=dispatch_id,
            conversation_id=conversation_id, message_id=message_id,
        )
    except HistoryError:
        return _error(503, "oracle_mesh_original_unavailable")
    except Exception:
        return _error(503, "oracle_mesh_unconfigured")
    if stored is None:
        return _error(404, "oracle_mesh_original_unavailable")
    payload, pinned_sha = stored
    if dispatch.get("kind") == "desktop":
        # A desktop capture serves its screenshot bytes. The pin already
        # binds these exact bytes; the magic is rechecked so a non-image can
        # never leave through the image path.
        if not payload.startswith(_DESKTOP_SCREENSHOT_MAGIC):
            return _error(503, "oracle_mesh_original_unavailable")
        return Response(
            payload, media_type="image/jpeg",
            headers={**_NO_STORE, "X-Oracle-Mesh-Content-SHA256": pinned_sha},
        )
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return _error(503, "oracle_mesh_original_unavailable")
    return Response(
        text, media_type="text/plain; charset=utf-8",
        headers={**_NO_STORE, "X-Oracle-Mesh-Content-SHA256": pinned_sha},
    )
