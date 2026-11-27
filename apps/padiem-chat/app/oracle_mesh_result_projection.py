"""Oracle Mesh result validation and presentation."""
from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from .oracle_mesh_contract import (
    _COMMAND_ECHO_MARK, _COMMAND_ECHO_PREFIX, _COMMAND_SHELL_LABEL,
    _DESKTOP_ORIGINAL_MARKER_PREFIX, _DESKTOP_SCREENSHOT_MAGIC,
    _DESKTOP_SCREENSHOT_MEDIA_TYPE, _DESKTOP_SHELL_LABEL,
    _EMPTY_RESULT_SHA256, _MAX_COMMAND_MESSAGE_CHARS,
    _MAX_COMMAND_MESSAGE_PARTS, _MAX_FILE_TEXT_BYTES,
    _RESULT_BLOB_KEYS, _SAFE_REF_CHARS,
)
from .oracle_mesh_desktop_ops import _parse_desktop_op_text
from .oracle_mesh_http import (
    _channel_proof, _channel_source, _error, _invalid_body, _read_result_body, _ref,
)
from .oracle_mesh_log import _RESULT_LOG
from .oracle_mesh_pc_paths import _PC_FILES_READ_ROOT_REF
from .pc_share_timeout import PC_SHARE_UNAVAILABLE_CODE, PC_SHARE_UNAVAILABLE_MESSAGE_KO


def _verified_desktop_note(wire: dict[str, Any]) -> str | None:
    """Revalidate a desktop observation note: short text, no control bytes."""
    note = wire.get("content_utf8")
    if not isinstance(note, str):
        return None
    try:
        note.encode("utf-8")
    except UnicodeEncodeError:
        return None
    if any(ord(ch) < 32 and ch not in "\n\r\t" for ch in note) or "\x7f" in note:
        return None
    return note


def _verified_desktop_blob(
    wire: dict[str, Any], max_bytes: int | None = _MAX_FILE_TEXT_BYTES,
    raw: bytes | None = None,
) -> bytes | bytearray | None:
    """Revalidate a desktop screenshot blob, or ``b""`` when absent.

    Returns None for a malformed blob. Absence (act ops) is ``b""``, never
    an error: only a half-present blob is untrusted. ``raw`` is the body of
    the binary frame; the legacy JSON shape carries the same bytes as base64.
    """
    media = wire.get("content_blob_media_type")
    encoded = wire.get("content_blob_base64")
    digest = wire.get("content_blob_sha256")
    size = wire.get("content_blob_bytes")
    if raw is None and media is None and encoded is None and digest is None and size is None:
        return b""
    if media != _DESKTOP_SCREENSHOT_MEDIA_TYPE:
        return None
    if not isinstance(digest, str) or not digest:
        return None
    if isinstance(size, bool) or not isinstance(size, int):
        return None
    if size <= 0 or (max_bytes is not None and size > max_bytes):
        return None
    if raw is not None:
        # A binary frame never also carries the base64 copy: exactly one shape.
        if encoded is not None:
            return None
        blob = raw
    else:
        if not isinstance(encoded, str) or not encoded:
            return None
        try:
            blob = base64.b64decode(encoded, validate=True)
        except ValueError:
            return None
    if len(blob) != size or hashlib.sha256(blob).hexdigest() != digest:
        return None
    if not blob.startswith(_DESKTOP_SCREENSHOT_MAGIC):
        return None
    return blob


_DESKTOP_OP_LABELS = {
    "capture": "화면 캡처",
    "type": "문자 입력",
    "keys": "키 입력",
    "click": "마우스 클릭",
}


def _desktop_op_description(op: str, arg: str | None) -> str:
    label = _DESKTOP_OP_LABELS.get(op, op)
    if op == "keys" and arg:
        return f"키 입력 ({arg})"
    if op == "click" and arg:
        return f"마우스 클릭 ({arg})"
    return label


def _desktop_head(dispatch: dict[str, Any], wire: dict[str, Any], op: str, arg: str | None) -> list[str]:
    """The fixed head of one desktop message: what ran, how, what is known."""
    lines = [
        "COM1 데스크톱 " + _DESKTOP_OP_LABELS.get(op, op),
        "동작: " + _desktop_op_description(op, arg),
        "실행 방식: " + _DESKTOP_SHELL_LABEL,
    ]
    termination = wire["termination"]
    if termination == "captured":
        lines.append("종료 상태: 화면 관측 완료")
    elif termination == "acted":
        lines.append("종료 상태: 입력 전달 완료 (릴레이 연결·화면 확인 후 전송)")
    elif termination == "desktop_unavailable":
        lines.append("종료 상태: 데스크톱 응답 없음 (세션이 연결되지 않았거나 화면이 완성되지 않음)")
    elif termination == "timed_out":
        lines.append("종료 상태: 대기 시간 초과 (PC 입력의 도달을 확인하지 못함)")
    elif termination == "not_executed":
        lines.append("종료 상태: 실행되지 않음 (실행 경계에서 거부됨)")
    elif termination == "output_too_large":
        lines.append("종료 상태: 화면이 전송 한도를 초과")
    else:
        lines.append("종료 상태: " + str(termination))
    return lines


def _desktop_capture_content(
    dispatch: dict[str, Any], wire: dict[str, Any], op: str, arg: str | None,
    note: str, digest: str,
) -> str:
    """One conversation message for one real screen capture.

    The message carries the observation and the owner-scoped retrieval
    reference in a server-shaped marker line; the browser renders the image
    from that same-origin path. The bytes live in the private original
    store, pinned by the dispatch row.
    """
    lines = _desktop_head(dispatch, wire, op, arg)
    lines.append("관측: " + note)
    lines.append("SHA-256: " + digest)
    lines.append(
        _DESKTOP_ORIGINAL_MARKER_PREFIX + str(dispatch["dispatch_id"])
    )
    return "\n".join(lines)


def _desktop_act_content(
    dispatch: dict[str, Any], wire: dict[str, Any], op: str, arg: str | None,
    note: str,
) -> str:
    """One conversation message for one delivered desktop input."""
    lines = _desktop_head(dispatch, wire, op, arg)
    lines.append("관측: " + note)
    return "\n".join(lines)


def _desktop_failed_content(
    dispatch: dict[str, Any], wire: dict[str, Any], op: str, arg: str | None,
    note: str,
) -> str:
    """A desktop turn that observed no success stays an explicit notice."""
    lines = _desktop_head(dispatch, wire, op, arg)
    if note:
        lines.append("관측: " + note)
    if wire["termination"] == "output_too_large":
        lines.append(
            "화면 본문은 전송 한도를 초과하여 전달되지 않았습니다. "
            "원문이 서버에 보관되지 않았으므로 다시 조회할 수 없습니다. "
            "한 번에 관측하는 화면 범위를 좁혀 다시 실행하십시오."
        )
    else:
        lines.append(
            "PC 화면·입력에 도달하지 못했습니다. "
            "같은 입력을 반복하기 전에 화면 캡처로 현재 상태를 확인하십시오."
        )
    return "\n".join(lines)


def _verified_result_text(
    dispatch: dict[str, Any], wire: dict[str, Any],
    max_bytes: int | None = _MAX_FILE_TEXT_BYTES,
) -> str | None:
    """Revalidate a submission against the claimed dispatch; return the text."""
    text = wire["content_utf8"]
    if not isinstance(text, str):
        return None
    try:
        raw = text.encode("utf-8")
    except UnicodeEncodeError:
        return None
    if (
        (max_bytes is not None and len(raw) > max_bytes)
        or wire["content_bytes"] != len(raw)
        or any(ord(ch) < 32 and ch not in "\n\r\t" for ch in text)
        or not isinstance(wire["content_sha256"], str)
        or wire["content_sha256"] != hashlib.sha256(raw).hexdigest()
    ):
        return None
    return text


def _verified_read_result_text(
    dispatch: dict[str, Any], wire: dict[str, Any],
) -> str | None:
    """Verify a read body by its own bytes and digest (#5882 A).

    The PC read lane no longer has a product cap of its own: a 20 MB answer
    bound refused a body the connector had already produced and the digest had
    already proved, while the reader's real limits are the connector's read
    envelope (what it is asked for) and the store. A file larger than one
    answer is paged by the Engine from its first range, not rejected here.
    Other read consumers keep the shared 6 MB envelope unchanged.
    """
    if dispatch.get("root_ref") == _PC_FILES_READ_ROOT_REF:
        return _verified_result_text(dispatch, wire, max_bytes=None)
    return _verified_result_text(dispatch, wire, max_bytes=_MAX_FILE_TEXT_BYTES)


def _pc_share_unavailable_output(output: str) -> bool:
    """#8037: the closed share-unavailable verdict the connector delivers.

    Only the exact closed shape counts — ok=false with the one reviewed code.
    Any other body keeps the lane's existing judgement.
    """
    try:
        parsed = json.loads(output)
    except (TypeError, ValueError):
        return False
    return (
        isinstance(parsed, dict)
        and parsed.get("ok") is False
        and parsed.get("error") == PC_SHARE_UNAVAILABLE_CODE
    )


def _command_header(dispatch: dict[str, Any], wire: dict[str, Any]) -> list[str]:
    """The fixed head of one command message: what ran, how, and what is known.

    A wait timeout is never reported as a terminated process, and an unobserved
    exit code stays "확인되지 않음" instead of 0.
    """
    lines = [
        "COM1 명령 실행 결과",
        "명령: " + str(dispatch.get("command_text") or ""),
        "실행 방식: " + _COMMAND_SHELL_LABEL,
        "출력: stdout+stderr 병합",
    ]
    termination = wire["termination"]
    if termination == "timed_out":
        lines.append("종료 상태: 대기 시간 초과 (PC 프로세스가 계속 실행 중일 수 있음)")
        lines.append("종료 코드: 확인되지 않음")
    elif termination == "cancelled":
        lines.append("종료 상태: 중지 요청됨 (PC에서 중지가 확인되지 않음; 계속 실행 중일 수 있음)")
        lines.append("종료 코드: 확인되지 않음")
    elif termination == "no_reply":
        lines.append("종료 상태: 콘솔 응답 없음")
        lines.append("종료 코드: 확인되지 않음")
    elif termination == "not_executed":
        # The command never reached the PC: the execution boundary refused it
        # (an argv element over the host limit, a bad node reference). Reporting
        # that as "콘솔 응답 없음" would blame a console that was never asked.
        lines.append("종료 상태: 실행되지 않음 (실행 경계에서 거부됨)")
        lines.append("종료 코드: 확인되지 않음")
    elif termination == "bad_reply":
        # The console answered and its envelope could not be read. Calling that
        # "응답 없음" would blame a console that did reply, and printing the raw
        # bytes would present mangled text as though the PC had printed it.
        lines.append("종료 상태: PC 응답을 해석하지 못했습니다 (인코딩 오류)")
        lines.append(
            "종료 코드: " + (
                str(wire["exit_code"])
                if isinstance(wire["exit_code"], int)
                else "확인되지 않음"
            )
        )
    elif termination == "no_exit_code":
        # The console answered and the shell reached the statement this lane
        # appends, but PowerShell only records $LASTEXITCODE for a native program
        # or script, so a cmdlet-only pipeline reports no number. The output is
        # delivered whole and the code stays "확인되지 않음" — never 0.
        lines.append(
            "종료 상태: 콘솔 응답 완료 (cmdlet 전용 파이프라인이라 종료 코드가 보고되지 않음)"
        )
        lines.append("종료 코드: 확인되지 않음")
    elif termination == "output_too_large":
        lines.append("종료 상태: 출력이 전송 한도를 초과")
        lines.append(
            "종료 코드: " + (
                str(wire["exit_code"])
                if isinstance(wire["exit_code"], int)
                else "확인되지 않음"
            )
        )
    else:
        lines.append("종료 상태: " + str(termination))
        lines.append(
            "종료 코드: " + (
                str(wire["exit_code"])
                if isinstance(wire["exit_code"], int)
                else "확인되지 않음"
            )
        )
    return lines


def _command_result_content(
    dispatch: dict[str, Any], wire: dict[str, Any], output: str,
) -> str:
    """One conversation message for one real command execution.

    The output is delimited by explicit markers so its own leading/trailing
    whitespace and newlines survive the shared history projection unchanged:
    the markers, not the output, are the message edges.
    """
    lines = _command_header(dispatch, wire)
    lines.append("--- 출력 시작 ---")
    lines.append(output)
    lines.append("--- 출력 끝 ---")
    return "\n".join(lines)


def _command_output_withheld_content(
    dispatch: dict[str, Any], wire: dict[str, Any],
) -> str:
    """An execution whose output never crossed the wire.

    The executor withheld the body at the wire envelope, so there is no
    stored original to point at: the message says exactly that instead of
    claiming the dispatch row holds a body it does not. Only the observed
    termination and exit code are delivered.
    """
    lines = _command_header(dispatch, wire)
    lines.append(
        "출력 본문은 전송 한도를 초과하여 전달되지 않았습니다. "
        "원문이 서버에 보관되지 않았으므로 다시 조회할 수 없습니다. "
        "출력 범위를 좁힌 명령으로 다시 실행하십시오."
    )
    return "\n".join(lines)


def _command_original_stored_content(
    dispatch: dict[str, Any], wire: dict[str, Any], output: str,
) -> str:
    """One notice for an output larger than the conversation budget.

    The full output passed verification (bytes and digest are pinned on the
    dispatch row) and the private original store accepted it before this
    message was built, so "stored" is only claimed after the put succeeds.
    The conversation carries a head preview sized to this message's own frame —
    a preview taken from another shape could overflow the shared per-message
    limit and strand the result — and the whole original is fetched through the
    owner-scoped retrieval reference below.
    """
    head = _command_head(dispatch, wire)
    opening = head + [
        "출력 " + str(wire["content_bytes"]) + "바이트 전체는 비공개 원문 저장소에 "
        "보관되었습니다. 아래는 앞부분 미리보기입니다.",
        "--- 출력 미리보기 시작 ---",
    ]
    closing = [
        "--- 출력 미리보기 끝 ---",
        "SHA-256: " + str(wire["content_sha256"]),
        "원문 전체 조회: GET "
        + "/api/claw/connector/mesh-results/" + str(dispatch["dispatch_id"]),
    ]
    room = (
        _MAX_COMMAND_MESSAGE_CHARS
        - sum(len(line) for line in opening + closing)
        - (len(opening) + len(closing))
    )
    return "\n".join(opening + [output[:max(room, 0)]] + closing)


def _command_part_messages(head: list[str], parts: list[str]) -> list[str]:
    """Wrap each output part in the shared frame, in order.

    ``"".join(parts)`` is the output verbatim, so the conversation carries every
    byte across its messages; the frame lines are display furniture and the
    pinned digest belongs to the unwrapped body.
    """
    total = str(len(parts))
    messages = []
    for index, part in enumerate(parts):
        lines = list(head)
        lines.append("--- 출력 " + str(index + 1) + "/" + total + " 시작 ---")
        lines.append(part)
        lines.append("--- 출력 끝 ---")
        messages.append("\n".join(lines))
    return messages


def _file_read_part_messages(parts: list[str]) -> list[str]:
    total = str(len(parts))
    messages = []
    for index, part in enumerate(parts):
        lines = ["PC 파일 읽기 결과"]
        lines.append("--- 출력 " + str(index + 1) + "/" + total + " 시작 ---")
        lines.append(part)
        lines.append("--- 출력 끝 ---")
        messages.append("\n".join(lines))
    return messages


def _file_read_stored_content(
    dispatch: dict[str, Any], wire: dict[str, Any], output: str,
) -> str:
    """Read-lane twin of the stored-original notice, sized to its own frame."""
    opening = [
        "PC 파일 읽기 결과",
        "출력 " + str(wire["content_bytes"]) + "바이트 전체는 비공개 원문 저장소에 "
        "보관되었습니다. 아래는 앞부분 미리보기입니다.",
        "--- 출력 미리보기 시작 ---",
    ]
    closing = [
        "--- 출력 미리보기 끝 ---",
        "SHA-256: " + str(wire["content_sha256"]),
        "원문 전체 조회: GET "
        + "/api/claw/connector/mesh-results/" + str(dispatch["dispatch_id"]),
    ]
    room = (
        _MAX_COMMAND_MESSAGE_CHARS
        - sum(len(line) for line in opening + closing)
        - (len(opening) + len(closing))
    )
    return "\n".join(opening + [output[:max(room, 0)]] + closing)


def _command_markers() -> tuple[str, str]:
    """The widest part-marker pair one message can carry.

    The digit count comes from the part guard, so the widest index/total pair
    the caller can ever print is already paid for.
    """
    digits = len(str(_MAX_COMMAND_MESSAGE_PARTS + 1))
    return (
        "--- 출력 " + "9" * digits + "/" + "9" * digits + " 시작 ---",
        "--- 출력 끝 ---",
    )


def _command_part_budget(head: list[str]) -> int:
    """How many characters one output part may use in this message shape.

    Derived, never estimated: the shared per-message bound minus the message
    head minus the marker frame around the part.
    """
    start, end = _command_markers()
    return _MAX_COMMAND_MESSAGE_CHARS - len("\n".join(head)) - len(start) - len(end) - 3


def _command_head(dispatch: dict[str, Any], wire: dict[str, Any]) -> list[str]:
    """The message head, fitted so an output part always has room.

    A command can now be as long as its dispatch row allows, and the head
    echoes it. Left unbounded, every part of a large output would overflow the
    shared per-message limit and the whole result would strand on a storage
    refusal. The echo is a label and the output is the payload, so when the head
    does not fit the label keeps at most half of what the fixed header lines and
    the marker frame leave over; the full command stays in the user's own turn
    and in the dispatch row, and the mark says so.
    """
    head = _command_header(dispatch, wire)
    if _command_part_budget(head) >= 1:
        return head
    index = next(
        (position for position, line in enumerate(head)
         if line.startswith(_COMMAND_ECHO_PREFIX)),
        None,
    )
    if index is None:
        return head
    start, end = _command_markers()
    others = len("\n".join(
        line for position, line in enumerate(head) if position != index
    ))
    room = max(
        0,
        (
            _MAX_COMMAND_MESSAGE_CHARS
            - others
            - len(start)
            - len(end)
            - 4
            - len(_COMMAND_ECHO_MARK)
        ) // 2,
    )
    bounded = list(head)
    bounded[index] = bounded[index][:room] + _COMMAND_ECHO_MARK
    if _command_part_budget(bounded) >= 1:
        return bounded
    # No label fits beside the output at all: drop it rather than let the
    # message carry no result. The dispatch row still holds the whole command.
    del bounded[index]
    return bounded


def _command_output_parts(output: str, limit: int) -> list[str]:
    """Partition one output so that ``"".join(parts)`` is the output verbatim.

    #4139: the former splitter kept the pending part as a joined string, so an
    empty line was indistinguishable from "nothing buffered" and every line
    boundary it crossed was swallowed — ``"\\n" + "a"*7401`` came back 7401
    characters. Each terminator now travels with its own line
    (``splitlines(keepends=True)``), so blank lines, consecutive newlines, CRLF
    and one long line reassemble byte for byte. A line longer than the limit is
    sliced, never cut, and no part is ever dropped.
    """
    if limit < 1:
        # Fail fast instead of looping: a head that leaves no room is a caller
        # bug, and slicing against a zero or negative bound would never finish.
        raise ValueError("output part limit must be at least one character")
    if len(output) <= limit:
        return [output]
    parts: list[str] = []
    buffer = ""
    for line in output.splitlines(keepends=True):
        while len(line) > limit:
            room = limit - len(buffer)
            if room > 0:
                buffer += line[:room]
                line = line[room:]
            parts.append(buffer)
            buffer = ""
        if len(buffer) + len(line) > limit:
            parts.append(buffer)
            buffer = line
        else:
            buffer += line
    if buffer:
        parts.append(buffer)
    return parts


async def _oracle_mesh_read_result_verify(
    request: Request,
) -> tuple[JSONResponse | None, dict[str, object]]:
    """서명·nonce·lease·termination·디스패치 조회 구간.

    본문은 리팩터 전 `oracle_mesh_read_result`의 연속 구간을 글자 그대로 옮긴다.
    보안 검사 순서와 `stage=received` 로그의 자리·문구를 그대로 지킨다.
    """
    parsed_result = await _read_result_body(request)
    if parsed_result is None:
        return _invalid_body("result"), {}
    wire, result_blob_raw = parsed_result
    if _ref(wire.get("dispatch_id"), 128) is None:
        return _invalid_body("result", "dispatch_id"), {}
    if _ref(wire.get("nonce"), 128) is None:
        return _invalid_body("result", "nonce"), {}
    submitted_node = wire.get("node_ref")
    if submitted_node is not None and (
        not isinstance(submitted_node, str) or not submitted_node
        or len(submitted_node) > 256
        or any(
            ch not in _SAFE_REF_CHARS and ch not in "\\/"
            for ch in submitted_node
        )
    ):
        return _invalid_body("result", "node_ref"), {}
    if wire.get("termination") not in (
        "exited", "cancelled", "timed_out", "no_reply", "no_exit_code",
        "not_executed", "output_too_large",
        "captured", "acted", "desktop_unavailable",
    ):
        return _invalid_body("result", "termination"), {}
    # #4139: a wait timeout and a console that never answered have NO observed
    # exit code. That is carried as null, never invented as 0; only a real
    # "exited" run must report an integer. A desktop turn never reports one
    # at all — there is no console sentinel on that lane.
    if wire.get("exit_code") is None:
        # ``no_exit_code`` keeps the code unobserved: PowerShell records
        # $LASTEXITCODE only for a native program or script, so a cmdlet-only
        # pipeline answers completely without reporting a number.
        if wire.get("termination") not in (
            "timed_out", "no_reply", "no_exit_code", "not_executed",
            "captured", "acted", "desktop_unavailable", "output_too_large",
            # An owner's stop ends the client, so nothing was ever observed from
            # the PC's console. That is carried as null, never invented as 0.
            "cancelled",
        ):
            return _invalid_body("result", "exit_code_missing"), {}
    elif isinstance(wire.get("exit_code"), bool) or not isinstance(wire.get("exit_code"), int):
        return _invalid_body("result", "exit_code_type"), {}
    if wire.get("content_bytes") == 0 and wire.get("content_sha256") == "":
        # Legacy empty-read shape: canonicalize before verification and
        # pinning so a 0-byte outcome is delivered instead of stranding.
        wire = {**wire, "content_sha256": _EMPTY_RESULT_SHA256}

    mesh_source = _channel_source(request)
    if mesh_source is None:
        return _error(503, "oracle_mesh_unconfigured"), {}
    if not _channel_proof(request, mesh_source):
        return _error(403, "oracle_mesh_channel_rejected"), {}
    history_store = getattr(request.app.state, "history_store", None)
    for method in ("consume_oracle_mesh_dispatch", "finish_oracle_mesh_dispatch",
                   "mark_oracle_mesh_store_failed",
                   "record_oracle_mesh_first_result",
                   "store_oracle_mesh_original",
                   "get_claw_run", "append_local_task_result"):
        if not callable(getattr(history_store, method, None)):
            return _error(503, "oracle_mesh_unconfigured"), {}

    try:
        dispatch = await history_store.consume_oracle_mesh_dispatch(
            dispatch_id=wire["dispatch_id"], nonce=wire["nonce"],
            node_ref=submitted_node,
        )
    except Exception:
        return _error(503, "oracle_mesh_dispatch_unavailable"), {}
    if dispatch is None:
        # Unknown, expired, already-consumed or nonce-mismatched dispatch. A
        # concurrent second submit of the same result loses the atomic update
        # here and is refused, rather than looking like the accepted request.
        return _error(409, "oracle_mesh_dispatch_rejected"), {}
    from .pc_correlation import run_hash as _result_run_hash, dispatch_id as _result_dispatch_id
    result_run_hash = _result_run_hash(dispatch.get("run_id")) or "none"
    result_dispatch_id = _result_dispatch_id(wire.get("dispatch_id")) or "none"
    result_log = _RESULT_LOG
    result_log.info("pc_result stage=received run_hash=%s dispatch_id=%s", result_run_hash, result_dispatch_id)
    claim = dispatch.get("claim")
    if claim not in ("first", "retry"):
        return _error(503, "oracle_mesh_dispatch_unavailable"), {}
    return None, {
        "wire": wire,
        "result_blob_raw": result_blob_raw,
        "result_log": result_log,
        "result_run_hash": result_run_hash,
        "result_dispatch_id": result_dispatch_id,
        "history_store": history_store,
        "dispatch": dispatch,
        "claim": claim,
    }


async def _oracle_mesh_read_result_outcome(
    dispatch: dict, result_blob_raw: bytes | None, wire: dict,
) -> tuple[JSONResponse | None, dict[str, object]]:
    """결과 검증·outcome 산출 구간 (본문 글자 그대로)."""
    outcome = "done"
    content = ""
    summary = ""
    status = ""
    #: #4139: the verified body of each lane, kept so a result larger than one
    #: conversation message can be split across deterministic message ids.
    command_output: str | None = None
    read_output: str | None = None
    #: #5015: the verified read body (a successful file or a bounded error
    #: marker) is stored through the existing original store before the
    #: conversation message is built, so the Engine result mode can re-feed
    #: exact bytes and the model lane sees the same error mapping.
    read_stored_output: str | None = None
    #: #4139 desktop lane: the verified observation note, the verified
    #: screenshot bytes (None when the turn carries no image) and the op the
    #: dispatch row ordered. Messages are built after the pin below.
    desktop_note: str | None = None
    desktop_blob: bytes | None = None
    desktop_op: str | None = None
    desktop_arg: str | None = None
    result_digest = wire["content_sha256"] if wire["content_bytes"] else _EMPTY_RESULT_SHA256
    result_size = wire["content_bytes"]
    if dispatch.get("kind") != "desktop" and (
        result_blob_raw is not None
        or any(key in wire for key in _RESULT_BLOB_KEYS)
    ):
        # Screenshot evidence on a non-desktop turn is untrusted by shape.
        # The consumed dispatch still closes as failed and nothing reaches
        # the conversation; an identical resend pins the same digest and
        # lands on the same verdict instead of appending twice.
        outcome = "failed"
        summary = "untrusted-result"
        status = "failed"
        content = (
            "실행 결과를 검증하지 못했습니다. "
            "사유: 결과 무결성 불일치."
        )
    elif dispatch.get("kind") == "command":
        # #4139 terminal lane. The body is the command output, verified with the
        # same UTF-8/SHA rules; the exit code is whatever the PC reported, and a
        # console that never answered stays "확인되지 않음". A large output is
        # split across messages, so this branch never rejects a verified result.
        verified_output = _verified_result_text(
            dispatch, wire, max_bytes=_MAX_FILE_TEXT_BYTES,
        )
        command_text = dispatch.get("command_text")
        if (
            verified_output is None
            or not isinstance(command_text, str) or not command_text
        ):
            outcome = "failed"
            summary = "untrusted-result"
            status = "failed"
            content = (
                "명령 실행 결과를 검증하지 못했습니다. "
                "사유: 결과 무결성 불일치."
            )
        else:
            content = _command_result_content(dispatch, wire, verified_output)
            command_output = verified_output
            if _pc_share_unavailable_output(verified_output):
                # #8037: the share bound closed this command. The row finishes
                # (the console answered a closed verdict), the turn is a named
                # failure, and the owner reads the one guidance sentence — not
                # a wedged command line.
                outcome, summary, status = "done", PC_SHARE_UNAVAILABLE_CODE, "failed"
                content = (
                    "PC 명령이 네트워크 공유에 연결하지 못해 20초 만에 정리되었습니다.\n"
                    + PC_SHARE_UNAVAILABLE_MESSAGE_KO
                )
            elif wire["termination"] in ("exited", "output_too_large"):
                if wire["exit_code"] == 0:
                    outcome, summary, status = "done", "exited/0", "completed"
                else:
                    outcome = "failed"
                    summary = str(wire["termination"]) + "/" + str(wire["exit_code"])
                    status = "failed"
            elif wire["termination"] == "not_executed":
                # Nothing ran, so nothing succeeded: a refusal is reported as a
                # failure of this turn without inventing a program exit code.
                outcome = "failed"
                summary = "not_executed"
                status = "failed"
            elif wire["termination"] == "no_exit_code":
                # Delivered and complete, with the code unobserved: the console
                # answered and the shell ran the appended sentinel statement, so
                # the turn is finished, while nothing here claims exit 0.
                outcome, summary, status = "done", "no_exit_code", "completed"
            else:
                outcome = "failed"
                summary = str(wire["termination"])
                status = "failed"
    elif dispatch.get("kind") == "desktop":
        # #4139 desktop lane. The note is the observation text, verified with
        # the same text rules; the screenshot (captures only) is verified
        # beside it with its own digest. A desktop turn never reports an exit
        # code — there is no console sentinel on this lane — so a non-null
        # code is untrusted. The pin covers the screenshot when one is
        # present, else the note, matching what the executor pinned first.
        parsed = _parse_desktop_op_text(dispatch.get("command_text"))
        verified_note = _verified_desktop_note(wire)
        verified_blob = _verified_desktop_blob(wire, raw=result_blob_raw)
        if (
            parsed is None
            or verified_note is None
            or verified_blob is None
            or wire.get("exit_code") is not None
        ):
            outcome = "failed"
            summary = "untrusted-result"
            status = "failed"
            content = (
                "데스크톱 실행 결과를 검증하지 못했습니다. "
                "사유: 결과 무결성 불일치."
            )
        else:
            blob = bytes(verified_blob)
            note_raw = verified_note.encode("utf-8")
            if blob:
                pinned_ok = (
                    wire["content_sha256"] == hashlib.sha256(blob).hexdigest()
                    and wire["content_bytes"] == len(blob)
                )
            else:
                pinned_ok = (
                    wire["content_sha256"] == hashlib.sha256(note_raw).hexdigest()
                    and wire["content_bytes"] == len(note_raw)
                )
            if not pinned_ok:
                outcome = "failed"
                summary = "untrusted-result"
                status = "failed"
                content = (
                    "데스크톱 실행 결과를 검증하지 못했습니다. "
                    "사유: 결과 무결성 불일치."
                )
            else:
                desktop_op, desktop_arg = parsed
                desktop_note = verified_note
                desktop_blob = blob if blob else None
                if wire["termination"] == "captured" and blob:
                    outcome, summary, status = "done", "captured", "completed"
                    content = ""
                elif wire["termination"] == "acted" and not blob:
                    outcome, summary, status = "done", "acted", "completed"
                    content = ""
                elif wire["termination"] in (
                    "desktop_unavailable", "timed_out", "not_executed",
                    "output_too_large",
                ):
                    outcome = "failed"
                    summary = str(wire["termination"])
                    status = "failed"
                    content = ""
                else:
                    outcome = "failed"
                    summary = "untrusted-result"
                    status = "failed"
                    content = (
                        "데스크톱 실행 결과를 검증하지 못했습니다. "
                        "사유: 결과 무결성 불일치."
                    )
    elif wire["termination"] == "exited" and wire["exit_code"] == 0:
        verified_text = _verified_read_result_text(dispatch, wire)
        if verified_text is None:
            # A clean execution claim with tampered body+hash is refused, and
            # the consumed dispatch still closes as failed: the bytes are
            # untrusted and must never reach a conversation.
            outcome = "failed"
            summary = "untrusted-result"
            status = "failed"
            content = (
                "로컬 러너 작업 결과를 검증하지 못했습니다. "
                f"명령: {dispatch['command_id']}, 사유: 결과 무결성 불일치."
            )
        else:
            content = (
                "PC 파일 읽기 결과\n--- 출력 1/1 시작 ---\n"
                + (verified_text if verified_text else "(빈 파일)")
                + "\n--- 출력 끝 ---"
            )
            read_output = verified_text if verified_text else None
            read_stored_output = read_output
            summary = "exited/0"
            status = "completed"
    elif wire["termination"] == "cancelled":
        summary = "cancelled"
        status = "cancelled"
        outcome = "failed"
        content = (
            "로컬 러너 작업에 중지 요청이 기록되었습니다. "
            "PC에서 중지가 확인되지 않았을 수 있습니다. "
            f"명령: {dispatch['command_id']}."
        )
    elif dispatch.get("kind") == "read":
        # #5015: a failed read keeps its verified body. The executor reports
        # ``PADIEM_PC_FILE_ERROR:too_large`` or ``:read_failed`` as an
        # exited/1 body, and the Engine maps that same marker. The
        # conversation still reports a failure, never the file as a success.
        verified_text = _verified_read_result_text(dispatch, wire)
        if verified_text is None:
            outcome = "failed"
            summary = "untrusted-result"
            status = "failed"
            content = (
                "PC 파일 읽기 결과를 검증하지 못했습니다. "
                f"명령: {dispatch['command_id']}, 사유: 결과 무결성 불일치."
            )
        else:
            outcome = "failed"
            # Keep the read lane's existing failure vocabulary: only a wait
            # timeout is named as such; every other non-clean read is
            # "failed". The verified marker body is stored separately.
            summary = "timed_out" if wire["termination"] == "timed_out" else "failed"
            status = summary
            read_stored_output = verified_text if verified_text else None
            content = (
                "PC 파일 읽기 작업이 실패했습니다. "
                f"명령: {dispatch['command_id']}, 상태: {wire['termination']}, "
                f"종료 코드: {wire['exit_code']}."
            )
    else:
        summary = "timed_out" if wire["termination"] == "timed_out" else "failed"
        status = summary
        outcome = "failed"
        content = (
            "로컬 러너 작업이 실패했습니다. "
            f"명령: {dispatch['command_id']}, 상태: {wire['termination']}, "
            f"종료 코드: {wire['exit_code']}."
        )
    return None, {
        "outcome": outcome,
        "content": content,
        "summary": summary,
        "status": status,
        "command_output": command_output,
        "read_output": read_output,
        "read_stored_output": read_stored_output,
        "desktop_note": desktop_note,
        "desktop_blob": desktop_blob,
        "desktop_op": desktop_op,
        "desktop_arg": desktop_arg,
        "result_digest": result_digest,
        "result_size": result_size,
    }
