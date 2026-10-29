#!/usr/bin/env python3
"""#5895: one real PC request through the product lane, so connector stability is a number.

The deploy gates prove a version is served. Nothing proved that a paired PC still
answers, which is the thing an owner feels as "the connector broke". This canary
signs in as the existing production QA identity, asks the PC that account has for a
top-level listing of its C: drive, and waits until the result arrives. It reports one
line: verdict, entry count, elapsed seconds, failure code.

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
    PASS        the run completed with a verified PC command result, lines counted
    FAIL        any other end, named: no dispatch result behind the answer, the run
                failed or was cancelled, the PC lane was never offered, a read that
                cannot see the run, or the monitor's own bound expiring while the
                server still calls the run unfinished (code=pc_result_wait_ceiling)
    SKIP_NO_PC  the QA account has no active paired PC — not a failure

Only the pre-existing QA identity is used (`B66_CGI_ALPHA_USERNAME` /
`B66_CGI_ALPHA_PASSWORD` — the same names the post-deploy chat smoke signs in with),
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
from urllib.request import Request, build_opener, HTTPCookieProcessor

sys.path.insert(0, str(Path(__file__).resolve().parent))

from b62_live_long_context_canary import (  # noqa: E402  (sibling script import)
    CHAT_TIMEOUT_SECONDS,
    CONVERSATION,
    LOGIN,
    ORIGIN,
    RESPONSE_BYTES_CAP,
    STATUS,
    STREAM_LINE_CAP,
    CanaryError,
    bounded_call,
    error_code,
)
from b62_live_long_context_canary import _ID as CONVERSATION_ID  # noqa: E402

ORCHESTRATION = "/api/orchestration"
PAIRINGS = "/api/pc/pairings"
DEVICES = "/api/claw/local-access/devices"
PENDING_RESULT_PATH = "/api/claw/runs/{run_id}/pending-result"
QA_USERNAME_ENV = "B66_CGI_ALPHA_USERNAME"
QA_PASSWORD_ENV = "B66_CGI_ALPHA_PASSWORD"
PC_RUN_ID = re.compile(r"\Achat_pcq_[0-9a-f]{32}\Z")
_SAFE_CODE = re.compile(r"\A[a-z][a-z0-9_]{0,40}\Z")
PROMPT = (
    "커넥터 점검입니다. 연결된 PC의 C:\\ 최상위 항목 목록만 나열해 주세요. "
    "파일 내용은 읽지 않고, 어떤 파일도 변경하지 않습니다."
)
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


def turn_payload(run_id: str) -> dict:
    return {"messages": [{"role": "user", "content": PROMPT}], "pc_run_id": run_id}


def count_entries(answer: str) -> int:
    """How many non-empty lines the stored PC result carries.

    A listing answer is the PC's own output lines beside the turn's final sentence,
    so this counts what came back, not a claim about the directory's total. The
    product marks a wider folder as truncated and says so (#5573), and the count
    follows that stored text exactly rather than a second summary.
    """

    return len([line for line in answer.splitlines() if line.strip()])


def active_pairing(body: Any) -> dict | None:
    """The first link that is a live pairing with at least one approved root.

    A paused or revoked link is not something to test: revoked links never appear
    at all, and a paused one is the owner's own "not right now".
    """

    links = body.get("links") if isinstance(body, dict) else None
    if not isinstance(links, list):
        return None
    for link in links:
        if not isinstance(link, dict) or link.get("state") != "active":
            continue
        roots = link.get("roots")
        if isinstance(roots, list) and any(
            isinstance(root, dict) and root.get("state") == "approved" for root in roots
        ):
            return link
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
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
            "User-Agent": "PADIEM-B62-pc-connector-canary/1.0",
            "Cache-Control": "no-store",
            "Origin": ORIGIN,
            "Referer": ORIGIN + "/",
        },
    )
    outcome = {"status": None, "done": False, "pc_pending": False, "conversation_id": None,
               "error_code": "none", "stream_stopped": False, "framed": False}

    def take(body) -> None:
        if isinstance(body, dict):
            found = _conversation_id(body)
            if found:
                outcome["conversation_id"] = found

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
                # A JSON answer with no stream: this turn was not given the PC lane.
                take(_json_or_none(text.encode("utf-8")))
                break
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
            if event_name == "error" or isinstance(frame.get("error"), dict):
                outcome["error_code"] = error_code(frame)
                take(frame)
                break
    return outcome


def sign_in(opener) -> None:
    username = os.environ.get(QA_USERNAME_ENV, "")
    password = os.environ.get(QA_PASSWORD_ENV, "")
    if not username or not password:
        raise CanaryError("qa_credential_missing")
    status, body = bounded_call(
        opener, LOGIN, method="POST",
        payload={"identifier": username, "password": password},
    )
    if status != 200 or body.get("ok") is not True:
        server_code = error_code(body) if isinstance(body, dict) else "no_json_body"
        print(f"QA_LOGIN_DIAGNOSTIC login_http_status={status} server_error_code={server_code}")
        raise CanaryError("qa_login_refused")
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
    opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
    conversation_id: str | None = None
    run_id = mint_pc_run_id()
    pc_state = "unknown"
    try:
        sign_in(opener)
        status, pairings = bounded_call(opener, PAIRINGS)
    except CanaryError as exc:
        return _fail(opener, None, exc.public_code)
    if status != 200 or not isinstance(pairings, dict) or pairings.get("ok") is not True:
        code = error_code(pairings) if isinstance(pairings, dict) else "pairings_unreadable"
        return _fail(opener, conversation_id, code)
    if active_pairing(pairings) is None:
        # Nothing to test is not a failure: this account simply has no PC.
        print(summary_line("SKIP_NO_PC", entries=0, elapsed=0,
                           code="no_active_pairing", pc_state=pc_state))
        return 0
    try:
        _status, devices = bounded_call(opener, DEVICES)
        pc_state = pc_device_state(devices)
    except CanaryError:
        pc_state = "unknown"

    # The wait may be long and the runner may end it, so the handle is recorded
    # before the turn is submitted: an unfinished hour stays attributable.
    print(f"PC_CANARY_RUN_ID={run_id} pc_state={pc_state}")
    started = time.monotonic()
    try:
        stream = read_pc_turn_stream(opener, turn_payload(run_id))
    except CanaryError as exc:
        return _fail(opener, conversation_id, exc.public_code, pc_state=pc_state)
    conversation_id = stream["conversation_id"] or conversation_id
    if stream["status"] is not None and stream["status"] != 200:
        return _fail(opener, conversation_id, stream["error_code"],
                     elapsed=int(round(time.monotonic() - started)), pc_state=pc_state)
    if stream["done"] is False and stream["stream_stopped"] is False and stream["framed"] is False:
        # A plain JSON answer with no PC frame: this turn was never given the PC
        # lane, so there is no durable PC result that could ever arrive for it.
        return _fail(opener, conversation_id, "pc_lane_not_offered", pc_state=pc_state)
    try:
        outcome = wait_for_result(opener, run_id, started=started)
    except CanaryError as exc:
        return _fail(opener, conversation_id, exc.public_code, pc_state=pc_state)
    print(summary_line(outcome["verdict"], entries=outcome["entries"],
                       elapsed=outcome["elapsed_seconds"], code=outcome["code"],
                       pc_state=pc_state,
                       last_status=outcome.get("last_status", _UNKNOWN_STATUS)))
    print(f"PC_CANARY_ANSWER_SOURCE={outcome['answer_source']} "
          f"PC_CANARY_STREAM_DONE={int(stream['done'])} PC_CANARY_STREAM_PENDING={int(stream['pc_pending'])}")
    print("PC_CANARY_ANSWER_TEXT_LOGGED=0 PC_CANARY_DEVICE_NAMES_LOGGED=0 CREDENTIAL_VALUES_LOGGED=0")
    _cleanup(opener, conversation_id)
    return 0 if outcome["verdict"] == "PASS" else 1


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
        "paused_link_is_not_a_pc": active_pairing(
            {"ok": True, "links": [{"state": "paused", "roots": [{"state": "approved"}]}]}) is None,
        "unapproved_link_is_not_a_pc": active_pairing(
            {"ok": True, "links": [{"state": "active", "roots": [{"state": "revoked"}]}]}) is None,
        "active_link_with_a_root_is_a_pc": active_pairing(
            {"ok": True, "links": [{"state": "active", "roots": [{"state": "approved", "path": "C:\\"}]}]}
        ) is not None,
        "connected_state": pc_device_state(
            {"ok": True, "available": True, "devices": [{"state": "CONNECTED"}, {"state": "OFFLINE"}]}
        ) == "connected",
        "run_id_is_canonical": bool(PC_RUN_ID.fullmatch(mint_pc_run_id())),
        "payload_is_a_pc_turn_only": turn_payload("chat_pcq_" + "b" * 32) == {
            "messages": [{"role": "user", "content": PROMPT}],
            "pc_run_id": "chat_pcq_" + "b" * 32,
        },
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
        "a_last_status_is_read_from_the_status_field_only": (
            last_reported_status({"result": {"status": "running"}}) == "running"
            and last_reported_status({"result": {"status": "a" * 60}}) == _UNKNOWN_STATUS
            and last_reported_status(None) == _UNKNOWN_STATUS
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
