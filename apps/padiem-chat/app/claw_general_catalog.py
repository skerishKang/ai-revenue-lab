"""B54 Claw general: model roster and verified PC work-context gate (#7809 5/13).

Declarations moved verbatim from claw_general_routes. The entry module
re-exports these functions for existing imports and patch_bound tests.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from padiem_ai_core.pc_device_identity import is_pc_device_id

from .auth_routes import auth_ready, current_user_id
from .claw_routes import _error
from .claw_general_stage import (
    CLAW_STAGE_CATALOG,
    CLAW_STAGE_PC_CONTEXT,
    _claw_stage,
    _claw_timed,
)


def _drain_task_result(task: "asyncio.Task[Any]") -> None:
    """Retrieve a background result the turn may never await.

    A turn refused by the PC target checks returns before the roster is
    evaluated. Retrieving the outcome here keeps that bounded metadata read
    from surfacing as an unretrieved task error; it never changes a response.
    """
    if task.cancelled():
        return
    try:
        task.exception()
    except Exception:
        pass


def _start_selectable_model_read(
    request: Any, central_route_model_id: str | None
) -> tuple["asyncio.Task[Any] | None", bool]:
    """#5614: start the model-roster read before the PC work context.

    The roster read and the PC work context are independent reads of the same
    signed request, and the roster read used to run strictly after the PC one.
    Starting it first lets the two overlap on the wire.

    Returns ``(task, unavailable)``. ``unavailable`` reproduces the exact 503
    the sequential code returned when the composed catalog authority cannot
    list models at all - the refusal is still raised at its original position
    (after the PC target checks), never earlier.
    """

    if central_route_model_id is None:
        return None, False
    resolver = getattr(
        getattr(getattr(request, "app", None), "state", None),
        "b14_model_choice_resolver",
        None,
    )
    if resolver is None:
        return None, False
    list_fn = getattr(resolver, "list_selectable_models", None)
    if not callable(list_fn):
        return None, True
    try:
        read = _claw_timed(CLAW_STAGE_CATALOG, list_fn())
    except Exception:
        return None, True
    task = asyncio.ensure_future(read)
    task.add_done_callback(_drain_task_result)
    return task, False


async def _claw_general_pc_work_context(
    request: Request, *,
    initial_pc_drive_query: bool,
    pc_files_requested: bool,
    pc_browser_requested: bool,
    desktop_device_id: str | None,
    pc_files_device_id: str | None,
    pc_browser_device_id: str | None,
    canonical_session_id: str | None,
) -> tuple[JSONResponse | Response | None, dict[str, object]]:
    """Resolve and verify one PC work context after the route preflight.

    The same owner/workspace/saved-selection/target checks as before; the
    caller keeps the catalog read and its finally around this call.
    """

    pc_work_text: str | None = None
    pc_owner = current_user_id(request) if auth_ready(request) else None
    if isinstance(pc_owner, str) and pc_owner:
        from .claw_memory_routes import _resolve_memory_workspace
        from .pc_work_context import (
            SAVED_SELECTION_SELECTED, SAVED_SELECTION_UNAVAILABLE,
            render_pc_work_context, resolve_pc_work_context,
            read_saved_device_selection,
        )

        try:
            pc_workspace = await _resolve_memory_workspace(request, pc_owner)
        except Exception:
            pc_workspace = None
        pc_target_requested = initial_pc_drive_query or pc_files_requested or pc_browser_requested
        explicit_pc_device_id = (
            desktop_device_id if initial_pc_drive_query
            else (pc_files_device_id if pc_files_requested else pc_browser_device_id if pc_browser_requested else None)
        )
        selected_pc_device_id = explicit_pc_device_id
        if (
            pc_target_requested
            and isinstance(pc_workspace, str) and pc_workspace
        ):
            # The saved value is the account's default target. A failed read
            # is NOT "no selection": never fall back to another PC.
            saved_selection = await read_saved_device_selection(
                request, owner_id=pc_owner, workspace_id=pc_workspace,
            )
            if explicit_pc_device_id is not None:
                if (
                    saved_selection.status == SAVED_SELECTION_SELECTED
                    and saved_selection.device_id != explicit_pc_device_id
                ):
                    # A stale tab must not execute on a target that differs
                    # from the current server preference.
                    return _error(
                        409, "pc_selection_stale",
                        "저장된 작업 대상과 화면 선택이 다릅니다. 내 컴퓨터에서 대상을 다시 선택해 주세요.",
                    ), None
            elif saved_selection.status == SAVED_SELECTION_SELECTED:
                selected_pc_device_id = saved_selection.device_id
            elif saved_selection.status == SAVED_SELECTION_UNAVAILABLE:
                return _error(
                    503, "pc_selection_unavailable",
                    "저장된 PC 작업 대상을 확인할 수 없습니다. 잠시 후 다시 시도해 주세요.",
                ), None
        pc_context = await resolve_pc_work_context(
            request, owner_id=pc_owner,
            workspace_id=pc_workspace,
            session_id=canonical_session_id,
            selected_device_id=selected_pc_device_id,
        )
        if pc_target_requested and selected_pc_device_id is not None:
            selected_row = next(
                (device for device in pc_context.devices
                 if device.device_id == selected_pc_device_id),
                None,
            )
            if selected_row is not None and selected_row.state == "REVOKED":
                return _error(
                    409, "pc_selection_revoked",
                    "선택한 PC의 연결이 해제되었습니다. 작업 대상을 다시 선택해 주세요.",
                ), None
            if not pc_context.selected_confirmed:
                # An explicit or saved target that did not resolve to the
                # verified Mesh execution target never falls back to another PC.
                if not pc_context.execution.ready:
                    return _error(
                        409, "pc_target_unavailable",
                        "선택한 PC의 서버 실행 대상을 확인할 수 없습니다. 작업 대상을 다시 확인해 주세요.",
                    ), None
                return _error(
                    403, "pc_target_mismatch",
                    "선택한 PC가 서버 실행 대상과 일치하지 않습니다. 작업 대상을 다시 선택해 주세요.",
                ), None
            # Carry the SAME effective target into the Engine plan for each
            # PC lane that this turn selected.
            if initial_pc_drive_query:
                desktop_device_id = selected_pc_device_id
            if pc_files_requested:
                pc_files_device_id = selected_pc_device_id
            if pc_browser_requested:
                pc_browser_device_id = selected_pc_device_id
        if (pc_browser_requested and pc_browser_device_id is None
                and pc_context.tool_available and pc_context.selected_confirmed
                and is_pc_device_id(pc_context.execution_device_id)):
            pc_browser_device_id = pc_context.execution_device_id
        pc_work_text = render_pc_work_context(pc_context)
    return None, {
        "pc_work_text": pc_work_text,
        "desktop_device_id": desktop_device_id,
        "pc_files_device_id": pc_files_device_id,
        "pc_browser_device_id": pc_browser_device_id,
    }


async def _claw_general_catalog_gate(
    request: Request,
    central_route_model_id: str | None,
    claw_route: Any,
    initial_pc_drive_query: bool,
    pc_files_requested: bool,
    pc_browser_requested: bool,
    desktop_device_id: str | None,
    pc_files_device_id: str | None,
    pc_browser_device_id: str | None,
    canonical_session_id: str | None,
) -> tuple[JSONResponse | Response | None, dict[str, object] | None]:
    """#7814 4/4b: moved verbatim from the pre-refactor main.
    Every early return keeps its exact response as ``(response, None)``.
    """
    # #5015: one per-request, server-verified PC work context. It reads BOTH
    # the owner/workspace-scoped Broker directory the "내 컴퓨터" panel shows
    # and the deployment's Mesh execution target, so an empty Broker list is
    # never reported as "unregistered" and an online badge never becomes tool
    # permission. It is not an execution grant: dispatch re-verifies the owner
    # and the exact target.
    pc_work_text: str | None = None
    pc_context_started = time.perf_counter()
    # #5614: the account's selectable-model roster is an independent read, so
    # it starts here and is evaluated after the PC block. The PC target checks
    # therefore still decide first and still fail closed; only the read itself
    # overlaps.
    catalog_task, catalog_unavailable = _start_selectable_model_read(
        request, central_route_model_id,
    )
    # #5479: every exit from this span - a PC-target refusal, an exception,
    # or a client that left - either already awaited the roster read or must
    # not leave it running. The finally below is the guarantee.
    try:
        pc_context_error, pc_values = await _claw_general_pc_work_context(
            request,
            initial_pc_drive_query=initial_pc_drive_query,
            pc_files_requested=pc_files_requested,
            pc_browser_requested=pc_browser_requested,
            desktop_device_id=desktop_device_id,
            pc_files_device_id=pc_files_device_id,
            pc_browser_device_id=pc_browser_device_id,
            canonical_session_id=canonical_session_id,
        )
        if pc_context_error is not None:
            return pc_context_error, None
        pc_work_text = pc_values["pc_work_text"]
        desktop_device_id = pc_values["desktop_device_id"]
        pc_files_device_id = pc_values["pc_files_device_id"]
        pc_browser_device_id = pc_values["pc_browser_device_id"]
        _claw_stage(CLAW_STAGE_PC_CONTEXT, pc_context_started)

        # #3790: in the production Worker Claw uses the central model
        # ready/owner-allowed metadata resolver. A server-resolved grade
        # route whose model is not listed by B14 advances to its explicitly
        # configured fallback; a forged client id never reaches this point
        # because it is ignored wholesale at the route step (#6828).
        # Test-only deployments without this optional view still rely on
        # B14's final exact-ID execution authority.
        #
        # #5614: the read was started before the PC work context and is only
        # EVALUATED here, so this refusal still comes after the PC target checks.
        if catalog_unavailable:
            return _error(503, "model_catalog_unavailable", "사용 가능한 모델 목록을 확인할 수 없습니다."), None
        if catalog_task is not None:
            try:
                available = await catalog_task
                if not isinstance(available, list):
                    raise ValueError("invalid model roster")
                eligible_ids = {row["model_id"] for row in available}
            except (Exception,):
                return _error(503, "model_catalog_unavailable", "사용 가능한 모델 목록을 확인할 수 없습니다."), None
            if central_route_model_id not in eligible_ids:
                if claw_route.fallback_model_id in eligible_ids:
                    central_route_model_id = claw_route.fallback_model_id
                else:
                    return _error(422, "model_not_available", "현재 사용할 수 없는 모델입니다. 다른 등급을 선택해 주세요."), None

    finally:
        # A task the evaluation awaited is done, where this is a no-op; one
        # the turn never reached is cancelled here, and the drain callback
        # keeps even its outcome retrieved.
        if catalog_task is not None and not catalog_task.done():
            catalog_task.cancel()
    return None, {
        "pc_work_text": pc_work_text,
        "desktop_device_id": desktop_device_id,
        "pc_files_device_id": pc_files_device_id,
        "pc_browser_device_id": pc_browser_device_id,
        "central_route_model_id": central_route_model_id,
    }
