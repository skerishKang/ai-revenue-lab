"""Chat model-turn connector tools: Drive READ + Calendar READ.

The model turn never received the connected Google connector tools: the
Engine resolves connector authority only on the execution path
(``worker_identity._tool_binding_resolver_for_env``), so the model answered
"현재 도구로는 Drive 접근 불가" even for a connected account. This module closes
the declaration side for the two approved READ tools only:

* the declaration schema is the Core canonical READ spec verbatim
  (``padiem_ai_core.drive_capability`` / ``padiem_ai_core.calendar_capability``)
  — the same specs the Engine registry registers, so declaration and
  execution point at the same tool;
* the model-facing tool name is a bounded alias because the provider
  function-name grammar rejects the canonical ``tool:google:...@1`` form;
  the alias→canonical mapping is a closed table pinned to the Core canonical
  id tuples at import time, never a heuristic;
* the grant check reuses the existing reviewed workspace truth
  (``connector_status_projection``) — no new grant store, identity or OAuth
  authority — and is bounded: per-user 30s memory cache, a 300ms budget,
  run concurrently with the PC tool offer. Unverified, absent, slow or failed
  checks declare nothing and never delay the turn;
* the cache is invalidated on disconnect and activation so a revoked
  connector cannot keep its declaration alive.

Gmail (#7088) and any scope widening (#4871) are explicitly out of scope.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from starlette.requests import Request

from padiem_ai_core.calendar_capability import (
    CALENDAR_CANONICAL_TOOL_IDS,
    CALENDAR_LIST_EVENTS_TOOL_ID,
    CALENDAR_READ_TOOL_IDS,
    calendar_read_tool_specs,
)
from padiem_ai_core.drive_capability import (
    DRIVE_CANONICAL_TOOL_IDS,
    DRIVE_READ_TOOL_IDS,
    DRIVE_SEARCH_FILES_TOOL_ID,
    drive_read_tool_specs,
)
from padiem_ai_core.tool_channel import ToolDefinition

from .connector_status_projection import (
    CALENDAR_READ_GRANT_ACTIVE,
    CALENDAR_READ_GRANT_INACTIVE,
    WORKSPACE_STATE_CONNECTED,
    _reviewed_calendar_read_grant_state,
    _reviewed_workspace_truth,
)
from .request_telemetry import emit_stage_event

_LOG = logging.getLogger("padiem_chat.connector_tools")

# The Engine pins the canonical connector app/agent provisioning identities in
# its connector_bindings (DRIVE_REFERENCE_APP_ID / DRIVE_AGENT_ID /
# CALENDAR_REFERENCE_APP_ID / CALENDAR_AGENT_ID). The Chat side repeats only
# these four closed identifiers — the same precedent as
# drive_case_folder_engine.PDF_BINARY_READ_APP_ID — and copies nothing else:
# tool ids and schemas come from Core below.
DRIVE_REFERENCE_APP_ID = "b54-padiem-claw-drive"
DRIVE_AGENT_ID = "agent:padiem:claw_drive_reader@1"
CALENDAR_REFERENCE_APP_ID = "b54-padiem-claw-calendar"
CALENDAR_AGENT_ID = "agent:padiem:claw_calendar_reader@1"

_DRIVE_SPEC_INDEX = {spec.id: spec for spec in drive_read_tool_specs()}
_CALENDAR_SPEC_INDEX = {spec.id: spec for spec in calendar_read_tool_specs()}
_DRIVE_SPEC = _DRIVE_SPEC_INDEX.get(DRIVE_SEARCH_FILES_TOOL_ID)
_CALENDAR_SPEC = _CALENDAR_SPEC_INDEX.get(CALENDAR_LIST_EVENTS_TOOL_ID)

# Provider function-call names reject ':'/'@', so each declaration carries a
# bounded alias and the lane resolves it through CONNECTOR_TOOL_BINDINGS.
DRIVE_READ_TOOL_NAME = "drive_read"
CALENDAR_READ_TOOL_NAME = "calendar_read"

_DRIVE_CANONICAL_ID = DRIVE_CANONICAL_TOOL_IDS[0]  # tool:google:drive.search_files@1
_CALENDAR_CANONICAL_ID = CALENDAR_CANONICAL_TOOL_IDS[2]  # tool:google:calendar.event_list@1

#: Closed alias -> (canonical Engine tool id, Engine app id, Engine agent id).
#: Execution authority stays Engine-side; this table only names the tool.
CONNECTOR_TOOL_BINDINGS: Mapping[str, tuple[str, str, str]] = {
    DRIVE_READ_TOOL_NAME: (_DRIVE_CANONICAL_ID, DRIVE_REFERENCE_APP_ID, DRIVE_AGENT_ID),
    CALENDAR_READ_TOOL_NAME: (
        _CALENDAR_CANONICAL_ID,
        CALENDAR_REFERENCE_APP_ID,
        CALENDAR_AGENT_ID,
    ),
}


def _require_reviewed_declarations() -> None:
    """Fail closed if the Core READ surface drifted from the reviewed mapping."""

    if _DRIVE_SPEC is None or _CALENDAR_SPEC is None:
        raise RuntimeError("core connector READ specs lost their reviewed entries")
    if DRIVE_READ_TOOL_IDS[0] != DRIVE_SEARCH_FILES_TOOL_ID:
        raise RuntimeError("core Drive READ spec order drifted from the canonical ids")
    if _DRIVE_CANONICAL_ID != "tool:google:drive.search_files@1":
        raise RuntimeError("core Drive canonical tool id drifted from the reviewed tool")
    if CALENDAR_READ_TOOL_IDS[2] != CALENDAR_LIST_EVENTS_TOOL_ID:
        raise RuntimeError("core Calendar READ spec order drifted from the canonical ids")
    if _CALENDAR_CANONICAL_ID != "tool:google:calendar.event_list@1":
        raise RuntimeError("core Calendar canonical tool id drifted from the reviewed tool")
    if CALENDAR_REFERENCE_APP_ID == DRIVE_REFERENCE_APP_ID:
        raise RuntimeError("connector app identities collapsed onto one id")


_require_reviewed_declarations()


#: The declared connector tools, in the bindings-table order (Drive, Calendar).
#: ``parameters`` is the Core input_schema verbatim — the schema the Engine's
#: own registry validates execution arguments against.
CONNECTOR_TOOL_DECLARATIONS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        name=DRIVE_READ_TOOL_NAME,
        description=_DRIVE_SPEC.description,
        parameters=dict(_DRIVE_SPEC.input_schema),
    ),
    ToolDefinition(
        name=CALENDAR_READ_TOOL_NAME,
        description=_CALENDAR_SPEC.description,
        parameters=dict(_CALENDAR_SPEC.input_schema),
    ),
)

_DECLARATION_BY_NAME = {
    declaration.name: declaration for declaration in CONNECTOR_TOOL_DECLARATIONS
}


def is_connector_tool_name(tool_name: Any) -> bool:
    """True only for this module's two declared alias names."""
    return isinstance(tool_name, str) and tool_name in CONNECTOR_TOOL_BINDINGS


GRANT_REASON_GRANTED = "granted"
GRANT_REASON_NOT_CONNECTED = "not_connected"
GRANT_REASON_UNVERIFIED = "unverified"
GRANT_REASON_TIMEOUT = "timeout"

#: Per-user memory cache for the bounded grant check.
CONNECTOR_TOOL_GRANT_TTL_SECONDS = 30.0
#: Hard budget for the truth read; a slower read declares nothing.
CONNECTOR_TOOL_GRANT_BUDGET_SECONDS = 0.3
_GRANT_CACHE_MAX_ENTRIES = 512

_GRANT_CACHE: dict[str, tuple[float, "ConnectorToolGrant"]] = {}


@dataclass(frozen=True, slots=True)
class ConnectorToolGrant:
    """The bounded per-turn connector declaration decision."""

    reason: str
    drive: bool
    calendar: bool


_UNDECLARED = ConnectorToolGrant(reason=GRANT_REASON_UNVERIFIED, drive=False, calendar=False)


def _tools_for_decision(decision: ConnectorToolGrant) -> tuple[ToolDefinition, ...]:
    if decision.reason != GRANT_REASON_GRANTED:
        return ()
    enabled = (decision.drive, decision.calendar)
    return tuple(
        declaration
        for declaration, on in zip(CONNECTOR_TOOL_DECLARATIONS, enabled)
        if on
    )


async def _grant_decision_for_uid(request: Request, *, uid: str) -> ConnectorToolGrant:
    """Ask the existing reviewed workspace truth about the two READ tools.

    Reuses ``connector_status_projection``'s reviewed resolution (product
    authentication first, then the canonical shadow and the Google OAuth
    truth). A missing or failed Calendar READ grant state never demotes the
    workspace answer: an unavailable check is not ``not_connected``.
    """

    overrides, _fallback_reason, authority, session_id = await _reviewed_workspace_truth(request)
    if not authority:
        return _UNDECLARED
    drive_state = (overrides.get("drive") or (None,))[0]
    calendar_state = (overrides.get("calendar") or (None,))[0]
    drive_ok = drive_state == WORKSPACE_STATE_CONNECTED
    calendar_ok = calendar_state == WORKSPACE_STATE_CONNECTED
    if calendar_ok:
        state = await _reviewed_calendar_read_grant_state(request, session_id)
        if state == CALENDAR_READ_GRANT_ACTIVE:
            calendar_ok = True
        elif state == CALENDAR_READ_GRANT_INACTIVE:
            calendar_ok = False
    if not drive_ok and not calendar_ok:
        return ConnectorToolGrant(
            reason=GRANT_REASON_NOT_CONNECTED, drive=False, calendar=False
        )
    return ConnectorToolGrant(
        reason=GRANT_REASON_GRANTED, drive=drive_ok, calendar=calendar_ok
    )


def _prune_grant_cache(now: float) -> None:
    if len(_GRANT_CACHE) < _GRANT_CACHE_MAX_ENTRIES:
        return
    for key in [
        key for key, (at, _decision) in _GRANT_CACHE.items()
        if now - at >= CONNECTOR_TOOL_GRANT_TTL_SECONDS
    ]:
        _GRANT_CACHE.pop(key, None)
    if len(_GRANT_CACHE) >= _GRANT_CACHE_MAX_ENTRIES:
        _GRANT_CACHE.clear()


def invalidate_connector_tool_grant_cache(uid: str | None = None) -> None:
    """Drop the cached decision after a disconnect or activation.

    ``uid=None`` clears every entry: used by routes that change connector
    state where the affected owner set is the whole cache's lifetime.
    """

    if uid is None:
        _GRANT_CACHE.clear()
    else:
        _GRANT_CACHE.pop(uid, None)


async def _bounded_grant_decision(
    request: Request, *, uid: str | None
) -> tuple[ConnectorToolGrant, float, bool]:
    """Resolve the decision inside the per-user cache and the hard budget.

    Returns ``(decision, elapsed_ms, timed_out)``. A timeout is never cached,
    so the next turn retries the check instead of staying tool-less for a
    full TTL after one slow read.
    """

    started = time.perf_counter()
    if not isinstance(uid, str) or not uid:
        return _UNDECLARED, 0.0, False
    cached = _GRANT_CACHE.get(uid)
    now = time.monotonic()
    if cached is not None and now - cached[0] < CONNECTOR_TOOL_GRANT_TTL_SECONDS:
        return cached[1], (time.perf_counter() - started) * 1000.0, False
    try:
        decision = await asyncio.wait_for(
            _grant_decision_for_uid(request, uid=uid),
            timeout=CONNECTOR_TOOL_GRANT_BUDGET_SECONDS,
        )
    except asyncio.TimeoutError:
        # A slow truth read never delays the turn and is never cached.
        elapsed = (time.perf_counter() - started) * 1000.0
        return (
            ConnectorToolGrant(reason=GRANT_REASON_TIMEOUT, drive=False, calendar=False),
            elapsed,
            True,
        )
    except Exception:  # noqa: BLE001 - a failed check declares nothing
        elapsed = (time.perf_counter() - started) * 1000.0
        return _UNDECLARED, elapsed, False
    now = time.monotonic()
    _prune_grant_cache(now)
    _GRANT_CACHE[uid] = (now, decision)
    return decision, (time.perf_counter() - started) * 1000.0, False


def _journal_decision(
    *, decision: ConnectorToolGrant, tool_count: int, elapsed_ms: float
) -> None:
    """One bounded journal line per turn (#6921 idiom).

    The line carries the declaration count, the closed reason label and the
    elapsed check time only: never the user identifier, never a file name,
    never calendar content, never tool arguments.
    """

    emit_stage_event(
        stage="chat.connector_tools",
        outcome="error" if tool_count == 0 else "ok",
        duration_ms=round(elapsed_ms, 1),
        code=decision.reason,
    )
    _LOG.info(
        "connector_tools declared=%d reason=%s",
        tool_count,
        decision.reason,
    )


async def connector_tools_for_turn(
    request: Request, *, uid: str | None
) -> tuple[ToolDefinition, ...]:
    """The connector tool declarations for this turn, or an empty tuple.

    Never raises and never exceeds the budget: every failure mode collapses
    to "declare nothing this turn" so the first token is never delayed.
    """

    try:
        decision, elapsed_ms, _timed_out = await _bounded_grant_decision(request, uid=uid)
    except Exception:  # noqa: BLE001 - the turn must proceed without tools
        _journal_decision(
            decision=_UNDECLARED, tool_count=0, elapsed_ms=0.0
        )
        return ()
    tools = _tools_for_decision(decision)
    _journal_decision(
        decision=decision, tool_count=len(tools), elapsed_ms=elapsed_ms
    )
    return tools


def connector_tool_arguments_ok(arguments: Any) -> bool:
    """The model's parsed arguments must be a bounded JSON object."""

    if not isinstance(arguments, Mapping) or isinstance(arguments, (str, bytes)):
        return False

    def _bounded(value: Any, depth: int = 0) -> bool:
        if depth > 8:
            return False
        if value is None or isinstance(value, (str, bool, int, float)):
            return True
        if isinstance(value, Mapping):
            return all(
                isinstance(key, str) and _bounded(item, depth + 1)
                for key, item in value.items()
            )
        if isinstance(value, (list, tuple)):
            return all(_bounded(item, depth + 1) for item in value)
        return False

    return _bounded(dict(arguments))


def connector_tool_request(tool_name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
    """The closed Engine execute request for one declared connector tool."""

    binding = CONNECTOR_TOOL_BINDINGS.get(tool_name)
    if binding is None:
        raise ValueError("undeclared connector tool")
    tool_id, app_id, agent_id = binding
    return {
        "app_id": app_id,
        "agent_id": agent_id,
        "tool_id": tool_id,
        "arguments": dict(arguments),
    }


# Only an explicitly Google-named connector question routes between lanes.
# "일정" alone stays with the workspace-native calendar and "드라이브" alone
# stays with the PC lane; "구글 캘린더"/"구글 드라이브" (or the English forms)
# name this product's Google connector tools.
_GOOGLE_CONNECTOR_INTENT = re.compile(
    r"구글\s*캘린더|구글\s*드라이브|google\s*calendar|google\s*drive",
    re.IGNORECASE,
)


def google_connector_intent(user_text: Any) -> bool:
    """True only when the turn's own words explicitly name a Google connector."""

    return isinstance(user_text, str) and bool(_GOOGLE_CONNECTOR_INTENT.search(user_text))


async def connector_tools_granted_for_fallback(request: Request, *, uid: str | None) -> bool:
    """The orchestration-path connector-intent guard.

    Reuses the main turn's bounded decision (30s per-user cache, 300ms budget,
    same journal line): True only when a verified authority said the Drive or
    Calendar READ grant is connected, so the orchestration lane can hand the
    turn to the main chat turn that declares the connector tools. Every
    failure mode answers False — grant-less owners keep the search path
    exactly as it is.
    """

    decision, elapsed_ms, _timed_out = await _bounded_grant_decision(request, uid=uid)
    granted = decision.reason == GRANT_REASON_GRANTED
    emit_stage_event(
        stage="chat.connector_tools",
        outcome="ok" if granted else "error",
        duration_ms=round(elapsed_ms, 1),
        code=decision.reason,
    )
    _LOG.info(
        "connector_tools orchestration_fallback=%s reason=%s",
        granted,
        decision.reason,
    )
    return granted
