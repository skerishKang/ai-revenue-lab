"""#4139 — Oracle-side executor for the server-server MeshCentral read.

Runs on the Oracle management host. One loop: claim the oldest dispatch from
the Chat server over the deployment channel secret, read the named file with
the OFFICIAL ``meshctrl.js`` client, and submit the outcome back. The
executor never mints approval or broker evidence, never invents a binding,
and never re-reads the PC file on a retry: a transient store failure is
answered by resending the bytes it already holds.
"""
from __future__ import annotations
USER_SESSION_UNAVAILABLE = "user_session_unavailable"
USER_HELPER_PIPE_PREFIX = "padiem-user-helper-"
#: #7182b: ``Get-ScheduledTask -TaskPath`` matches the folder's own path exactly,
#: trailing separator included. The installer registers the task under
#: ``\\Padiem\\`` (``claw_connect.user_helper_registration.TASK_FOLDER``), so a
#: path without the separator selects nothing and the client stopped at its very
#: first step with "helper task is not registered" - before any pipe connect.
#: Measured on 컴1 2026-11-08: the deployed client returned that message in 1s
#: while the task was Running, and the same script with ``\\Padiem\\`` returned
#: the command's output in 1.6s.
USER_HELPER_TASK_PATH = "\\Padiem\\"
USER_HELPER_TASK_NAME = "PadiemUserSessionHelper"

from .pc_correlation import run_hash as _pc_run_hash

import base64
import hashlib
import hmac
import json
import os
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
from .local_agent_meshcentral_private_reader import (
    MeshCentralReadRequestRefused,
    MeshCentralReadTooLarge,
)
from .reparse_guard import walk_hits_reparse_point

_DEVICE_ID_RAW = re.compile(r"^[A-Za-z0-9_.$:@+\-]{1,256}\Z")


def user_helper_pipe_suffix(device_id: str) -> str:
    if not isinstance(device_id, str) or _DEVICE_ID_RAW.fullmatch(device_id) is None:
        raise ValueError("device_id is not a device identifier")
    return "dev_" + hashlib.sha256(device_id.encode("utf-8")).hexdigest()[:32]


def user_helper_pipe_name(device_id: str) -> str:
    return USER_HELPER_PIPE_PREFIX + user_helper_pipe_suffix(device_id)

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
COM2_IDLE_POLL_MAX_SECONDS = 10
#: An idle loop says so at most this often. The counter line is printed only on a
#: round that carried work, so without this a quiet lane looks like a lost counter.
IDLE_HEARTBEAT_SECONDS = 300
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
#: #261105: a result lane aimed at the Chat host's own loopback crosses
#: ``com2_edge_middleware``, which answers a request that does not carry the four
#: ``x-padiem-edge-*`` headers with a bare 403 — before the route ever sees the
#: channel secret. The Engine already signs that way for its own chat binding
#: (``local_runtime.LocalChatServiceBinding._edge_headers``), so the executor reuses
#: the same composition — the canonical string joins ``v1``, the method, the path,
#: the unix seconds, one fresh 32-byte-hex request id and the TLS label with
#: newlines, and the server's own ``EdgeProofVerifier`` is what decides. Over the
#: public https origin nothing is added — the edge already sits upstream there,
#: which is today's behaviour.
EDGE_SECRET_FILE_ENV = "ORACLE_MESH_EDGE_SECRET_FILE"
EDGE_AT_HEADER = "x-padiem-edge-at"
EDGE_ID_HEADER = "x-padiem-edge-id"
EDGE_TLS_HEADER = "x-padiem-edge-tls"
EDGE_PROOF_HEADER = "x-padiem-edge-proof"
EDGE_HEADERS = (EDGE_AT_HEADER, EDGE_ID_HEADER, EDGE_TLS_HEADER, EDGE_PROOF_HEADER)
#: Exactly the label the verifier accepts for a loopback hop that carries no TLS.
EDGE_TLS_VERSION = "TLSv1.3"
MIN_EDGE_SECRET_CHARS = 32


def _is_loopback_channel_origin(origin: Any) -> bool:
    if not isinstance(origin, str) or not origin.startswith("http://"):
        return False
    try:
        parsed = urllib.parse.urlsplit(origin)
        host = parsed.hostname
        # urlsplit.hostname alone accepts [::1].outside.example as ::1.
        # Validate the complete authority and the parsed port, not a prefix.
        parsed.port
    except ValueError:
        return False
    return bool(
        isinstance(host, str) and host.lower() in LOOPBACK_CHANNEL_HOSTS
        and re.fullmatch(r"(?:localhost|127\.0\.0\.1|\[::1\])(?::[0-9]+)?", parsed.netloc, re.I)
        and not parsed.path and not parsed.query and not parsed.fragment
    )


def edge_proof_headers(secret: str, *, method: str, path: str) -> dict[str, str]:
    """The four headers Chat's edge verifier accepts for one request on this host.

    Byte-compatible with the Engine's chat binding, and deliberately so: the verifier
    stores the request ids it has seen, so a reused id is a replay and a retry must
    sign a fresh one. The path is signed without a query string, which is what the
    verifier rebuilds from the ASGI scope.
    """

    at = str(int(time.time()))
    request_id = os.urandom(32).hex()
    signed = "\n".join(("v1", method.upper(), path, at, request_id, EDGE_TLS_VERSION)).encode(
        "utf-8"
    )
    proof = "v1=" + hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return {
        EDGE_AT_HEADER: at,
        EDGE_ID_HEADER: request_id,
        EDGE_TLS_HEADER: EDGE_TLS_VERSION,
        EDGE_PROOF_HEADER: proof,
    }


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
#: #6606 report follow-up: the read envelope joins the same decision. The
#: server computes each dispatch's read bound per row and pages a bigger file
#: through the #6541 first-range + read_file_chunk flow, so a large read
#: arrives as per-call bounded requests. This executor keeps only the shape
#: checks — a read bound is a positive integer, and an oversize result is
#: still refused whole, never truncated — and leaves the one-answer size to
#: the platform that carries the bytes.
MAX_READ_BYTES_ENVELOPE: int | None = None
MAX_READ_BYTES = 6_000_000
#: Existing PC-file error markers the Engine already maps. A read failure is a
#: truthful body, not an empty success: the executor reports the marker so the
#: verified result lane can deliver the same outcome the model lane expects.
PC_FILE_ERROR_PREFIX = "PADIEM_PC_FILE_ERROR:"
PC_FILE_TOO_LARGE_MARKER = PC_FILE_ERROR_PREFIX + "too_large"
#: #5994 D3 후속 — a junction/symlink below the granted root refuses the
#: whole read before the download starts (the PC-side ReparsePoint walk).
PC_FILE_LINK_REFUSED_MARKER = PC_FILE_ERROR_PREFIX + "link_refused"
PC_FILE_READ_FAILED_MARKER = PC_FILE_ERROR_PREFIX + "read_failed"
#: A request this host refused before the client ran. Same read lane, but a
#: different event: the PC was never asked, so the wording that surfaces it
#: must not read as a missing file or a registered-root violation.
PC_FILE_READ_REFUSED_MARKER = PC_FILE_ERROR_PREFIX + "read_failed_refused_local"
#: How much of a refusal's own message reaches the trace. The reason is what a
#: silent read_failed cost on 2026-10-30; the bound keeps one line one line.
_ERROR_TEXT_CHARS = 160
#: The base deadline for one PC step when the deployment names none. This is the
#: value every executor had before 2026-10-17, and the read/desktop lanes still
#: multiply it by four, so no new ceiling is introduced by naming it.
DEFAULT_STEP_TIMEOUT_SECONDS = 30
#: 2026-11-05: one small pc_files read used to cost TWO MeshCentral logins - a
#: command-channel walk for the ReparsePoint guard, then a separate
#: ``meshctrl.js download``. This flag folds both into ONE ``runcommand`` reply:
#: the walk runs first, and only a clear walk reads the bytes, so the order the
#: guard established (guard before bytes) is unchanged. On by default; ``0``
#: keeps the previous two-step path only.
READ_SINGLE_ROUNDTRIP_ENV = "ORACLE_MESH_READ_SINGLE_ROUNDTRIP"
#: The largest file the single-roundtrip path may carry. The command lane has no
#: PADIEM output ceiling of its own (#5895 left ``MAX_TRANSCRIPT_BYTES`` None),
#: so the bound is read from the one reply bound that still exists:
#: ``HANDOFF_CAPTURE_LIMIT`` (262,144 bytes) in
#: ``local_agent_meshcentral_command_port``. The reply is base64 twice over -
#: once for the bytes on the PC's console (4/3) and once for the console text in
#: the transport envelope (4/3), 16/9 in all - so 262,144 * 9 / 16 = 147,456,
#: minus one header line and its wrapping: 131,072 (128 KiB). A larger file is
#: not refused; it falls back to the download path, which the server's own
#: ``max_bytes`` already bounds.
SINGLE_ROUNDTRIP_MAX_BYTES = 131_072
#: The one line the single-roundtrip script writes before its payload. The word
#: after it is either ``link_refused`` (the PC walk found a link, no bytes) or
#: ``<length>:<sha256>`` for the base64 lines that follow.
READ_META_PREFIX = "PADIEM_READ="
#: Verdicts the script writes INSTEAD of bytes. Only ``link_refused`` is a
#: decision; every other word is a mechanical miss and falls back to the two-step
#: path, which refuses exactly as it always has when its own guard cannot answer.
READ_VERDICT_LINK_REFUSED = "link_refused"
READ_VERDICT_TOO_LARGE = "too_large"
READ_VERDICT_GUARD_ERROR = "guard_error"
READ_VERDICT_READ_ERROR = "read_error"
_READ_META_RE = re.compile(r"(\d+):([0-9a-f]{64})")
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
    """Bounded refusal of one executor/server exchange. Never carries content.

    `leg` says which server was asked - `chat` or `queue` - and it is an attribute, not
    part of the message: the message text is what the operator and the monitor already
    read, and #5881's cutover proved that one text for two servers makes an edge block
    indistinguishable from a Worker failure. Nothing here carries a URL or a secret.
    """

    def __init__(self, message: str, *, leg: str | None = None) -> None:
        super().__init__(message)
        self.leg = leg


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
    #: #6460 step 2: the typed value, delivered once by the poll that
    #: claimed this dispatch. Kept off every persisted record here.
    desktop_text: str | None = None
    #: #5994 D3 후속: the granted root the poll response names for this read,
    #: used only by the pre-download reparse walk. A missing value keeps the
    #: read exactly as before — the guard runs only when the server named it.
    granted_root: str | None = None
    # Only the authenticated queue projection may set these fields.
    background: bool = False
    owner_ref: str | None = None
    # #7076c: route command through the PC logged-in user helper (pipe).
    user_mode: bool = False
    device_id: str | None = None


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


def _safe_error_text(exc: BaseException) -> str:
    """One bounded line naming a failure, never the bytes it was about.

    A decode error's message quotes the offending bytes, which is file content,
    so only the class travels for it. Every other reason is collapsed to a
    single line and cut at ``_ERROR_TEXT_CHARS``.
    """
    name = exc.__class__.__name__
    if isinstance(exc, UnicodeDecodeError):
        return name
    text = " ".join(str(exc).split())[:_ERROR_TEXT_CHARS]
    return f"{name}:{text}" if text else name


def _ps_literal_for_root(value: str) -> str:
    """One single-quoted PowerShell literal for a path."""
    return "'" + value.replace("'", "''") + "'"


def _pc_guard_root(value: str) -> str:
    """The granted root as the PC walk needs it: one trailing separator.

    ``"C:"`` is not the C: drive root on Windows - it is that drive's current
    folder (SYSTEM's is usually ``C:\\Windows\\System32``), so a drive-only root is
    completed to ``"C:\\"`` before one segment is joined. Every other root keeps
    its own text and gains the single separator the join needs.
    """
    text = value.strip().replace("/", "\\")
    if len(text) == 2 and text[1] == ":" and text[0].isalpha():
        return text + "\\"
    return text if text.endswith("\\") else text + "\\"


def _step_timeout_seconds(env: dict[str, str]) -> int:
    """The deployment's own PC-step deadline, in seconds.

    Absent, this is the value every executor had before 2026-10-17. The read and
    desktop lanes multiply it by four themselves, so the variable is the base
    deadline, not the wire deadline. No second ceiling is invented here.
    """
    raw = env.get("ORACLE_MESH_READ_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return DEFAULT_STEP_TIMEOUT_SECONDS
    try:
        value = int(raw)
    except ValueError:
        raise ContractError(
            "ORACLE_MESH_READ_TIMEOUT_SECONDS must be a positive integer"
        ) from None
    if isinstance(value, bool) or value < 1:
        raise ContractError(
            "ORACLE_MESH_READ_TIMEOUT_SECONDS must be a positive integer"
        )
    return value


def _single_roundtrip_enabled(env: dict[str, str]) -> bool:
    """The deployment's switch for the one-reply read; absent means on."""
    raw = env.get(READ_SINGLE_ROUNDTRIP_ENV, "").strip().lower()
    if not raw:
        return True
    return raw not in ("0", "false", "off", "no")


def _single_roundtrip_script(
    *, granted_root: str, file_path: str, max_bytes: int,
) -> str:
    """One PowerShell run: the SAME walk first, then the bytes.

    The walk is byte-for-byte the one ``_pc_reparse_check`` sends, and it runs
    before a single byte is read: a hit writes the verdict and nothing else, so
    the order the #5994 guard established is preserved. The size is measured
    before ``ReadAllBytes`` so a file past this lane's bound never becomes an
    in-memory read on the customer PC. Any mechanical failure writes a word the
    executor treats as "use the two-step path", never as content.
    """
    root = _pc_guard_root(granted_root)
    target = file_path.strip().replace("/", "\\")
    return (
        "$ErrorActionPreference='Stop';"
        "$root = " + _ps_literal_for_root(root) + ";"
        "$target = " + _ps_literal_for_root(target) + ";"
        "$hit = $false; $failed = $false;"
        "try {"
        " if (-not $target.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) { $hit = $true };"
        " if (-not $hit) {"
        "  $rest = $target.Substring($root.Length); $walk = $root;"
        "  foreach ($seg in $rest.Split([char]'\\')) {"
        "   if (-not $seg) { continue };"
        "   $walk = Join-Path $walk $seg;"
        "   if (-not (Test-Path -LiteralPath $walk)) { break };"
        "   $item = Get-Item -LiteralPath $walk -Force -ErrorAction SilentlyContinue;"
        "   if ($item -and (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0))"
        "   { $hit = $true; break }"
        "  }"
        " }"
        "} catch { $failed = $true };"
        "if ($hit) { Write-Output 'PADIEM_READ=" + READ_VERDICT_LINK_REFUSED + "' }"
        " elseif ($failed) { Write-Output 'PADIEM_READ=" + READ_VERDICT_GUARD_ERROR + "' }"
        " else {"
        "  $info = Get-Item -LiteralPath $target -Force;"
        "  if ($info.Length -gt " + str(int(max_bytes)) + ") {"
        "   Write-Output 'PADIEM_READ=" + READ_VERDICT_TOO_LARGE + "'"
        "  } else {"
        "   try {"
        "    $bytes = [IO.File]::ReadAllBytes($target);"
        "    $sha = [Security.Cryptography.SHA256]::Create();"
        "    $hash = ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-','').ToLowerInvariant();"
        "    Write-Output ('PADIEM_READ=' + $bytes.Length + ':' + $hash);"
        "    Write-Output ([Convert]::ToBase64String($bytes));"
        "   } catch { Write-Output 'PADIEM_READ=" + READ_VERDICT_READ_ERROR + "' }"
        "  }"
        " }"
    )


def _parse_single_roundtrip(raw: bytes) -> tuple[str, bytes | None]:
    """Read one reply as ``(verdict, bytes)``; unknown shapes are a fallback.

    The console wraps a long line and the transport strips nothing, so the reply
    is read with its whitespace removed: the header keeps its exact spelling and
    the base64 run follows it. A length or digest that does not match the bytes
    it carries is a fallback, never a shorter body reported as the file.
    """
    text = raw.decode("utf-8", errors="replace")
    flat = "".join(text.split())
    start = flat.find(READ_META_PREFIX)
    if start < 0:
        return "fallback", None
    rest = flat[start + len(READ_META_PREFIX):]
    if rest.startswith(READ_VERDICT_LINK_REFUSED):
        return READ_VERDICT_LINK_REFUSED, None
    match = _READ_META_RE.match(rest)
    if match is None:
        return "fallback", None
    declared = int(match.group(1))
    digest = match.group(2)
    payload_text = rest[match.end():]
    if not payload_text:
        return "fallback", None
    try:
        payload = base64.b64decode(payload_text, validate=True)
    except Exception:
        return "fallback", None
    if len(payload) != declared or hashlib.sha256(payload).hexdigest() != digest:
        return "fallback", None
    return "bytes", payload


def _desktop_dispatch_text(dispatch: "OracleMeshDispatch") -> str | None:
    """The typed value for a type op, and only from the claim that carried it.

    A missing value is None: the caller refuses the op rather than typing the
    marker or a value remembered from an earlier dispatch.
    """
    try:
        from .local_agent_meshcentral_desktop_port import parse_desktop_op

        op, _arg = parse_desktop_op(dispatch.command_text or "")
    except Exception:
        return None
    if op != "type":
        return None
    text = dispatch.desktop_text
    return text if isinstance(text, str) and text else None


class OracleMeshExecutor:
    """Single-thread executor over one authenticated Chat channel.

    ``read_port`` is the merged private MeshCentral port: it owns the operator
    credential (call-time provider, stdin only, marker on argv) and runs the
    official client. ``transport`` is injected so the network boundary is
    explicit and testable; the default performs a verified HTTPS request with
    redirects explicitly refused.
    """

    #: The one-reply read, on by default. Kept as a class attribute as well so an
    #: executor built without ``__init__`` to exercise a single method still has
    #: the switch the live composition would have set.
    _read_single_roundtrip = True

    def __init__(
        self,
        *,
        chat_origin: str,
        channel_secret: str,
        queue_origin: Optional[str] = None,
        edge_secret: Optional[str] = None,
        read_port: Any,
        command_port: Any = None,
        desktop_port: Any = None,
        timeout_seconds: int | None = None,
        channel_timeout_seconds: int = CHANNEL_SOCKET_TIMEOUT_SECONDS,
        idle_poll_max_seconds: int = IDLE_POLL_MAX_SECONDS,
        transport: Optional[Callable[..., tuple[int, dict[str, Any]]]] = None,
        pending_dir: Optional[str] = None,
        claim_gate: Optional[Callable[[], bool]] = None,
        presence_provider: Optional[Callable[[], Any]] = None,
        pairing_provider: Optional[Callable[[], Any]] = None,
        presence_round_begin: Optional[Callable[[], None]] = None,
        read_single_roundtrip: bool = True,
    ) -> None:
        # The result lane may be aimed at the Chat host on this machine — the one
        # origin shape the edge middleware guards, rather than the public Worker. The
        # rule is the queue's and nothing wider: loopback http only, any other http is
        # refused exactly as before, because the channel secret crosses the wire.
        if not isinstance(chat_origin, str) or not (
            chat_origin.startswith("https://") or _is_loopback_channel_origin(chat_origin)
        ):
            raise ContractError("the chat channel must be an https or loopback origin")
        if len(chat_origin) > 300 or chat_origin.rstrip("/") != chat_origin:
            raise ContractError("the chat origin must be a bare origin")
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
        # Only the Chat host sits behind the edge middleware, so only a chat leg aimed
        # at it loopback needs the four proof headers. The queue leg on this host never
        # carried them and still does not.
        self._chat_reaches_edge = _is_loopback_channel_origin(chat_origin)
        if self._chat_reaches_edge and not (
            isinstance(edge_secret, str) and len(edge_secret) >= MIN_EDGE_SECRET_CHARS
        ):
            raise ContractError("a loopback chat channel needs the edge proof secret")
        self._edge_secret = edge_secret if self._chat_reaches_edge else None
        # One TLS context and one opener for the life of the executor instead of one
        # per request. They are made on first use, not in here: a deployment that
        # injects its own transport never touches them, and the tests that watch the
        # socket deadline patch the builder around the call they care about.
        self._ssl_context: Optional[ssl.SSLContext] = None
        self._opener: Any = None
        if type(read_single_roundtrip) is not bool:
            raise ContractError("the single-roundtrip read switch must be a boolean")
        self._read_port = read_port
        self._read_single_roundtrip = read_single_roundtrip
        self._command_port = command_port
        self._desktop_port = desktop_port
        self._timeout = timeout_seconds
        self._channel_timeout = channel_timeout_seconds
        self.idle_poll_max_seconds = idle_poll_max_seconds
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
        self._active_background: dict[str, str] = {}
        self._node_execution_locks: dict[str, threading.Lock] = {}
        self._background_jobs = None
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

    def _leg_for(self, path: str) -> str:
        """One word for which server `_origin_for` would ask: `chat` or `queue`.

        Derived from the routing rule itself rather than repeated here, so the two can
        never disagree about where a request was going.
        """

        return "chat" if self._origin_for(path) == self._origin else "queue"

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
        headers = {
            "Content-Type": content_type,
            CHANNEL_HEADER: self._secret,
            "Accept": "application/json",
            "User-Agent": PRODUCT_USER_AGENT,
            # Retain the authenticated HTTPS request until a queued
            # dispatch is available. Old consumers still get immediate poll.
            **({"X-Oracle-Mesh-Wait": "5"} if path == POLL_PATH else {}),
        }
        if self._chat_reaches_edge and self._leg_for(path) == "chat":
            # The Chat host's edge middleware answers an unsigned loopback request with
            # a bare 403 before the channel secret is ever read, so the leg signs itself
            # the way the Engine's chat binding does — a fresh request id per call,
            # because the server stores the ids it has already seen.
            headers.update(edge_proof_headers(
                str(self._edge_secret), method="POST", path=path,
            ))
        request = urllib.request.Request(url, data=data, method="POST", headers=headers)
        # urllib follows 30x by default; an executor channel must never be
        # silently moved to another origin, so redirects are refused outright.
        # The opener and its TLS context are made once per executor, not per
        # request: the loop posts every poll, renew, busy beat and submit through
        # them, and rebuilding a certificate store each time bought nothing.
        if self._opener is None:
            self._ssl_context = ssl.create_default_context()
            self._opener = urllib.request.build_opener(
                _NoRedirect(), urllib.request.HTTPSHandler(context=self._ssl_context)
            )
        try:
            with self._opener.open(request, timeout=self._channel_timeout) as response:
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
            raise OracleMeshChannelRefused("chat channel transport refused",
                                           leg=self._leg_for(path)) from exc
        finally:
            # Inventory is independent of command progress. Its background
            # traffic must not conceal a stalled dispatch loop from the watchdog.
            from .local_agent_mesh_drive_reporter import DRIVES_PATH, DRIVE_TARGETS_PATH
            if path not in {DRIVES_PATH, DRIVE_TARGETS_PATH}:
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
            raise OracleMeshChannelRefused("chat channel transport refused",
                                           leg=self._leg_for(path)) from exc

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
        leg = self._leg_for(POLL_PATH)
        status, data = self._post(POLL_PATH, payload)
        if status != 200 or data.get("ok") is not True:
            raise OracleMeshChannelRefused("chat channel refused the poll", leg=leg)
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
            raise OracleMeshChannelRefused("chat channel returned a malformed dispatch", leg=leg)
        kind = dispatch.get("kind") or "read"
        if kind not in ("read", "command", "desktop"):
            raise OracleMeshChannelRefused("chat channel returned an unknown dispatch kind", leg=leg)
        command_text = dispatch.get("command_text")
        if kind in ("command", "desktop"):
            # The server owns the command; the executor never invents one and
            # never falls back to the file lane when it is missing.
            if not isinstance(command_text, str) or not command_text.strip():
                raise OracleMeshChannelRefused(
                    "chat channel returned a command dispatch without a command", leg=leg,
                )
        else:
            command_text = None
        max_bytes = None
        if kind == "read":
            supplied = dispatch.get("max_bytes")
            if supplied is not None:
                # The server decides the bound; the executor checks the shape
                # only. A read bound is a positive integer — no bool, no zero,
                # no negative — and the executor never invents one of its own.
                if (
                    isinstance(supplied, bool)
                    or not isinstance(supplied, int)
                    or supplied < 1
                ):
                    raise OracleMeshChannelRefused(
                        "chat channel returned an unbounded read limit", leg=leg,
                    )
                max_bytes = supplied
        desktop_text = None
        if kind == "desktop":
            supplied_text = dispatch.get("desktop_text")
            if supplied_text is not None:
                if (not isinstance(supplied_text, str) or not supplied_text
                        or len(supplied_text) > 20000
                        or "\x00" in supplied_text or "\r" in supplied_text):
                    raise OracleMeshChannelRefused(
                        "chat channel returned an unusable typed value", leg=leg,
                    )
                desktop_text = supplied_text
        background = dispatch.get("background", False)
        if type(background) is not bool or (background and kind not in ("read", "command")):
            raise OracleMeshChannelRefused("invalid background dispatch", leg=leg)
        owner_ref = dispatch.get("owner_ref")
        if background:
            owner_ref = _require_text(owner_ref, "owner_ref")
        else:
            owner_ref = None
        request_id = dispatch.get("request_id")
        if request_id is not None:
            request_id = _require_text(request_id, "request_id")
        granted_root = dispatch.get("granted_root")
        if granted_root is not None:
            granted_root = _require_text(granted_root, "granted_root")
        user_mode = dispatch.get("user_mode", False)
        if type(user_mode) is not bool or (user_mode and kind != "command"):
            raise OracleMeshChannelRefused("invalid user_mode dispatch", leg=leg)
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
            desktop_text=desktop_text,
            max_bytes=max_bytes,
            granted_root=granted_root,
            background=background,
            owner_ref=owner_ref,
            user_mode=user_mode,
            device_id=_require_text(dispatch.get("device_id"), "device_id") if dispatch.get("device_id") is not None else None,
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
        # #5994 D3 후속: before the download, every folder from the granted
        # root down to the file — and the file itself — is checked for a
        # ReparsePoint crossing. The executor's own filesystem answers first
        # (the connector executor runs on the user's PC); where that cannot
        # see — the COM2 relay executor — the same walk runs ON THE PC through
        # the MeshCentral command channel. A hit (or a PC check that cannot
        # complete) refuses the read with the ``link_refused`` marker so not
        # one byte of an outside file crosses the relay. A server that names
        # no root keeps the read exactly as it was before this guard.
        read_bound = dispatch.max_bytes
        if read_bound is None:
            read_bound = MAX_READ_BYTES
        if MAX_READ_BYTES_ENVELOPE is not None:
            read_bound = max(1, min(read_bound, MAX_READ_BYTES_ENVELOPE))
        guard_started = time.monotonic()
        raw: bytes | None = None
        if dispatch.granted_root:
            if walk_hits_reparse_point(dispatch.granted_root, dispatch.file_path):
                self._trace_read(dispatch, "link_refused", guard_started,
                                 reason="local_hit")
                return OracleMeshExecutionOutcome(
                    termination="exited", exit_code=1,
                    body=PC_FILE_LINK_REFUSED_MARKER.encode("utf-8"),
                )
            if self._command_port is not None:
                refused = False
                if self._read_single_roundtrip:
                    raw, refused = self._read_in_one_roundtrip(
                        dispatch, read_bound, guard_started,
                    )
                if refused:
                    return OracleMeshExecutionOutcome(
                        termination="exited", exit_code=1,
                        body=PC_FILE_LINK_REFUSED_MARKER.encode("utf-8"),
                    )
                # No bytes from the one-reply path means it fell back (a shape it
                # could not verify, a file past its bound, or no command port);
                # the PC walk below then runs exactly as it did before.
                if raw is None:
                    hit, reason, detail = self._pc_reparse_check(
                        granted_root=dispatch.granted_root,
                        file_path=dispatch.file_path,
                        node_ref=dispatch.node_ref,
                    )
                    if hit:
                        self._trace_read(dispatch, "link_refused", guard_started,
                                         reason=reason, detail=detail)
                        return OracleMeshExecutionOutcome(
                            termination="exited", exit_code=1,
                            body=PC_FILE_LINK_REFUSED_MARKER.encode("utf-8"),
                        )
        started = time.monotonic()
        if raw is None:
            # The guard asked the PC and answered, and the bytes are the next round
            # trip. When the one-reply path already produced the payload there is
            # nothing to separate, and no second line is written for it.
            self._trace_read(dispatch, "guard_done", guard_started,
                             path="two_step")
            call: dict[str, Any] = {
                "node_ref": dispatch.node_ref,
                "file_path": dispatch.file_path,
            }
            # The port validates this deadline outright and refuses before the
            # official client runs. An executor with no deadline of its own must
            # therefore leave the argument out so the port's default applies; the
            # None that used to travel here refused every read from 2026-10-29 on.
            if self._timeout is not None:
                call["timeout_seconds"] = self._timeout * 4
            if dispatch.max_bytes is not None:
                # Pass the server-computed bound only when the poll supplied one;
                # older servers keep the port's historical default.
                call["max_bytes"] = read_bound
            try:
                body = self._read_port.read_bytes(**call)
            except MeshCentralReadTooLarge as exc:
                self._trace_read(dispatch, "read_too_large", started,
                                 error=_safe_error_text(exc))
                return OracleMeshExecutionOutcome(
                    termination="exited", exit_code=1,
                    body=PC_FILE_TOO_LARGE_MARKER.encode("utf-8"),
                )
            except MeshCentralReadRequestRefused as exc:
                # Validation refused the request here: no client ran, no PC was
                # contacted. Reporting this as read_failed hid that distinction.
                self._trace_read(dispatch, "read_refused", started,
                                 error=_safe_error_text(exc))
                return OracleMeshExecutionOutcome(
                    termination="exited", exit_code=1,
                    body=PC_FILE_READ_REFUSED_MARKER.encode("utf-8"),
                )
            except Exception as exc:
                # The class and a bounded message are the only explanation a refused
                # read ever leaves; the file itself is never part of the trace.
                self._trace_read(dispatch, "read_failed", started,
                                 error=_safe_error_text(exc))
                return OracleMeshExecutionOutcome(
                    termination="exited", exit_code=1,
                    body=PC_FILE_READ_FAILED_MARKER.encode("utf-8"),
                )
            if not isinstance(body, (bytes, bytearray)):
                self._trace_read(dispatch, "read_failed", started,
                                 error="body_not_bytes")
                return OracleMeshExecutionOutcome(
                    termination="exited", exit_code=1,
                    body=PC_FILE_READ_FAILED_MARKER.encode("utf-8"),
                )
            raw = bytes(body)
            self._trace_read(dispatch, "read_ok", started,
                             path="download", bytes=len(raw))
        if len(raw) > read_bound:
            # Oversize is refused, never truncated.
            self._trace_read(dispatch, "read_too_large", started,
                             error="staged_oversize")
            return OracleMeshExecutionOutcome(
                termination="exited", exit_code=1,
                body=PC_FILE_TOO_LARGE_MARKER.encode("utf-8"),
            )
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            self._trace_read(dispatch, "read_failed", started, error="not_utf8")
            return OracleMeshExecutionOutcome(
                termination="exited", exit_code=1,
                body=PC_FILE_READ_FAILED_MARKER.encode("utf-8"),
            )
        return OracleMeshExecutionOutcome(termination="exited", exit_code=0, body=raw)

    def _read_in_one_roundtrip(
        self,
        dispatch: OracleMeshDispatch,
        read_bound: int,
        started: float,
    ) -> tuple[bytes | None, bool]:
        """Guard-then-read in ONE command reply; ``(bytes, refused)``.

        ``(None, False)`` means "use the two-step path": the reply could not be
        verified, the file is past this lane's bound, or no command port exists.
        ``(None, True)`` is the guard's own verdict, and it is returned without a
        single byte, exactly as the separate walk refused before.
        """
        max_bytes = min(int(read_bound), SINGLE_ROUNDTRIP_MAX_BYTES)
        script = _single_roundtrip_script(
            granted_root=dispatch.granted_root or "",
            file_path=dispatch.file_path,
            max_bytes=max_bytes,
        )
        call_started = time.monotonic()
        try:
            outcome = self._command_port.run_command(
                node_ref=dispatch.node_ref,
                command=script,
                # The same deadline shape the read lane uses: a deployment that
                # names a base step gets four of them, and one that names none
                # keeps the platform's own bound.
                timeout_seconds=(self._timeout * 4 if self._timeout is not None else None),
            )
        except Exception as exc:
            self._trace_read(dispatch, "single_roundtrip_fallback", call_started,
                             error=_safe_error_text(exc))
            return None, False
        termination = getattr(outcome, "termination", None)
        if termination not in ("exited", "no_exit_code"):
            self._trace_read(dispatch, "single_roundtrip_fallback", call_started,
                             termination=str(termination))
            return None, False
        raw = getattr(outcome, "output", b"")
        if not isinstance(raw, (bytes, bytearray)):
            self._trace_read(dispatch, "single_roundtrip_fallback", call_started,
                             error="output_not_bytes")
            return None, False
        verdict, payload = _parse_single_roundtrip(bytes(raw))
        if verdict == READ_VERDICT_LINK_REFUSED:
            self._trace_read(dispatch, "link_refused", started, reason="pc_hit")
            return None, True
        if verdict != "bytes" or payload is None:
            self._trace_read(dispatch, "single_roundtrip_fallback", call_started,
                             error="unverified_reply")
            return None, False
        self._trace_read(dispatch, "read_ok", call_started,
                         path="single_roundtrip", bytes=len(payload))
        return payload, False

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
                f" run_hash={_pc_run_hash(dispatch.run_id) or 'none'}"
                + (f" {safe}" if safe else ""),
                file=sys.stderr,
                flush=True,
            )
        except Exception:
            # Instrumentation is best-effort; the command outcome is authoritative.
            pass

    def _pc_reparse_check(
        self, *, granted_root: str, file_path: str, node_ref: str,
    ) -> tuple[bool, str | None, str | None]:
        """Run a ReparsePoint walk ON THE PC through the MeshCentral command channel.

        The walk checks every folder from the granted root down to the file -
        and the file itself - for the ReparsePoint attribute. A hit (or a check
        that cannot be completed) means the read is refused before the download
        starts, so not one byte of an outside file crosses the relay.

        Returns ``(hit, reason, detail)``. Every refusal used to share one fixed
        trace string, so a real link hit could not be told from a check that
        never ran — the 11-05 outage was the second kind. ``reason`` is
        ``pc_hit``, ``pc_no_marker`` or ``pc_check_error``; ``detail`` names the
        exception class or the termination that failed the check closed, and
        never carries command output.
        """
        if self._command_port is None:
            # 명령 채널이 없으면 검사 자체가 불가능 — fail closed
            return True, "pc_check_error", "no_command_port"
        guard_root = _pc_guard_root(granted_root)
        guard_target = file_path.strip().replace("/", "\\")
        script = (
            "$ErrorActionPreference = 'Stop';"
            "$root = " + _ps_literal_for_root(guard_root) + ";"
            "$target = " + _ps_literal_for_root(guard_target) + ";"
            "$walk = $root;"
            "$hit = $false;"
            "try {"
            " if (-not $target.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) { $hit = $true };"
            " if (-not $hit) {"
            "  $rest = $target.Substring($root.Length);"
            "  foreach ($seg in $rest.Split([char]'\\')) {"
            "   if (-not $seg) { continue };"
            "   $walk = Join-Path $walk $seg;"
            "   if (-not (Test-Path -LiteralPath $walk)) { break };"
            "   $item = Get-Item -LiteralPath $walk -Force -ErrorAction SilentlyContinue;"
            "   if ($item -and (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0))"
            "   { $hit = $true; break }"
            "  }"
            " }"
            "} catch { $hit = $true };"
            "$account = [ordered]@{hit=[bool]$hit};"
            "$json = ConvertTo-Json -InputObject $account -Compress;"
            "$encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json));"
            "Write-Output ('PADIEM_PC_REPARSE=' + $encoded);"
        )
        try:
            outcome = self._command_port.run_command(
                node_ref=node_ref, command=script, timeout_seconds=30,
            )
            # 11-05: the command port's outcome carries ``output`` — the same
            # field the command lane reads. ``outcome.body`` never existed on
            # MeshCentralCommandOutcome (a frozen slots dataclass), so this
            # line raised AttributeError, fell into the except below, and the
            # guard failed closed for every read on every PC even when the PC
            # answered hit=false. Only a run the PC actually finished can
            # carry a verdict.
            # The guard is cmdlets and .NET calls only, so PowerShell leaves
            # ``$LASTEXITCODE`` empty and the port reports ``no_exit_code``:
            # the console answered completely, the code is simply unobserved
            # (measured on the real PC, 11-05 16:20). Both shapes carry the
            # whole transcript; anything else did not finish on the PC.
            termination = getattr(outcome, "termination", None)
            if termination not in ("exited", "no_exit_code"):
                # 검사 명령이 끝까지 돌지 못함 → fail closed
                return True, "pc_check_error", f"termination={termination}"
            raw = getattr(outcome, "output", b"")
            if not isinstance(raw, (bytes, bytearray)):
                return True, "pc_check_error", "output_not_bytes"
            text = bytes(raw).decode("utf-8", errors="replace")
            for line in text.splitlines():
                if not line.startswith("PADIEM_PC_REPARSE="):
                    continue
                try:
                    parsed = json.loads(
                        base64.b64decode(line[len("PADIEM_PC_REPARSE="):]))
                except Exception as exc:
                    return True, "pc_check_error", exc.__class__.__name__
                hit = parsed.get("hit") if isinstance(parsed, dict) else None
                # A marker that does not carry an explicit boolean verdict is a
                # check that cannot report — refuse closed, and say so.
                if type(hit) is not bool:
                    return True, "pc_check_error", "hit_not_bool"
                if hit:
                    return True, "pc_hit", None
                return False, None, None
            return True, "pc_no_marker", None  # account line 없음 — 검사 실패
        except Exception as exc:
            # A channel that refuses or breaks cannot answer the walk, so the
            # read stays refused — and the trace now says which failure it was.
            return True, "pc_check_error", exc.__class__.__name__

    def _trace_read(
        self, dispatch: OracleMeshDispatch, phase: str, started: float,
        **fields: Any,
    ) -> None:
        """Bounded read-lane correlation: a class and a reason, never content.

        Every read failure used to leave the process as one fixed marker, so a
        refused read could not be told apart from a missing file or a dead
        channel. This line is the observable that answers "why" without ever
        carrying bytes the PC was asked to hand over.
        """
        try:
            elapsed_ms = max(0, int((time.monotonic() - started) * 1000))
            safe = " ".join(
                f"{key}={value}"
                for key, value in fields.items()
                if value is not None and isinstance(value, (str, int, bool))
            )
            print(
                "oracle-mesh-read"
                f" phase={phase}"
                f" ts={datetime.now(timezone.utc).isoformat()}"
                f" elapsed_ms={elapsed_ms}"
                f" dispatch_id={dispatch.dispatch_id}"
                f" run_hash={_pc_run_hash(dispatch.run_id) or 'none'}"
                + (f" {safe}" if safe else ""),
                file=sys.stderr,
                flush=True,
            )
        except Exception:
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

    @staticmethod
    def build_user_helper_pipe_client_ps(*, request_id: str, shell: str,
                                         command: str, cwd: str | None,
                                         timeout_seconds: int,
                                         distro: str | None,
                                         task_arguments: str | None = None,
                                         task_path: str = USER_HELPER_TASK_PATH,
                                         task_name: str = USER_HELPER_TASK_NAME) -> str:
        """#7076c/#7105: PS pipe client sent via runcommand (SYSTEM) to the PC.

        The script runs on the target PC as SYSTEM. It reads the registered
        Padiem task's own arguments, takes ``--device-id`` from that string, and
        computes the pipe name locally with UTF-8 SHA-256. The dispatch's
        ``device_id`` is never used: both installation lanes (one-click pairing
        tag and connector ``mesh_node_id``) are already represented by the value
        the installer wrote into the task.

        ``task_arguments`` is a test seam. A CI runner has no registered Padiem
        task, so a test can supply the exact argument string the installer
        writes. No production caller passes it, and the parsing, hashing, frame
        bytes and nonce are the same either way.

        Secret value is never printed. A missing task, a missing ``--device-id``,
        or a missing secret file is reported as user_session_unavailable before
        any pipe connect - no SYSTEM fallback.
        """
        import base64 as _b64
        import json as _json
        mat = "\n".join([request_id, shell, cwd or "", command, str(int(timeout_seconds)), distro or ""]).encode("utf-8")
        # material is not secret; embed as base64 data for exact byte fidelity.
        mat_b64 = _b64.b64encode(mat).decode("ascii")
        payload = {
            "request_id": request_id, "shell": shell, "cwd": cwd,
            "command": command, "timeout_seconds": int(timeout_seconds), "distro": distro,
        }
        req_b64 = _b64.b64encode(_json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")).decode("ascii")
        if task_arguments is None:
            # #7196: Get-ScheduledTask reaches the task through the Task Scheduler COM
            # service, which carries no timeout of its own and was a second way for
            # this client to wait with no bound. The task's definition is also a file
            # the installer writes under %SystemRoot%\System32\Tasks, and SYSTEM (this
            # client's account) reads it directly, so ``--device-id`` and
            # ``--secret-file`` come from that file's <Arguments> with no service call.
            # The relative path is the registered task folder plus its name.
            _rel_parts = [p for p in str(task_path).split("\\") if p]
            _task_rel = "\\".join(_rel_parts + [str(task_name)]).replace("'", "''")
            arguments_source = (
                "\n  $txp=[IO.Path]::Combine($env:SystemRoot,'System32\\Tasks\\@@TASK_REL@@')"
                "\n  if(-not [IO.File]::Exists($txp)){ Fail 'user_session_unavailable' 'helper task file is not present' }"
                "\n  $arg=''"
                "\n  try { $__tx=New-Object System.Xml.XmlDocument; $__tx.Load($txp); $__ex=@($__tx.Task.Actions.Exec); if($__ex.Count -ge 1){ $arg=[string]$__ex[0].Arguments } } catch { $arg='' }"
                "\n  if(-not $arg){ Fail 'user_session_unavailable' 'helper task arguments are unavailable' }"
            ).replace("@@TASK_REL@@", _task_rel)
        else:
            arguments_source = (
                "\n  $arg=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('"
                + _b64.b64encode(str(task_arguments).encode("utf-8")).decode("ascii")
                + "'))"
            )
        # #7196: an overall backstop so a helper that accepts and then neither
        # finishes nor drops cannot hold forever. The floor is 180s and the request
        # timeout gets +120s of slack, so a command that finishes within its own
        # timeout is never cut - this is why the request timeout is NOT used as the
        # deadline directly (that cut a healthy 32s command, #7107). The operator can
        # raise it (PADIEM_MESH_USER_HELPER_REPLY_SECONDS > 0) or disable it (< 0).
        overall_backstop = max(180, int(timeout_seconds) + 120)
        script = r"""
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$ConfirmPreference='None'
function Trace($m){ try{ if([IO.File]::Exists('C:\ProgramData\Padiem\client-trace.enabled')){ [IO.File]::AppendAllText('C:\ProgramData\Padiem\client-trace.log',((Get-Date).ToString('o')+' '+[string]$m+"`r`n")) } }catch{} }
Trace 'client start'
$mat=[Convert]::FromBase64String('@@MAT_B64@@')
$reqB64='@@REQ_B64@@'
# #7182b: never 'exit' from this client. The SYSTEM lane runs it inside
# ``& { <client> } 2>&1 | Out-String`` and prints the reply envelope and the
# ``__PADIEM_EXIT__`` sentinel only AFTER that block returns; an 'exit' ends
# PowerShell first, so the transcript carried no sentinel at all and every
# user-mode command - a success as much as a refusal - was read back as
# 'no reply'. Measured on 컴1 2026-11-08: the wrapped client answered 'ok' in
# 1.7s with an empty stdout for the lane. Fail therefore throws a code-prefixed
# message, the answer is written on the pipeline, and the script returns.
function Fail($code,$msg){ throw [string]($code+': '+$msg) }
# #7184c: a wait that ran out says which bound ran out, so the executor's reply
# names the actual stop instead of a generic read timeout.
function Timeout(){
  if($__firstBy -gt 0 -and [Environment]::TickCount -ge $__firstBy){ throw 'user_helper_timeout: first-frame deadline expired' }
  if($__deadline -gt 0 -and [Environment]::TickCount -ge $__deadline){ throw 'user_helper_timeout: overall deadline expired' }
  throw 'user_helper_timeout: frame read deadline expired'
}
try {@@ARGUMENTS_SOURCE@@
  $deviceId=$null
  if($arg -match '--device-id\s+"([^"]+)"'){ $deviceId=$Matches[1] }
  elseif($arg -match "--device-id\s+'([^']+)'"){ $deviceId=$Matches[1] }
  elseif($arg -match '--device-id\s+([^\s]+)'){ $deviceId=$Matches[1] }
  if(-not $deviceId){ Fail 'user_session_unavailable' 'helper device id is not configured' }
  if($deviceId -notmatch '^[A-Za-z0-9_.$:@+\-]{1,256}$'){ Fail 'user_session_unavailable' 'helper device id is not valid' }
  $sha=[System.Security.Cryptography.SHA256]::Create()
  $digest=-join ($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($deviceId)) | ForEach-Object { $_.ToString('x2') })
  $pipeName='padiem-user-helper-dev_'+$digest.Substring(0,32)
  $pipePath='\\.\pipe\'+$pipeName
  Trace 'device id ok, pipe computed'
  $secretFile=$null
  if($arg -match '--secret-file\s+"([^"]+)"'){ $secretFile=$Matches[1] }
  elseif($arg -match "--secret-file\s+'([^']+)'"){ $secretFile=$Matches[1] }
  elseif($arg -match '--secret-file\s+([^\s]+)'){ $secretFile=$Matches[1] }
  if(-not $secretFile){ Fail 'user_session_unavailable' 'helper secret file is not configured' }
  $raw=[System.IO.File]::ReadAllBytes($secretFile)
  $secretText=[System.Text.Encoding]::UTF8.GetString($raw).Trim()
  $secret=[System.Text.Encoding]::UTF8.GetBytes($secretText)
  if($secret.Length -eq 0){ Fail 'user_session_unavailable' 'helper secret is unavailable' }
  $hmac=New-Object System.Security.Cryptography.HMACSHA256 -ArgumentList (,$secret)
  $nonce=-join ($hmac.ComputeHash($mat) | ForEach-Object { $_.ToString('x2') })
  $req=[System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($reqB64)) | ConvertFrom-Json
  $req | Add-Member -NotePropertyName nonce -NotePropertyValue $nonce -Force
  $body=[System.Text.Encoding]::UTF8.GetBytes(($req | ConvertTo-Json -Compress -Depth 5))
  $len=[System.BitConverter]::GetBytes([int]$body.Length); [Array]::Reverse($len)
  $client=New-Object System.IO.Pipes.NamedPipeClientStream('.',$pipeName,[System.IO.Pipes.PipeDirection]::InOut)
  # #7106: every pipe step is bounded. Connect 5s, each write 5s, each frame
  # 15s. A helper that accepted and then died fails here instead of holding
  # the executor's single dispatch loop open forever. The 15s read window is
  # per frame, not a command deadline: while a stage-2 command runs the helper
  # sends a heartbeat every 5s, so a long command keeps its lane.
  $client.Connect(5000)
  Trace 'pipe connected'
  # #7184c: the wait for the helper's FIRST frame is a communication wait and is
  # bounded (30s default, PADIEM_MESH_USER_HELPER_FIRST_FRAME_SECONDS). After
  # that frame the wait is the work itself: the helper heartbeats while the user
  # child runs, and the owner ends that through pc_shell_stop.
  # #7196: an overall backstop (PADIEM_MESH_USER_HELPER_REPLY_SECONDS, default
  # max(180, timeout+120), <0 disables) also bounds the whole wait, so a helper
  # that accepts and then neither finishes nor drops cannot hold forever.
  $__firstFrame=30; try{ $__v=[int]$env:PADIEM_MESH_USER_HELPER_FIRST_FRAME_SECONDS; if($__v -gt 0){ $__firstFrame=$__v } }catch{}
  # #7196: the overall backstop defaults to max(180, timeout+120) (baked below).
  # The operator switch overrides it: a positive value sets the seconds, a negative
  # value turns the backstop off. The request timeout is never the deadline itself.
  $__overall=@@OVERALL_SECONDS@@
  try{ $__cap=[int]$env:PADIEM_MESH_USER_HELPER_REPLY_SECONDS; if($__cap -gt 0){ $__overall=$__cap } elseif($__cap -lt 0){ $__overall=0 } }catch{}
  $__firstBy=[Environment]::TickCount + ($__firstFrame*1000)
  $__deadline=0
  if($__overall -gt 0){ $__deadline=[Environment]::TickCount + ($__overall*1000) }
  $w=$client.WriteAsync($len,0,4); if(-not $w.Wait(5000)){ throw 'helper write timeout' }
  $w=$client.WriteAsync($body,0,$body.Length); if(-not $w.Wait(5000)){ throw 'helper write timeout' }
  $client.Flush()
  Trace 'request sent'
  # #7107: the helper streams stdout/stderr as chunks. Accumulate them in
  # memory and emit one reply object; there is no 256 KiB cut and no fixed
  # command deadline. The 15s read window is per frame, and a 5s heartbeat
  # keeps a healthy long command alive.
  $stdout=New-Object System.Collections.Generic.List[byte]
  $stderr=New-Object System.Collections.Generic.List[byte]
  while($true){
    if($__firstBy -gt 0 -and [Environment]::TickCount -gt $__firstBy){ throw 'user_helper_timeout: first-frame deadline expired' }
    if($__deadline -gt 0 -and [Environment]::TickCount -gt $__deadline){ throw 'user_helper_timeout: overall deadline expired' }
    # A frame window may be shorter than 15s, never longer than the bound that
    # contains it: a 15s read would otherwise swallow a 3s first-frame bound.
    $__wait=15000
    if($__firstBy -gt 0){ $__left=$__firstBy-[Environment]::TickCount; if($__left -lt $__wait){ $__wait=$__left } }
    if($__deadline -gt 0){ $__left=$__deadline-[Environment]::TickCount; if($__left -lt $__wait){ $__wait=$__left } }
    if($__wait -lt 1){ $__wait=1 }
    $hdr=New-Object byte[] 4; $read=0
    while($read -lt 4){
      $t=$client.ReadAsync($hdr,$read,4-$read); if(-not $t.Wait($__wait)){ Timeout }
      $n=$t.Result; if($n -le 0){ throw 'short header' }; $read+=$n
    }
    [Array]::Reverse($hdr); $rlen=[System.BitConverter]::ToInt32($hdr,0)
    if($rlen -lt 0 -or $rlen -gt 2097152){ throw 'bad frame length' }
    $rbody=New-Object byte[] $rlen; $read=0
    while($read -lt $rlen){
      $t=$client.ReadAsync($rbody,$read,$rlen-$read); if(-not $t.Wait($__wait)){ Timeout }
      $n=$t.Result; if($n -le 0){ throw 'short body' }; $read+=$n
    }
    $text=[System.Text.Encoding]::UTF8.GetString($rbody)
    $frame=$text | ConvertFrom-Json; $__firstBy=0
    if($frame.status -eq 'started' -or $frame.status -eq 'running'){ continue }
    if($frame.status -eq 'stdout'){
      $stdout.AddRange([byte[]][Convert]::FromBase64String([string]$frame.data_b64)); continue
    }
    if($frame.status -eq 'stderr'){
      $stderr.AddRange([byte[]][Convert]::FromBase64String([string]$frame.data_b64)); continue
    }
    $__finalOut=[string]$frame.stdout_b64; $__finalErr=[string]$frame.stderr_b64
    if($stdout.Count -eq 0 -and $__finalOut){ $stdout.AddRange([byte[]][Convert]::FromBase64String($__finalOut)) }
    if($stderr.Count -eq 0 -and $__finalErr){ $stderr.AddRange([byte[]][Convert]::FromBase64String($__finalErr)) }
    $reply=[ordered]@{
      request_id=$frame.request_id; status=$frame.status; exit_code=$frame.exit_code;
      stdout_b64=[Convert]::ToBase64String($stdout.ToArray());
      stderr_b64=[Convert]::ToBase64String($stderr.ToArray());
      truncated=$false; error_code=$frame.error_code; duration_ms=$frame.duration_ms
    }
    Trace ('reply '+[string]$frame.status)
    $client.Dispose()
    Write-Output ($reply | ConvertTo-Json -Compress)
    [Console]::Out.Flush()
    return
  }
} catch {
  try { $client.Dispose() } catch {}
  [Console]::Out.Flush()
  $detail=[string]$_.Exception.Message
  if($detail -notmatch '^[a-z_]+: '){ $detail='user_session_unavailable: helper pipe is not available' }
  Trace ('catch '+$detail)
  Write-Output $detail
  return
}
""".strip()
        return (
            script.replace("@@MAT_B64@@", mat_b64)
            .replace("@@REQ_B64@@", req_b64)
            .replace("@@ARGUMENTS_SOURCE@@", arguments_source)
            .replace("@@OVERALL_SECONDS@@", str(overall_backstop))
        )

    @staticmethod
    def _parse_user_helper_outcome(raw: bytes) -> OracleMeshExecutionOutcome:
        import json as _json
        text = raw.decode("utf-8", errors="replace").strip() if isinstance(raw, (bytes, bytearray)) else str(raw).strip()
        if not text:
            return OracleMeshExecutionOutcome(termination="no_reply", exit_code=None, body=b"")
        try:
            obj = _json.loads(text)
        except Exception:
            # pipe-unavailable marker emitted by PS client
            if text.startswith(USER_SESSION_UNAVAILABLE):
                return OracleMeshExecutionOutcome(termination="exited", exit_code=1,
                    body=_json.dumps({"ok": False, "error_code": USER_SESSION_UNAVAILABLE, "detail": "helper pipe is not available"}, ensure_ascii=True).encode("utf-8"))
            return OracleMeshExecutionOutcome(termination="exited", exit_code=1, body=raw if isinstance(raw,(bytes,bytearray)) else text.encode("utf-8","replace"))
        if not isinstance(obj, dict):
            return OracleMeshExecutionOutcome(termination="exited", exit_code=1, body=raw if isinstance(raw,(bytes,bytearray)) else text.encode("utf-8","replace"))
        status = obj.get("status")
        if status == "cancelled":
            # The helper ended the child because the owner stopped the dispatch
            # or the SYSTEM client went away. That is a stop, not a silent reply.
            return OracleMeshExecutionOutcome(termination="cancelled", exit_code=None, body=b"")
        if status == "ok":
            stdout = obj.get("stdout_b64")
            try:
                body = __import__("base64").b64decode(stdout) if isinstance(stdout,str) else b""
            except Exception:
                body = b""
            if not body:
                # #7105: a failing stage-2 command often writes only to stderr.
                # An empty body with a non-zero code would read as "no answer".
                stderr = obj.get("stderr_b64")
                try:
                    body = __import__("base64").b64decode(stderr) if isinstance(stderr, str) else b""
                except Exception:
                    body = b""
            code = obj.get("exit_code")
            if isinstance(code, bool) or not isinstance(code, int): code = 0
            return OracleMeshExecutionOutcome(termination="exited", exit_code=code, body=body)
        err = obj.get("error_code") if isinstance(obj.get("error_code"), str) else "user_helper_refused"
        detail = obj.get("detail") if isinstance(obj.get("detail"), str) else ""
        return OracleMeshExecutionOutcome(termination="exited", exit_code=1,
            body=_json.dumps({"ok": False, "error_code": err, "detail": detail}, ensure_ascii=True).encode("utf-8"))

    def _execute_user_mode_command(self, dispatch: OracleMeshDispatch, *, additional_cancel_probe=None) -> OracleMeshExecutionOutcome:
        if self._command_port is None:
            raise OracleMeshChannelRefused("command execution is not configured")
        import json as _json
        node_ref = dispatch.node_ref
        raw = getattr(dispatch, "command_text", "") or ""
        # user_mode carries helper request material JSON (shell/command/cwd/timeout/distro).
        try:
            mat = _json.loads(raw)
            if not isinstance(mat, dict): raise ValueError("not object")
        except Exception:
            return OracleMeshExecutionOutcome(termination="not_executed", exit_code=None,
                body=_json.dumps({"ok": False, "error_code": USER_SESSION_UNAVAILABLE, "detail": "user mode request unavailable"}, ensure_ascii=True).encode("utf-8"))
        req_id = f"req_{dispatch.dispatch_id.replace('dsp_','')[:32].ljust(32,'0')}"
        shell_name = mat.get("shell") if isinstance(mat.get("shell"), str) else "whoami"
        cmd = mat.get("command") if isinstance(mat.get("command"), str) else ""
        cwd = mat.get("cwd") if isinstance(mat.get("cwd"), str) else None
        distro = mat.get("distro") if isinstance(mat.get("distro"), str) else None
        timeout_s = mat.get("timeout_seconds")
        if not isinstance(timeout_s, int) or isinstance(timeout_s, bool): timeout_s = 30
        # #7117 PR-3: the pipe name comes from the registered task's own
        # --device-id, not from dispatch.device_id. The value is written by the
        # installer (one-click pairing tag or connector mesh_node_id), so both
        # lanes hash the same string on the PC. A missing task or argument is
        # reported by the PS client before any pipe wait.
        try:
            ps = self.build_user_helper_pipe_client_ps(request_id=req_id, shell=shell_name, command=cmd, cwd=cwd, timeout_seconds=timeout_s, distro=distro)
        except Exception:
            return OracleMeshExecutionOutcome(termination="not_executed", exit_code=None,
                body=_json.dumps({"ok": False, "error_code": USER_SESSION_UNAVAILABLE, "detail": "user mode client unavailable"}, ensure_ascii=True).encode("utf-8"))
        # #7107: a background job's own cancel event is not the only stop path.
        # pc_shell_stop marks the dispatch cancelled on the server; the owner
        # probe is what makes this PS client notice and hang up, which in turn
        # makes the helper end the user child. Check both, like the SYSTEM lane.
        owner_cancel = self._cancel_probe(dispatch)

        def cancelled():
            return ((callable(additional_cancel_probe) and additional_cancel_probe())
                    or owner_cancel())

        # #7177: user-mode dispatches journal the same phase spine as SYSTEM —
        # without it a silent user job reads as "claimed then nothing", which is
        # exactly how the 11-08 incident read in the journal.
        started = time.monotonic()
        self._trace_command(dispatch, "start", started)

        def phase(phase_name: str) -> None:
            self._trace_command(dispatch, phase_name, started)

        try:
            # #7180: the client console must name its own dispatch. Without the
            # id the PC-side PowerShell left no pid marker, so the owner's stop
            # had nothing to aim at once this dispatch was gone and the orphaned
            # console held the agent for as long as it lived (measured 19 hours).
            # #7184c: the same marker is what lets pc_shell_stop end a user-mode
            # client that is still waiting - measured 2026-11-08 on 컴1: the stop
            # left the SYSTEM PowerShell alive and every later runcommand on that
            # console was dropped by MeshCentral, which never queues one.
            observed = self._command_port.run_command(
                node_ref=node_ref, command=ps, timeout_seconds=None,
                cancel_probe=cancelled, phase_observer=phase,
                dispatch_id=getattr(dispatch, "dispatch_id", None),
                # #7214: the user-mode client is ~7KB of multi-line PowerShell. Sent
                # as the console body it left the agent's ``powershell -command -``
                # waiting on an unclosed block and never returned, so the console
                # held the agent's single command slot and every later PC command was
                # dropped (measured 2026-11-07..08, ~19 hours). File delivery stages
                # it and runs it with ``-File``; the SYSTEM lane is untouched.
                deliver_as_file=True,
            )
        except Exception:
            self._trace_command(dispatch, "error", started, error_type="port_failed")
            return OracleMeshExecutionOutcome(termination="exited", exit_code=1,
                body=_json.dumps({"ok": False, "error_code": USER_SESSION_UNAVAILABLE, "detail": "helper pipe is not available"}, ensure_ascii=True).encode("utf-8"))
        term = getattr(observed, "termination", "no_reply")
        out = getattr(observed, "output", b"") or b""
        if not isinstance(out, (bytes, bytearray)): out = str(out).encode("utf-8","replace")
        self._trace_command(dispatch, "result", started, termination=term, output_bytes=len(bytes(out)))
        if term == "cancelled":
            # The #7107 helper ended the user child when this dispatch was stopped.
            return OracleMeshExecutionOutcome(termination="cancelled", exit_code=None, body=b"")
        # #7182b: the wrapped client ends with cmdlet-only work, so PowerShell
        # records no $LASTEXITCODE and the sentinel prints an empty value
        # (``no_exit_code``). That is a completed answer, not a silent console:
        # the reply frame carries the command's own exit code. Requiring the
        # literal string "exited" here turned the fix for the missing sentinel
        # into the same "helper pipe is not available" reply.
        if term not in ("exited", "no_exit_code"):
            return OracleMeshExecutionOutcome(termination="exited", exit_code=1,
                body=_json.dumps({"ok": False, "error_code": USER_SESSION_UNAVAILABLE, "detail": "helper pipe is not available"}, ensure_ascii=True).encode("utf-8"))
        return self._parse_user_helper_outcome(bytes(out))

    def _execute_command(
        self, dispatch: OracleMeshDispatch, *, additional_cancel_probe=None
    ) -> OracleMeshExecutionOutcome:
        if getattr(dispatch, "user_mode", False):
            return self._execute_user_mode_command(dispatch, additional_cancel_probe=additional_cancel_probe)
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

        owner_cancel = self._cancel_probe(dispatch)
        def cancelled():
            return (callable(additional_cancel_probe) and additional_cancel_probe()) or owner_cancel()

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
                cancel_probe=cancelled,
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
        if op == "type":
            # The row names the value, never carries it. A claim without the
            # one-shot delivery is refused: typing a marker or a stale string
            # would be worse than not acting.
            text = _desktop_dispatch_text(dispatch)
            if text is None:
                return OracleMeshExecutionOutcome(
                    termination="not_executed", exit_code=None, body=b"",
                    note="the typed text was not delivered",
                )
            arg = text
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
            "background": dispatch.background,
            "owner_ref": dispatch.owner_ref,
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
                background=meta.get("background", False),
                owner_ref=meta.get("owner_ref"),
            )
            if dispatch.kind not in ("read", "command", "desktop"):
                raise ValueError("pending kind is unknown")
            if dispatch.max_bytes is not None and (
                dispatch.kind != "read"
                or isinstance(dispatch.max_bytes, bool)
                or not isinstance(dispatch.max_bytes, int)
                or dispatch.max_bytes < 1
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
        persist_started = time.monotonic()
        persist_error = self._persist_pending()
        # The read_ok→submit gap suspects the persist (it owns the fsyncs): one
        # phase line in the existing format names how long it took. It carries
        # no values and no paths — instrumentation only, never a behaviour.
        self._trace_command(dispatch, "persisted", persist_started)
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
            return self._active_by_node.get(node_ref) or next(
                (job for job, node in self._active_background.items() if node == node_ref), None
            )

    def active_dispatch_ids(self) -> tuple[str, ...]:
        """Every dispatch this connector is running, on any PC.

        The line sweep protects exactly these. Nothing here is inferred from a
        transcript or a log line, so a PC cannot talk its way out of being skipped.
        """
        with self._active_lock:
            return tuple(self._active_by_node.values()) + tuple(self._active_background)

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
            if dispatch.background:
                self._active_background[dispatch_id] = node_ref
            else:
                self._active_by_node[node_ref] = dispatch_id

    def _clear_active(self, dispatch: OracleMeshDispatch) -> None:
        node_ref = str(getattr(dispatch, "node_ref", "") or "")
        with self._active_lock:
            self._active_background.pop(dispatch.dispatch_id, None)
            if self._active_by_node.get(node_ref) == str(
                getattr(dispatch, "dispatch_id", "") or ""
            ):
                self._active_by_node.pop(node_ref, None)

    @staticmethod
    def _background_owner(dispatch):
        if not dispatch.background or not dispatch.owner_ref:
            raise OracleMeshChannelRefused("background owner is required")
        return json.dumps([dispatch.owner_ref, dispatch.node_ref, dispatch.run_id], separators=(",", ":"))

    def _background_manager(self):
        if self._background_jobs is None:
            import os
            from padiem_ai_core.pc_background import RemoteBackgroundJobs
            directory = self._pending_dir_path()
            if directory is None:
                raise OracleMeshChannelRefused("background receipt directory is not configured")
            self._background_jobs = RemoteBackgroundJobs(
                os.path.join(directory, "background-jobs"), runner=self._run_background_dispatch
            )
        return self._background_jobs

    def _node_execution_lock(self, dispatch):
        with self._active_lock:
            return self._node_execution_locks.setdefault(dispatch.node_ref, threading.Lock())

    def _run_background_dispatch(self, payload, *, cancel_probe):
        dispatch = OracleMeshDispatch(**payload)
        renewer = self.start_lease_renewal(dispatch)
        # #7107: a user-mode command runs in the logged-in user's session, not
        # on the SYSTEM console, so it must not hold the per-node console lock.
        # A long user command would otherwise block the next SYSTEM dispatch
        # even though the two lanes cannot collide.
        lock = None if getattr(dispatch, "user_mode", False) else self._node_execution_lock(dispatch)
        acquired = lock is None
        try:
            # Keep this claim alive while another command owns the same PC.
            # Other PCs have independent locks and can continue executing.
            while not acquired:
                acquired = lock.acquire(timeout=0.2)
                if not acquired and (cancel_probe() or self._cancel_probe(dispatch)()):
                    return {"termination": "cancelled", "exit_code": None, "body": b""}
            if cancel_probe() or self._cancel_probe(dispatch)():
                return {"termination": "cancelled", "exit_code": None, "body": b""}
            self._mark_active(dispatch)
            if dispatch.kind == "command":
                outcome = self._execute_command(dispatch, additional_cancel_probe=cancel_probe)
            else:
                outcome = self._execute_read(dispatch)
            return {"termination": outcome.termination, "exit_code": outcome.exit_code,
                    "body": outcome.body}
        finally:
            self._clear_active(dispatch)
            if acquired and lock is not None:
                lock.release()
            if renewer is not None:
                renewer.set()

    def _ack_background_delivery(self, dispatch):
        if dispatch.background and self._pending is None:
            self._background_manager().acknowledge(
                dispatch.dispatch_id, owner=self._background_owner(dispatch)
            )

    def _completed_background(self):
        import os
        directory = self._pending_dir_path()
        if self._background_jobs is None and not (
            directory and os.path.isdir(os.path.join(directory, "background-jobs"))
        ):
            return None
        for record, body in self._background_manager().pending_results():
            dispatch = OracleMeshDispatch(**record["dispatch"])
            outcome = OracleMeshExecutionOutcome(
                termination=record["termination"], exit_code=record["exit_code"], body=body
            )
            return dispatch, outcome
        return None

    def run_once(self) -> Optional[dict[str, Any]]:
        """Retry a held result if any; otherwise poll, execute and submit."""
        if self._pending is not None:
            self.last_round = ROUND_SKIPPED
            dispatch = self._pending[0]
            report = self.resend_pending_result()
            self._ack_background_delivery(dispatch)
            return report
        completed = self._completed_background()
        if completed is not None:
            self.last_round = ROUND_WORKED
            dispatch, outcome = completed
            report = self._with_line_observations(self.submit(dispatch, outcome))
            self._ack_background_delivery(dispatch)
            return report
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
        # The claim is its own instant. A round used to be observable only at its ends,
        # so "the queue was slow to hand this over" and "this PC took that long to
        # answer" printed as one number and the journal could not tell them apart.
        self._trace_command(dispatch, "claimed", time.monotonic())
        if dispatch.background:
            from dataclasses import asdict
            started = self._background_manager().start(
                asdict(dispatch), owner=self._background_owner(dispatch)
            )
            return {"ok": True, "background": True, **started}
        renewer = self.start_lease_renewal(dispatch)
        self._mark_active(dispatch)
        try:
            with self._node_execution_lock(dispatch):
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

    def start_drive_reporting(self, source):
        """Use the production queue channel; no Broker or PC grant is involved."""
        from .local_agent_mesh_drive_reporter import MeshDriveReporter

        if self._queue_origin is None:
            return None
        reporter = getattr(self, "_drive_reporter", None)
        if reporter is None:
            reporter = MeshDriveReporter(post=self._post, source=source,
                                         may_report=self._claim_gate)
            self._drive_reporter = reporter
        reporter.start()
        return reporter

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
    "IDLE_HEARTBEAT_SECONDS",
    "MAX_COMMAND_BYTES",
    "MAX_READ_BYTES",
    "PC_FILE_ERROR_PREFIX",
    "PC_FILE_READ_FAILED_MARKER",
    "PC_FILE_READ_REFUSED_MARKER",
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
    edge_secret: Optional[str] = None,
    meshctrl_js: str,
    login_user: str,
    password_provider: Callable[[], str],
    mesh_url: str = "wss://127.0.0.1:4443",
    work_dir: str | None = None,
    timeout_seconds: int | None = None,
    channel_timeout_seconds: int = CHANNEL_SOCKET_TIMEOUT_SECONDS,
    idle_poll_max_seconds: int = IDLE_POLL_MAX_SECONDS,
    claim_gate: Optional[Callable[[], bool]] = None,
    presence_provider: Optional[Callable[[], Any]] = None,
    pairing_provider: Optional[Callable[[], Any]] = None,
    presence_round_begin: Optional[Callable[[], None]] = None,
    read_single_roundtrip: bool = True,
    # #7065: opt-in run-as-user. False keeps the argv an existing host already sends.
    run_as_user: bool = False,
    run_as_user_only: bool = False,
    login_key_file: str | None = None,
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
        login_key_file=login_key_file,
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
        # #7065: off unless the deployment asks for it, so the argv an existing
        # host sends is unchanged.
        run_as_user=run_as_user,
        run_as_user_only=run_as_user_only,
        login_key_file=login_key_file,
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
        edge_secret=edge_secret,
        read_port=read_port,
        command_port=command_port,
        desktop_port=desktop_port,
        timeout_seconds=timeout_seconds,
        channel_timeout_seconds=channel_timeout_seconds,
        idle_poll_max_seconds=idle_poll_max_seconds,
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


def channel_refusal_line(exc: BaseException) -> str:
    """One journal line for a refused exchange: the message as it always was, plus the leg.

    #5881's cutover is why the leg is on this line at all. While the queue and the Worker
    printed the same words, an edge bot block was indistinguishable from a Worker failure,
    and the lane had to be diagnosed by comparing two databases. The message text itself is
    unchanged - operators and monitors already read it - and neither an origin nor any
    credential belongs on this line.
    """
    leg = getattr(exc, "leg", None)
    return "oracle-mesh-executor channel refusal: %s%s" % (
        exc, " leg=" + leg if leg in ("chat", "queue") else "")


def main(environ: Optional[dict[str, str]] = None) -> int:
    """Startup entrypoint: one poll/execute/submit loop on the Oracle host.

    Configuration is environment-only and bounded:
      ORACLE_MESH_CHAT_ORIGIN       https origin of the Chat worker (bare), or
                                    this host's loopback Chat origin
                                    (http://127.0.0.1:8798). Any other http origin
                                    is still refused: only a literal loopback
                                    address can be reached without TLS.
      ORACLE_MESH_QUEUE_ORIGIN      optional; the origin of the 컴2 PC queue that
                                    answers the claim lane on this host
                                    (http://127.0.0.1:8797). Unset, every leg —
                                    including the claim — goes to the Worker, which
                                    is the state before the queue and the rollback.
                                    The result submission always goes to the Worker.
      ORACLE_MESH_CHANNEL_SECRET_FILE  mode-0600 file holding the channel secret
      ORACLE_MESH_EDGE_SECRET_FILE  required only when the Chat origin is this
                                    host's loopback: the mode-0600 file holding the
                                    COM2 edge proof secret, read once at start and
                                    never printed. It signs the four
                                    x-padiem-edge-* headers the Chat host's edge
                                    middleware demands before any route runs.
      ORACLE_MESH_MESHCTRL_JS       path to the official meshctrl.js
      ORACLE_MESH_LOGIN_USER        MeshCentral operator account
      ORACLE_MESH_PASSWORD_FILE     mode-0600 file holding the operator password
      ORACLE_MESH_LOGIN_KEY_FILE    optional mode-0600 file holding the MeshCentral
                                    server login key; when set, presence signs in with
                                    it instead of the password (2FA stays on)
      ORACLE_MESH_URL               optional, default wss://127.0.0.1:4443
      ORACLE_MESH_WORK_DIR          optional scratch directory
      ORACLE_MESH_POLL_SECONDS      optional interval after a refused channel, default 5
      ORACLE_MESH_IDLE_POLL_MAX_SECONDS
                                    optional ceiling on the idle wait, default 10 with a queue origin,
                                    otherwise 60;
                                    one reproduces the pre-backoff cadence verbatim
      ORACLE_MESH_READ_TIMEOUT_SECONDS
                                    optional PC-step deadline in seconds, default
                                    30; the read and desktop lanes wait four times
                                    this, exactly as they did before 2026-10-17
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
                # 2FA stays on the operator account: when the deployment names a
                # login-key file, presence signs in with it instead of a password.
                login_key_file=(
                    env.get("ORACLE_MESH_LOGIN_KEY_FILE", "").strip() or None
                ),
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

        queue_origin = env.get("ORACLE_MESH_QUEUE_ORIGIN", "").strip() or None
        default_idle_max = COM2_IDLE_POLL_MAX_SECONDS if queue_origin else IDLE_POLL_MAX_SECONDS
        raw_idle_max = env.get("ORACLE_MESH_IDLE_POLL_MAX_SECONDS")
        if raw_idle_max is None:
            idle_max = default_idle_max
        else:
            try:
                idle_max = int(raw_idle_max)
                if idle_max <= 0:
                    raise ValueError
                idle_max = min(idle_max, 300)
            except (ValueError, TypeError):
                idle_max = default_idle_max
                print(f"oracle-mesh-executor: invalid ORACLE_MESH_IDLE_POLL_MAX_SECONDS; using default {default_idle_max}",
                      file=sys.stderr)

        chat_origin = need("ORACLE_MESH_CHAT_ORIGIN")
        # Read once, at start: the edge secret is deployment material, and a
        # rotation is a supervised restart like every other file on this list.
        # Nothing about it is ever printed — the only signal is the refusal below.
        edge_file = env.get(EDGE_SECRET_FILE_ENV, "").strip()
        edge_secret = (
            _read_secret_file(edge_file, "edge proof secret")
            if _is_loopback_channel_origin(chat_origin) else None
        )

        executor = make_oracle_mesh_executor(
            chat_origin=chat_origin,
            channel_secret=_read_secret_file(
                need("ORACLE_MESH_CHANNEL_SECRET_FILE"), "channel secret"
            ),
            queue_origin=queue_origin,
            edge_secret=edge_secret,
            idle_poll_max_seconds=idle_max,
            meshctrl_js=need("ORACLE_MESH_MESHCTRL_JS"),
            login_user=need("ORACLE_MESH_LOGIN_USER"),
            password_provider=password_provider,
            mesh_url=mesh_url,
            work_dir=env.get("ORACLE_MESH_WORK_DIR", "").strip() or None,
            # A deployment that names no deadline gets the pre-2026-10-17 one.
            # Sending None instead refused every PC read inside the port before
            # the official client was ever started.
            timeout_seconds=_step_timeout_seconds(env),
            presence_provider=presence_provider,
            pairing_provider=pairing_provider,
            presence_round_begin=beat.begin_round if beat is not None else None,
            read_single_roundtrip=_single_roundtrip_enabled(env),
            # #7065: opt-in only. The connector keeps running its commands as the
            # agent account (LocalSystem on Windows) unless the deployment says
            # otherwise, and an enabled flag is a request the PC may still ignore
            # on Windows (see the port's note).
            run_as_user=str(env.get("PADIEM_MESH_RUN_AS_USER", "")).strip().lower()
            in {"1", "true"},
            run_as_user_only=str(env.get("PADIEM_MESH_RUN_AS_USER_ONLY", "")).strip().lower()
            in {"1", "true"},
        )
        idle = max(1, min(int(env.get("ORACLE_MESH_POLL_SECONDS", "5") or 5), 300))
        # The idle ceiling is readable for the operator who wants to weigh the old
        # cadence against the new one on a live host: one is exactly the behaviour every
        # executor had before this schedule existed.
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

    if queue_origin:
        from .local_agent_mesh_drive_inventory import MeshDriveInventorySource

        executor.start_drive_reporting(MeshDriveInventorySource(
            meshctrl_js=need("ORACLE_MESH_MESHCTRL_JS"), mesh_url=mesh_url,
            login_user=need("ORACLE_MESH_LOGIN_USER"),
            password_provider=password_provider,
        ))

    #: The wait before the next ask. It grows only across rounds the lane itself
    #: answered empty, and resets the moment the queue produces work.
    gap = IDLE_POLL_BASE_SECONDS
    #: None, not 0.0: monotonic() is seconds since boot, and a fresh container can
    #: report less than the heartbeat interval.
    idle_reported_at = None
    while True:
        try:
            result = executor.run_once()
        except OracleMeshChannelRefused as exc:
            # Bounded: the message never carries dispatch content or secrets. A
            # channel that will not complete rounds is not a quiet queue, so the wait
            # returns to the base and the interval the operator named.
            print(channel_refusal_line(exc), file=sys.stderr)
            gap = IDLE_POLL_BASE_SECONDS
            time.sleep(idle)
            continue
        if result is None:
            # The lane held this request five seconds and answered "nothing waiting",
            # or this host asked for nothing at all. Only the first of those says
            # something about the queue, and only for it does the next ask wait
            # longer - a skipped round goes back to the base so a failover landing on
            # this host starts claiming on the next second.
            if (executor.last_round == ROUND_IDLE
                    and (idle_reported_at is None
                         or time.monotonic() - idle_reported_at >= IDLE_HEARTBEAT_SECONDS)):
                print("oracle-mesh-executor poll idle", flush=True)
                idle_reported_at = time.monotonic()
            time.sleep(gap)
            gap = (IDLE_POLL_BASE_SECONDS if executor.last_round != ROUND_IDLE
                   else min(gap * 2, executor.idle_poll_max_seconds))
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
