"""#4139 — Oracle-side executor for the server-server MeshCentral read.

Runs on the Oracle management host. One loop: claim the oldest dispatch from
the Chat server over the deployment channel secret, read the named file with
the OFFICIAL ``meshctrl.js`` client, and submit the outcome back. The
executor never mints approval or broker evidence, never invents a binding,
and never re-reads the PC file on a retry: a transient store failure is
answered by resending the bytes it already holds.
"""
from __future__ import annotations

import hashlib
import json
import re
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from .contracts import ContractError
from .local_agent_meshcentral_private_reader import MeshCentralReadTooLarge

#: Same path the Chat worker mounts. Executor and server must agree exactly.
POLL_PATH = "/api/claw/connector/mesh-reads/poll"
RESULT_PATH = "/api/claw/connector/mesh-reads/result"
#: The owner's stop, read back while a command is already running. One dispatch id
#: in, one boolean out; nothing is claimed and nothing is written.
CANCEL_PATH = "/api/claw/connector/mesh-reads/cancel"
#: #5997: a live claim is renewed while the command still runs. The server's lease is
#: one minute, so a third of it keeps a healthy executor always ahead of expiry while a
#: dead one stops renewing and is re-delivered by the same lease as before. Nothing
#: here is a time ceiling: the command runs until the console answers.
LEASE_RENEW_PATH = "/api/claw/connector/mesh-reads/renew"
RENEW_INTERVAL_SECONDS = 20
#: What the loop waits after a round that asked for work and got none. A poll already
#: holds five seconds on the live channel and the lane answers the moment a dispatch
#: exists, so an empty answer is a fact about the queue rather than a timeout, and the
#: next ask may come later.
#: The ceiling is a measurement, not a product rule: the beat that says "this executor
#: is alive and this PC was reachable" rides the poll body, and the product calls a
#: presence row stale at 180 seconds
#: (`apps/padiem-chat/app/claw_local_access_source.py:102`,
#: `MESH_PRESENCE_MAX_AGE_SECONDS`) while the connector watch alarms at 300
#: (`.github/scripts/connector_lane_watch.py:59`, `BEAT_STALL_SECONDS`). Sixty seconds
#: of gap plus the five the lane already holds leaves a beat at most 65 seconds old -
#: 2.8 times inside the freshness the product actually acts on. What it costs is one
#: longer wait before a dispatch that arrives into a quiet lane is claimed, measured in
#: `docs/architecture/PADIEM_CONNECTOR_IDLE_POLL_BACKOFF_4139_20261029.md` together with
#: the rounds per minute before and after.
IDLE_POLL_BASE_SECONDS = 1
IDLE_POLL_MAX_SECONDS = 60
#: Only an empty answer from the lane earns a longer wait. A round this host skipped -
#: the failover gate closed, or a held result still waiting to be sent - proves nothing
#: about the queue, and backing off there would slow exactly the moment a handover needs
#: the new host to start claiming at once.
ROUND_IDLE = "idle"
ROUND_SKIPPED = "skipped"
ROUND_WORKED = "worked"
#: #6106 follow-up: before anything on a customer PC is ended, the executor asks the
#: server whether that PC has a live claim at all. The connector's own map covers the
#: host it runs on; this is the only view that also covers the failover partner
#: (#5462), which can hold a claim on the same PC during a handover. One node
#: reference and the asker's own dispatch id in, one boolean out — the same read-only
#: shape, the same channel proof and the same ownership boundary as poll.
BUSY_PATH = "/api/claw/connector/mesh-reads/busy"
#: #5881 follow-on: the result submission is the one leg the 컴2 queue does not serve.
#: Framing the answer and writing the conversation rows stay in the Chat Worker, which
#: asks the queue only for the atomic consume. So when the claim lane is answered on
#: this host, a submission still travels to the Worker - by path, not by a second
#: switch that could be set wrong.
CHAT_ONLY_PATHS = frozenset({RESULT_PATH})
#: A channel request may never own the loop indefinitely. One host met a half-dead
#: TCP path on a single poll and blocked for 5 h 36 m with no log line at all (last
#: send and last receive 20,125 s apart, 1,971 of 3,099 bytes retransmitted), so no
#: dispatch was claimable on any PC meanwhile. This is a transport deadline on the
#: socket only - a command still runs until the console answers, by owner decision.
CHANNEL_SOCKET_TIMEOUT_SECONDS = 90
#: How long without a completed channel round means the loop itself is stuck. Only
#: the loop is watched, because while a command runs the renewer answers every
#: RENEW_INTERVAL_SECONDS and the console is the thing with no ceiling by design.
CHANNEL_STALL_SECONDS = 300
CHANNEL_WATCHDOG_INTERVAL_SECONDS = 15
#: systemd Restart=always brings the process back in RestartSec=10; exiting is the
#: only reliable way to drop a socket this process cannot see inside of.
EXIT_STALLED_CHANNEL = 87
#: Header carrying the deployment channel secret on both legs.
CHANNEL_HEADER = "X-Oracle-Mesh-Secret"
#: #5881 follow-on: the 컴2 PC queue answers the claim lane on this host's loopback,
#: and the executor runs on that host. A literal loopback address cannot be routed to
#: and cannot be met on the way, so the queue leg may cross it without TLS. Every other
#: origin still has to be https - the Worker's origin included, because its traffic can
#: leave the machine. The header, its secret and the server's check of it are unchanged.
LOOPBACK_CHANNEL_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def _is_loopback_channel_origin(origin: Any) -> bool:
    if not isinstance(origin, str) or not origin.startswith("http://"):
        return False
    try:
        host = urllib.parse.urlsplit(origin).hostname
    except ValueError:
        return False
    return isinstance(host, str) and host.lower() in LOOPBACK_CHANNEL_HOSTS


#: #5553: bound shared with the Chat poll route's presence envelope.
MAX_PRESENCE_ENTRIES = 8
#: #5573: the install tag an agent name may carry. The token rule is the same one
#: the server applies, so a lookalike inside a longer run is never a pairing.
_PAIRING_TAG_RE = re.compile(
    r"(?<![0-9A-Za-z])pd-[0-9a-f]{8}(?![0-9A-Za-z])", re.IGNORECASE,
)


def _pairing_tag_of(agent_name: Any) -> str | None:
    if not isinstance(agent_name, str):
        return None
    found = [match.group(0).lower() for match in _PAIRING_TAG_RE.finditer(agent_name)]
    return found[0] if len(found) == 1 else None
#: Cloudflare's Browser Integrity Check blocks the default Python-urllib
#: signature (error 1010) at the edge, before the channel secret is ever
#: evaluated. This executor is a first-party product client, so it identifies
#: itself with the same product token the kagent transport already sends.
PRODUCT_USER_AGENT = "PadiemClaw/1.0 (kagent; oracle-mesh-executor)"
#: Owner decision 2026-10-28: no PADIEM byte ceiling on command output or the
#: desktop wire. None means no product bound; the platforms that carry the
#: bytes keep their own limits. A server-authorized PC read still names its own
#: requested amount (the dispatch max_bytes, else the legacy default below).
MAX_COMMAND_BYTES: int | None = None
MAX_READ_BYTES_ENVELOPE = 20_000_000
MAX_READ_BYTES = 6_000_000
#: Existing PC-file error markers the Engine already maps. A read failure is a
#: truthful body, not an empty success: the executor reports the marker so the
#: verified result lane can deliver the same outcome the model lane expects.
PC_FILE_ERROR_PREFIX = "PADIEM_PC_FILE_ERROR:"
PC_FILE_TOO_LARGE_MARKER = PC_FILE_ERROR_PREFIX + "too_large"
PC_FILE_READ_FAILED_MARKER = PC_FILE_ERROR_PREFIX + "read_failed"
#: A result the server refuses for a non-retryable reason is quarantined to
#: the pending dir instead of dropped: the bytes survive a restart, the cause
#: is recorded next to them, and the queue moves on. Retrying forever would
#: block the whole queue behind one dead result; dropping silently would lose
#: the only copy of an execution.
MAX_RESULT_REJECTIONS = 3
#: First resend wait and cap for transient failures. The wait grows per
#: consecutive transient refusal and resets on any decisive answer, so a
#: flapping channel is not hammered at the poll cadence.
_BACKOFF_FIRST_SECONDS = 5
_BACKOFF_MAX_SECONDS = 60
#: Pending-result files under the pending dir. The body travels as raw bytes
#: beside the JSON meta so no hex/base64 copy inflates a large output. A body
#: written by this revision is named after its own digest, so a new result
#: never truncates the body an existing manifest still points at.
_PENDING_META_NAME = "pending-result.json"
_PENDING_BODY_NAME = "pending-result.body"
_PENDING_BODY_PREFIX = "pending-result-"
_PENDING_BODY_SUFFIX = ".body"


class OracleMeshChannelRefused(RuntimeError):
    """Bounded refusal of one executor/server exchange. Never carries content."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuses 30x instead of following it.

    ``urllib.request.urlopen`` builds a default opener that *follows* redirects.
    An executor channel carrying the deployment secret must never be replayed to
    another origin, so the redirect is surfaced as an ordinary refusal.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        del req, fp, code, msg, headers, newurl
        return None


@dataclass(frozen=True, slots=True)
class OracleMeshDispatch:
    """One claimed dispatch: exactly what the server authorized, nothing more."""

    dispatch_id: str
    nonce: str
    node_ref: str
    file_path: str
    command_id: str
    run_id: str
    #: #5015: server correlation id from the dispatch, when an older server
    #: supplies it. Used only for bounded phase logs, never for execution.
    request_id: str | None = None
    #: #4139: "read" (the 047 file lane) or "command" (the 048 terminal lane).
    kind: str = "read"
    #: The exact single-line command for kind="command"; never used for a read.
    command_text: str | None = None
    #: #5015: server-computed read bound. Only the poll response may set it;
    #: a missing value keeps the shared 6 MB read envelope for older servers.
    max_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class OracleMeshExecutionOutcome:
    """What one real execution produced, already size-bounded and hashed.

    ``exit_code`` is ``None`` only when the PC never reported one (a console
    that never answered, or a run that hit the time limit). It is never
    defaulted to 0: an unobserved exit code is not a successful one.
    """

    termination: str
    exit_code: int | None
    body: bytes = b""
    #: Human-readable observation for lanes whose evidence is not the body
    #: itself (desktop notes and screenshot descriptions). Always text-safe.
    note: str = ""


def _require_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise OracleMeshChannelRefused(f"{name} is not a bounded reference")
    return value


class OracleMeshExecutor:
    """Single-thread executor over one authenticated Chat channel.

    ``read_port`` is the merged private MeshCentral port: it owns the operator
    credential (call-time provider, stdin only, marker on argv) and runs the
    official client. ``transport`` is injected so the network boundary is
    explicit and testable; the default performs a verified HTTPS request with
    redirects explicitly refused.
    """

    def __init__(
        self,
        *,
        chat_origin: str,
        channel_secret: str,
        queue_origin: Optional[str] = None,
        read_port: Any,
        command_port: Any = None,
        desktop_port: Any = None,
        timeout_seconds: int | None = None,
        channel_timeout_seconds: int = CHANNEL_SOCKET_TIMEOUT_SECONDS,
        transport: Optional[Callable[..., tuple[int, dict[str, Any]]]] = None,
        pending_dir: Optional[str] = None,
        claim_gate: Optional[Callable[[], bool]] = None,
        presence_provider: Optional[Callable[[], Any]] = None,
        pairing_provider: Optional[Callable[[], Any]] = None,
        presence_round_begin: Optional[Callable[[], None]] = None,
    ) -> None:
        if not isinstance(chat_origin, str) or not chat_origin.startswith("https://"):
            raise ContractError("the chat channel must be an https origin")
        if len(chat_origin) > 300 or chat_origin.rstrip("/") != chat_origin:
            raise ContractError("the chat origin must be a bare https origin")
        # An empty or absent queue origin is today's behaviour: every leg, including
        # the claim, travels to the Worker. That is also the rollback, which is why it
        # is the state the field falls back to rather than a mode to configure.
        if queue_origin and (
            not isinstance(queue_origin, str)
            or len(queue_origin) > 300
            or queue_origin.rstrip("/") != queue_origin
            or not (queue_origin.startswith("https://")
                    or _is_loopback_channel_origin(queue_origin))
        ):
            raise ContractError("the queue channel must be an https or loopback origin")
        if (
            not isinstance(channel_secret, str)
            or not 16 <= len(channel_secret) <= 256
            or any(ord(ch) < 33 or ord(ch) > 126 for ch in channel_secret)
        ):
            raise ContractError("the deployment channel secret is required")
        if not callable(getattr(read_port, "read_bytes", None)):
            raise ContractError("a private MeshCentral file read port is required")
        if command_port is not None and not callable(
            getattr(command_port, "run_command", None)
        ):
            raise ContractError("a MeshCentral command port must expose run_command")
        if desktop_port is not None and not callable(
            getattr(desktop_port, "run_desktop_op", None)
        ):
            raise ContractError("a MeshCentral desktop port must expose run_desktop_op")
        if (
            not isinstance(channel_timeout_seconds, int)
            or isinstance(channel_timeout_seconds, bool)
            or not 1 <= channel_timeout_seconds <= 900
        ):
            raise ContractError("the channel socket deadline must be 1..900 seconds")
        self._origin = chat_origin
        self._queue_origin = queue_origin or None
        self._secret = channel_secret
        self._read_port = read_port
        self._command_port = command_port
        self._desktop_port = desktop_port
        self._timeout = timeout_seconds
        self._channel_timeout = channel_timeout_seconds
        #: When the last channel round reached an answer or a classified failure.
        #: Only the watchdog reads it, and a round that fails counts: the stall this
        #: guards is a loop that stopped asking at all, not a channel that answers
        #: badly.
        self._last_round_at = time.monotonic()
        #: Which of the three shapes the last round had, read by the service loop to
        #: decide whether the queue really is empty. Starts as a skip: no lane has
        #: answered for this process yet, so nothing has been earned.
        self.last_round = ROUND_SKIPPED
        self._transport = transport or self._https_post
        self._pending: Optional[tuple[OracleMeshDispatch, OracleMeshExecutionOutcome]] = None
        #: The connector's own answer to "is a dispatch running on this PC right now".
        #: One entry per PC, written when a claim starts and removed when the console
        #: has answered, so the line sweep can be told "busy" from "abandoned" from a
        #: real field instead of a text match. A held result is NOT in here: the work
        #: on the PC already finished, so that PC's console is free.
        self._active_by_node: dict[str, str] = {}
        self._active_lock = threading.Lock()
        #: Line-blockage observations, counted here so the journal and the report can
        #: say how often a PC needed clearing without anyone being asked.
        self._line_blocked = 0
        self._line_cleared = 0
        self._rejections = 0
        self._transients = 0
        self._pending_dir = pending_dir
        #: The body file the current manifest points at, once durable.
        self._pending_body: Optional[str] = None
        # #5462: an optional claim gate. When the failover controller has
        # moved the claim to the other host, the gate refuses the poll on
        # this host, so the two executors never claim the same dispatch.
        # A host with no gate keeps the historical behaviour.
        if claim_gate is not None and not callable(claim_gate):
            raise ContractError("the claim gate must be callable")
        self._claim_gate = claim_gate
        # #5553: an optional presence observation that rides on the ONE
        # authenticated poll. It is derived from the local MeshCentral probe,
        # never from caller input, and a probe failure removes the field
        # instead of blocking the poll.
        if presence_provider is not None and not callable(presence_provider):
            raise ContractError("the presence provider must be callable")
        self._presence_provider = presence_provider
        # #5573: the pairing observation is a second, separate source of the SAME
        # authenticated beat. Tags are remembered only in this process: a claim
        # already completed must not be re-offered on every poll, and a restart
        # costs nothing because the server refuses a used tag on its own.
        if pairing_provider is not None and not callable(pairing_provider):
            raise ContractError("the pairing provider must be callable")
        self._pairing_provider = pairing_provider
        # The round boundary of a shared device table, if the deployment hands one
        # over. It is called before either provider is read, never after.
        if presence_round_begin is not None and not callable(presence_round_begin):
            raise ContractError("the presence round boundary must be callable")
        self._presence_round_begin = presence_round_begin
        self._reported_pairing_tags: set[str] = set()
        self._carried_pairing_tags: list[str] = []

    # ---- channel -------------------------------------------------------
    def _origin_for(self, path: str) -> str:
        """Which server this leg asks.

        The claim lane is answered by the queue on this host when one is configured;
        the result submission is not served there and always travels to the Worker.
        With no queue configured every leg asks the Worker, which is the state the
        lane has run in and the state it rolls back to.
        """

        if self._queue_origin is not None and path not in CHAT_ONLY_PATHS:
            return self._queue_origin
        return self._origin

    def _https_post(
        self, path: str, payload: Optional[dict[str, Any]] | bytes,
    ) -> tuple[int, dict[str, Any]]:
        """One verified HTTPS POST. Redirects are refused, not followed."""
        url = f"{self._origin_for(path)}{path}"
        if isinstance(payload, (bytes, bytearray)):
            # #4379: an already framed body (desktop screenshot) travels as
            # octet-stream; its JPEG bytes are never re-encoded as base64.
            data = bytes(payload)
            content_type = "application/octet-stream"
        else:
            # UTF-8 as JSON permits: escaping every non-ASCII byte would inflate
            # a Korean command output about six times, so a body far below the
            # wire envelope would still be refused as too large and quarantined.
            data = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
            content_type = "application/json"
        request = urllib.request.Request(
            url, data=data, method="POST",
            headers={
                "Content-Type": content_type,
                CHANNEL_HEADER: self._secret,
                "Accept": "application/json",
                "User-Agent": PRODUCT_USER_AGENT,
                # Retain the authenticated HTTPS request until a queued
                # dispatch is available. Old consumers still get immediate poll.
                **({"X-Oracle-Mesh-Wait": "5"} if path == POLL_PATH else {}),
            },
        )
        context = ssl.create_default_context()
        # urllib follows 30x by default; an executor channel must never be
        # silently moved to another origin, so redirects are refused outright.
        opener = urllib.request.build_opener(_NoRedirect())
        try:
            with opener.open(request, timeout=self._channel_timeout) as response:
                # One extra byte is the overflow detector, never content: a
                # poll response carries the command it wants run, so reading a
                # fixed 64 KiB used to truncate a long command's JSON and make
                # the dispatch look absent. The bound is the same wire envelope
                # the submit leg is held to.
                raw = response.read()
                status = int(getattr(response, "status", 0) or 0)
        except urllib.error.HTTPError as exc:
            raw = exc.read(4096)
            status = int(exc.code)
        except OracleMeshChannelRefused:
            raise
        except Exception as exc:  # transport refused/unreachable
            raise OracleMeshChannelRefused("chat channel transport refused") from exc
        finally:
            self._last_round_at = time.monotonic()
        try:
            decoded = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            decoded = {}
        if not isinstance(decoded, dict):
            decoded = {}
        return status, decoded

    def _post(self, path: str, payload: Optional[dict[str, Any]] | bytes) -> tuple[int, dict[str, Any]]:
        try:
            return self._transport(path, payload)
        except OracleMeshChannelRefused:
            raise
        except Exception as exc:
            raise OracleMeshChannelRefused("chat channel transport refused") from exc

    # ---- legs ----------------------------------------------------------
    def _poll_payload(self) -> Optional[dict[str, Any]]:
        """The optional presence beat for this poll, or None when absent.

        The executor observes; it never claims ONLINE. The server re-derives
        the canonical device/account from the deployment map and stamps the
        receipt itself. Any probe failure, malformed value or empty result
        omits the field entirely so the poll proceeds exactly as before.
        """
        provider = self._presence_provider
        pairing_provider = self._pairing_provider
        if provider is None and pairing_provider is None:
            return None
        if self._presence_round_begin is not None:
            # A new poll asks the local server anew. Without this boundary a second
            # round behind a fast first one could report the previous round's table.
            self._presence_round_begin()
        try:
            carried: list[str] = []
            tagged: list[dict[str, Any]] = []
            if pairing_provider is not None:
                pairing_rows = pairing_provider()
                if pairing_rows is None:
                    pairing_rows = ()
                elif not isinstance(pairing_rows, (list, tuple)):
                    return None
                for row in pairing_rows:
                    entry = self._presence_entry(row)
                    if entry is None:
                        return None
                    tag = _pairing_tag_of(entry.get("agent_name"))
                    # Only a name carrying exactly one tag is a pairing candidate,
                    # and an untagged name is never sent: it is private text about
                    # somebody's machine, not evidence this server can use.
                    if tag is None or tag in self._reported_pairing_tags:
                        continue
                    entry["pairing_tag"] = tag
                    tagged.append(entry)
            rows = () if provider is None else provider()
            if not isinstance(rows, (list, tuple)):
                return None
            configured: list[dict[str, Any]] = []
            for row in rows:
                entry = self._presence_entry(row)
                if entry is None:
                    return None
                # A name travels only when it carries a pairing tag. Otherwise it
                # is private text about somebody's machine that the server has no
                # use for, and the same node is already reported by id.
                if "agent_name" in entry and _pairing_tag_of(entry["agent_name"]) is None:
                    entry.pop("agent_name")
                configured.append(entry)
            # Tags are the point of this beat, so they take the budget first and
            # ordinary presence fills what is left. Anything that does not fit is
            # simply not carried, and its tag stays unreported until a later poll.
            carried_ids = {entry["device_id"] for entry in tagged}
            entries = (tagged + [
                entry for entry in configured if entry["device_id"] not in carried_ids
            ])[:MAX_PRESENCE_ENTRIES]
            self._carried_pairing_tags = [
                entry.pop("pairing_tag") for entry in entries if "pairing_tag" in entry
            ]
            if not entries:
                return None
        except Exception:
            # The beat is evidence, not work: a failed probe must never turn
            # into a channel refusal that stalls the queue.
            return None
        return {"presence": entries}

    def _presence_entry(self, row: Any) -> Optional[dict[str, Any]]:
        """One beat entry, or ``None`` when the row is not a well-formed beat.

        The shape is closed and the values are bounded, so neither source - the
        ordinary probe nor the pairing enumeration - can widen what travels.
        """
        if type(row) is not dict or not {"device_id", "connected"} <= set(row) or (
            set(row) - {"device_id", "connected", "agent_name"}
        ):
            return None
        device_id = row["device_id"]
        if (
            not isinstance(device_id, str)
            or not device_id
            or len(device_id) > 256
            or any(ord(ch) < 33 or ord(ch) > 126 for ch in device_id)
        ):
            return None
        connected = row["connected"]
        if type(connected) is not bool:
            return None
        entry: dict[str, Any] = {"device_id": device_id, "connected": connected}
        agent_name = row.get("agent_name")
        if agent_name is not None:
            if (
                not isinstance(agent_name, str)
                or not 1 <= len(agent_name) <= 256
                # Names are prose: a space is allowed, a control character or a
                # non-ASCII byte is not.
                or any(ord(ch) < 32 or ord(ch) > 126 for ch in agent_name)
            ):
                return None
            entry["agent_name"] = agent_name
        return entry

    def poll_once(self) -> Optional[OracleMeshDispatch]:
        """Claim the oldest dispatch, or None when the queue is empty."""
        payload = self._poll_payload()
        status, data = self._post(POLL_PATH, payload)
        if status != 200 or data.get("ok") is not True:
            raise OracleMeshChannelRefused("chat channel refused the poll")
        if self._carried_pairing_tags and isinstance(payload, dict) and payload.get("presence"):
            # Reported only once the server took the beat: a poll that was
            # refused or lost leaves the tag unreported so a later poll offers
            # it again, rather than silently dropping a pairing until restart.
            self._reported_pairing_tags.update(self._carried_pairing_tags)
        self._carried_pairing_tags = []
        dispatch = data.get("dispatch")
        if dispatch is None:
            return None
        if not isinstance(dispatch, dict):
            raise OracleMeshChannelRefused("chat channel returned a malformed dispatch")
        kind = dispatch.get("kind") or "read"
        if kind not in ("read", "command", "desktop"):
            raise OracleMeshChannelRefused("chat channel returned an unknown dispatch kind")
        command_text = dispatch.get("command_text")
        if kind in ("command", "desktop"):
            # The server owns the command; the executor never invents one and
            # never falls back to the file lane when it is missing.
            if not isinstance(command_text, str) or not command_text.strip():
                raise OracleMeshChannelRefused("chat channel returned a command dispatch without a command")
        else:
            command_text = None
        max_bytes = None
        if kind == "read":
            supplied = dispatch.get("max_bytes")
            if supplied is not None:
                # The server decides the bound. A value outside the shared
                # envelope is malformed, and the executor never lets a caller
                # raise its own limit.
                if (
                    isinstance(supplied, bool)
                    or not isinstance(supplied, int)
                    or not 0 < supplied <= MAX_READ_BYTES_ENVELOPE
                ):
                    raise OracleMeshChannelRefused(
                        "chat channel returned an unbounded read limit"
                    )
                max_bytes = supplied
        request_id = dispatch.get("request_id")
        if request_id is not None:
            request_id = _require_text(request_id, "request_id")
        return OracleMeshDispatch(
            dispatch_id=_require_text(dispatch.get("dispatch_id"), "dispatch_id"),
            nonce=_require_text(dispatch.get("nonce"), "nonce"),
            node_ref=_require_text(dispatch.get("node_ref"), "node_ref"),
            file_path=_require_text(dispatch.get("file_path"), "file_path"),
            command_id=_require_text(dispatch.get("command_id"), "command_id"),
            run_id=_require_text(dispatch.get("run_id"), "run_id"),
            request_id=request_id,
            kind=kind,
            command_text=command_text,
            max_bytes=max_bytes,
        )

    def execute(self, dispatch: OracleMeshDispatch) -> OracleMeshExecutionOutcome:
        """One real official-client execution. Failures are outcomes, not exceptions."""
        if dispatch.kind == "command":
            return self._execute_command(dispatch)
        if dispatch.kind == "desktop":
            return self._execute_desktop(dispatch)
        return self._execute_read(dispatch)

    def _execute_read(
        self, dispatch: OracleMeshDispatch
    ) -> OracleMeshExecutionOutcome:
        """#5015: one private read whose failures keep an identifiable body.

        The read port is bounded by the server-computed dispatch value (the
        shared 6 MB envelope when an older server omits it). Oversize is
        reported as the existing ``too_large`` marker, every other read or
        download failure as ``read_failed``, and invalid UTF-8 as
        ``read_failed`` too ? the verified result lane is a UTF-8 text lane,
        so that body cannot cross it. A failed read is never collapsed into an
        empty success.
        """
        read_bound = dispatch.max_bytes
        if read_bound is None:
            read_bound = MAX_READ_BYTES
        read_bound = max(1, min(read_bound, MAX_READ_BYTES_ENVELOPE))
        call: dict[str, Any] = {
            "node_ref": dispatch.node_ref,
            "file_path": dispatch.file_path,
            "timeout_seconds": (self._timeout * 4 if self._timeout is not None else None),
        }
        if dispatch.max_bytes is not None:
            # Pass the server-computed bound only when the poll supplied one;
            # older servers keep the port's historical default.
            call["max_bytes"] = read_bound
        try:
            body = self._read_port.read_bytes(**call)
        except MeshCentralReadTooLarge:
            return OracleMeshExecutionOutcome(
                termination="exited", exit_code=1,
                body=PC_FILE_TOO_LARGE_MARKER.encode("utf-8"),
            )
        except Exception:
            return OracleMeshExecutionOutcome(
                termination="exited", exit_code=1,
                body=PC_FILE_READ_FAILED_MARKER.encode("utf-8"),
            )
        if not isinstance(body, (bytes, bytearray)):
            return OracleMeshExecutionOutcome(
                termination="exited", exit_code=1,
                body=PC_FILE_READ_FAILED_MARKER.encode("utf-8"),
            )
        raw = bytes(body)
        if len(raw) > read_bound:
            # Oversize is refused, never truncated.
            return OracleMeshExecutionOutcome(
                termination="exited", exit_code=1,
                body=PC_FILE_TOO_LARGE_MARKER.encode("utf-8"),
            )
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            return OracleMeshExecutionOutcome(
                termination="exited", exit_code=1,
                body=PC_FILE_READ_FAILED_MARKER.encode("utf-8"),
            )
        return OracleMeshExecutionOutcome(termination="exited", exit_code=0, body=raw)

    def _trace_command(
        self,
        dispatch: OracleMeshDispatch,
        phase: str,
        started: float,
        **fields: Any,
    ) -> None:
        """Bounded phase correlation only: never command or output content.

        Logging is strictly observational. A closed/broken stderr, a formatter
        error, or a failing test double must never change the execution result.
        """
        try:
            elapsed_ms = max(0, int((time.monotonic() - started) * 1000))
            safe = " ".join(
                f"{key}={value}"
                for key, value in fields.items()
                if value is not None and isinstance(value, (str, int, bool))
            )
            print(
                "oracle-mesh-command"
                f" phase={phase}"
                f" ts={datetime.now(timezone.utc).isoformat()}"
                f" elapsed_ms={elapsed_ms}"
                f" dispatch_id={dispatch.dispatch_id}"
                f" request_id={dispatch.request_id or '-'}"
                f" command_id={dispatch.command_id}"
                f" run_id={dispatch.run_id}"
                + (f" {safe}" if safe else ""),
                file=sys.stderr,
                flush=True,
            )
        except Exception:
            # Instrumentation is best-effort; the command outcome is authoritative.
            pass

    def _cancel_probe(self, dispatch: OracleMeshDispatch) -> Callable[[], bool]:
        """Ask the server, once per idle read slice, whether the owner stopped this.

        The answer that ends a real command must come from the server's own record
        of the owner's press, so every other case - no dispatch id, a refused
        channel, a non-200, a body that is not that shape - is "no". Choosing "no"
        on a transport problem is deliberate: an unreadable answer is not an owner's
        stop, and the cost of the other reading is a PC operation that was never
        asked to end.
        """
        dispatch_id = str(getattr(dispatch, "dispatch_id", "") or "")
        if not dispatch_id:
            return lambda: False

        def probe() -> bool:
            try:
                status, body = self._post(CANCEL_PATH, {"dispatch_id": dispatch_id})
            except Exception:
                return False
            if status != 200 or not isinstance(body, dict):
                return False
            return body.get("cancelled") is True

        return probe

    def _line_guard(self, dispatch: OracleMeshDispatch) -> Callable[[], bool]:
        """Ask the server whether this PC's console may be cleared at all.

        True means "nothing on this PC is claimed, clear it". Every other answer -
        a live claim under any executor host, a refused channel, a non-200, a body
        that is not that shape - is False. The reading is deliberate and is the
        opposite of the cancel probe's: the action this answer unlocks ends a process
        on a customer machine, so an unreadable answer must never be the one that
        authorises it. A PC that stays wedged for one more minute is recoverable; a
        real command cut short is not, and standard rule 1 forbids it.
        """
        node_ref = str(getattr(dispatch, "node_ref", "") or "")
        dispatch_id = str(getattr(dispatch, "dispatch_id", "") or "")
        if not node_ref:
            return lambda: False

        def probe() -> bool:
            try:
                status, body = self._post(
                    BUSY_PATH,
                    {"node_ref": node_ref, "dispatch_id": dispatch_id},
                )
            except Exception:
                return False
            if status != 200 or not isinstance(body, dict):
                return False
            if body.get("ok") is not True:
                return False
            return body.get("working") is False

        return probe

    def _execute_command(
        self, dispatch: OracleMeshDispatch
    ) -> OracleMeshExecutionOutcome:
        """#4139 terminal lane: run the command the server put in the dispatch.

        The exit code is whatever the PC reported through the sentinel. When no
        code was observed the outcome says so (``no_reply`` for no console
        answer, ``timed_out`` for a wait that expired, ``no_exit_code`` for a
        complete console answer whose ``$LASTEXITCODE`` was empty) instead of
        borrowing the shell's own success.
        """
        if self._command_port is None:
            # A command dispatch on an executor that was not composed with a
            # command port is a misconfiguration, not a silent no-op.
            raise OracleMeshChannelRefused("command execution is not configured")
        started = time.monotonic()
        self._trace_command(dispatch, "start", started)

        def phase(phase_name: str) -> None:
            self._trace_command(dispatch, phase_name, started)

        try:
            observed = self._command_port.run_command(
                node_ref=dispatch.node_ref,
                command=dispatch.command_text or "",
                # Long-running commands carry no PADIEM client deadline; the
                # progress trace is already reported through phase (#5983). The
                # owner's stop is what ends one now (#5895): the probe asks the
                # server between read slices whether this dispatch was cancelled.
                timeout_seconds=None,
                phase_observer=phase,
                cancel_probe=self._cancel_probe(dispatch),
                # The marker the PC-side stop needs: this command's own dispatch.
                dispatch_id=getattr(dispatch, "dispatch_id", None),
                # What the console sweep may never touch: the dispatches this
                # connector is running, read from its own state.
                keep_dispatch_ids=self.active_dispatch_ids(),
                # Whether the server sees any live claim on this PC at all. The
                # connector's own map cannot see the failover partner's claim.
                line_guard=self._line_guard(dispatch),
            )
        except Exception as exc:
            if type(exc).__name__ == "MeshCentralCommandRefused":
                # The port refused before the PC was asked. Collapsing that into
                # ``no_reply`` would report a silent console for a command that
                # never ran, so the two observations stay separate.
                self._trace_command(dispatch, "refused", started, reason="port")
                return OracleMeshExecutionOutcome(
                    termination="not_executed", exit_code=None, body=b"",
                )
            self._trace_command(
                dispatch, "error", started, error_type=type(exc).__name__,
            )
            return OracleMeshExecutionOutcome(termination="no_reply", exit_code=None, body=b"")
        termination = getattr(observed, "termination", "no_reply")
        if termination not in (
            "exited", "timed_out", "no_reply", "no_exit_code", "not_executed",
            "output_too_large", "bad_reply", "cancelled",
        ):
            termination = "no_reply"
        exit_code = getattr(observed, "exit_code", None)
        if isinstance(exit_code, bool) or not isinstance(exit_code, int):
            exit_code = None
        if termination in ("exited", "output_too_large") and exit_code is None:
            # The sentinel line arrived without a number: the exit code is not
            # observed, so the run cannot claim a clean exit.
            termination = "no_reply"
        body = getattr(observed, "output", b"")
        if not isinstance(body, (bytes, bytearray)):
            body = b""
        raw = bytes(body)
        blocked = getattr(observed, "line_blocked", 0)
        cleared = getattr(observed, "line_cleared", 0)
        blocked = blocked if isinstance(blocked, int) and not isinstance(blocked, bool) else 0
        cleared = cleared if isinstance(cleared, int) and not isinstance(cleared, bool) else 0
        self._line_blocked += max(0, blocked)
        self._line_cleared += max(0, cleared)
        self._trace_command(
            dispatch, "result", started, termination=termination,
            output_bytes=len(raw),
            line_blocked=blocked or None,
            line_cleared=cleared or None,
        )
        return OracleMeshExecutionOutcome(
            termination=termination, exit_code=exit_code, body=raw,
        )

    def _execute_desktop(
        self, dispatch: OracleMeshDispatch
    ) -> OracleMeshExecutionOutcome:
        """#4139 desktop lane: one relay observation or input on the PC.

        The op grammar is parsed before the PC is asked: an unknown op is
        ``not_executed``, never a guessed click. A capture returns the JPEG
        bytes as the body with the observation as the note; an input op
        returns an empty body with its note. Oversize bodies are withheld,
        never truncated.
        """
        from .local_agent_meshcentral_desktop_port import parse_desktop_op

        if self._desktop_port is None:
            raise OracleMeshChannelRefused("desktop execution is not configured")
        try:
            op, arg = parse_desktop_op(dispatch.command_text or "")
        except Exception:
            return OracleMeshExecutionOutcome(
                termination="not_executed", exit_code=None, body=b"",
                note="the desktop op was refused before the PC was asked",
            )
        try:
            desktop_timeout: dict[str, Any] = {}
            if self._timeout is not None:
                # A full multi-monitor redraw moves megabytes of tiles; the
                # read lane already waits timeout*4 for the same reason.
                desktop_timeout["timeout_seconds"] = max(1, self._timeout * 4)
            observed = self._desktop_port.run_desktop_op(
                node_ref=dispatch.node_ref,
                op=op,
                arg=arg,
                **desktop_timeout,
            )
        except Exception as exc:
            if type(exc).__name__ == "MeshCentralDesktopRefused":
                return OracleMeshExecutionOutcome(
                    termination="not_executed", exit_code=None, body=b"",
                    note="the desktop relay was refused before the PC was asked",
                )
            return OracleMeshExecutionOutcome(
                termination="desktop_unavailable", exit_code=None, body=b"",
                note="the desktop session did not answer",
            )
        termination = getattr(observed, "termination", "desktop_unavailable")
        if termination not in (
            "captured", "acted", "desktop_unavailable", "timed_out",
            "not_executed", "output_too_large",
        ):
            termination = "desktop_unavailable"
        note = getattr(observed, "note", "")
        if not isinstance(note, str):
            note = ""
        body = getattr(observed, "image", b"")
        if not isinstance(body, (bytes, bytearray)):
            body = b""
        raw = bytes(body)
        if termination == "captured" and not raw:
            termination = "desktop_unavailable"
            note = (note + "; no image bytes" if note else "no image bytes")

        return OracleMeshExecutionOutcome(
            termination=termination, exit_code=None, body=raw, note=note,
        )

    # ---- held-result persistence -------------------------------------
    def _pending_dir_path(self) -> Optional[str]:
        import os

        if not isinstance(self._pending_dir, str) or not self._pending_dir:
            return None
        return self._pending_dir

    def _pending_meta_path(self) -> Optional[str]:
        import os

        directory = self._pending_dir_path()
        if directory is None:
            return None
        return os.path.join(directory, _PENDING_META_NAME)

    @staticmethod
    def _pending_body_name(digest: str) -> str:
        """The body file is named after its own digest.

        A new held result therefore lands in a new file instead of truncating
        the body an existing manifest still points at, which is what makes the
        two-step commit below safe.
        """
        return _PENDING_BODY_PREFIX + digest[:32] + _PENDING_BODY_SUFFIX

    @staticmethod
    def _atomic_write(directory: str, name: str, payload: bytes) -> None:
        """Create-or-replace one file, fully written, or leave the old one alone.

        Node/POSIX guarantee ``os.replace`` is atomic within a directory, and
        the fsyncs put both the bytes and the rename on disk before the executor
        posts. The previous code opened the live file with ``O_TRUNC`` and
        ignored the error, so a full disk or a crash mid-write destroyed the
        only copy of an execution the PC had already performed.
        """
        import os
        import tempfile

        fd, temp = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".part")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, os.path.join(directory, name))
        except BaseException:
            try:
                os.unlink(temp)
            except OSError:
                pass
            raise
        try:
            dir_fd = os.open(directory, os.O_RDONLY)
        except OSError:
            return  # not every platform lets a directory be fsynced
        try:
            os.fsync(dir_fd)
        except OSError:
            pass
        finally:
            os.close(dir_fd)

    def _persist_pending(self) -> Optional[str]:
        """Make the held result durable before submitting it.

        Returns ``None`` when the result is durable (or already was), and the
        OSError name when it is not — the caller reports that instead of
        pretending a write that failed happened. A crash between a real
        execution and the server's acceptance must never re-execute the PC
        command on restart, so recovery only resends these exact bytes.

        Commit order: the content-addressed body first, then the manifest that
        names it. A crash between the two leaves the previous complete pair
        readable and the new body unreferenced, never a manifest whose bytes
        are gone.
        """
        import os

        directory = self._pending_dir_path()
        if directory is None or self._pending is None:
            return None
        dispatch, outcome = self._pending
        digest = hashlib.sha256(outcome.body).hexdigest()
        body_name = self._pending_body_name(digest)
        meta = {
            "dispatch_id": dispatch.dispatch_id,
            "nonce": dispatch.nonce,
            "node_ref": dispatch.node_ref,
            "file_path": dispatch.file_path,
            "command_id": dispatch.command_id,
            "run_id": dispatch.run_id,
            "kind": dispatch.kind,
            "command_text": dispatch.command_text,
            "max_bytes": dispatch.max_bytes,
            "termination": outcome.termination,
            "exit_code": outcome.exit_code,
            "note": outcome.note if isinstance(outcome.note, str) else "",
            "content_sha256": digest,
            "content_bytes": len(outcome.body),
            "body_name": body_name,
        }
        encoded = json.dumps(meta).encode("utf-8")
        meta_path = os.path.join(directory, _PENDING_META_NAME)
        if self._pending_body_name_matches(meta_path, encoded):
            # The exact same held result is already durable. A plain resend
            # rewrites nothing, so the good copy is never exposed to a write
            # that cannot change it.
            self._pending_body = body_name
            return None
        try:
            if not os.path.exists(os.path.join(directory, body_name)):
                self._atomic_write(directory, body_name, outcome.body)
            self._atomic_write(directory, _PENDING_META_NAME, encoded)
        except OSError as exc:
            return type(exc).__name__
        previous = self._pending_body
        if previous is not None and previous != body_name:
            try:
                os.remove(os.path.join(directory, previous))
            except OSError:
                pass  # an unreferenced body is harmless; the manifest is current
        self._pending_body = body_name
        return None

    def _pending_body_name_matches(self, meta_path: str, encoded: bytes) -> bool:
        import os

        try:
            with open(meta_path, "rb") as handle:
                current = handle.read()
        except OSError:
            return False
        if current != encoded:
            return False
        try:
            manifest = json.loads(current.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return False
        name = manifest.get("body_name") if isinstance(manifest, dict) else None
        if not isinstance(name, str) or not name:
            return False
        return os.path.exists(os.path.join(os.path.dirname(meta_path), name))

    @staticmethod
    def _safe_quarantine_stem(dispatch_id: str) -> str:
        import hashlib as _hashlib

        if (
            isinstance(dispatch_id, str)
            and dispatch_id
            and len(dispatch_id) <= 128
            and all(ch.isalnum() or ch in "-_." for ch in dispatch_id)
        ):
            return dispatch_id
        return "id-" + _hashlib.sha256(str(dispatch_id).encode("utf-8")).hexdigest()[:16]

    def _clear_persisted_pending(self) -> None:
        """Drop the accepted manifest and the body it names, nothing newer.

        Bodies are removed through the manifest that references them, so an
        accepted result cannot delete a body another result still points at.
        """
        import os

        directory = self._pending_dir_path()
        if directory is None:
            return
        meta_path = os.path.join(directory, _PENDING_META_NAME)
        names = [_PENDING_META_NAME]
        try:
            with open(meta_path, "rb") as handle:
                manifest = json.loads(handle.read().decode("utf-8"))
            if isinstance(manifest, dict) and isinstance(manifest.get("body_name"), str):
                names.append(manifest["body_name"])
        except (OSError, ValueError, UnicodeDecodeError):
            pass
        if self._pending_body:
            names.append(self._pending_body)
        names.append(_PENDING_BODY_NAME)  # pre-content-addressed layout
        for name in dict.fromkeys(names):
            try:
                os.remove(os.path.join(directory, name))
            except OSError:
                pass
        self._pending_body = None

    def _quarantine_pending(self, *, reason: str, status: Any = None, code: Any = None) -> dict[str, Any]:
        """Preserve a permanently refused result and release the queue.

        The bytes, the dispatch identity and the refusal cause stay on disk
        under a dispatch-derived name; nothing is re-executed and nothing is
        silently discarded.
        """
        import os
        import time

        dispatch, outcome = self._pending if self._pending is not None else (None, None)
        stem = self._safe_quarantine_stem(
            dispatch.dispatch_id if dispatch is not None else "unknown"
        )
        record: dict[str, Any] = {
            "reason": reason,
            "status": status,
            "code": code,
            "quarantined_at": int(time.time()),
        }
        quarantine_path: Any = None
        persist_error: Any = None
        if self._pending is not None and self._pending_dir:
            body = outcome.body if outcome is not None else b""
            record.update({
                "dispatch_id": dispatch.dispatch_id,
                "nonce_sha256": hashlib.sha256(dispatch.nonce.encode("utf-8")).hexdigest(),
                "node_ref": dispatch.node_ref,
                "run_id": dispatch.run_id,
                "kind": dispatch.kind,
                "max_bytes": dispatch.max_bytes,
                "termination": outcome.termination,
                "exit_code": outcome.exit_code,
                "note": outcome.note if isinstance(outcome.note, str) else "",
                "content_sha256": hashlib.sha256(body).hexdigest(),
                "content_bytes": len(body),
            })
            base = os.path.join(self._pending_dir, "quarantine-" + stem)
            quarantine_path = base + ".json"
            body_name = os.path.basename(base) + ".body"
            record["body_name"] = body_name
            persist_error: Any = None
            try:
                if not os.path.exists(base + ".body"):
                    self._atomic_write(self._pending_dir, body_name, body)
                if not os.path.exists(quarantine_path):
                    self._atomic_write(
                        self._pending_dir, os.path.basename(quarantine_path),
                        json.dumps(record).encode("utf-8"),
                    )
            except OSError as exc:
                # The cause is reported instead of swallowed: a quarantine that
                # could not be written must not look like preserved evidence.
                persist_error = type(exc).__name__
                record["persist_error"] = persist_error
                try:
                    self._atomic_write(
                        self._pending_dir, os.path.basename(quarantine_path),
                        json.dumps(record).encode("utf-8"),
                    )
                except OSError:
                    quarantine_path = None
        self._pending = None
        self._rejections = 0
        self._transients = 0
        self._clear_persisted_pending()
        report: dict[str, Any] = {
            "ok": False, "dropped": True, "quarantined": True,
            "quarantine_path": quarantine_path, "status": status, "code": code,
            "reason": reason,
        }
        if persist_error is not None:
            report["persist_error"] = persist_error
        return report

    def load_pending(self) -> bool:
        """Recover a result held across a restart: resend-only, never re-run.

        Returns True when a held result was restored. A corrupt or foreign
        file is quarantined aside, never executed: recovery resends bytes the
        PC really produced, nothing else.
        """
        import os

        directory = self._pending_dir_path()
        if directory is None:
            return False
        meta_path = os.path.join(directory, _PENDING_META_NAME)
        if not os.path.exists(meta_path):
            return False
        try:
            with open(meta_path, "r", encoding="utf-8") as handle:
                meta = json.load(handle)
        except OSError:
            return False
        except (ValueError, UnicodeDecodeError):
            stem = "corrupt-" + str(os.getpid())
            try:
                os.replace(meta_path, os.path.join(directory, "quarantine-" + stem + ".json"))
            except OSError:
                pass
            return False
        # The manifest names its own body, so a body is only ever read through
        # the manifest that describes it. The fixed legacy name is still
        # accepted: a result held by the previous executor revision must not be
        # lost across this upgrade.
        name = meta.get("body_name") if isinstance(meta, dict) else None
        if not isinstance(name, str) or not name or os.path.dirname(name):
            name = _PENDING_BODY_NAME
        body_path = os.path.join(directory, name)
        try:
            with open(body_path, "rb") as handle:
                body = handle.read()
        except OSError:
            return False
        self._pending_body = name
        try:
            if not isinstance(meta, dict):
                raise ValueError("pending meta is not an object")
            body_hash = hashlib.sha256(body).hexdigest()
            if meta.get("content_sha256") != body_hash or meta.get("content_bytes") != len(body):
                raise ValueError("pending body does not match its manifest")
            dispatch = OracleMeshDispatch(
                dispatch_id=_require_text(meta.get("dispatch_id"), "dispatch_id"),
                nonce=_require_text(meta.get("nonce"), "nonce"),
                node_ref=_require_text(meta.get("node_ref"), "node_ref"),
                file_path=_require_text(meta.get("file_path"), "file_path"),
                command_id=_require_text(meta.get("command_id"), "command_id"),
                run_id=_require_text(meta.get("run_id"), "run_id"),
                kind=meta.get("kind") or "read",
                command_text=meta.get("command_text"),
                max_bytes=meta.get("max_bytes"),
            )
            if dispatch.kind not in ("read", "command", "desktop"):
                raise ValueError("pending kind is unknown")
            if dispatch.max_bytes is not None and (
                dispatch.kind != "read"
                or isinstance(dispatch.max_bytes, bool)
                or not isinstance(dispatch.max_bytes, int)
                or not 0 < dispatch.max_bytes <= MAX_READ_BYTES_ENVELOPE
            ):
                raise ValueError("pending read limit is unbounded")
            if dispatch.kind in ("command", "desktop") and (
                not isinstance(dispatch.command_text, str) or not dispatch.command_text.strip()
            ):
                raise ValueError("pending command has no command")
            termination = meta.get("termination")
            if termination not in (
                "exited", "cancelled", "timed_out", "no_reply", "no_exit_code",
                "not_executed", "output_too_large", "bad_reply",
                "captured", "acted", "desktop_unavailable",
            ):
                raise ValueError("pending termination is unknown")
            exit_code = meta.get("exit_code")
            if exit_code is not None and (
                isinstance(exit_code, bool) or not isinstance(exit_code, int)
            ):
                raise ValueError("pending exit code is not an integer")
            if dispatch.kind == "read" and len(body) > (
                dispatch.max_bytes or MAX_READ_BYTES
            ):
                raise ValueError("pending read body exceeds the requested amount")
            note = meta.get("note", "")
            if not isinstance(note, str):
                raise ValueError("pending note is not text")
            outcome = OracleMeshExecutionOutcome(
                termination=termination, exit_code=exit_code, body=body,
                note=note,
            )
        except (ValueError, OracleMeshChannelRefused, ContractError):
            stem = "corrupt-" + str(os.getpid())
            # Both halves move together, so a restart cannot re-quarantine the
            # same unreadable pair over and over. A missing half is not an
            # error: only the manifest is a commit marker.
            for source, suffix in ((meta_path, ".json"), (body_path, ".body")):
                try:
                    os.replace(source, os.path.join(directory, "quarantine-" + stem + suffix))
                except OSError:
                    pass
            self._pending = None
            self._pending_body = None
            return False
        self._pending = (dispatch, outcome)
        self._rejections = 0
        self._transients = 0
        return True

    def _transient_wait_seconds(self) -> int:
        wait = _BACKOFF_FIRST_SECONDS * (2 ** min(self._transients, 4))
        return max(1, min(_BACKOFF_MAX_SECONDS, wait))

    def _submit_desktop(
        self, dispatch: OracleMeshDispatch, outcome: OracleMeshExecutionOutcome
    ) -> dict[str, Any]:
        """Submit one desktop observation or input.

        The note travels as the UTF-8 text; a screenshot travels beside it as
        the raw JPEG in one binary frame (4-byte big-endian header length +
        UTF-8 JSON header + bytes) with its own digest. The dispatch pin covers
        the JPEG when one is present, else the note — so a resend is compared
        against the same bytes the server pinned first.
        """
        note = outcome.note if isinstance(outcome.note, str) else ""
        try:
            note_raw = note.encode("utf-8")
        except (UnicodeEncodeError, ValueError):
            note_raw = b""
        if (
            any(ord(ch) < 32 and ch not in "\n\r\t" for ch in note)
            or "\x7f" in note
        ):
            self._pending = (dispatch, outcome)
            self._persist_pending()
            return self._quarantine_pending(reason="desktop_note_invalid")
        body = bytes(outcome.body) if isinstance(outcome.body, (bytes, bytearray)) else b""
        payload = {
            "dispatch_id": dispatch.dispatch_id,
            "nonce": dispatch.nonce,
            "termination": outcome.termination,
            "exit_code": outcome.exit_code,
            "content_utf8": note,
            "content_sha256": hashlib.sha256(body).hexdigest() if body else hashlib.sha256(note_raw).hexdigest(),
            "content_bytes": len(body) if body else len(note_raw),
        }
        if body:
            payload["content_blob_sha256"] = hashlib.sha256(body).hexdigest()
            payload["content_blob_bytes"] = len(body)
            payload["content_blob_media_type"] = "image/jpeg"
            # #4379: the screenshot is the body, not a base64 field. Removing
            # the 4/3 inflation also removes the metadata-only envelope refusal
            # for a JPEG that fits the same byte budget.
            header = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            framed: Optional[dict[str, Any]] | bytes = (
                len(header).to_bytes(4, "big") + header + body
            )
            wire_bytes = len(framed)
        else:
            framed = payload
            wire_bytes = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        # The channel envelope limits the whole frame (header + bytes), never a
        # base64 expansion of it. Persist the image before any refusal.

        self._pending = (dispatch, outcome)
        persist_error = self._persist_pending()
        try:
            status, data = self._post(RESULT_PATH, framed)
        except OracleMeshChannelRefused:
            wait = self._transient_wait_seconds()
            self._transients += 1
            return self._with_persist_warning(
                {"ok": False, "retryable": True, "resend_pending": True,
                 "wait_seconds": wait}, persist_error)
        if status == 200 and data.get("ok") is True:
            self._pending = None
            self._rejections = 0
            self._transients = 0
            self._clear_persisted_pending()
            return data
        return self._submit_refused(status, data, persist_error)

    def _submit_refused(
        self, status: Any, data: dict[str, Any], persist_error: Optional[str]
    ) -> dict[str, Any]:
        """Share one refusal policy between the text and desktop submit legs.

        A transient store/channel failure keeps the exact bytes for a resend;
        an ambiguous 409 is retried boundedly, then quarantined; ownership and
        malformed-body refusals quarantine at once. Nothing is re-executed and
        nothing is dropped silently on any leg.
        """
        error = data.get("error")
        code = error.get("code") if isinstance(error, dict) else None
        if status == 413:
            # The platform's own request-body limit: this path cannot carry the
            # result, so the caller shows exactly that reason. The bytes stay in
            # the pending file for the operator; nothing is resent.
            return self._with_persist_warning(
                {"ok": False, "retryable": False, "resend_pending": False,
                 "reason": "result_too_large_for_this_path",
                 "status": status, "code": code}, persist_error)
        if status == 503 or status == 429 or status >= 500:
            self._rejections = 0
            wait = self._transient_wait_seconds()
            self._transients += 1
            return self._with_persist_warning(
                {"ok": False, "retryable": True, "resend_pending": True,
                 "status": status, "code": code, "wait_seconds": wait}, persist_error)
        if status == 409 and code == "oracle_mesh_result_fingerprint_mismatch":
            return self._quarantine_pending(
                reason="result_fingerprint_mismatch", status=status, code=code)
        if status in (400, 403):
            return self._quarantine_pending(
                reason="result_refused", status=status, code=code)
        self._rejections += 1
        if self._rejections < MAX_RESULT_REJECTIONS:
            wait = self._transient_wait_seconds()
            self._transients += 1
            return self._with_persist_warning(
                {"ok": False, "retryable": True, "resend_pending": True,
                 "status": status, "code": code, "wait_seconds": wait}, persist_error)
        return self._quarantine_pending(
            reason="dispatch_rejected", status=status, code=code)

    def submit(
        self, dispatch: OracleMeshDispatch, outcome: OracleMeshExecutionOutcome
    ) -> dict[str, Any]:
        """Submit one outcome, and keep it until the server decides it.

        The bytes are persisted before the post and resent unchanged on a
        transient refusal — the PC file is never read a second time and a
        held command is never re-executed. ``resend_pending`` reports that
        held outcome so the caller can drive the retry without touching
        either port.
        """
        if dispatch.kind == "desktop":
            return self._submit_desktop(dispatch, outcome)
        try:
            text = outcome.body.decode("utf-8") if outcome.body else ""
        except UnicodeDecodeError:
            # Not submittable on the UTF-8 wire, but still a real outcome:
            # preserve it instead of dropping it on the floor.
            self._pending = (dispatch, outcome)
            self._persist_pending()
            return self._quarantine_pending(reason="result_not_utf8")
        payload = {
            "dispatch_id": dispatch.dispatch_id,
            "nonce": dispatch.nonce,
            "termination": outcome.termination,
            "exit_code": outcome.exit_code,
            "content_utf8": text,
            "content_sha256": hashlib.sha256(outcome.body).hexdigest(),
            "content_bytes": len(outcome.body),
        }
        self._pending = (dispatch, outcome)
        # A persistence failure is reported, never hidden: the bytes stay in
        # memory and are still submitted, but the operator must be able to see
        # that this result is not durable across a restart.
        persist_error = self._persist_pending()
        submit_started = time.monotonic()
        self._trace_command(dispatch, "submit", submit_started)
        try:
            status, data = self._post(RESULT_PATH, payload)
        except OracleMeshChannelRefused:
            # Transport down: same bytes, backed off, never re-executed.
            self._trace_command(
                dispatch, "submit_retry", submit_started, reason="transport",
            )
            wait = self._transient_wait_seconds()
            self._transients += 1
            return self._with_persist_warning(
                {"ok": False, "retryable": True, "resend_pending": True,
                 "wait_seconds": wait}, persist_error)
        if status == 200 and data.get("ok") is True:
            self._trace_command(
                dispatch, "submit_ok", submit_started, status=status,
            )
            self._pending = None
            self._rejections = 0
            self._transients = 0
            self._clear_persisted_pending()
            return data
        self._trace_command(
            dispatch, "submit_refused", submit_started, status=status,
        )
        return self._submit_refused(status, data, persist_error)

    @staticmethod
    def _with_persist_warning(report: dict[str, Any], persist_error: Optional[str]):
        if persist_error is not None:
            report["persist_error"] = persist_error
        return report

    @property
    def resend_pending(self) -> bool:
        """True while an accepted-by-execution result still awaits delivery."""
        return self._pending is not None

    def resend_pending_result(self) -> Optional[dict[str, Any]]:
        """Deliver the already-executed result again, without re-reading."""
        if self._pending is None:
            return None
        dispatch, outcome = self._pending
        return self.submit(dispatch, outcome)

    # ---- which PC is busy, in the connector's own words -----------------
    def active_dispatch_id(self, node_ref: str) -> Optional[str]:
        """The dispatch this connector is running on that PC right now, or None."""
        with self._active_lock:
            return self._active_by_node.get(node_ref)

    def active_dispatch_ids(self) -> tuple[str, ...]:
        """Every dispatch this connector is running, on any PC.

        The line sweep protects exactly these. Nothing here is inferred from a
        transcript or a log line, so a PC cannot talk its way out of being skipped.
        """
        with self._active_lock:
            return tuple(self._active_by_node.values())

    def line_observations(self) -> dict[str, int]:
        """How often a held console line was found, and how often it was freed.

        Totals for this process, not for one round: a monitor watching for a PC that
        needs clearing more than once an hour reads a counter, and a counter has to
        say so in its own name.
        """
        return {
            "line_blocked_total": self._line_blocked,
            "line_cleared_total": self._line_cleared,
        }

    def _mark_active(self, dispatch: OracleMeshDispatch) -> None:
        node_ref = str(getattr(dispatch, "node_ref", "") or "")
        dispatch_id = str(getattr(dispatch, "dispatch_id", "") or "")
        if not node_ref or not dispatch_id:
            return
        with self._active_lock:
            self._active_by_node[node_ref] = dispatch_id

    def _clear_active(self, dispatch: OracleMeshDispatch) -> None:
        node_ref = str(getattr(dispatch, "node_ref", "") or "")
        with self._active_lock:
            if self._active_by_node.get(node_ref) == str(
                getattr(dispatch, "dispatch_id", "") or ""
            ):
                self._active_by_node.pop(node_ref, None)

    def run_once(self) -> Optional[dict[str, Any]]:
        """Retry a held result if any; otherwise poll, execute and submit."""
        if self._pending is not None:
            self.last_round = ROUND_SKIPPED
            return self.resend_pending_result()
        # #5462: a held result is still resent while this host is not the
        # active one — the bytes the PC really produced must reach the
        # server exactly once. Only a NEW claim is gated, because claiming
        # is what could execute the same work twice.
        if self._claim_gate is not None and not self._claim_gate():
            self.last_round = ROUND_SKIPPED
            return None
        dispatch = self.poll_once()
        if dispatch is None:
            self.last_round = ROUND_IDLE
            return None
        # Claimed: the lane had something for this host, which is the one answer that
        # ends an idle stretch. Set before the work, not after the submission, so a
        # round that dies mid-command still says the queue was not empty.
        self.last_round = ROUND_WORKED
        renewer = self.start_lease_renewal(dispatch)
        self._mark_active(dispatch)
        try:
            outcome = self.execute(dispatch)
        finally:
            # The PC owns its console again the moment the console has answered,
            # not when the result is finally accepted: a held result is bytes this
            # host already has, and the line sweep must not be told a finished PC
            # is busy.
            self._clear_active(dispatch)
            if renewer is not None:
                renewer.set()
        return self._with_line_observations(self.submit(dispatch, outcome))

    def _with_line_observations(self, report: Any) -> Any:
        """Put the line-blockage counts on the round's own report.

        Only when there is something to say: an idle queue and a healthy PC keep the
        report exactly as it was, so a monitor reads a number as an event and not as
        noise on every line.
        """
        if not isinstance(report, dict):
            return report
        observations = self.line_observations()
        if (observations["line_blocked_total"]
                or observations["line_cleared_total"]):
            report.update(observations)
        return report

    def start_lease_renewal(self, dispatch: OracleMeshDispatch) -> Optional[threading.Event]:
        """#5997 — hold this claim for as long as the command actually runs.

        A separate thread posts the same dispatch id and the same nonce every
        ``RENEW_INTERVAL_SECONDS``, and the server pushes ``claimed_until`` forward
        under that nonce — the very nonce the later submission carries, so the claim
        and the result can never drift apart. A renewal the server refuses means the
        claim is already gone (the lane re-delivered the work); the loop stops rather
        than reviving it. If this process dies the thread dies with it, the lease runs
        out, and the existing expiry hands the work out again.
        """

        stop = threading.Event()

        def loop() -> None:
            while not stop.wait(RENEW_INTERVAL_SECONDS):
                try:
                    status, _data = self._post(
                        LEASE_RENEW_PATH,
                        {"dispatch_id": dispatch.dispatch_id, "nonce": dispatch.nonce},
                    )
                except OracleMeshChannelRefused:
                    continue
                except Exception:
                    continue
                if status == 409:
                    return

        thread = threading.Thread(
            target=loop, name="oracle-mesh-lease-renew", daemon=True,
        )
        thread.start()
        return stop

    # ---- watchdog ------------------------------------------------------
    def channel_stalled(self, now: float | None = None) -> bool:
        """True when no channel round has finished for CHANNEL_STALL_SECONDS."""

        moment = time.monotonic() if now is None else now
        return (moment - self._last_round_at) > CHANNEL_STALL_SECONDS

    def watchdog_tick(self) -> bool:
        """One watchdog decision. True means this process must stop and restart.

        The socket deadline bounds a single request; this bounds the loop. A round
        that answers badly already logs a refusal, so the only thing left to catch is
        a loop that stopped asking at all - and the one thing that fixes a socket this
        process cannot see inside of is a new process.
        """

        if not self.channel_stalled():
            return False
        print(
            "oracle-mesh-executor watchdog: no channel round for %s s; "
            "exiting for a supervised restart" % CHANNEL_STALL_SECONDS,
            file=sys.stderr, flush=True,
        )
        return True

    def start_channel_watchdog(self) -> threading.Thread:
        """Watch the loop, not the command: a running command has no ceiling by design."""

        def loop() -> None:
            import os

            while not self.watchdog_tick():
                time.sleep(CHANNEL_WATCHDOG_INTERVAL_SECONDS)
            os._exit(EXIT_STALLED_CHANNEL)

        thread = threading.Thread(
            target=loop, name="oracle-mesh-channel-watchdog", daemon=True,
        )
        thread.start()
        return thread


__all__ = [
    "CHANNEL_HEADER",
    "CHANNEL_SOCKET_TIMEOUT_SECONDS",
    "CHANNEL_STALL_SECONDS",
    "IDLE_POLL_BASE_SECONDS",
    "IDLE_POLL_MAX_SECONDS",
    "MAX_COMMAND_BYTES",
    "MAX_READ_BYTES",
    "PC_FILE_ERROR_PREFIX",
    "PC_FILE_READ_FAILED_MARKER",
    "PC_FILE_TOO_LARGE_MARKER",
    "POLL_PATH",
    "PRODUCT_USER_AGENT",
    "RESULT_PATH",
    "OracleMeshChannelRefused",
    "OracleMeshDispatch",
    "OracleMeshExecutionOutcome",
    "OracleMeshExecutor",
    "ROUND_IDLE",
    "ROUND_SKIPPED",
    "ROUND_WORKED",
    "deployment_secret_password_provider",
    "make_oracle_mesh_executor",
]

def make_oracle_mesh_executor(
    *,
    chat_origin: str,
    channel_secret: str,
    queue_origin: Optional[str] = None,
    meshctrl_js: str,
    login_user: str,
    password_provider: Callable[[], str],
    mesh_url: str = "wss://127.0.0.1:4443",
    work_dir: str | None = None,
    timeout_seconds: int | None = None,
    channel_timeout_seconds: int = CHANNEL_SOCKET_TIMEOUT_SECONDS,
    claim_gate: Optional[Callable[[], bool]] = None,
    presence_provider: Optional[Callable[[], Any]] = None,
    pairing_provider: Optional[Callable[[], Any]] = None,
    presence_round_begin: Optional[Callable[[], None]] = None,
) -> OracleMeshExecutor:
    """Build the executor with the REAL official meshctrl read port.

    This is the operational composition: ``meshctrl_js`` is the official
    ``meshctrl.js`` shipped with the MeshCentral server, ``password_provider``
    yields the operator credential at call time (on this host it is the
    mode-0600 deployment secret file), and every read runs that client. No
    stand-in port is constructible from here.
    """
    from .local_agent_meshcentral_command_port import MeshCentralCliCommandPort
    from .local_agent_meshcentral_desktop_port import MeshCentralDesktopPort
    from .local_agent_meshcentral_private_reader import MeshCentralCliFileReadPort

    def _popen(argv, **kwargs):
        import subprocess

        return subprocess.Popen(argv, **kwargs)

    def _run(argv, **kwargs):
        # The merged private read port hands the operator credential to the
        # child on STDIN ("<password>\n"); the OS argv carries only the public
        # marker. Dropping that input here would leave the official client
        # waiting on a prompt it can never answer, so it is passed through
        # verbatim as UTF-8 text.
        import subprocess

        supplied = kwargs.get("input")
        call: dict = {
            "capture_output": True,
            "text": True,
            "encoding": "utf-8",
            "timeout": kwargs.get("timeout", 120),
        }
        if supplied is not None:
            call["input"] = supplied
        return subprocess.run(argv, **call)

    read_port = MeshCentralCliFileReadPort(
        command_runner=_run,
        meshctrl_js=meshctrl_js,
        login_user=login_user,
        password_provider=password_provider,
        url=mesh_url,
        work_dir=work_dir,
        # #5015: observe the staged download while the official client runs.
        # This is detection-then-abort, not a transport cap; the read still
        # refuses an oversize file whole.
        popen_factory=_popen,
    )
    # The terminal lane reuses the SAME official client, operator credential and
    # private tunnel; nothing new is opened for commands.
    command_port = MeshCentralCliCommandPort(
        command_runner=_run,
        meshctrl_js=meshctrl_js,
        login_user=login_user,
        password_provider=password_provider,
        url=mesh_url,
        work_dir=work_dir,
        # #4139: the command lane reads the child incrementally so a runaway
        # command can never be buffered whole before it is size-checked.
        popen_factory=_popen,
    )
    # The desktop lane reuses the SAME operator credential and private tunnel
    # over the official relay protocol; only the wire changes (MSC frames),
    # never the trust basis.
    desktop_port = MeshCentralDesktopPort(
        login_user=login_user,
        password_provider=password_provider,
        url=mesh_url,
    )
    return OracleMeshExecutor(
        chat_origin=chat_origin,
        channel_secret=channel_secret,
        queue_origin=queue_origin,
        read_port=read_port,
        command_port=command_port,
        desktop_port=desktop_port,
        timeout_seconds=timeout_seconds,
        channel_timeout_seconds=channel_timeout_seconds,
        pending_dir=work_dir,
        claim_gate=claim_gate,
        presence_provider=presence_provider,
        pairing_provider=pairing_provider,
        presence_round_begin=presence_round_begin,
    )


def deployment_secret_password_provider(path: str) -> Callable[[], str]:
    """Read the mode-restricted deployment secret file at call time only."""
    import os

    if not isinstance(path, str) or not path.strip():
        raise ContractError("the deployment secret path is required")
    if not os.path.isfile(path):
        raise ContractError("the deployment secret file is missing")

    def provider() -> str:
        with open(path, "r", encoding="utf-8") as handle:
            secret = handle.read().strip()
        if not secret:
            raise OracleMeshChannelRefused("the deployment secret file is empty")
        return secret

    return provider


def _read_secret_file(path: str, name: str) -> str:
    import os

    if not isinstance(path, str) or not path.strip() or not os.path.isfile(path):
        raise ContractError(f"the {name} file is missing")
    with open(path, "r", encoding="utf-8") as handle:
        value = handle.read().strip()
    if not value:
        raise ContractError(f"the {name} file is empty")
    return value


class _PresenceBeat:
    """One device table per poll round, read by both halves of the beat.

    A quiet round used to enumerate the local server five times for two named devices:
    `is_connected` and `name_of` per device, and `pairing_candidates` once on top, each
    of which starts its own ``meshctrl.js listdevices`` on this host. One round now
    reads one table and answers both questions from it.

    The share lasts no longer than the service loop's own shortest gap, and the round
    boundary is stated out loud as well (`begin_round`): a poll that runs with no gap
    at all - a busy lane, where the loop does not sleep between rounds - must still not
    carry last round's answer about somebody's PC into this one.

    A presence object that cannot hand over one table is answered ``None``, and the
    caller falls back to the per-device questions it always had. The beat is evidence;
    a narrower probe is not worth a wrong statement about a PC.
    """

    def __init__(self, presence: Any, fresh_for_seconds: float) -> None:
        self._presence = presence
        self._fresh_for = float(fresh_for_seconds)
        self._rows: Optional[list[dict[str, Any]]] = None
        self._taken_at = 0.0

    def begin_round(self) -> None:
        self._rows = None

    def rows(self) -> Optional[list[dict[str, Any]]]:
        listing = getattr(self._presence, "listing", None)
        if not callable(listing):
            return None
        now = time.monotonic()
        if self._rows is None or now - self._taken_at >= self._fresh_for:
            self._rows = [_beat_row(row) for row in listing() or ()]
            self._taken_at = now
        return self._rows


def _beat_row(row: Any) -> dict[str, Any]:
    """One server row in the shape both halves of the beat read.

    `conn` is the field the official client prints for reachability, and the pairing
    tag is recognised here once rather than in every caller, so a name that carries no
    tag is never treated as pairing evidence twice over.
    """
    if type(row) is not dict:
        return {"device_id": "", "connected": False, "agent_name": "", "tagged": False}
    device_id = row.get("id")
    name = row.get("name")
    name = name.strip()[:256] if isinstance(name, str) else ""
    try:
        connected = int(row.get("conn", 0) or 0) == 1
    except (TypeError, ValueError):
        connected = False
    return {
        "device_id": device_id if isinstance(device_id, str) else "",
        "connected": connected,
        "agent_name": name,
        "tagged": bool(name) and _pairing_tag_of(name) is not None,
    }


def main(environ: Optional[dict[str, str]] = None) -> int:
    """Startup entrypoint: one poll/execute/submit loop on the Oracle host.

    Configuration is environment-only and bounded:
      ORACLE_MESH_CHAT_ORIGIN       https origin of the Chat worker (bare)
      ORACLE_MESH_QUEUE_ORIGIN      optional; the origin of the 컴2 PC queue that
                                    answers the claim lane on this host
                                    (http://127.0.0.1:8797). Unset, every leg —
                                    including the claim — goes to the Worker, which
                                    is the state before the queue and the rollback.
                                    The result submission always goes to the Worker.
      ORACLE_MESH_CHANNEL_SECRET_FILE  mode-0600 file holding the channel secret
      ORACLE_MESH_MESHCTRL_JS       path to the official meshctrl.js
      ORACLE_MESH_LOGIN_USER        MeshCentral operator account
      ORACLE_MESH_PASSWORD_FILE     mode-0600 file holding the operator password
      ORACLE_MESH_URL               optional, default wss://127.0.0.1:4443
      ORACLE_MESH_WORK_DIR          optional scratch directory
      ORACLE_MESH_POLL_SECONDS      optional interval after a refused channel, default 5
      ORACLE_MESH_IDLE_POLL_MAX_SECONDS
                                    optional ceiling on the idle wait, default 60;
                                    one reproduces the pre-backoff cadence verbatim
      MESH_FAILOVER_DEVICE_ID       optional comma-separated devices (max 8);
                                    poll carries one beat per device
    Secrets are read from files at call time; they never appear on argv.
    """
    import os
    import sys
    import time

    env = dict(os.environ if environ is None else environ)

    def need(key: str) -> str:
        value = env.get(key, "").strip()
        if not value:
            raise ContractError(f"{key} is required")
        return value

    try:
        mesh_url = env.get("ORACLE_MESH_URL", "").strip() or "wss://127.0.0.1:4443"
        password_provider = deployment_secret_password_provider(
            need("ORACLE_MESH_PASSWORD_FILE")
        )
        # #5553: observe presence only for the device this deployment names.
        # An unnamed target omits the field instead of guessing a device.
        presence_provider = None
        pairing_provider = None
        beat = None
        raw_devices = env.get("MESH_FAILOVER_DEVICE_ID", "").strip()
        presence_device_ids = list(dict.fromkeys(part.strip() for part in raw_devices.split(","))) if raw_devices else []
        if (len(presence_device_ids) > MAX_PRESENCE_ENTRIES
                or any(not device for device in presence_device_ids)):
            raise ContractError("MESH_FAILOVER_DEVICE_ID requires 1 to 8 non-empty device ids")
        if presence_device_ids:
            from .local_agent_mesh_failover import MeshCentralDevicePresence

            presence = MeshCentralDevicePresence(
                meshctrl_js=need("ORACLE_MESH_MESHCTRL_JS"),
                mesh_url=mesh_url,
                login_user=need("ORACLE_MESH_LOGIN_USER"),
                password_provider=password_provider,
            )
            beat = _PresenceBeat(presence, IDLE_POLL_BASE_SECONDS)

            def pairing_provider():
                # #5573: one enumeration, tag-carrying nodes only. An untagged
                # name is never sent, and no bound is applied to the candidates -
                # the beat budget that limits what travels, decided below.
                shared = beat.rows()
                if shared is not None:
                    return [
                        {"device_id": row["device_id"], "connected": True,
                         "agent_name": row["agent_name"]}
                        for row in shared
                        if row.get("tagged") and row.get("connected")
                    ]
                listing = getattr(presence, "pairing_candidates", None)
                return listing() if callable(listing) else []

            def presence_provider():
                shared = beat.rows()
                if shared is not None:
                    # The one table answers every named device: whether it is
                    # connected and what it is called. This is the shape that used to
                    # cost two enumerations per device.
                    by_id = {row["device_id"]: row for row in shared}
                    entries = []
                    for presence_device_id in presence_device_ids:
                        row = by_id.get(presence_device_id)
                        entry = {
                            "device_id": presence_device_id,
                            "connected": bool(row and row.get("connected")),
                        }
                        if row and isinstance(row.get("agent_name"), str) and row["agent_name"]:
                            entry["agent_name"] = row["agent_name"]
                        entries.append(entry)
                    return entries
                entries = []
                for presence_device_id in presence_device_ids:
                    entry = {
                        "device_id": presence_device_id,
                        "connected": presence.is_connected(presence_device_id),
                    }
                    # #5573: the agent name rides along so the server can finish
                    # a pairing claim from the tag it stamped. Nothing is kept
                    # here, and a name this deployment cannot read changes
                    # nothing about the presence beat itself.
                    lookup = getattr(presence, "name_of", None)
                    if callable(lookup):
                        try:
                            observed_name = lookup(presence_device_id)
                        except Exception:
                            observed_name = None
                        if isinstance(observed_name, str) and observed_name.strip():
                            entry["agent_name"] = observed_name.strip()[:256]
                    entries.append(entry)
                return entries

        executor = make_oracle_mesh_executor(
            chat_origin=need("ORACLE_MESH_CHAT_ORIGIN"),
            channel_secret=_read_secret_file(
                need("ORACLE_MESH_CHANNEL_SECRET_FILE"), "channel secret"
            ),
            queue_origin=env.get("ORACLE_MESH_QUEUE_ORIGIN", "").strip() or None,
            meshctrl_js=need("ORACLE_MESH_MESHCTRL_JS"),
            login_user=need("ORACLE_MESH_LOGIN_USER"),
            password_provider=password_provider,
            mesh_url=mesh_url,
            work_dir=env.get("ORACLE_MESH_WORK_DIR", "").strip() or None,
            presence_provider=presence_provider,
            pairing_provider=pairing_provider,
            presence_round_begin=beat.begin_round if beat is not None else None,
        )
        idle = max(1, min(int(env.get("ORACLE_MESH_POLL_SECONDS", "5") or 5), 300))
        # The idle ceiling is readable for the operator who wants to weigh the old
        # cadence against the new one on a live host: one is exactly the behaviour every
        # executor had before this schedule existed.
        idle_max = max(
            IDLE_POLL_BASE_SECONDS,
            min(int(env.get("ORACLE_MESH_IDLE_POLL_MAX_SECONDS",
                            str(IDLE_POLL_MAX_SECONDS)) or IDLE_POLL_MAX_SECONDS), 300),
        )
    except (ContractError, ValueError) as exc:
        print(f"oracle-mesh-executor refused to start: {exc}", file=sys.stderr)
        return 2

    # A restart never re-executes: a persisted held result is resent as-is.
    try:
        if executor.load_pending():
            print("oracle-mesh-executor restored a held result; resending only",
                  file=sys.stderr)
    except OSError as exc:
        print(f"oracle-mesh-executor pending restore refused: {exc}", file=sys.stderr)

    # The loop, never the command: a channel that stopped completing rounds cannot be
    # revived from inside the round that is stuck.
    executor.start_channel_watchdog()

    #: The wait before the next ask. It grows only across rounds the lane itself
    #: answered empty, and resets the moment the queue produces work.
    gap = IDLE_POLL_BASE_SECONDS
    while True:
        try:
            result = executor.run_once()
        except OracleMeshChannelRefused as exc:
            # Bounded: the message never carries dispatch content or secrets. A
            # channel that will not complete rounds is not a quiet queue, so the wait
            # returns to the base and the interval the operator named.
            print(f"oracle-mesh-executor channel refusal: {exc}", file=sys.stderr)
            gap = IDLE_POLL_BASE_SECONDS
            time.sleep(idle)
            continue
        if result is None:
            # The lane held this request five seconds and answered "nothing waiting",
            # or this host asked for nothing at all. Only the first of those says
            # something about the queue, and only for it does the next ask wait
            # longer - a skipped round goes back to the base so a failover landing on
            # this host starts claiming on the next second.
            time.sleep(gap)
            gap = (IDLE_POLL_BASE_SECONDS if executor.last_round != ROUND_IDLE
                   else min(gap * 2, idle_max))
            continue
        gap = IDLE_POLL_BASE_SECONDS
        observations = executor.line_observations()
        print(
            f"oracle-mesh-executor result ok={result.get('ok')} "
            f"retryable={result.get('retryable', False)} "
            f"quarantined={result.get('quarantined', False)} "
            f"line_blocked_total={observations['line_blocked_total']} "
            f"line_cleared_total={observations['line_cleared_total']}",
            flush=True,
        )
        if result.get("ok") is True:
            continue
        wait = result.get("wait_seconds") if isinstance(result, dict) else None
        if not isinstance(wait, int) or isinstance(wait, bool):
            wait = idle
        time.sleep(max(1, min(wait, 300)))


if __name__ == "__main__":
    raise SystemExit(main())