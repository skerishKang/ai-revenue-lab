#!/usr/bin/env python3
"""#5895: one real PC request through the product lane, so connector stability is a number.

The deploy gates prove a version is served. Nothing proved that a paired PC still
answers, which is the thing an owner feels as "the connector broke". This canary
signs in as the existing production QA identity, asks the PC that account has for its
drive list (inside the granted scope), and waits until the result arrives. It reports
one line: verdict, entry count, elapsed seconds, failure code.

Sign-in reuses the common login route the daily real-usage check already uses
(#7078): ``shared_login_client.login_session_cookie`` tries the direct Chat
email login and, when the server answers 409 ``email_login_moved``, follows
the same common login form the browser_shared_login flow drives. No new login
method is invented here.

The lane is the one the composer itself uses (#4469): ``POST /api/orchestration`` with
a client-minted ``chat_pcq_<32hex>`` run id, so the durable run row is addressable
from the first instant. The wait is the #5983 read-back —
``GET /api/claw/runs/<run_id>/pending-result``. Two different waits are kept apart
here, because the owner standard keeps them apart: the PC's WORK carries no ceiling
(this canary never interrupts a running command, and #6073 accepts its result late),
while this MONITOR's patience is bounded by ``RESULT_WAIT_CEILING_SECONDS`` (#82
standard 4: a stop must be known within ten minutes). Before that bound existed, a
stalled executor kept the run ``pending``, this script never printed a verdict, and
the runner's own 35-minute ceiling ended the hour with nothing recorded anywhere.

What is measured:
    PASS        the run this turn asked for completed with a verified PC command
                result, and its lines are counted. The verdict is the owner's own
                durable read (``GET /api/claw/runs/<run_id>/pending-result``), not a
                frame in the answer: the operating lane answers in text when the
                model selected no tool, so a stream shape alone would report a
                healthy PC as a broken one (2026-11-16: the lane was open,
                ``pc_lane_closed=none``, and the turn ended as a text answer).
                The legacy SSE PC lane, which the server takes only when the
                model-first lane declines the turn, ends at the same read.
    FAIL        any other end, named: no dispatch result behind the answer, the run
                failed or was cancelled, no run row exists for the id this turn
                minted (code=pc_lane_not_offered: no PC tool ran, whether the lane
                was closed or the model answered in text), a read that cannot see
                the run, or the monitor's own bound expiring while the server still
                calls the run unfinished (code=pc_result_wait_ceiling)
    SKIP_NO_PC  the QA account has no active paired PC — reported as a named end,
                and no longer as a quiet success: since 2026-11-16 this script
                exits non-zero for it, because "measured nothing" must never look
                like "the PC is fine" (the canary spent 11-05 → 11-15 doing
                exactly that).
                A state word this script does not recognise is a FAIL
                (``pairing_state_unrecognized``), never a SKIP.

Only the pre-existing QA identity is used (`QA_MANUAL_USERNAME` /
`QA_MANUAL_PASSWORD` — the same names the post-deploy chat smoke signs in with),
the transport and its byte and line guards are the existing long-context canary's, and
the QA conversation is deleted afterwards exactly as the smoke deletes it. No answer
text, no device label, no cookie and no credential value is ever printed: counts,
seconds and error-code names only. This workflow deploys nothing and rolls nothing
back.
"""
from __future__ import annotations

import http.cookiejar
import json
import os
import re
import secrets
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPCookieProcessor

sys.path.insert(0, str(Path(__file__).resolve().parent))

from b62_live_long_context_canary import (  # noqa: E402  (sibling script import)
    CHAT_TIMEOUT_SECONDS,
    CONVERSATION,
    ORIGIN,
    RESPONSE_BYTES_CAP,
    STATUS,
    STREAM_LINE_CAP,
    CanaryError,
    bounded_call,
    error_code,
)
from b62_live_long_context_canary import _ID as CONVERSATION_ID  # noqa: E402
from shared_login_client import (  # noqa: E402  (sibling script import)
    SESSION_COOKIE as SESSION_COOKIE_NAME,
    SharedLoginError,
    login_session_cookie,
)

ORCHESTRATION = "/api/orchestration"
PAIRINGS = "/api/pc/pairings"
DEVICES = "/api/claw/local-access/devices"
#: The screen's own "which PC" save. The canary keeps no browser, so the
#: preference a person would have stored is stored here for this one account.
DEVICE_SELECT = "/api/claw/local-access/devices/select"
PENDING_RESULT_PATH = "/api/claw/runs/{run_id}/pending-result"
#: The composer's own answer request shape: the screen asks for NDJSON lines.
NDJSON_ACCEPT = "application/x-ndjson"
#: Progress-frame kinds a model-selected tool run leaves in that stream. They are
#: reported, never judged: the public durable read is the verdict (#7841).
TOOL_FRAME_KINDS = frozenset({"tool_started", "tool_completed", "tool_failed"})
#: A read that cannot see the run at all: on the model-first lane a turn whose tool
#: never ran leaves no run for this id, which is the old verdict name.
RUN_ABSENT_CODES = frozenset({"pc_run_not_staged"})
PC_LANE_NOT_OFFERED = "pc_lane_not_offered"
QA_USERNAME_ENV = "QA_MANUAL_USERNAME"
QA_PASSWORD_ENV = "QA_MANUAL_PASSWORD"
PC_RUN_ID = re.compile(r"\Achat_pcq_[0-9a-f]{32}\Z")
#: The PC identity grammar, copied from ``padiem_ai_core.pc_device_identity``:
#: a bare device id or a composed ``node/...`` Mesh identity, never a path.
DEVICE_ID_RE = re.compile(
    r"\A(?:[A-Za-z0-9_.$:@+-]{1,128}"
    r"|node/[A-Za-z0-9._-]{0,64}/[A-Za-z0-9_.$:@+-]{1,128})\Z"
)
#: A pairing whose PC is not connected leaves nothing real to ask.
NO_USABLE_DEVICE = "no_usable_pc_device"
#: Saving the screen's own preference is a write; a failure to save is named.
DEVICE_SELECT_UNSAVED = "device_selection_not_saved"
_SAFE_CODE = re.compile(r"\A[a-z][a-z0-9_]{0,40}\Z")
PROMPT = (
    "커넥터 점검입니다. 연결된 PC의 드라이브 목록만 알려 주세요. "
    "파일 내용은 읽지 않고, 어떤 파일도 변경하지 않습니다."
)
#: The link label is read to be *said*, never printed: naming the machine is how
#: the server learns which PC this turn means when the account keeps no saved
#: selection (a browser keeps one; this canary has none).
LABEL_MAX_CHARS = 80
# The product's own status-read cadence: the PC step driver and the browser recovery
# both space read-only polls by 2 seconds. It spaces GETs and never ends the wait, so
# it is not a deadline.
POLL_INTERVAL_SECONDS = 2.0
UNANSWERED_STATUSES = frozenset({"pending", "running"})
TERMINAL_FAILURE_STATUSES = frozenset({"failed", "cancelled"})
#: #82: how long this MONITOR is willing to wait for an answer. Standard 1 keeps the
#: PC's own work free of any ceiling — the dispatch this canary started stays alive,
#: keeps its lease (#5997) and is still accepted when it answers late (#6073) — and
#: standard 4 requires a stop to be known within ten minutes. Those are two different
#: objects, so only the second one gets a bound here. Before this, the wait ended on
#: the server's terminal status or not at all: when the executor stalled on 2026-10-29
#: the run stayed ``pending``, this step never printed a verdict, and the runner's own
#: 35-minute ceiling swallowed the hour with no signal anywhere.
RESULT_WAIT_CEILING_SECONDS = 600
#: The status words the durable result route can actually name (#5983 read-back).
#: A verdict reads one of these and nothing else: a safe-shaped string is not a safe
#: value, and a long hex handle is exactly what was once misread out of log text.
REPORTABLE_RUN_STATUSES = UNANSWERED_STATUSES | TERMINAL_FAILURE_STATUSES | frozenset({
    "completed", "paused",
})
#: The status word the server itself reported last, when it reported one of these.
_UNKNOWN_STATUS = "unknown"
UNREADABLE_RUN_STATUSES = {401: "pc_result_unauthorized", 403: "pc_result_unauthorized",
                           404: "pc_run_not_staged", 503: "pc_result_unavailable"}


def mint_pc_run_id() -> str:
    """The same canonical handle the browser composer mints for a PC turn."""

    return "chat_pcq_" + secrets.token_hex(16)


def save_device_selection(opener, device_id: str) -> tuple[str, str]:
    """Save this account's own PC choice through the screen's own save.

    The browser stores the PC a person picked (``apps/padiem-chat/app/
    claw_device_directory_routes.py:715``); the preference is what lets a later
    turn reach that PC without naming it again. This canary keeps no browser, so
    it stores the same value once and reads it back as saved: the write is the
    account's own preference, carries no grant, and every execution still
    re-checks the directory.
    """
    status, body = bounded_call(opener, DEVICE_SELECT, method="POST",
                                payload={"device_id": device_id})
    ok = isinstance(body, dict) and body.get("ok") is True
    if status == 200 and ok:
        return "saved", "none"
    return "unsaved", (error_code(body) if isinstance(body, dict)
                        else "selection_unreadable")


def turn_prompt(label: Any) -> str:
    """The ask, naming the linked PC the way its owner would say it.

    ``apps/padiem-chat/app/chat_pc_drive.py:857`` reads the PC named in the turn
    and ``:877`` closes the lane when no PC is either named or saved, so a turn
    that names nothing is answered by the plain model path. The label is the
    account's own names for that machine and it rides only in the request.
    """
    if isinstance(label, str):
        named = " ".join(label.split())[:LABEL_MAX_CHARS]
        if named:
            return (f"커넥터 점검입니다. {named} PC의 드라이브 목록만 알려 주세요. "
                    "파일 내용은 읽지 않고, 어떤 파일도 변경하지 않습니다.")
    return PROMPT


def turn_payload(run_id: str, device_id: str | None = None,
                 prompt: str = PROMPT) -> dict:
    """The browser composer's own request shape: the PC this turn asks.

    The composer attaches the id of the PC the screen chose; a turn that names
    nothing inherits the browser's stored choice. This canary has no browser
    and keeps no stored choice, so it sends the id it just verified CONNECTED.
    Without it the server keeps the plain stream: no PC lane is ever opened and
    the run would report ``pc_lane_not_offered`` rather than a PC result.
    """
    payload = {"messages": [{"role": "user", "content": prompt}], "pc_run_id": run_id}
    if isinstance(device_id, str) and device_id:
        payload["device_id"] = device_id
    return payload


def count_entries(answer: str) -> int:
    """How many non-empty lines the stored PC result carries.

    A listing answer is the PC's own output lines beside the turn's final sentence,
    so this counts what came back, not a claim about the directory's total. The
    product marks a wider folder as truncated and says so (#5573), and the count
    follows that stored text exactly rather than a second summary.
    """

    return len([line for line in answer.splitlines() if line.strip()])


#: The pairing vocabulary the server actually emits. These are mirrored rather
#: than imported: this script runs from ``.github/scripts`` with no product import
#: path. ``.github/tests/test_pc_connector_canary.py`` reads the store's own
#: constants (``apps/padiem-chat/app/pc_device_pairing_store.py``) and fails when
#: these stop agreeing, so a renamed server state cannot silently turn the pair
#: test into a permanent "nothing to test".
LINK_ACTIVE = "active"
LINK_PAUSED = "paused"
LINK_REPLACED = "replaced"
LINK_REVOKED = "revoked"
LINK_PENDING_VERIFICATION = "pending_verification"
ROOT_GRANTED = "active"
ROOT_REVOKED = "revoked"
KNOWN_LINK_STATES = frozenset({
    LINK_ACTIVE, LINK_PAUSED, LINK_REPLACED, LINK_REVOKED, LINK_PENDING_VERIFICATION,
})
KNOWN_ROOT_STATES = frozenset({ROOT_GRANTED, ROOT_REVOKED})
#: A pairing read this canary cannot interpret: reported, never skipped.
PAIRING_STATE_UNRECOGNIZED = "pairing_state_unrecognized"
NO_ACTIVE_PAIRING = "no_active_pairing"
#: The exit code for "there was nothing to measure". Non-zero on purpose: the
#: workflow turns this into a failed run, so an hour that measured no PC is never
#: recorded as a healthy one.
EXIT_SKIP_NO_PC = 3


def active_pairing(body: Any) -> tuple[dict | None, str]:
    """``(link, code)``: the first live pairing with a granted root, or a reason.

    A paused or revoked link is not something to test: revoked links only appear as
    superseded history, and a paused one is the owner's own "not right now".

    The state words come from the server's own store, not from an older guess. A
    root is granted when its state is ``active`` (the store's only granted word);
    until 2026-11-16 this compared against ``"approved"``, which the server never
    emits, so every hour ended as SKIP_NO_PC and the canary never once reached the
    PC. An unrecognised word is a FAIL, not a SKIP, so a future rename surfaces
    instead of hiding.
    """

    links = body.get("links") if isinstance(body, dict) else None
    if not isinstance(links, list):
        return None, PAIRING_STATE_UNRECOGNIZED
    for link in links:
        if not isinstance(link, dict):
            return None, PAIRING_STATE_UNRECOGNIZED
        state = link.get("state")
        if state not in KNOWN_LINK_STATES:
            return None, PAIRING_STATE_UNRECOGNIZED
        if state != LINK_ACTIVE:
            continue
        roots = link.get("roots")
        if not isinstance(roots, list):
            return None, PAIRING_STATE_UNRECOGNIZED
        granted = False
        for root in roots:
            if not isinstance(root, dict):
                return None, PAIRING_STATE_UNRECOGNIZED
            root_state = root.get("state")
            if root_state not in KNOWN_ROOT_STATES:
                return None, PAIRING_STATE_UNRECOGNIZED
            if root_state == ROOT_GRANTED:
                granted = True
        if granted:
            return link, "none"
    return None, NO_ACTIVE_PAIRING


def usable_device_id(body: Any) -> str | None:
    """The id of the connected PC this turn should ask, never its name.

    One value is carried and it is the server's own directory id: the turn asks
    the machine the read just verified usable, and the server re-checks that the
    account owns it before any tool runs.
    """
    if not isinstance(body, dict) or body.get("available") is not True:
        return None
    devices = body.get("devices")
    if not isinstance(devices, list):
        return None
    for row in devices:
        if not isinstance(row, dict) or row.get("usable") is not True:
            continue
        device_id = row.get("deviceId")
        if isinstance(device_id, str) and DEVICE_ID_RE.fullmatch(device_id):
            return device_id
    return None


def pc_device_state(body: Any) -> str:
    """One safe word about the executor's own liveness, never a device name."""

    if not isinstance(body, dict) or body.get("available") is not True:
        return "unknown"
    devices = body.get("devices")
    if not isinstance(devices, list) or not devices:
        return "none"
    states = {row.get("state") for row in devices if isinstance(row, dict)}
    for state in ("CONNECTED", "OFFLINE", "REVOKED"):
        if state in states:
            return state.lower()
    return "unknown"


def pending_result_verdict(payload: Any) -> tuple[str, str, int, str]:
    """Read one durable result answer: ``(state, code, entries, answer_source)``.

    ``WAIT`` means the server itself still calls the run unfinished. A completed run
    passes only when the stored answer is the verified PC command result for this
    run: a model reply or an unknown source means the PC produced nothing to attach,
    which is precisely the state this canary exists to catch.
    """

    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        return "WAIT", error_code(payload) if isinstance(payload, dict) else "no_safe_error_code", 0, "none"
    status = result.get("status")
    source = result.get("answer_source") if isinstance(result.get("answer_source"), str) else "unknown"
    answer = result.get("answer")
    if isinstance(status, str) and status in UNANSWERED_STATUSES:
        return "WAIT", "none", 0, "none"
    if status == "completed":
        if source != "pc_command_result" or not isinstance(answer, str) or not answer.strip():
            return "FAIL", "pc_no_dispatch_result", 0, source
        return "PASS", "none", count_entries(answer), source
    if isinstance(status, str) and status in TERMINAL_FAILURE_STATUSES:
        return "FAIL", "pc_run_" + status, 0, "none"
    safe = status if isinstance(status, str) and _SAFE_CODE.fullmatch(status) else "unknown_state"
    return "FAIL", "pc_run_" + safe, 0, "none"


def last_reported_status(payload: Any) -> str:
    """The server's own status word for this run, or ``unknown``.

    Only the ``status`` field is read, and only when it names a state the route can
    report. Nothing is decided by matching text inside an answer, so a hex run id or a
    Korean file name in the body cannot move a verdict.
    """
    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        return _UNKNOWN_STATUS
    status = result.get("status")
    return status if status in REPORTABLE_RUN_STATUSES else _UNKNOWN_STATUS


def wait_for_result(opener, run_id: str, *, started: float | None = None,
                    clock=time.monotonic, sleep=time.sleep,
                    ceiling_seconds: int | None = RESULT_WAIT_CEILING_SECONDS) -> dict:
    """Poll the owner's own durable run result until it is terminal, or the bound ends.

    Two endings are deliberately separated. The WORK has no ceiling: a PC command that
    is still running is not interrupted, its lease keeps renewing and its result is
    still accepted late. This monitor's PATIENCE has one, because a stop nobody notices
    is the failure the owner reported on 2026-10-29. When the bound expires the answer
    is a named FAIL carrying the last status the server itself reported — never an
    implicit pass, and never a silent absence of a verdict.
    """

    started_at = clock() if started is None else started
    path = PENDING_RESULT_PATH.format(run_id=run_id)
    while True:
        status, body = bounded_call(opener, path)
        state, code, entries, source = pending_result_verdict(body)
        elapsed = max(0, int(round(clock() - started_at)))
        if state != "WAIT":
            return {"verdict": state, "code": code, "entries": entries,
                    "answer_source": source, "elapsed_seconds": elapsed,
                    "last_status": last_reported_status(body)}
        if ceiling_seconds is not None and elapsed >= ceiling_seconds:
            return {"verdict": "FAIL", "code": "pc_result_wait_ceiling",
                    "entries": 0, "answer_source": source,
                    "elapsed_seconds": elapsed,
                    "last_status": last_reported_status(body)}
        if status in UNREADABLE_RUN_STATUSES:
            # A run this read cannot see at all is a named end, never an endless loop.
            return {"verdict": "FAIL", "code": UNREADABLE_RUN_STATUSES[status],
                    "entries": 0, "answer_source": "none", "elapsed_seconds": elapsed,
                    "last_status": _UNKNOWN_STATUS}
        sleep(POLL_INTERVAL_SECONDS)


def _json_or_none(raw: bytes):
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError):
        return None


def _conversation_id(payload: dict) -> str | None:
    value = payload.get("conversation_id")
    return value if isinstance(value, str) and CONVERSATION_ID.fullmatch(value) else None


def take_answer_fields(outcome: dict, body: Any) -> None:
    """Carry the two server-owned fields out of one answer body.

    #7826: a server that names why it closed the PC lane says so in one word; it is
    carried out unchanged and never interpreted here.
    """

    if not isinstance(body, dict):
        return
    found = _conversation_id(body)
    if found:
        outcome["conversation_id"] = found
    closed = body.get("pc_lane_closed")
    if isinstance(closed, str) and _SAFE_CODE.match(closed):
        outcome["pc_lane_closed"] = closed


def frame_error_code(body: Any) -> str:
    """The code an error frame carries, whichever shape the server wrote.

    #7841: the model-first stream puts its code at the top level of the frame
    (``{"type": "error", "code": ...}``), while the older envelope nests it
    under ``error``. Reading only the nested place recorded a real refusal as
    ``no_safe_error_code``, which hid the reason from every reader. Both places
    are read, and only a short lower-case token survives either way.
    """

    if not isinstance(body, dict):
        return "no_safe_error_code"
    error = body.get("error")
    code = error.get("code") if isinstance(error, dict) else None
    if not (isinstance(code, str) and _SAFE_CODE.fullmatch(code)):
        code = body.get("code")
    if isinstance(code, str) and _SAFE_CODE.fullmatch(code):
        return code
    return "no_safe_error_code"


def apply_answer_line(outcome: dict, body: Any) -> bool:
    """Read one answer line into ``outcome``; ``True`` means nothing more arrives.

    Two shapes reach this function. The screen's model-first lane writes one JSON
    object per line, each carrying its own ``type``; older clients and the legacy PC
    lane answer with one whole JSON body. Only the tool progress frames of the first
    shape say a dispatch happened, and even those are reported rather than judged: the
    public durable read is the verdict (#7841).
    """

    if not isinstance(body, dict):
        return True
    take_answer_fields(outcome, body)
    frame_type = body.get("type")
    if not isinstance(frame_type, str):
        # A whole JSON answer: the turn was answered in text and this response is done.
        return True
    outcome["ndjson"] = True
    if frame_type == "progress" and body.get("kind") in TOOL_FRAME_KINDS:
        outcome["tool_frames"] += 1
    if frame_type == "done" or body.get("done") is True:
        outcome["done"] = True
        outcome["pc_pending"] = body.get("pc_pending") is True
        return True
    if frame_type == "error":
        outcome["error_code"] = frame_error_code(body)
        return True
    if frame_type == "orchestration_pause":
        outcome["error_code"] = "orchestration_pause"
        return True
    return False


def new_answer_outcome() -> dict:
    """The empty record one answer response fills; shared by the reader and tests."""

    return {"status": None, "done": False, "pc_pending": False, "conversation_id": None,
            "error_code": "none", "stream_stopped": False, "framed": False,
            "ndjson": False, "tool_frames": 0, "pc_lane_closed": ""}


def closed_lane_code(code: str) -> str:
    """The name this canary reports for one durable-read ending.

    A read that cannot see a run for an id it minted means no PC tool was dispatched
    for that turn. That is the same end this canary has always called
    ``pc_lane_not_offered``; every other unreadable end keeps its own name.
    """

    return PC_LANE_NOT_OFFERED if code in RUN_ABSENT_CODES else code


def read_pc_turn_stream(opener, payload: dict) -> dict:
    """Post one composer turn and read its stream to the first terminal frame.

    The composer's PC lane answers as a stream; the durable result is read after it.
    A stream that never delivers its terminal frame is survivable by design (#5976):
    the run keeps executing on the server and the pending-result read decides.
    """

    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = Request(
        ORIGIN + ORCHESTRATION,
        method="POST",
        data=data,
        headers={
            # The screen's own Accept: the model-first lane answers NDJSON lines,
            # and the legacy PC lane still answers SSE whatever this says.
            "Accept": NDJSON_ACCEPT,
            "Content-Type": "application/json",
            "User-Agent": "PADIEM-B62-pc-connector-canary/1.0",
            "Cache-Control": "no-store",
            "Origin": ORIGIN,
            "Referer": ORIGIN + "/",
        },
    )
    outcome = new_answer_outcome()

    def take(body) -> None:
        take_answer_fields(outcome, body)

    try:
        response = opener.open(request, timeout=CHAT_TIMEOUT_SECONDS)
    except HTTPError as err:
        body = _json_or_none(err.read(RESPONSE_BYTES_CAP + 1))
        outcome["status"] = err.code
        outcome["error_code"] = error_code(body) if isinstance(body, dict) else "no_safe_error_code"
        take(body)
        return outcome
    except (TimeoutError, URLError, OSError):
        # The turn is still the server's; the durable read decides.
        outcome["stream_stopped"] = True
        return outcome
    with response:
        outcome["status"] = response.status
        event_name = ""
        total = 0
        for count, line in enumerate(response, 1):
            if count > STREAM_LINE_CAP or total > RESPONSE_BYTES_CAP:
                outcome["stream_stopped"] = True
                break
            total += len(line)
            text = line.decode("utf-8", "replace").rstrip("\r\n")
            if text.startswith("event:"):
                event_name = text[6:].strip()
                continue
            if text.startswith("{"):
                if apply_answer_line(outcome, _json_or_none(text.encode("utf-8"))):
                    break
                continue
            if not text.startswith("data:"):
                continue
            outcome["framed"] = True
            frame = _json_or_none(text[5:].strip().encode("utf-8"))
            if not isinstance(frame, dict):
                continue
            if event_name == "done" or frame.get("done") is True:
                outcome["done"] = True
                outcome["pc_pending"] = frame.get("pc_pending") is True
                take(frame)
                break
            if (event_name == "error" or isinstance(frame.get("error"), dict)
                    or frame.get("type") == "error"):
                outcome["error_code"] = frame_error_code(frame)
                take(frame)
                break
    return outcome


def _install_session_cookie(jar: http.cookiejar.CookieJar, origin: str, value: str) -> None:
    """Install the shared login's Chat session cookie into this canary's jar.

    ``login_session_cookie`` returns the bare ``padiem_session`` value in memory
    only; this rebuilds the host-only, path="/", Secure session cookie the
    server issues so every later ``bounded_call`` carries it. The value is
    never printed, logged or written anywhere.
    """

    host = urlsplit(origin).hostname
    if not host or not value:
        raise CanaryError("qa_session_unverified")
    jar.set_cookie(http.cookiejar.Cookie(
        version=0, name=SESSION_COOKIE_NAME, value=value,
        port=None, port_specified=False,
        domain=host, domain_specified=False, domain_initial_dot=False,
        path="/", path_specified=True,
        secure=True, expires=None, discard=True,
        comment=None, comment_url=None, rest={}, rfc2109=False,
    ))


def sign_in(opener, jar) -> None:
    """Sign in the way the USAGE_CHECK flows sign in (#7078), not a new way.

    ``shared_login_client.login_session_cookie`` is the existing helper the
    daily real-usage check logs in with: the direct Chat email login first,
    and when the server answers 409 ``email_login_moved`` the common login
    form (the same route the browser_shared_login flow drives) is followed and
    the Chat session cookie its callback issues is returned. The cookie is
    installed into this canary's own jar and the session is verified with the
    existing status read. No credential or cookie value is printed.
    """

    username = os.environ.get(QA_USERNAME_ENV, "")
    password = os.environ.get(QA_PASSWORD_ENV, "")
    if not username or not password:
        raise CanaryError("qa_credential_missing")
    try:
        session_cookie = login_session_cookie(ORIGIN, username, password)
    except SharedLoginError as exc:
        print(f"QA_LOGIN_DIAGNOSTIC login_mode=shared_login server_error_code={exc.public_code}")
        # #7853 follow-up: the helper answers the one-time age screen once; a
        # screen that returns after that keeps its own closed code.
        if exc.public_code == "shared_login_age_confirm_loop":
            raise CanaryError("qa_age_confirm_loop") from exc
        raise CanaryError("qa_login_refused") from exc
    _install_session_cookie(jar, ORIGIN, session_cookie)
    status, state = bounded_call(opener, STATUS)
    if status != 200 or state.get("authenticated") is not True:
        state_code = error_code(state) if isinstance(state, dict) else "no_json_body"
        print(f"QA_SESSION_DIAGNOSTIC status_http_status={status} server_error_code={state_code}")
        raise CanaryError("qa_session_unverified")


def summary_line(verdict: str, *, entries: int, elapsed: int, code: str, pc_state: str,
                 last_status: str = _UNKNOWN_STATUS) -> str:
    return (
        f"CANARY={verdict} items={entries} elapsed_seconds={elapsed} "
        f"code={code} pc_state={pc_state} last_status={last_status}"
    )


def _cleanup(opener, conversation_id: str | None) -> None:
    if conversation_id is None:
        return
    try:
        bounded_call(opener, CONVERSATION + conversation_id, method="DELETE")
        print("PC_CANARY_QA_CONVERSATION_CLEANUP=PASS")
    except Exception:
        print("PC_CANARY_QA_CONVERSATION_CLEANUP=NEEDS_REVIEW")


def _fail(opener, conversation_id: str | None, code: str, *, entries: int = 0,
          elapsed: int = 0, pc_state: str = "unknown") -> int:
    print(summary_line("FAIL", entries=entries, elapsed=elapsed, code=code, pc_state=pc_state))
    _cleanup(opener, conversation_id)
    return 1


def run() -> int:
    jar = http.cookiejar.CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar))
    conversation_id: str | None = None
    run_id = mint_pc_run_id()
    pc_state = "unknown"
    try:
        sign_in(opener, jar)
        status, pairings = bounded_call(opener, PAIRINGS)
    except CanaryError as exc:
        return _fail(opener, None, exc.public_code)
    if status != 200 or not isinstance(pairings, dict) or pairings.get("ok") is not True:
        code = error_code(pairings) if isinstance(pairings, dict) else "pairings_unreadable"
        return _fail(opener, conversation_id, code)
    pairing, pairing_code = active_pairing(pairings)
    if pairing is None:
        if pairing_code != NO_ACTIVE_PAIRING:
            # A pairing read this canary cannot interpret is an end it must name:
            # the previous silent SKIP would have hidden exactly this.
            return _fail(opener, conversation_id, pairing_code, pc_state=pc_state)
        # Nothing to test: the code path is reported, and the exit code is
        # non-zero so the scheduled run fails instead of looking healthy.
        # (2026-11-05 → 11-15 every hour ended here and every one was green.)
        print(summary_line("SKIP_NO_PC", entries=0, elapsed=0,
                           code=NO_ACTIVE_PAIRING, pc_state=pc_state))
        print("PC_CANARY_SKIP_IS_A_WARNING=1 measured_no_pc=1")
        return EXIT_SKIP_NO_PC
    device_id: str | None = None
    already_selected = False
    try:
        _status, devices = bounded_call(opener, DEVICES)
        pc_state = pc_device_state(devices)
        device_id = usable_device_id(devices)
        already_selected = isinstance(devices, dict) and devices.get(
            "selectedDeviceId") == device_id
    except CanaryError:
        pc_state = "unknown"
    if device_id is None:
        # A pairing that grants nothing connected can only be described, not
        # measured: the turn would be answered without a PC lane.
        return _fail(opener, conversation_id, NO_USABLE_DEVICE, pc_state=pc_state)
    selection_saved = "already_saved"
    if not already_selected:
        try:
            selection_saved, selection_code = save_device_selection(opener, device_id)
        except CanaryError as exc:
            return _fail(opener, conversation_id, exc.public_code, pc_state=pc_state)
        if selection_saved != "saved":
            return _fail(opener, conversation_id, DEVICE_SELECT_UNSAVED,
                         pc_state=pc_state)

    # The wait may be long and the runner may end it, so the handle is recorded
    # before the turn is submitted: an unfinished hour stays attributable.
    print(f"PC_CANARY_RUN_ID={run_id} pc_state={pc_state} "
          f"device_selection={selection_saved}")
    started = time.monotonic()
    try:
        prompt = turn_prompt(pairing.get("label"))
        stream = read_pc_turn_stream(opener, turn_payload(run_id, device_id, prompt))
    except CanaryError as exc:
        return _fail(opener, conversation_id, exc.public_code, pc_state=pc_state)
    conversation_id = stream["conversation_id"] or conversation_id
    if stream["status"] is not None and stream["status"] != 200:
        return _fail(opener, conversation_id, stream["error_code"],
                     elapsed=int(round(time.monotonic() - started)), pc_state=pc_state)
    if stream["done"] is False and stream["error_code"] not in ("none", "") \
            and stream["stream_stopped"] is False:
        # The turn itself ended in an error frame; nothing was dispatched.
        return _fail(opener, conversation_id, stream["error_code"],
                     elapsed=int(round(time.monotonic() - started)), pc_state=pc_state)
    # #7841: the operating lane is the model-first one, and it answers in text when
    # the model chose no tool. A stream frame is therefore no longer the verdict: the
    # run this turn asked for is read back on the owner's own public route, and only
    # that row can say a PC tool actually ran once and succeeded. The legacy SSE PC
    # lane (the server takes it only when model-first declines the turn) ends at the
    # same read, so both shapes are judged by the same evidence.
    try:
        outcome = wait_for_result(opener, run_id, started=started)
    except CanaryError as exc:
        return _fail(opener, conversation_id, exc.public_code, pc_state=pc_state)
    # Printed on both endings: the shape this turn really was is the only way a
    # reader can tell a closed lane from an open lane the model answered in text.
    print(f"PC_CANARY_ANSWER_SOURCE={outcome['answer_source']} "
          f"PC_CANARY_STREAM_DONE={int(stream['done'])} PC_CANARY_STREAM_PENDING={int(stream['pc_pending'])} "
          f"PC_CANARY_STREAM_NDJSON={int(stream['ndjson'])} PC_CANARY_TOOL_FRAMES={stream['tool_frames']}")
    print("PC_CANARY_ANSWER_TEXT_LOGGED=0 PC_CANARY_DEVICE_NAMES_LOGGED=0 CREDENTIAL_VALUES_LOGGED=0")
    if outcome["code"] in RUN_ABSENT_CODES:
        # No run exists for this id, so no PC tool ran on this turn. The reporting
        # name stays the one this canary has always used for that end.
        if stream["pc_lane_closed"]:
            print(f"PC_CANARY_PC_LANE_CLOSED={stream['pc_lane_closed']}")
        return _fail(opener, conversation_id, closed_lane_code(outcome["code"]),
                     elapsed=outcome["elapsed_seconds"], pc_state=pc_state)
    print(summary_line(outcome["verdict"], entries=outcome["entries"],
                       elapsed=outcome["elapsed_seconds"], code=outcome["code"],
                       pc_state=pc_state,
                       last_status=outcome.get("last_status", _UNKNOWN_STATUS)))
    _cleanup(opener, conversation_id)
    return 0 if outcome["verdict"] == "PASS" else 1


def _session_cookie_reaches_jar() -> bool:
    """Pure proof: a jar built the way run() builds it carries the session.

    After ``_install_session_cookie`` a request to the chat origin must carry
    the ``padiem_session`` cookie, and a request to another host must not. No
    network and no real value: the cookie value here is a placeholder.
    """

    jar = http.cookiejar.CookieJar()
    _install_session_cookie(jar, ORIGIN, "placeholder-value")
    request = Request(ORIGIN + STATUS)
    jar.add_cookie_header(request)
    carried = request.get_header("Cookie") or ""
    if SESSION_COOKIE_NAME + "=" not in carried:
        return False
    other = Request("https://example.invalid" + STATUS)
    jar.add_cookie_header(other)
    return (other.get_header("Cookie") or "") == ""


def _missing_session_value_is_refused() -> bool:
    """Pure proof: an empty session value never becomes a silent pass."""

    try:
        _install_session_cookie(http.cookiejar.CookieJar(), ORIGIN, "")
    except CanaryError as exc:
        return exc.public_code == "qa_session_unverified"
    return False


def _outcome_after(bodies: list) -> dict:
    """The record left after feeding these answer lines, in order."""

    outcome = new_answer_outcome()
    for body in bodies:
        if apply_answer_line(outcome, body):
            break
    return outcome


def _stop_after(bodies: list) -> bool:
    """Whether the last of these lines ends the read."""

    stop = False
    outcome = new_answer_outcome()
    for body in bodies:
        stop = apply_answer_line(outcome, body)
        if stop:
            break
    return stop


def self_test() -> int:
    """Pure checks, no network: the verdict table, the pairing rule and the line."""

    run_id = "chat_pcq_" + "a" * 32
    cid = "chat_" + "c" * 32
    checks = {
        "completed_pc_result": pending_result_verdict({"ok": True, "result": {
            "run_id": run_id, "conversation_id": cid, "status": "completed",
            "answer_source": "pc_command_result",
            "answer": "Applications\nWindows\nUsers\nProgram Files\n",
        }}) == ("PASS", "none", 4, "pc_command_result"),
        "running_still_waits": pending_result_verdict({"ok": True, "result": {
            "run_id": run_id, "conversation_id": cid, "status": "running",
        }})[0] == "WAIT",
        "model_reply_is_not_a_pc_answer": pending_result_verdict({"ok": True, "result": {
            "run_id": run_id, "conversation_id": cid, "status": "completed",
            "answer_source": "model_reply", "answer": "PC를 확인하지 못했습니다.",
        }})[:2] == ("FAIL", "pc_no_dispatch_result"),
        "failed_run_is_named": pending_result_verdict({"ok": True, "result": {
            "run_id": run_id, "conversation_id": cid, "status": "failed",
        }})[:2] == ("FAIL", "pc_run_failed"),
        "unreadable_shape_waits_for_a_status": pending_result_verdict(
            {"error": {"code": "run_result_unavailable"}})[:2] == ("WAIT", "run_result_unavailable"),
        # The pairing test reads the server's own vocabulary: a granted root is
        # "active", never "approved" (that word the server never emits, and
        # comparing against it turned every hour into SKIP_NO_PC).
        "paused_link_is_not_a_pc": active_pairing(
            {"ok": True, "links": [{"state": "paused", "roots": [{"state": "active"}]}]}) == (
                None, NO_ACTIVE_PAIRING),
        "revoked_root_is_not_a_pc": active_pairing(
            {"ok": True, "links": [{"state": "active", "roots": [{"state": "revoked"}]}]}) == (
                None, NO_ACTIVE_PAIRING),
        "active_link_with_a_granted_root_is_a_pc": active_pairing(
            {"ok": True, "links": [{"state": "active", "roots": [{"state": "active", "path": "C:\\"}]}]}
        )[1] == "none",
        "an_unknown_link_state_is_a_failure_not_a_skip": active_pairing(
            {"ok": True, "links": [{"state": "approved", "roots": [{"state": "active"}]}]}) == (
                None, PAIRING_STATE_UNRECOGNIZED),
        "an_unknown_root_state_is_a_failure_not_a_skip": active_pairing(
            {"ok": True, "links": [{"state": "active", "roots": [{"state": "approved"}]}]}) == (
                None, PAIRING_STATE_UNRECOGNIZED),
        "a_body_without_links_is_a_failure_not_a_skip": active_pairing({"ok": True}) == (
            None, PAIRING_STATE_UNRECOGNIZED),
        # "Measured nothing" must not exit 0: the scheduled run has to go red.
        "nothing_to_measure_is_not_a_zero_exit": EXIT_SKIP_NO_PC != 0,
        "connected_state": pc_device_state(
            {"ok": True, "available": True, "devices": [{"state": "CONNECTED"}, {"state": "OFFLINE"}]}
        ) == "connected",
        "run_id_is_canonical": bool(PC_RUN_ID.fullmatch(mint_pc_run_id())),
        "payload_is_a_pc_turn_only": turn_payload("chat_pcq_" + "b" * 32) == {
            "messages": [{"role": "user", "content": PROMPT}],
            "pc_run_id": "chat_pcq_" + "b" * 32,
        },
        # The lane is opened by the turn naming a PC. The canary sends the id it
        # read from the server's own directory, so the ask is the same one a
        # person makes and the server still re-checks ownership.
        "the_turn_names_the_pc_it_verified": turn_payload("chat_pcq_" + "b" * 32, "pc_abc") == {
            "messages": [{"role": "user", "content": PROMPT}],
            "pc_run_id": "chat_pcq_" + "b" * 32,
            "device_id": "pc_abc",
        },
        # The name rides the request and never the log: the same machine has
        # several names and this asks the one the account chose for it.
        "the_turn_names_the_linked_pc": turn_prompt("K_lipvoice · 컴2").startswith(
            "커넥터 점검입니다. K_lipvoice · 컴2 PC의"),
        "an_unnamed_link_keeps_the_plain_ask": turn_prompt(None) == PROMPT,
        "a_label_is_flattened_to_one_line": "\n" not in turn_prompt("a\nb\tc"),
        "only_a_usable_pc_is_asked": usable_device_id(
            {"ok": True, "available": True, "devices": [
                {"deviceId": "pc_off", "usable": False, "state": "OFFLINE"},
                {"deviceId": "pc_on", "usable": True, "state": "CONNECTED"},
            ]}) == "pc_on",
        "a_missing_directory_has_no_pc_to_ask": usable_device_id(
            {"ok": True, "available": False}) is None,
        "a_path_like_id_is_never_sent": usable_device_id(
            {"ok": True, "available": True,
             "devices": [{"deviceId": "C:/Users/owner", "usable": True}]}) is None,
        "a_composed_mesh_identity_is_accepted": usable_device_id(
            {"ok": True, "available": True,
             "devices": [{"deviceId": "node/eu/pc_abc", "usable": True}]}) == "node/eu/pc_abc",
        # Nothing connected is a named failure, not a quiet skip in another word.
        "a_pairing_with_no_connected_pc_is_named": NO_USABLE_DEVICE == "no_usable_pc_device",
        "one_summary_line": summary_line("PASS", entries=4, elapsed=41, code="none",
                                         pc_state="connected") == (
            "CANARY=PASS items=4 elapsed_seconds=41 code=none pc_state=connected "
            "last_status=unknown"),
        "the_ceiling_line_names_the_state_it_saw": summary_line(
            "FAIL", entries=0, elapsed=600, code="pc_result_wait_ceiling",
            pc_state="connected", last_status="running") == (
            "CANARY=FAIL items=0 elapsed_seconds=600 code=pc_result_wait_ceiling "
            "pc_state=connected last_status=running"),
        # Standard 1 and standard 4 are different objects: the PC's work keeps no
        # ceiling, this monitor's patience has one, and it is a named failure.
        "the_monitor_wait_is_bounded_at_ten_minutes": RESULT_WAIT_CEILING_SECONDS == 600,
        # The sign-in path: the shared login's session cookie must actually be
        # carried by a jar built the way run() builds it, for the chat origin.
        "the_shared_session_cookie_reaches_the_canary_jar": _session_cookie_reaches_jar(),
        "a_missing_session_value_is_refused": _missing_session_value_is_refused(),
        "a_last_status_is_read_from_the_status_field_only": (
            last_reported_status({"result": {"status": "running"}}) == "running"
            and last_reported_status({"result": {"status": "a" * 60}}) == _UNKNOWN_STATUS
            and last_reported_status(None) == _UNKNOWN_STATUS
        ),
        # #7841: the screen's own answer shape. One JSON object per line, and the
        # tool frames are counted while the durable read stays the verdict. These
        # drive the reader's own line function, not a copy of it.
        "a_stream_frame_is_not_a_whole_answer": apply_answer_line(
            new_answer_outcome(), {"type": "progress", "kind": "tool_started",
                                  "sequence": 1, "label": "진행 중"}) is False,
        "a_tool_frame_is_counted_not_judged": _outcome_after([
            {"type": "progress", "kind": "tool_completed", "sequence": 2, "label": "진행 중"},
        ]) == {**new_answer_outcome(), "ndjson": True, "tool_frames": 1},
        "a_done_frame_ends_the_read": (
            _stop_after([{"type": "done", "done": True}]),
            _outcome_after([{"type": "done", "done": True}])["done"],
        ) == (True, True),
        "an_error_frame_names_the_end": (
            _stop_after([{"type": "error", "error": {"code": "engine_execution_failed"}}]),
            _outcome_after([{"type": "error", "error": {"code": "engine_execution_failed"}}])["error_code"],
        ) == (True, "engine_execution_failed"),
        # #7841: the operating stream writes its code at the top level of the
        # frame. Reading only the nested place turned a real refusal into
        # no_safe_error_code on run 43853199977.
        "a_top_level_error_code_is_read": (
            _outcome_after([{"type": "error", "code": "oracle_mesh_file_path_invalid"}])["error_code"]
        ) == "oracle_mesh_file_path_invalid",
        "a_nested_error_code_still_wins": (
            frame_error_code({"type": "error", "code": "top_level",
                              "error": {"code": "nested_code"}})
        ) == "nested_code",
        "an_error_frame_without_a_code_stays_unnamed": (
            frame_error_code({"type": "error"}) == "no_safe_error_code"
            and frame_error_code({"type": "error", "code": "Not A Code"}) == "no_safe_error_code"
            and frame_error_code(None) == "no_safe_error_code"
        ),
        "a_whole_json_answer_ends_the_read": _stop_after([{"answer": "ok"}]) is True,
        # An id this canary minted that has no run behind it is the old lane name.
        "an_absent_run_is_the_lane_name": (
            closed_lane_code("pc_run_not_staged") == PC_LANE_NOT_OFFERED
            and closed_lane_code("pc_result_unauthorized") == "pc_result_unauthorized"
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    for name in failed:
        print(f"PC_CONNECTOR_CANARY_SELF_TEST_FAILED={name}")
    print(f"PC_CONNECTOR_CANARY_SELF_TEST={'PASS' if not failed else 'FAIL'} "
          f"CHECKS={len(checks) - len(failed)}/{len(checks)}")
    return 0 if not failed else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--self-test" in argv:
        return self_test()
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
