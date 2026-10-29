#!/usr/bin/env python3
"""#82: read the connector lane every ten minutes and say what its own state is.

Standard 4 of the connector stability rule is "a stop is known within ten minutes".
The hourly PC canary (#6129) now guarantees a verdict exists, but it can only say
something when it dares to start a real command on a real PC, and an hour is not ten
minutes. This script is the cheap read-only half: it asks the lane's own status route
(#6134) and Chat ``/health``, and judges.

Three rules the owner wrote decide its shape:

* **One authoritative source.** ``PC_QUEUE_BACKEND`` names which store is the live
  one. After the COM2 move the D1 dispatch, pairing and presence rows are a frozen
  copy, and a copy that stopped changing is not evidence that the lane is idle. So a
  ``com2`` configuration is reported as ``unsupported_source`` — UNKNOWN — rather
  than quietly reading the stale D1 numbers, and the queue side is Qoder's to wire
  (this script deliberately does not touch ``apps/padiem-mesh-queue``).
* **Verdicts come from state fields.** Counts, ages, timestamps and the HTTP status.
  No response text is searched: a hex id, a Korean file name or a log line has
  already been misread once.
* **Not knowing is never healthy.** A missing channel secret, a 404 from a route that
  is not deployed yet, a 5xx, an absent presence row or an unparseable timestamp all
  answer UNKNOWN. UNKNOWN prints its reason and is shown as a neutral status, so a
  stalled lane and an unwatchable lane are two different visible things, and neither
  one is called "ok".

And the rule the whole lane exists for: a PC whose work is under a live claim is
BUSY, not stalled. The route separates ``open`` from ``waiting`` exactly so this
script can never cut a running job short by calling it late.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

LANE_STATUS_PATH = "/api/claw/connector/mesh-reads/lane-status"
LANE_STATUS_HEADER = "X-Oracle-Mesh-Secret"
#: The READ-ONLY watch secret, never the executor channel secret: that one can claim
#: a dispatch and submit a result on a customer PC, and a scheduled workflow is the
#: last place to keep it.
WATCH_SECRET_ENV = "CONNECTOR_WATCH_READ_SECRET"
CHAT_HEALTH_PATH = "/health"
#: The product's own presence freshness is 180 s (#5553). The monitor uses a wider
#: window on purpose: one slow poll must not page anyone, while a lane that has not
#: beaten for five minutes has missed the beat many times over and is well inside the
#: ten-minute rule with the ten-minute cadence.
BEAT_STALL_SECONDS = 300
#: Work nobody has claimed for this long is the queue standing still. It is below the
#: ten-minute reporting rule on purpose: alerting at exactly 600 s under a 600 s
#: cadence would report the stop on the hour after it happened.
QUEUE_STATIC_SECONDS = 300
#: One PC's unclaimed work is silent here for a little longer than the queue rule,
#: because a PC can be offline for reasons of its own (laptop closed) and that is a
#: different fact from a stopped executor — both are reported, this is not.
PC_SILENT_SECONDS = 600
#: Requests are bounded: this is a communication wait, and standard 1 puts no ceiling
#: on any work — there is no work here, only reads.
REQUEST_TIMEOUT_SECONDS = 20

OK = "ok"
STALL = "stall"
UNKNOWN = "unknown"

_SEVERITY = {OK: 0, UNKNOWN: 1, STALL: 2}
_SAFE_WORD = re.compile(r"\A[a-z][a-z0-9_]{0,39}\Z")
#: Only these values of PC_QUEUE_BACKEND are read as "the lane's live store".
SOURCE_D1 = "d1"
SOURCE_COM2 = "com2"


def _age_seconds(stamp: Any, now: float) -> int | None:
    """How old an ISO stamp is, in whole seconds, or None when it cannot be read.

    A stamp in the future is 0, not a negative age: two hosts' clocks disagreeing is
    a fact about clocks and must not look like work from before the flood.
    """
    if not isinstance(stamp, str) or not stamp.strip():
        return None
    try:
        moment = datetime.fromisoformat(stamp.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return max(0, int(now - moment.timestamp()))


def _seconds(value: Any) -> int | None:
    """A reported age, trusted only as a non-negative whole number."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _count(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def queue_verdict(lane: Any, *, bound: int = QUEUE_STATIC_SECONDS) -> tuple[str, str]:
    """Is the queue holding work that nobody is claiming?"""
    unclaimed = lane.get("unclaimed") if isinstance(lane, dict) else None
    if not isinstance(unclaimed, dict):
        return UNKNOWN, "queue_counts_absent"
    count = _count(unclaimed.get("count"))
    if count is None:
        return UNKNOWN, "queue_counts_unreadable"
    if count == 0:
        return OK, "queue_idle"
    oldest = _seconds(unclaimed.get("oldest_seconds"))
    if oldest is None:
        return UNKNOWN, "queue_age_unreadable"
    if oldest > bound:
        return STALL, f"queue_unclaimed_{oldest}s"
    return OK, "queue_claimed_recently"


def pc_silence_verdict(lane: Any, *, bound: int = PC_SILENT_SECONDS) -> tuple[str, str]:
    """Is one PC holding work that no claim covers, past the silence bound?

    Only `waiting` is read, never `open`: work under a live claim is the PC doing
    its job, and that work has no ceiling by owner decision.
    """
    nodes = lane.get("nodes") if isinstance(lane, dict) else None
    if not isinstance(nodes, list):
        return UNKNOWN, "pc_rows_absent"
    worst = 0
    seen_any = False
    for row in nodes:
        if not isinstance(row, dict):
            continue
        waiting = _count(row.get("waiting"))
        if waiting is None:
            return UNKNOWN, "pc_waiting_unreadable"
        if waiting == 0:
            continue
        seen_any = True
        age = _seconds(row.get("waiting_oldest_seconds"))
        if age is None:
            # Work is waiting and its age cannot be read: that is not "fresh".
            return UNKNOWN, "pc_waiting_age_unreadable"
        worst = max(worst, age)
    if not seen_any:
        return OK, "pc_nothing_waiting"
    if worst > bound:
        return STALL, f"pc_unanswered_{worst}s"
    return OK, "pc_waiting_recently"


def liveness_verdict(lane: Any, *, now: float, bound: int = BEAT_STALL_SECONDS) -> tuple[str, str]:
    """Has the executor beaten for every PC it was asked about?"""
    beats = lane.get("beats") if isinstance(lane, dict) else None
    if not isinstance(beats, list) or not beats:
        return UNKNOWN, "beats_absent"
    oldest = 0
    for row in beats:
        if not isinstance(row, dict):
            return UNKNOWN, "beat_row_unreadable"
        if row.get("seen") is not True:
            return UNKNOWN, "beat_never_recorded"
        age = _age_seconds(row.get("received_at"), now)
        if age is None:
            return UNKNOWN, "beat_stamp_unreadable"
        oldest = max(oldest, age)
    if oldest > bound:
        return STALL, f"executor_silent_{oldest}s"
    return OK, "executor_beating"


#: Cloudflare's own error numbers that mean the Worker itself did not answer: 1101 is
#: an exception in the Worker, 1102 the CPU limit. On 2026-10-29 the LAX path returned
#: them for 40-50% of turns while other paths were fine, so the number is the fact to
#: record — the status code alone cannot tell "the edge answered for a dead worker"
#: from "the worker said no".
CLOUDFLARE_WORKER_ERRORS = (1101, 1102)


def cloudflare_error_code(payload: Any) -> int | None:
    """The edge's numeric error code, when the body carries one of the known numbers.

    Only an integer field is read, from the two shapes Cloudflare uses for a Worker
    that did not answer (`error_code` at the top level, or `errors[0].code`). Text is
    never searched: a number that only looks like 1102 somewhere in a page is not a
    verdict, and a string "1102" is not the field.
    """
    if not isinstance(payload, dict):
        return None
    candidates = [payload.get("error_code")]
    errors = payload.get("errors")
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        candidates.append(errors[0].get("code"))
    for candidate in candidates:
        if isinstance(candidate, bool) or not isinstance(candidate, int):
            continue
        if candidate in CLOUDFLARE_WORKER_ERRORS:
            return candidate
    return None


def chat_health_verdict(status: Any, edge_error: Any = None) -> tuple[str, str]:
    """The public read of Chat's own health endpoint.

    200 is the only answer this reads as healthy; a transport failure is UNKNOWN, not
    a failure, because a runner's own network is not evidence about the worker. A 5xx
    that carries a Cloudflare Worker error number says which way the worker failed,
    and that number is part of the reason.
    """
    code = _count(status)
    if code is None:
        return UNKNOWN, "chat_health_unreadable"
    if code == 200:
        return OK, "chat_health_200"
    named = cloudflare_error_code({"error_code": edge_error})
    if code >= 500:
        return STALL, (f"chat_health_{code}_cloudflare_{named}" if named
                       else f"chat_health_{code}")
    return UNKNOWN, (f"chat_health_{code}_cloudflare_{named}" if named
                     else f"chat_health_{code}")


def source_verdict(configured: Any) -> tuple[str, str]:
    """Which store is the lane's live one, and whether this script may read it.

    A default of ``d1`` is the state before the COM2 move. Once ``PC_QUEUE_BACKEND``
    says ``com2``, the D1 dispatch rows are a copy that no longer changes, and reading
    them would report a stalled lane as an idle one — the exact mistake this rule was
    written to prevent. The queue's own status read is wired by whoever moves the
    backend, and this script says so instead of guessing.
    """
    if configured is None:
        value = SOURCE_D1
    elif isinstance(configured, str):
        value = configured.strip().lower() or SOURCE_D1
    else:
        value = None
    if value == SOURCE_D1:
        return OK, "source_d1"
    if value == SOURCE_COM2:
        return UNKNOWN, "source_com2_read_queue_side"
    return UNKNOWN, "source_unnamed"


def combine(named: dict[str, tuple[str, str]]) -> tuple[str, list[str]]:
    """One state from the checks, with the worst thing first.

    Stall outranks unknown, and unknown outranks ok, so a lane that is both partly
    unwatchable and demonstrably stopped is reported as stopped.
    """
    state = OK
    reasons: list[str] = []
    for name, (verdict, reason) in named.items():
        # A verdict this module does not know is UNKNOWN, never carried onward as
        # itself: the state has to be one of the three words the caller publishes.
        known = verdict if verdict in _SEVERITY else UNKNOWN
        if _SEVERITY[known] > _SEVERITY[state]:
            state = known
        if known != OK:
            reasons.append(f"{name}={reason}")
    return state, reasons


# ---- transport (thin; every decision lives above) ----------------------
def _post_lane_status(origin: str, secret: str, device_ids: list[str]) -> tuple[int | None, Any]:
    request = urllib.request.Request(
        f"{origin}{LANE_STATUS_PATH}",
        data=json.dumps({"device_ids": device_ids}).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 LANE_STATUS_HEADER: secret,
                 "User-Agent": "PadiemConnectorWatch/1.0 (#82)"},
    )
    # Redirects are refused rather than followed: this request carries the channel
    # secret, and an origin that moves under it must not be replayed there.
    opener = urllib.request.build_opener(_RefuseRedirect())
    try:
        with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return response.status, json.loads(response.read(262_144).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except Exception:
        return None, None


#: One health answer is small; an edge error page can be larger than that and is
#: still bounded here. Only the number is kept — never body text.
_HEALTH_BODY_BYTES = 8_192


def _health_error_code(body: bytes) -> int | None:
    try:
        return cloudflare_error_code(json.loads(body.decode("utf-8", "replace")))
    except Exception:
        return None


def _get_health(origin: str) -> tuple[int | None, int | None]:
    """The status and, when the edge named one, its Worker error number."""
    request = urllib.request.Request(
        f"{origin}{CHAT_HEALTH_PATH}", method="GET",
        headers={"Accept": "application/json",
                 "User-Agent": "PadiemConnectorWatch/1.0 (#82)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return response.status, _health_error_code(response.read(_HEALTH_BODY_BYTES))
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(_HEALTH_BODY_BYTES)
        except Exception:
            body = b""
        return exc.code, _health_error_code(body)
    except Exception:
        return None, None


class _RefuseRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        del req, fp, code, msg, headers, newurl
        return None


def _device_ids(raw: str | None) -> list[str]:
    """The devices to ask about, bounded by the route's own presence limit."""
    if not raw:
        return []
    out: list[str] = []
    for part in raw.split(","):
        piece = part.strip()
        if piece and piece not in out and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", piece):
            out.append(piece)
        if len(out) == 8:
            break
    return out


def run(env: dict[str, str]) -> int:
    origin = (env.get("CONNECTOR_WATCH_CHAT_ORIGIN") or "https://chat.padiem.net").rstrip("/")
    if not origin.startswith("https://") or "@" in origin:
        print("CONNECTOR_WATCH=unknown reason=origin_refused")
        return 0
    secret = (env.get(WATCH_SECRET_ENV) or "").strip()
    devices = _device_ids(env.get("CONNECTOR_WATCH_DEVICE_IDS"))
    now = time.time()
    checks: dict[str, tuple[str, str]] = {}

    source_state, source_reason = source_verdict(env.get("PC_QUEUE_BACKEND"))
    checks["source"] = (source_state, source_reason)
    if source_state is not OK:
        # Reading the wrong store is not a verdict about the lane at all.
        checks["queue"] = (UNKNOWN, "not_read")
        checks["pc"] = (UNKNOWN, "not_read")
        checks["beat"] = (UNKNOWN, "not_read")
    elif not secret or not devices:
        checks["queue"] = (UNKNOWN, "read_secret_absent" if not secret else "devices_unset")
        checks["pc"] = (UNKNOWN, "not_read")
        checks["beat"] = (UNKNOWN, "read_secret_absent" if not secret else "devices_unset")
    else:
        status, lane = _post_lane_status(origin, secret, devices)
        if status != 200 or not isinstance(lane, dict) or lane.get("ok") is not True:
            # A 404 here means the route is not deployed yet. That is "cannot tell",
            # and it is reported as such instead of "zero work is waiting".
            checks["queue"] = (UNKNOWN, f"lane_status_http_{status if status is not None else 'none'}")
            checks["pc"] = (UNKNOWN, "not_read")
            checks["beat"] = (UNKNOWN, "not_read")
        else:
            checks["queue"] = queue_verdict(lane)
            checks["pc"] = pc_silence_verdict(lane)
            checks["beat"] = liveness_verdict(lane, now=now)
    health_status, health_edge_error = _get_health(origin)
    checks["chat"] = chat_health_verdict(health_status, health_edge_error)

    state, reasons = combine(checks)
    print(f"CONNECTOR_WATCH={state} reasons={','.join(reasons) if reasons else 'none'}")
    for name, (verdict, reason) in sorted(checks.items()):
        if _SAFE_WORD.fullmatch(name) and verdict in _SEVERITY:
            print(f"CONNECTOR_WATCH_CHECK {name}={verdict} reason={reason}")
    print("CONNECTOR_WATCH_ANSWER_TEXT_LOGGED=0 CONNECTOR_WATCH_MUTATIONS=NONE")
    return 1 if state == STALL else 0


def main(argv: list[str] | None = None) -> int:
    del argv
    return run(dict(os.environ))


if __name__ == "__main__":
    raise SystemExit(main())
