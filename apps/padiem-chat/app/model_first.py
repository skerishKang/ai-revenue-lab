"""Model-first answer path (#4651).

When ``PADIEM_CHAT_MODEL_FIRST`` is on, the answer model receives the question
and the server-composed tool list in one B14 call. A text answer is used
directly; only a model tool call enters the existing P01 execution lane. The
switch is off by default and the route keeps its existing engine path when off.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .worker_config import binding_value

MODEL_FIRST_FLAG_ENV = "PADIEM_CHAT_MODEL_FIRST"
PATH_ENGINE = "engine"
PATH_DIRECT = "model_first_direct"
PATH_TOOL = "model_first_tool"
PATHS = frozenset({PATH_ENGINE, PATH_DIRECT, PATH_TOOL})


def model_first_enabled(source: Any) -> bool:
    """Server-owned switch; Worker bindings and host env read the same value."""

    value = binding_value(source, MODEL_FIRST_FLAG_ENV)
    return (value.strip() if isinstance(value, str) else "").lower() in {
        "1",
        "true",
        "on",
    }


def model_supports_pc_tools(model_id: Any) -> bool:
    """Whether the resolved route may receive the closed PC tool set."""

    from .chat_pc_drive import PC_TOOL_EXCLUDED_MODEL_PREFIXES

    return (
        isinstance(model_id, str)
        and bool(model_id)
        and not model_id.startswith(PC_TOOL_EXCLUDED_MODEL_PREFIXES)
    )


def pc_tools_for_context(
    pc_context: Any, user_text: Any,
) -> tuple[Any, ...]:
    """The model-visible subset of the verified PC scope, or an empty tuple.

    The scopes come from the same server-derived ``pc_context`` the existing PC
    lane uses. The model's later tool request is only a name: the lane
    re-verifies owner, grant, target and scope before executing anything.
    """

    if not isinstance(pc_context, Mapping):
        return ()
    pc_tools = pc_context.get("pc_tools")
    if not isinstance(pc_tools, Mapping):
        return ()
    scopes = pc_tools.get("allowed_scopes")
    if not isinstance(scopes, (list, tuple)):
        return ()
    allowed = {scope for scope in scopes if isinstance(scope, str)}
    if not allowed:
        return ()
    from .chat_pc_drive import (
        CHAT_PC_TOOL_DEFINITIONS,
        PC_WRITE_TOOL_DEFINITION,
        pc_write_intent,
    )

    tools = tuple(
        tool for tool in CHAT_PC_TOOL_DEFINITIONS if tool.name in allowed
    )
    if "files_write" in allowed and pc_write_intent(user_text):
        tools = tools + (PC_WRITE_TOOL_DEFINITION,)
    return tools


async def execute_model_first_tool(
    request: Any,
    *,
    tool_name: str,
    policy: Any,
    messages: list[dict[str, str]],
    skill: Any,
    raw: Mapping[str, Any],
    user_text: str,
    conversation_id: str | None,
    store: Any,
    grounding_context: str | None,
):
    """Delegate one model-selected tool to the existing P01 PC lane.

    The orchestration surface itself owns no executor or target store. The
    model's name is the only input; the existing lane re-verifies the owner,
    grant, PC target and scope before dispatching to the Engine.
    """

    from .chat_pc_drive import execute_chat_pc_drive_lane
    from .pc_action_context import build_pc_action_context

    execution_user_text = next(
        (
            item.get("content")
            for item in reversed(policy.messages)
            if isinstance(item, dict) and item.get("role") == "user"
        ),
        None,
    )
    return await execute_chat_pc_drive_lane(
        request,
        user_text=user_text,
        execution_user_text=execution_user_text,
        skill=skill,
        model_id=policy.model_id,
        conversation_id=conversation_id,
        device_id=raw.get("device_id"),
        run_id=raw.get("pc_run_id"),
        conversation_messages=messages,
        pc_action_context=build_pc_action_context(
            messages,
            user_text=user_text,
            trusted_history=(conversation_id is not None and store is not None),
            tool_results=(("web", grounding_context),),
        ),
        selected_tool=tool_name,
    )


def pc_context_is_relevant(user_text: Any, *, requested_device: bool) -> bool:
    """Whether this turn should carry the rendered PC work context.

    A general question without a selected/requested PC keeps its exact old
    context and pays no extra device read. A PC-explicit turn (including one
    whose selected PC is offline) carries the server notice.
    """

    from .chat_pc_drive import pc_explicit_request

    return pc_explicit_request(
        user_text, named_device=False, requested_device=requested_device,
    )


async def model_first_context(
    request: Any, *, owner_id: str, grounding_context: str | None,
) -> str | None:
    """The trusted context for the direct answer model.

    The server-rendered PC work context is included even when no tool is
    offered, so an offline selected PC is explained as an offline PC instead
    of being guessed as an account permission failure.
    """

    pc_text: str | None = None
    try:
        from .pc_work_context import build_pc_work_context_text

        rendered = await build_pc_work_context_text(request, owner_id=owner_id)
        if isinstance(rendered, str) and rendered.strip():
            pc_text = rendered
    except Exception:
        pc_text = None
    parts = [
        part.strip()
        for part in (grounding_context, pc_text)
        if isinstance(part, str) and part.strip()
    ]
    return "\n\n".join(parts) or None
