"""PADIEM Claw general PC branch classification (#7809 12/13).

Source moved verbatim. Command/TXT dispatch is owned by pc_command, and
desktop dispatch by pc_desktop; the original route entrypoint re-exports.
"""

from __future__ import annotations

import re
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from padiem_ai_core.pc_device_identity import is_pc_device_id

from .claw_desktop_intent import direct_typing_eligible, explicit_pc_instruction
from .claw_routes import _error, _resolve_intake_session_reference
from .claw_general_response import _claw_general_sse
from .claw_general_pc_intent import (
    _requested_local_desktop,
    _requested_read_only_screen_view,
    _requested_desktop_control,
    _desktop_exception_question,
    _requested_desktop_task,
    _requested_local_command,
    _requested_natural_pc_files,
    _requested_natural_pc_query,
    _requested_local_txt_path,
)
from .claw_general_pc_desktop import (
    _stage_desktop_type_confirmation,
    _dispatch_user_desktop_request,
    _confirmed_staged_desktop_type,
)
from .claw_general_pc_command import (
    _confirmed_staged_pc_command,
    _dispatch_user_command_request,
    _stage_pc_command_confirmation,
    _dispatch_user_txt_request,
)


async def _claw_general_pc_branch(
    request: Request, data: dict, user_text: str, attachment_conflict: object,
) -> tuple[JSONResponse | Response | None, dict[str, object]]:
    """Run the desktop, command, confirmation and PC-classification branches.

    Returns the original response at the same point, or the nine PC context
    values the later PC work-context and staging steps receive.
    """

    # The desktop grammar is narrower than a shell command, so it is checked
    # first: a span that parses as a desktop op is never executed as one.
    desktop_requested, desktop_op = _requested_local_desktop(user_text)
    if desktop_requested:
        if attachment_conflict is not None:
            return attachment_conflict, None
        if desktop_op is None:
            return _error(422, "desktop_op_required",
                          "수행할 데스크톱 동작을 백틱으로 하나만 지정해 주세요."), None
        if desktop_op.startswith("desktop:type\n") and not (
            "\n" not in user_text.strip()
            and direct_typing_eligible(desktop_op.split("\n", 1)[1])
        ):
            return await _stage_desktop_type_confirmation(
                request, user_text=user_text, value=desktop_op.split("\n", 1)[1], data=data,
            ), None
        return await _dispatch_user_desktop_request(
            request, user_text=user_text, desktop_op=desktop_op, data=data,
        ), None

    # #6460 S1: a natural-language screen view is the same verified capture as
    # the backtick op, taken once and shown in the conversation. It never asks
    # the model and never reaches an input op.
    if _requested_read_only_screen_view(user_text):
        if attachment_conflict is not None:
            return attachment_conflict, None
        return await _dispatch_user_desktop_request(
            request, user_text=user_text, desktop_op="desktop:capture", data=data,
            pending_copy="PC 화면을 한 장 가져오는 중입니다. 완료되면 이 대화에 표시됩니다.",
            failure_guidance=True,
        ), None

    # #6460: a plain-language single desktop action. Pre-delegated: the server
    # re-verifies owner, device and the command grant on every send, and no
    # per-action button exists. The four exception families are asked once in
    # the conversation and never start from this lane.
    control_requested, control_op = _requested_desktop_control(user_text)
    if control_requested and control_op is not None:
        if attachment_conflict is not None:
            return attachment_conflict, None
        question = _desktop_exception_question(user_text)
        if question is not None:
            conversation_id, denial = await _resolve_intake_session_reference(request, data)
            if denial is not None:
                return denial, None
            return _claw_general_sse(question, conversation_id=conversation_id), None
        if control_op.startswith("desktop:type\n"):
            value = control_op.split("\n", 1)[1]
            # #7561: one short line typed by the owner runs at once; a
            # multi-line turn or a long value waits for the owner's '네'.
            if "\n" in user_text.strip() or not direct_typing_eligible(value):
                return await _stage_desktop_type_confirmation(
                    request, user_text=user_text, value=value, data=data,
                ), None
        return await _dispatch_user_desktop_request(
            request, user_text=user_text, desktop_op=control_op, data=data,
            pending_copy="요청한 PC 동작을 보내는 중입니다. 결과는 이 대화에 표시됩니다.",
            failure_guidance=True,
        ), None

    # One owner-requested initial observation runs through P01/Engine ToolRuntime
    # rather than the manual backtick diagnostic lane above.
    # #7561: the screen is only captured for a one-line instruction that
    # names the owner's PC; "내가 화면을 봤는데…" is an ordinary question.
    initial_pc_capture = explicit_pc_instruction(user_text) and bool(re.search(
        r"(?:내|우리|PC|pc|컴퓨터|COM1|com1).{0,40}"
        r"(?:화면|스크린|screen).{0,40}"
        r"(?:캡처|찍|보여|봐|capture|observe)",
        user_text, re.I,
    ))
    # #6460 step 3: a task whose next action depends on the screen runs the
    # same Engine lane, which captures, lets the trusted model choose one
    # action, executes it and captures again until the model finishes or the
    # owner presses 그만. Pre-delegated: no per-action confirmation exists.
    desktop_task_requested = not initial_pc_capture and _requested_desktop_task(user_text)
    if desktop_task_requested:
        if attachment_conflict is not None:
            return attachment_conflict, None
        question = _desktop_exception_question(user_text)
        if question is not None:
            conversation_id, denial = await _resolve_intake_session_reference(request, data)
            if denial is not None:
                return denial, None
            return _claw_general_sse(question, conversation_id=conversation_id), None
        initial_pc_capture = True
    if initial_pc_capture and attachment_conflict is not None:
        return attachment_conflict, None
    # A selected PC is shape-checked once here and then bound to the two PC
    # lanes below. It is only a target hint: the server re-verifies that the
    # account actually has this Mesh execution target before dispatch.
    requested_device_id = data.get("device_id")
    if requested_device_id is not None and not is_pc_device_id(requested_device_id):
        return _error(422, "oracle_mesh_device_invalid", "PC 장치 선택이 유효하지 않습니다."), None
    desktop_device_id = requested_device_id if initial_pc_capture else None

    # 2026-11-11: a bare affirmative turn confirms the staged PC command card.
    confirmed_command = await _confirmed_staged_pc_command(request, user_text, data)
    if confirmed_command is not None:
        return await _dispatch_user_command_request(
            request, user_text=user_text, command=confirmed_command, data=data,
        ), None
    # #7561: the same bare affirmative confirms a staged typed-value card.
    confirmed_value = await _confirmed_staged_desktop_type(request, user_text, data)
    if confirmed_value is not None:
        return await _dispatch_user_desktop_request(
            request, user_text=user_text, desktop_op="desktop:type\n" + confirmed_value,
            data=data,
            pending_copy="요청한 PC 입력을 보내는 중입니다. 결과는 이 대화에 표시됩니다.",
            failure_guidance=True,
        ), None

    command_requested, command_text = _requested_local_command(user_text)
    if command_requested:
        if attachment_conflict is not None:
            return attachment_conflict, None
        if command_text is None:
            return _error(422, "command_text_required",
                          "실행할 명령을 백틱으로 하나만 지정해 주세요."), None
        from .pc_command_confirmation import direct_command_eligible
        if direct_command_eligible(user_text, command_text):
            return await _dispatch_user_command_request(
                request, user_text=user_text, command=command_text, data=data,
            ), None
        return await _stage_pc_command_confirmation(
            request, user_text=user_text, command=command_text, data=data,
        ), None

    # #4976: a natural-language folder/file task (list then read) uses the
    # model-selected PC file tools. It is classified before the older
    # single-command/TXT lanes so a named TXT is read by the model from the
    # actual listing rather than by a fixed-path shortcut.
    from .pc_browser_intent import requested_pc_browser
    pc_browser_requested = requested_pc_browser(user_text)
    pc_browser_device_id = requested_device_id if pc_browser_requested else None
    if pc_browser_requested:
        initial_pc_capture = False
        desktop_device_id = None
    pc_files_requested = not pc_browser_requested and _requested_natural_pc_files(user_text)
    if pc_files_requested and attachment_conflict is not None:
        return attachment_conflict, None
    # The browser hint was already shape-checked once above; the saved target
    # or the server-verified target replaces it before dispatch.
    pc_files_device_id = requested_device_id if pc_files_requested else None

    # #4139: natural-language PC state query (no backtick). Routes a clear
    # question about the verified PC to a bounded inventory command on that PC.
    natural_pc_requested, natural_pc_command = _requested_natural_pc_query(user_text)
    if natural_pc_requested and not pc_browser_requested:
        if attachment_conflict is not None:
            return attachment_conflict, None
        if natural_pc_command is None:
            return _error(422, "natural_pc_command_required",
                          "PC 조회 명령을 결정할 수 없습니다."), None
        if "Get-PSDrive" not in natural_pc_command:
            return await _dispatch_user_command_request(
                request, user_text=user_text, command=natural_pc_command, data=data,
            ), None
        initial_pc_drive_query = True
        desktop_device_id = requested_device_id
    else:
        initial_pc_drive_query = False

    txt_requested, txt_path = _requested_local_txt_path(user_text)
    if txt_requested and not pc_files_requested and not pc_browser_requested:
        if attachment_conflict is not None:
            return attachment_conflict, None
        if txt_path is None:
            return _error(422, "txt_read_path_required",
                          "내 PC에서 읽을 TXT 파일의 상대 경로를 하나 지정해 주세요."), None
        return await _dispatch_user_txt_request(
            request, user_text=user_text, path_relative=txt_path, data=data,
        ), None
    return None, {
        "initial_pc_capture": initial_pc_capture,
        "desktop_task_requested": desktop_task_requested,
        "desktop_device_id": desktop_device_id,
        "requested_device_id": requested_device_id,
        "pc_browser_requested": pc_browser_requested,
        "pc_browser_device_id": pc_browser_device_id,
        "pc_files_requested": pc_files_requested,
        "pc_files_device_id": pc_files_device_id,
        "initial_pc_drive_query": initial_pc_drive_query,
    }
