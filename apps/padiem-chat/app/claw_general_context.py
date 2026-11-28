"""B54 Claw general: public grounding, staged PC run and trusted context (#7809 8/13).

Definitions moved verbatim; the entry module re-exports every name.
The original first-turn grant failure and quota refund effects remain in
the same await flow. No task scheduling or policy is changed here.
"""

from __future__ import annotations

import time
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .auth_routes import auth_ready, current_user_id
from .claw_first_turn_authority import (
    B54VerifiedCodingContextV1,
    fail_first_turn_grant,
)
from .claw_general_search import _claw_public_search_grounding
from .claw_general_stage import CLAW_STAGE_JUDGEMENT, _claw_stage
from .claw_routes import _error
from .dispatch_quota import _refund_active_reservation


def _combine_system_context(*parts: str | None) -> str | None:
    """Join optional trusted context blocks in a fixed order.

    Each part is server-composed; a browser-supplied string never reaches this
    helper. Empty/absent blocks disappear instead of emitting a blank section.
    """
    blocks = [part for part in parts if isinstance(part, str) and part]
    return "\n\n".join(blocks) if blocks else None


async def _claw_general_grounding(
    request: Request,
    adapter: Any,
    model_user_text: str,
    central_route_model_id: str | None,
    drive_context: Any,
    drive_sources: Any,
    initial_pc_drive_query: bool,
    pc_files_requested: bool,
    pc_browser_requested: bool,
) -> tuple[JSONResponse | Response | None, dict[str, object] | None]:
    """#7814 4/4b: moved verbatim from the pre-refactor main.
    Every early return keeps its exact response as ``(response, None)``.
    """
    # #4469: optional public web grounding, judged by the model and off unless the
    # server says otherwise. It reads the SAME owner-verified history the answer lane
    # uses, never browser-supplied prior turns, so forged history cannot move the
    # search target. Everything downstream is unchanged when it returns nothing.
    # Private Drive data never enters the public web search judgement/query.
    if initial_pc_drive_query or pc_files_requested or pc_browser_requested:
        # #5015/#4976: a PC drive or file task needs no public web evidence.
        # Skipping the judgement call keeps this turn from spending a model
        # call before the Engine PC tool dispatch.
        grounding_context, search_sources = None, ()
    elif drive_context is None:
        judgement_started = time.perf_counter()
        grounding_context, search_sources = await _claw_public_search_grounding(
            request, adapter, model_user_text,
            model_id=central_route_model_id,
        )
        _claw_stage(CLAW_STAGE_JUDGEMENT, judgement_started)
    else:
        grounding_context, search_sources = drive_context, drive_sources
    return None, {
        "grounding_context": grounding_context,
        "search_sources": search_sources,
    }


async def _claw_general_staging(
    request: Request,
    user_text: str,
    conversation_id: str | None,
    run: Any,
    first_turn_context: B54VerifiedCodingContextV1 | None,
    initial_pc_capture: bool,
    initial_pc_drive_query: bool,
    pc_files_requested: bool,
    pc_browser_requested: bool,
    desktop_task_requested: bool,
) -> tuple[JSONResponse | Response | None, dict[str, object] | None]:
    """#7814 4/4b: moved verbatim from the pre-refactor main.
    Every early return keeps its exact response as ``(response, None)``.
    """
    # #4139: a model-driven desktop run must have an owner-bound run row
    # BEFORE Engine dispatch. The signed internal desktop route resolves the
    # target conversation, workspace and owner session from that row, so an
    # unstaged run can only fail after the model has already started.
    staged_conversation_id: str | None = None
    stage_uid: str | None = None
    if initial_pc_capture or initial_pc_drive_query or pc_files_requested or pc_browser_requested:
        from .claw_memory_routes import _resolve_memory_workspace
        stage_uid = current_user_id(request) if auth_ready(request) else None
        stage = getattr(
            getattr(request.app.state, "history_store", None),
            "record_txt_pending_run", None,
        )
        if not isinstance(stage_uid, str) or not stage_uid or not callable(stage):
            await _refund_active_reservation()
            await fail_first_turn_grant(request, first_turn_context)
            return _error(503, "desktop_history_unavailable",
                          "대화 저장소를 확인할 수 없습니다."), None
        try:
            stage_workspace = await _resolve_memory_workspace(request, stage_uid)
        except Exception:
            stage_workspace = None
        if not isinstance(stage_workspace, str) or not stage_workspace:
            await _refund_active_reservation()
            await fail_first_turn_grant(request, first_turn_context)
            return _error(503, "desktop_workspace_unavailable",
                          "대화 범위를 확인할 수 없습니다."), None
        try:
            staged_conversation_id = await stage(
                user_id=stage_uid, run_id=run.run_id,
                workspace_id=stage_workspace, user_text=user_text,
                conversation_id=conversation_id,
                **({"action": "pc_browser_query"} if pc_browser_requested else
                   {"action": "desktop_task"} if desktop_task_requested else {}),
            )
        except Exception:
            await _refund_active_reservation()
            await fail_first_turn_grant(request, first_turn_context)
            return _error(503, "desktop_history_unavailable",
                          "대화 저장에 실패했습니다."), None
    return None, {
        "staged_conversation_id": staged_conversation_id,
        "stage_uid": stage_uid,
    }


async def _claw_general_context_bundle(
    request: Request,
    user_text: str,
    grounding_context: Any,
    document_context: Any,
    pc_work_text: str | None,
    drive_context: Any,
    initial_pc_drive_query: bool,
    pc_files_requested: bool,
    pc_browser_requested: bool,
    stage_uid: str | None,
) -> tuple[JSONResponse | Response | None, dict[str, object] | None]:
    """#7814 4/4b: moved verbatim from the pre-refactor main.
    Every early return keeps its exact response as ``(response, None)``.
    """
    # #5015: the verified PC context travels on the same optional
    # `additional_system_context` seam grounding already uses. It is composed
    # server-side per request; the browser cannot supply or suppress it.
    # #2505: an attached document rides the same seam, as the same untrusted
    # reference data Chat already builds for its own turn.
    combined_system_context = _combine_system_context(
        grounding_context, document_context, pc_work_text,
    )
    # This side channel is assembled only from the signed owner's saved rows,
    # the actual latest user message and server-read external data. Browser
    # history and browser pc_action_context fields are never copied into it.
    pc_action_context = list(getattr(request.state, "claw_pc_action_context", (
        {"role": "user", "content": user_text},
    )))
    for content, source in (
        (grounding_context, "file" if drive_context is not None else "web"),
        (document_context, "file"),
    ):
        if content:
            pc_action_context.append({
                "role": "tool_result", "content": content, "source": source,
            })
    pc_delegation = None
    if initial_pc_drive_query or pc_files_requested or pc_browser_requested:
        from .pc_delegation_routes import load_pc_delegation

        # stage_uid is the authenticated owner whose PC run was just staged.
        # No browser delegation field participates in this decision snapshot.
        pc_delegation = await load_pc_delegation(request, stage_uid)
    return None, {
        "combined_system_context": combined_system_context,
        "pc_action_context": pc_action_context,
        "pc_delegation": pc_delegation,
    }
