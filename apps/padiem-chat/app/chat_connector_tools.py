"""Chat model-turn connector tools: Drive READ + Calendar READ + Gmail READ.

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
* Gmail (#7088) follows the same shape with two READ tools — mail search
  and one-message read. Send, drafts and deletion are out of scope; the
  journal records counts only, never a mail body, subject or sender;
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
from padiem_ai_core.connectors import (
    GMAIL_CANONICAL_TOOL_IDS,
    GMAIL_GET_MESSAGE_TOOL_ID,
    GMAIL_SEARCH_MESSAGES_TOOL_ID,
    gmail_read_tool_specs,
)
from padiem_ai_core.drive_capability import (
    DRIVE_CANONICAL_TOOL_IDS,
    DRIVE_READ_TOOL_IDS,
    DRIVE_SEARCH_FILES_TOOL_ID,
    drive_read_tool_specs,
)
from padiem_ai_core.gmail_capability import GMAIL_READ_TOOL_IDS
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
# CALENDAR_REFERENCE_APP_ID / CALENDAR_AGENT_ID / GMAIL_REFERENCE_APP_ID). The
# Chat side repeats only these five closed provisioning identifiers — the same
# precedent as drive_case_folder_engine.PDF_BINARY_READ_APP_ID — and copies
# nothing else: tool ids and schemas come from Core below. The Gmail agent id
# is the reviewed canary provisioning value (a14_gmail_read_production_canary).
DRIVE_REFERENCE_APP_ID = "b54-padiem-claw-drive"
DRIVE_AGENT_ID = "agent:padiem:claw_drive_reader@1"
CALENDAR_REFERENCE_APP_ID = "b54-padiem-claw-calendar"
CALENDAR_AGENT_ID = "agent:padiem:claw_calendar_reader@1"
GMAIL_REFERENCE_APP_ID = "b54-padiem-claw"
GMAIL_AGENT_ID = "agent:padiem:claw_mail_reader@1"

_DRIVE_SPEC_INDEX = {spec.id: spec for spec in drive_read_tool_specs()}
_CALENDAR_SPEC_INDEX = {spec.id: spec for spec in calendar_read_tool_specs()}
_GMAIL_SPEC_INDEX = {spec.id: spec for spec in gmail_read_tool_specs()}
_DRIVE_SPEC = _DRIVE_SPEC_INDEX.get(DRIVE_SEARCH_FILES_TOOL_ID)
_CALENDAR_SPEC = _CALENDAR_SPEC_INDEX.get(CALENDAR_LIST_EVENTS_TOOL_ID)
_GMAIL_SEARCH_SPEC = _GMAIL_SPEC_INDEX.get(GMAIL_SEARCH_MESSAGES_TOOL_ID)
_GMAIL_GET_SPEC = _GMAIL_SPEC_INDEX.get(GMAIL_GET_MESSAGE_TOOL_ID)

# Provider function-call names reject ':'/'@', so each declaration carries a
# bounded alias and the lane resolves it through CONNECTOR_TOOL_BINDINGS.
DRIVE_READ_TOOL_NAME = "drive_read"
CALENDAR_READ_TOOL_NAME = "calendar_read"
GMAIL_SEARCH_TOOL_NAME = "gmail_search"
GMAIL_READ_TOOL_NAME = "gmail_read"

_DRIVE_CANONICAL_ID = DRIVE_CANONICAL_TOOL_IDS[0]  # tool:google:drive.search_files@1
_CALENDAR_CANONICAL_ID = CALENDAR_CANONICAL_TOOL_IDS[2]  # tool:google:calendar.event_list@1
_GMAIL_SEARCH_CANONICAL_ID = GMAIL_CANONICAL_TOOL_IDS[0]  # tool:google:gmail.search_messages@1
_GMAIL_GET_CANONICAL_ID = GMAIL_CANONICAL_TOOL_IDS[1]  # tool:google:gmail.get_message@1

#: Closed alias -> (canonical Engine tool id, Engine app id, Engine agent id).
#: Execution authority stays Engine-side; this table only names the tool.
CONNECTOR_TOOL_BINDINGS: Mapping[str, tuple[str, str, str]] = {
    DRIVE_READ_TOOL_NAME: (_DRIVE_CANONICAL_ID, DRIVE_REFERENCE_APP_ID, DRIVE_AGENT_ID),
    CALENDAR_READ_TOOL_NAME: (
        _CALENDAR_CANONICAL_ID,
        CALENDAR_REFERENCE_APP_ID,
        CALENDAR_AGENT_ID,
    ),
    GMAIL_SEARCH_TOOL_NAME: (
        _GMAIL_SEARCH_CANONICAL_ID,
        GMAIL_REFERENCE_APP_ID,
        GMAIL_AGENT_ID,
    ),
    GMAIL_READ_TOOL_NAME: (_GMAIL_GET_CANONICAL_ID, GMAIL_REFERENCE_APP_ID, GMAIL_AGENT_ID),
}


def _require_reviewed_declarations() -> None:
    """Fail closed if the Core READ surface drifted from the reviewed mapping."""

    if _DRIVE_SPEC is None or _CALENDAR_SPEC is None or _GMAIL_SEARCH_SPEC is None or _GMAIL_GET_SPEC is None:
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
    if GMAIL_READ_TOOL_IDS[0] != GMAIL_SEARCH_MESSAGES_TOOL_ID:
        raise RuntimeError("core Gmail READ spec order drifted from the canonical ids")
    if GMAIL_READ_TOOL_IDS[1] != GMAIL_GET_MESSAGE_TOOL_ID:
        raise RuntimeError("core Gmail READ spec order drifted from the canonical ids")
    if _GMAIL_SEARCH_CANONICAL_ID != "tool:google:gmail.search_messages@1":
        raise RuntimeError("core Gmail canonical tool id drifted from the reviewed tool")
    if _GMAIL_GET_CANONICAL_ID != "tool:google:gmail.get_message@1":
        raise RuntimeError("core Gmail canonical tool id drifted from the reviewed tool")
    if GMAIL_REFERENCE_APP_ID == DRIVE_REFERENCE_APP_ID or GMAIL_REFERENCE_APP_ID == CALENDAR_REFERENCE_APP_ID:
        raise RuntimeError("connector app identities collapsed onto one id")


_require_reviewed_declarations()


#: The declared connector tools: Drive READ, Calendar READ, then the two Gmail
#: READ tools (search + read one message). ``parameters`` is the Core
#: input_schema verbatim — the schema the Engine's own registry validates
#: execution arguments against.
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
    ToolDefinition(
        name=GMAIL_SEARCH_TOOL_NAME,
        description=_GMAIL_SEARCH_SPEC.description,
        parameters=dict(_GMAIL_SEARCH_SPEC.input_schema),
    ),
    ToolDefinition(
        name=GMAIL_READ_TOOL_NAME,
        description=_GMAIL_GET_SPEC.description,
        parameters=dict(_GMAIL_GET_SPEC.input_schema),
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

#: Per-user memory cache for the bounded grant check. Production measurement
#: (main 2e2fab26): the workspace truth costs ~2.7s end to end, so a granted
#: answer is worth keeping for five minutes while an absent answer stays
#: short-lived; a timeout or failed check is never cached.
CONNECTOR_TOOL_GRANT_GRANTED_TTL_SECONDS = 300.0
CONNECTOR_TOOL_GRANT_NOT_CONNECTED_TTL_SECONDS = 30.0
#: Hard budget for the truth read on a connector-intent turn (explicit Google
#: naming or a broad read intent). The measured /api/connectors/status path
#: (identity resolve + Google RPC) needs seconds, not milliseconds; a general
#: turn pays no check at all.
CONNECTOR_TOOL_GRANT_INTENT_BUDGET_SECONDS = 3.0
_GRANT_CACHE_MAX_ENTRIES = 512

_GRANT_CACHE: dict[str, tuple[float, "ConnectorToolGrant"]] = {}


@dataclass(frozen=True, slots=True)
class ConnectorToolGrant:
    """The bounded per-turn connector declaration decision."""

    reason: str
    drive: bool
    calendar: bool
    gmail: bool = False


_UNDECLARED = ConnectorToolGrant(
    reason=GRANT_REASON_UNVERIFIED, drive=False, calendar=False, gmail=False
)


def _cache_ttl_for(decision: ConnectorToolGrant) -> float:
    """The per-reason cache lifetime; a non-positive value means never cache."""

    if decision.reason == GRANT_REASON_GRANTED:
        return CONNECTOR_TOOL_GRANT_GRANTED_TTL_SECONDS
    if decision.reason == GRANT_REASON_NOT_CONNECTED:
        return CONNECTOR_TOOL_GRANT_NOT_CONNECTED_TTL_SECONDS
    return 0.0


def _tools_for_decision(decision: ConnectorToolGrant) -> tuple[ToolDefinition, ...]:
    if decision.reason != GRANT_REASON_GRANTED:
        return ()
    enabled = (decision.drive, decision.calendar, decision.gmail, decision.gmail)
    return tuple(
        declaration
        for declaration, on in zip(CONNECTOR_TOOL_DECLARATIONS, enabled)
        if on
    )


async def _grant_decision_for_uid(request: Request, *, uid: str) -> ConnectorToolGrant:
    """Ask the existing reviewed workspace truth about the READ tools.

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
    gmail_state = (overrides.get("gmail") or (None,))[0]
    drive_ok = drive_state == WORKSPACE_STATE_CONNECTED
    calendar_ok = calendar_state == WORKSPACE_STATE_CONNECTED
    gmail_ok = gmail_state == WORKSPACE_STATE_CONNECTED
    if calendar_ok:
        state = await _reviewed_calendar_read_grant_state(request, session_id)
        if state == CALENDAR_READ_GRANT_ACTIVE:
            calendar_ok = True
        elif state == CALENDAR_READ_GRANT_INACTIVE:
            calendar_ok = False
    if not drive_ok and not calendar_ok and not gmail_ok:
        return ConnectorToolGrant(
            reason=GRANT_REASON_NOT_CONNECTED, drive=False, calendar=False, gmail=False
        )
    return ConnectorToolGrant(
        reason=GRANT_REASON_GRANTED, drive=drive_ok, calendar=calendar_ok, gmail=gmail_ok
    )


def _prune_grant_cache(now: float) -> None:
    if len(_GRANT_CACHE) < _GRANT_CACHE_MAX_ENTRIES:
        return
    for key in [
        key for key, (at, decision) in _GRANT_CACHE.items()
        if now - at >= _cache_ttl_for(decision)
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
    request: Request, *, uid: str | None,
    budget: float = CONNECTOR_TOOL_GRANT_INTENT_BUDGET_SECONDS,
) -> tuple[ConnectorToolGrant, float, bool]:
    """Resolve the decision inside the per-user cache and the hard budget.

    Returns ``(decision, elapsed_ms, timed_out)``. A timeout and a failed
    check are never cached, so the next turn retries the check instead of
    staying tool-less for a full TTL after one slow read.
    """

    started = time.perf_counter()
    if not isinstance(uid, str) or not uid:
        return _UNDECLARED, 0.0, False
    cached = _GRANT_CACHE.get(uid)
    now = time.monotonic()
    if cached is not None and now - cached[0] < _cache_ttl_for(cached[1]):
        return cached[1], (time.perf_counter() - started) * 1000.0, False
    try:
        decision = await asyncio.wait_for(
            _grant_decision_for_uid(request, uid=uid),
            timeout=budget,
        )
    except asyncio.TimeoutError:
        # A slow truth read is never cached: the next turn retries the check.
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
    if _cache_ttl_for(decision) > 0:
        _GRANT_CACHE[uid] = (now, decision)
    return decision, (time.perf_counter() - started) * 1000.0, False


def seed_connector_grant_cache(uid: str | None, decision: ConnectorToolGrant) -> None:
    """Fill the per-user cache from a truth answer computed elsewhere.

    The ``/api/connectors/status`` projection already pays the identity and
    Google RPCs for its own document; when its trusted answer is cacheable,
    the next connector-intent turn reads this cache at 0ms instead of
    re-asking. Uncacheable decisions (timeout, unverified) are ignored.
    """

    if not isinstance(uid, str) or not uid:
        return
    if _cache_ttl_for(decision) <= 0:
        return
    now = time.monotonic()
    _prune_grant_cache(now)
    _GRANT_CACHE[uid] = (now, decision)


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
    # One always-visible journal line: the host captures stdout, while the
    # telemetry emitter only prints failures and the logger has no handler on
    # the host. The line names the declaration count, the closed reason label
    # and the elapsed check time only — never a user identifier, file name,
    # calendar content or mail content.
    print(
        f"connector_tools declared={tool_count} reason={decision.reason} "
        f"check_ms={round(elapsed_ms, 1)}",
        flush=True,
    )


async def connector_tools_for_turn(
    request: Request, *, uid: str | None, intent_turn: bool,
) -> tuple[ToolDefinition, ...]:
    """The connector tool declarations for this turn, or an empty tuple
    (Drive READ, Calendar READ, Gmail search + read).

    A general turn never pays the grant check: the tools are declared only on
    a connector-intent turn (explicit Google naming, or a broad read intent
    whose named service is granted), whose check may wait up to
    ``CONNECTOR_TOOL_GRANT_INTENT_BUDGET_SECONDS`` for the same truth the
    connection screen shows. Never raises: every failure mode collapses to
    "declare nothing this turn".
    """

    if not intent_turn:
        return ()
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
# stays with the PC lane; "구글 캘린더"/"구글 드라이브"/"지메일"/"구글 메일"
# (or the English forms) name this product's Google connector tools.
_GOOGLE_CONNECTOR_INTENT = re.compile(
    r"구글\s*캘린더|구글\s*드라이브|구글\s*메일|지메일|gmail|google\s*calendar|google\s*drive",
    re.IGNORECASE,
)

# Broad read intents are deliberately narrower than "any sentence containing a
# calendar or file word". They are only promoted after the named service's
# grant check says connected, so a non-connected owner keeps the native
# calendar / PC lane exactly as before. Creation, editing, how-to and general
# knowledge questions are refused here and stay on their existing path.
_CALENDAR_BROAD_TIME = re.compile(
    r"(?:오늘|어제|내일|모레|지난\s*주|이번\s*주|다음\s*주|지난\s*달|이번\s*달|다음\s*달|"
    r"이번\s*주말|다음\s*주말|주말|(?:월|화|수|목|금|토|일)요일|"
    r"오전|오후|\d{1,2}\s*시(?!간)|\d{1,2}월\s*\d{1,2}일)"
)
_CALENDAR_BROAD_NOUN = re.compile(
    r"(?:일정(?!한|하|된|되|적)|스케줄(?!러)|약속(?!한|하|된|되)|"
    r"회의(?!록|적|실)|미팅|캘린더)"
)
_CALENDAR_BROAD_QUERY = re.compile(
    r"(?:뭐|무슨|알려|보여|조회|확인|있어|있나|몇\s*(?:개|건)|어때|언제|어디|"
    r"정리|요약|검색|찾아|[?？])"
)
_CALENDAR_BROAD_CREATE = re.compile(r"(?:잡아|등록|추가|생성|만들|예약|변경|취소|삭제)")

_DRIVE_BROAD_LOCATOR = re.compile(r"(?:드라이브|내\s*드라이브)")
_DRIVE_BROAD_PERSONAL = re.compile(r"내\s*파일")
_DRIVE_BROAD_NOUN = re.compile(
    r"(?:파일|문서|폴더|견적서|보고서|자료|사진|스프레드시트|프레젠테이션|시트)"
)
_DRIVE_BROAD_READ = re.compile(
    r"(?:찾아|검색|보여|열어|확인|조회|목록|뭐가|어디|올린|공유된|공유한|"
    r"저장한|업로드한|받은)"
)
_DRIVE_BROAD_TIME = re.compile(
    r"(?:오늘|어제|지난\s*주|지난\s*달|이번\s*주|이번\s*달|최근|올린|공유된|공유한|"
    r"저장한|업로드한)"
)
_DRIVE_BROAD_WRITE = re.compile(r"(?:올려|업로드해|저장해|삭제|이동|공유해|편집|수정|만들어|작성해)")
_GENERAL_HOWTO = re.compile(
    r"(?:방법|(?:하는|쓰는|지키는|정리하는|관리하는|찾는|여는|고치는|작성하는|사용하는)\s*법|"
    r"작성법|가이드|뜻|의미|차이|how\s*to)",
    re.IGNORECASE,
)


def _calendar_broad_read_intent(text: str) -> bool:
    if _CALENDAR_BROAD_CREATE.search(text):
        return False
    return bool(
        _CALENDAR_BROAD_TIME.search(text)
        and _CALENDAR_BROAD_NOUN.search(text)
        and _CALENDAR_BROAD_QUERY.search(text)
    )


def _drive_broad_read_intent(text: str) -> bool:
    if _DRIVE_BROAD_WRITE.search(text):
        return False
    locator = _DRIVE_BROAD_LOCATOR.pattern
    personal = _DRIVE_BROAD_PERSONAL.pattern
    noun = _DRIVE_BROAD_NOUN.pattern
    read = _DRIVE_BROAD_READ.pattern
    time_marker = _DRIVE_BROAD_TIME.pattern
    if re.search(rf"(?:{locator}).{{0,40}}(?:{noun}|{read})", text):
        return True
    if re.search(rf"(?:{noun}|{read}).{{0,40}}(?:{locator})", text):
        return True
    if re.search(rf"(?:{personal}).{{0,40}}(?:{read})", text):
        return True
    if re.search(rf"(?:{noun}).{{0,24}}(?:{read})", text):
        return True
    if re.search(rf"(?:{read}).{{0,24}}(?:{noun})", text):
        return True
    if re.search(rf"(?:{time_marker}).{{0,24}}(?:{noun})", text):
        return True
    return False


def google_connector_intent(user_text: Any) -> bool:
    """True only when the turn's own words explicitly name a Google connector."""

    return isinstance(user_text, str) and bool(_GOOGLE_CONNECTOR_INTENT.search(user_text))


def google_connector_broad_intent(user_text: Any) -> str | None:
    """The broad READ service for this turn, or None.

    Only ``calendar`` and ``drive`` are broadened; Gmail keeps its explicit
    naming rule. Explicit Google naming is handled by ``google_connector_intent``
    and is not repeated here. The caller must still require the named service's
    grant before treating the result as a connector turn.
    """

    if not isinstance(user_text, str):
        return None
    text = user_text.strip()
    if not text or _GOOGLE_CONNECTOR_INTENT.search(text) or _GENERAL_HOWTO.search(text):
        return None
    if _drive_broad_read_intent(text):
        return "drive"
    if _calendar_broad_read_intent(text):
        return "calendar"
    return None


async def google_connector_turn_for_text(
    request: Request, *, uid: str | None, user_text: Any,
) -> bool:
    """Whether this chat turn should use the connector READ tools.

    Explicit Google naming keeps its existing path; the declaration's own
    grant check still runs later. A broad read intent is promoted only when
    the named service is actually granted, so a non-connected owner keeps the
    native calendar / PC lane. The decision is cached for the declaration call
    that follows.
    """

    if google_connector_intent(user_text):
        return True
    service = google_connector_broad_intent(user_text)
    if service is None or not isinstance(uid, str) or not uid:
        return False
    decision, _elapsed_ms, _timed_out = await _bounded_grant_decision(request, uid=uid)
    return decision.reason == GRANT_REASON_GRANTED and bool(getattr(decision, service, False))


async def connector_tools_granted_for_fallback(
    request: Request, *, uid: str | None, service: str | None = None,
) -> bool:
    """The orchestration-path connector-intent guard.

    The caller has already matched an explicit Google name or a broad read
    intent. The decision reuses the same per-user cache (granted 5min /
    not_connected 30s) and the 3s intent budget, and journals one line. True
    only when a verified authority said the named READ grant is connected;
    without ``service``, any READ grant (the explicit Google path), so the
    orchestration lane can hand the turn to the main chat turn that declares
    the connector tools. Every failure mode answers False — grant-less owners
    keep the search path exactly as it is.
    """

    decision, elapsed_ms, _timed_out = await _bounded_grant_decision(request, uid=uid)
    granted = decision.reason == GRANT_REASON_GRANTED
    if granted and service is not None:
        granted = bool(getattr(decision, service, False))
    emit_stage_event(
        stage="chat.connector_tools",
        outcome="ok" if granted else "error",
        duration_ms=round(elapsed_ms, 1),
        code=decision.reason,
    )
    _LOG.info(
        "connector_tools orchestration_fallback=%s reason=%s service=%s",
        granted,
        decision.reason,
        service or "any",
    )
    return granted
