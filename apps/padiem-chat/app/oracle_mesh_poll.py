"""Oracle Mesh polling, cancellation, busy and lane state."""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from .oracle_mesh_contract import ORACLE_MESH_READ_CANCEL_POLL_PATH, _MAX_FILE_TEXT_BYTES
from .oracle_mesh_pc_paths import PC_FILES_READ_MAX_BYTES, _PC_FILES_READ_ROOT_REF, _PC_FILES_READ_TOOL_MARKER
from .oracle_mesh_http import (
    _channel_proof, _channel_source, _error, _invalid_body, _ref, _response, _watch_read_proof,
)
from .oracle_mesh_desktop_ops import _desktop_text_ref
from .oracle_mesh_presence import _read_presence, _record_mesh_presence


def _oracle_mesh_poll_max_bytes(dispatch: dict[str, Any]) -> int | None:
    """Server-computed read bound for one dispatch row.

    #5015: the Chat PC-files read is a 20 MB call; every other read consumer
    keeps the shared 6 MB envelope. The decision is made here from the row the
    server staged (its stable per-call reference), never from the model, the
    executor or any request value.
    """
    if (dispatch.get("kind") or "read") == "read":
        # The server-owned root marker is authoritative: the caller-supplied
        # tool_call_ref can never decide the bound. The per-call marker is a
        # second, same-lane hint for rows that carry it.
        if dispatch.get("root_ref") == _PC_FILES_READ_ROOT_REF:
            return PC_FILES_READ_MAX_BYTES
        tool_request_ref = dispatch.get("tool_request_ref")
        if (
            isinstance(tool_request_ref, str)
            and _PC_FILES_READ_TOOL_MARKER in tool_request_ref
        ):
            return PC_FILES_READ_MAX_BYTES
    return _MAX_FILE_TEXT_BYTES


def _oracle_mesh_poll_granted_root(dispatch: dict[str, Any]) -> str | None:
    """The granted root for one PC-files read dispatch, named once on poll.

    #5994 D3 후속: the executor's pre-download reparse walk needs the real
    root the read grant admitted, and the staged row already holds it —
    ``file_path`` is staged as ``root + "/" + path_relative`` for this lane,
    so the root is what survives stripping the staged relative path. The
    decision is made here from the row the server staged, never from the
    model, the executor or any request value. A row that does not
    reconstruct cleanly names no root, which keeps older executors and
    every other lane byte-for-byte unchanged.
    """
    if (dispatch.get("kind") or "read") != "read":
        return None
    if dispatch.get("root_ref") != _PC_FILES_READ_ROOT_REF:
        return None
    file_path = dispatch.get("file_path")
    relative = dispatch.get("path_relative")
    if (
        not isinstance(file_path, str) or not file_path
        or not isinstance(relative, str)
    ):
        return None
    rel = relative.strip("/")
    if not rel:
        return file_path.rstrip("/") or None
    marker = "/" + rel
    if not file_path.lower().endswith(marker.lower()):
        return None
    return file_path[:-len(marker)] or None


def _oracle_mesh_poll_share_roots(dispatch: dict[str, Any]) -> list[str] | None:
    """#8037: the share addresses this command was staged against, named on poll.

    The staging lane resolved them from the owner's approved roots; the claim
    response echoes that server decision so the executor bounds exactly the
    shares the server admitted. A row without the declaration keeps the exact
    older response and the executor runs it with no share deadline.
    """
    if (dispatch.get("kind") or "read") != "command":
        return None
    roots = dispatch.get("share_roots")
    if not isinstance(roots, list) or not roots:
        return None
    if any(
        not isinstance(item, str) or not item or len(item) > 32000
        or any(ord(ch) < 32 for ch in item)
        for item in roots
    ):
        return None
    return list(roots)


async def oracle_mesh_read_poll(request: Request) -> JSONResponse:
    """Executor poll: channel-secret proof, one claimed dispatch, one nonce."""
    mesh_source = _channel_source(request)
    if mesh_source is None:
        return _error(503, "oracle_mesh_unconfigured")
    if not _channel_proof(request, mesh_source):
        return _error(403, "oracle_mesh_channel_rejected")
    history_store = getattr(request.app.state, "history_store", None)
    if not callable(getattr(history_store, "oldest_pending_oracle_mesh_dispatch", None)):
        return _error(503, "oracle_mesh_unconfigured")
    if not callable(getattr(history_store, "claim_oracle_mesh_dispatch", None)):
        return _error(503, "oracle_mesh_unconfigured")
    # #5553: an optional presence beat is recorded before the claim. It can
    # never change the claim, the response or the authorization, and every
    # failure is log-only so an older executor keeps its exact contract.
    try:
        presence = await _read_presence(request)
        if presence:
            await _record_mesh_presence(request, mesh_source, presence)
    except Exception:
        logging.getLogger(__name__).warning("oracle_mesh_presence=ignored")
    # Existing authenticated HTTPS channel, not a second broker. Optional
    # bounded wait is only enabled by the Oracle executor; legacy consumers
    # retain their immediate response. D1 remains the durable source of truth.
    import asyncio
    import time
    wait_header = request.headers.get("x-oracle-mesh-wait", "")
    # #5479: a long wait held a Worker request open for 20 seconds, re-reading
    # D1 every couple of seconds, so concurrent polls piled onto one event loop.
    # The executor already re-requests as soon as an empty answer comes back, so
    # the ceiling is now five seconds and a legacy "20" is capped to it too.
    wait_seconds = 5 if wait_header in ("5", "20") else 0
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            pending = await history_store.oldest_pending_oracle_mesh_dispatch()
        except Exception:
            return _error(503, "oracle_mesh_dispatch_unavailable")
        if pending is not None or time.monotonic() >= deadline:
            break
        await asyncio.sleep(min(2, max(0.01, deadline - time.monotonic())))
    if pending is None:
        return _response({"ok": True, "dispatch": None})
    # #7076d: the execution mode is the one fact this response may never guess.
    # A store that cannot state the mode of a row leaves the executor with no
    # basis to call it anything but its default, and that default is the SYSTEM
    # lane — which is exactly how a `mode=user` request ran as `nt authority\system`.
    # Such a row is therefore not handed out at all: no claim, no execution,
    # until a path that carries `user_mode` answers. The poll is fail-closed here
    # rather than fail-open in the executor, because only the row knows the mode.
    raw_user_mode = pending.get("user_mode")
    if isinstance(raw_user_mode, bool):
        user_mode = raw_user_mode
    elif type(raw_user_mode) is int and raw_user_mode in (0, 1):
        user_mode = bool(raw_user_mode)
    else:
        return _error(503, "oracle_mesh_dispatch_mode_unavailable")
    if user_mode and (pending.get("kind") or "read") != "command":
        # Only a command dispatch can be delegated to the PC's user session;
        # a row that asks for it on any other lane is one this lane cannot run
        # as asked, so it is refused instead of being run as SYSTEM.
        return _error(503, "oracle_mesh_dispatch_mode_unavailable")
    nonce = secrets.token_hex(16)
    nonce_sha256 = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
    try:
        claimed = await history_store.claim_oracle_mesh_dispatch(
            dispatch_id=pending["dispatch_id"], nonce_sha256=nonce_sha256,
        )
    except Exception:
        return _error(503, "oracle_mesh_dispatch_unavailable")
    if claimed is not True:
        return _response({"ok": True, "dispatch": None})
    # #6460 step 2: a typed value is taken exactly once, for this claim only.
    # A missing value is not an error here - the executor refuses the op itself.
    desktop_text = None
    text_ref = _desktop_text_ref(pending.get("command_text"))
    if text_ref is not None:
        text_store = getattr(request.app.state, "desktop_text_store", None)
        taker = getattr(text_store, "take_desktop_text", None)
        if callable(taker):
            try:
                desktop_text = await taker(ref=text_ref)
            except Exception:
                desktop_text = None
    session_input_text = None
    from .mcp_gateway_session import pc_session_enabled, session_input_ref
    session_ref = session_input_ref(pending.get("command_text"))
    if (pc_session_enabled(request) and user_mode and pending.get("kind") == "command"
            and pending.get("background") is not True and session_ref is not None):
        taker = getattr(getattr(request.app.state, "desktop_text_store", None), "take_desktop_text", None)
        if callable(taker):
            try:
                session_input_text = await taker(ref=session_ref)
            except Exception:
                session_input_text = None
    granted_root = _oracle_mesh_poll_granted_root(pending)
    share_roots = _oracle_mesh_poll_share_roots(pending)
    # #7215: hand the user-mode client a per-dispatch cancel token and the public URL
    # to poll it at, so a stop reaches the command after it has left the queue. Only
    # when a public base is configured; a missing base keeps the exact older response
    # and the client simply never self-cancels (the backstop still bounds it).
    cancel_fields: dict[str, Any] = {}
    if user_mode:
        public_base = getattr(
            getattr(request.app.state, "settings", None), "public_base_url", "") or ""
        if isinstance(public_base, str) and public_base:
            cancel_fields = {
                "cancel_poll_url": public_base.rstrip("/") + ORACLE_MESH_READ_CANCEL_POLL_PATH,
                "cancel_token": mesh_source.cancel_check_token(pending["dispatch_id"]),
            }
    return _response({
        "ok": True,
        "dispatch": {
            "dispatch_id": pending["dispatch_id"],
            "nonce": nonce,
            "expires_at": pending["expires_at"],
            "node_ref": pending["node_ref"],
            "file_path": pending["file_path"],
            "account_ref": pending["account_ref"],
            "device_id": pending["device_id"],
            "binding_ref": pending["binding_ref"],
            "root_ref": pending["root_ref"],
            "path_relative": pending["path_relative"],
            "command_id": pending["command_id"],
            "run_id": pending["run_id"],
            "tool_request_ref": pending["tool_request_ref"],
            "request_id": pending["request_id"],
            "revision_ref": pending["revision_ref"],
            "evidence_ref": pending["evidence_ref"],
            "request_fingerprint": pending["request_fingerprint"],
            "kind": pending.get("kind") or "read",
            "command_text": pending.get("command_text"),
            **({"desktop_text": desktop_text} if desktop_text is not None else {}),
            **({"session_input_text": session_input_text} if session_input_text is not None else {}),
            "max_bytes": _oracle_mesh_poll_max_bytes(pending),
            **({"granted_root": granted_root} if granted_root else {}),
            **({"share_roots": share_roots} if share_roots else {}),
            **({"background": True, "owner_ref": pending["user_id"]}
               if pending.get("background") is True else {}),
            "user_mode": user_mode,
            **cancel_fields,
        },
    })


async def oracle_mesh_read_cancel_check(request: Request) -> JSONResponse:
    """Executor read of one owner's stop: is the command I am running cancelled?

    The same deployment channel secret as poll and submit, one dispatch id in and
    one boolean out. Nothing is claimed and nothing is written, so an executor may
    ask as often as it likes while a PC works - which is what makes an owner's
    ``그만`` reach a command that has already left the queue. #5995 removed the
    client-side deadline, so a command that never answers would otherwise hold that
    PC - and every operation queued behind it - open indefinitely.

    Anything unreadable answers ``cancelled: false``. A transport or store problem
    is not an owner's stop, and the one thing this must never do is end a real
    command on a real PC because a read failed.
    """
    mesh_source = _channel_source(request)
    if mesh_source is None:
        return _error(503, "oracle_mesh_unconfigured")
    if not _channel_proof(request, mesh_source):
        return _error(403, "oracle_mesh_channel_rejected")
    try:
        body = json.loads((await request.body()).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return _invalid_body("cancel_check", "json_decode")
    if not isinstance(body, dict):
        return _invalid_body("cancel_check", "body_shape")
    dispatch_id = _ref(body.get("dispatch_id"), 128)
    if dispatch_id is None:
        return _invalid_body("cancel_check", "dispatch_id")
    history_store = getattr(request.app.state, "history_store", None)
    reader = getattr(history_store, "oracle_mesh_dispatch_cancellation", None)
    if not callable(reader):
        return _error(503, "oracle_mesh_unconfigured")
    try:
        cancelled = await reader(dispatch_id=dispatch_id)
    except Exception:
        return _response({"ok": True, "cancelled": False})
    return _response({"ok": True, "cancelled": cancelled is True})


async def oracle_mesh_read_cancel_poll(request: Request) -> JSONResponse:
    """PUBLIC per-dispatch-token read of one dispatch's stop flag (#7215).

    The user-mode PC client (SYSTEM) carries a per-dispatch token — never the channel
    secret — and asks every few seconds only whether THIS dispatch is cancelled. It is
    the one path that reaches a stop to a user-mode command after it has left the
    queue: the PC's MeshAgent console lane echoes input instead of running it, so the
    executor's ``taskkill`` never fires (R4 #7188 wires the process lane). Read-only;
    nothing is claimed or written.

    The token is the whole authority. A request whose token is not this dispatch's own
    answers 404 with a fixed body, so a caller without it learns nothing — not even
    whether the dispatch exists. An unreadable store answers ``cancelled: false``
    (never end a real command on a read failure), exactly like the executor leg.
    """
    mesh_source = _channel_source(request)
    if mesh_source is None:
        return _error(503, "oracle_mesh_unconfigured")
    try:
        body = json.loads((await request.body()).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return _error(404, "not_found")
    if not isinstance(body, dict):
        return _error(404, "not_found")
    dispatch_id = _ref(body.get("dispatch_id"), 128)
    token = body.get("token")
    if dispatch_id is None or not isinstance(token, str):
        return _error(404, "not_found")
    if not mesh_source.cancel_check_token_matches(dispatch_id, token):
        return _error(404, "not_found")
    history_store = getattr(request.app.state, "history_store", None)
    reader = getattr(history_store, "oracle_mesh_dispatch_cancellation", None)
    if not callable(reader):
        return _response({"ok": True, "cancelled": False})
    try:
        cancelled = await reader(dispatch_id=dispatch_id)
    except Exception:
        return _response({"ok": True, "cancelled": False})
    return _response({"ok": True, "cancelled": cancelled is True})


async def oracle_mesh_read_busy_check(request: Request) -> JSONResponse:
    """Executor read of one PC's live claims: is anything working there right now?

    #6106 clears a console line the agent is holding for nothing, and the only
    thing that proves "for nothing" across two executor hosts is this row set: the
    failover partner (#5462) can hold a claim on the same PC during a handover, and
    ending its running command would cut a real job short, which the owner rule
    forbids. The claim is read from the lease's own columns, never from text.

    The same deployment channel secret as poll, submit and cancel-check, and the
    same ownership boundary: the caller names only a node reference and the dispatch
    id it already holds, and it may not address another account's work by anything
    else. One read, nothing claimed, nothing written.

    Anything this route cannot prove answers ``working: true``. That is the
    opposite default from cancel-check, for the same reason read the other way: an
    unreadable answer must never be what ends a command on a customer machine. The
    cost of the safe reading is one more minute of a wedged line, and the line is
    retried on the next command anyway.
    """
    mesh_source = _channel_source(request)
    if mesh_source is None:
        return _error(503, "oracle_mesh_unconfigured")
    if not _channel_proof(request, mesh_source):
        return _error(403, "oracle_mesh_channel_rejected")
    try:
        body = json.loads((await request.body()).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return _invalid_body("busy_check", "json_decode")
    if not isinstance(body, dict):
        return _invalid_body("busy_check", "body_shape")
    node_ref = _ref(body.get("node_ref"), 256)
    if node_ref is None:
        return _invalid_body("busy_check", "node_ref")
    dispatch_id = body.get("dispatch_id")
    if dispatch_id is None:
        dispatch_id = ""
    elif not isinstance(dispatch_id, str) or len(dispatch_id) > 128:
        return _invalid_body("busy_check", "dispatch_id")
    history_store = getattr(request.app.state, "history_store", None)
    reader = getattr(history_store, "oracle_mesh_node_live_claims", None)
    if not callable(reader):
        return _error(503, "oracle_mesh_unconfigured")
    try:
        live = await reader(node_ref=node_ref, except_dispatch_id=dispatch_id)
    except Exception:
        return _response({"ok": True, "working": True, "live_claims": 1})
    return _response({"ok": True, "working": live > 0, "live_claims": live})


async def oracle_mesh_read_lane_status(request: Request) -> JSONResponse:
    """Executor-side read of the lane's own state, for whoever watches the connector.

    #82 standard 4 asks that a stop be known within ten minutes. Nothing answered
    that on 2026-10-29: the canary was silent and the executor's own counters lived
    only in its process. This route is the part of that state that is already in the
    lane's tables — work waiting for a claim, work under a live claim, and per PC how
    long its oldest unanswered dispatch has been waiting — plus the presence beat the
    poll already writes, which is the only real evidence of "the executor was alive
    at this instant".

    Every number comes from the lane's own columns. Nothing is counted by matching
    text in a log, a transcript or a name, and no caller-supplied string reaches a
    query as anything but a bound value.

    A store that will not answer is a 503, not a zero: a monitor reading "nothing is
    waiting" from a failed read would call a stalled lane healthy.
    """
    mesh_source = _channel_source(request)
    if mesh_source is None:
        return _error(503, "oracle_mesh_unconfigured")
    # The read-only proof: the watch secret opens this leg and this leg only.
    if not _watch_read_proof(request, mesh_source):
        return _error(403, "oracle_mesh_channel_rejected")
    try:
        body = json.loads((await request.body()).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        body = {}
    device_ids: list[str] = []
    if body:
        if not isinstance(body, dict):
            return _invalid_body("lane_status", "body_shape")
        wanted = body.get("device_ids")
        if wanted is None:
            wanted = []
        if not isinstance(wanted, list):
            return _invalid_body("lane_status", "device_ids_shape")
        for wanted_id in wanted:
            bounded = _ref(wanted_id, 128)
            if bounded is None:
                return _invalid_body("lane_status", "device_id")
            device_ids.append(bounded)
    history_store = getattr(request.app.state, "history_store", None)
    reader = getattr(history_store, "oracle_mesh_lane_status", None)
    if not callable(reader):
        return _error(503, "oracle_mesh_unconfigured")
    try:
        lane = await reader()
    except Exception:
        return _error(503, "oracle_mesh_lane_unavailable")
    if not isinstance(lane, dict):
        return _error(503, "oracle_mesh_lane_unavailable")
    presence_store = getattr(request.app.state, "mesh_device_presence_store", None)
    beats: list[dict[str, Any]] = []
    loader = getattr(presence_store, "load", None)
    if callable(loader):
        for device_id in device_ids:
            try:
                row = await loader(device_id)
            except Exception:
                row = None
            beats.append({
                "device_id": device_id,
                "connected": bool(row.get("connected")) if isinstance(row, dict) else None,
                "received_at": row.get("received_at") if isinstance(row, dict) else None,
                "seen": isinstance(row, dict),
            })
    payload: dict[str, Any] = {"ok": True}
    payload.update(lane)
    if beats:
        payload["beats"] = beats
    return _response(payload)
