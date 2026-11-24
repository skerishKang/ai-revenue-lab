"""#8634 — read the Mesh Agent build date from the server's node document.

MeshCentral's ``getsysinfo`` handler answers from the stored ``si<nodeid>``
document only: it never sends a command to the PC and never writes to it
(``meshuser.js``, ``serverCommandGetSysInfo``). The agent put
``process.versions`` in ``hardware.agentvers`` when it connected
(``agents/meshcore.js``: ``results.hardware.agentvers = process.versions``),
so ``hardware.agentvers.commitDate`` is the build date the operations-centre
table wants. The installed executable does not carry it.

This module owns the request shape, the response parsing, the conversion to
the one bounded UTC stamp and the value-free failure codes. The wire itself is
the executor's already authenticated ``control.ashx`` socket; no new
credential, port, device command or device write is introduced.

Authentication on that socket is confirmed by the server's own greeting
(``serverinfo``/``userinfo`` from ``meshuser.js``), the same proof the existing
PC command path uses. An ``authcookie`` is a relay-tunnel credential, not an
authentication confirmation for a server-document read. See
:class:`kagent.local_agent_meshcentral_process_port.MeshCentralProcessSocket`.
"""
from __future__ import annotations

import json
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from padiem_ai_core.pc_device_identity import is_pc_device_id
from padiem_ai_core.pc_helper_ready import validate_mesh_agent_version

GETSYSINFO_ACTION = "getsysinfo"
#: The server echoes ``tag`` on both success and refusal, so one exchange can
#: be correlated without forwarding any node or operator value to a log.
SYSINFO_TAG_PREFIX = "padiem-sysinfo-"

_ISO_STAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})\Z")
_BUILD_STAMP = re.compile(
    r"(20[0-9]{2})-([A-Z][a-z]{2})-([0-9]{2}) "
    r"([0-9]{2}):([0-9]{2}):([0-9]{2})([+-])([0-9]{2})([0-9]{2})\Z")
_MONTHS = {name: number for number, name in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}

#: Every ``None`` has its own stage code. No exception text, path, node value
#: or response body is ever printed by this lane. The ``sysinfo_*`` codes are
#: wire stages: they name why the authenticated socket failed before a usable
#: stored node document reached the parser. ``sysinfo_error`` is only the
#: last-resort bucket for an exception no wire stage claims.
SYSINFO_REASON_CODES = frozenset({
    "observed", "no_answer", "invalid_answer", "wrong_action", "wrong_tag",
    "info_unavailable", "info_not_stored", "info_node_unavailable",
    "no_hardware", "no_agentvers", "no_commit_date",
    "format_mismatch",
    "sysinfo_nodeid", "sysinfo_denied", "sysinfo_transport",
    "sysinfo_timeout", "sysinfo_no_reply", "sysinfo_shape", "sysinfo_error",
})

#: Named wire-stage codes. These doubles as the whole text of a wire failure,
#: so no response body, node id, host, credential or exception text can leak.
SYSINFO_NODEID = "sysinfo_nodeid"
#: The operator header was rejected, or the server never sent its authenticated
#: ``serverinfo``/``userinfo`` greeting. No credential or refusal body is kept.
SYSINFO_DENIED = "sysinfo_denied"
SYSINFO_TRANSPORT = "sysinfo_transport"
SYSINFO_TIMEOUT = "sysinfo_timeout"
SYSINFO_NO_REPLY = "sysinfo_no_reply"
SYSINFO_SHAPE = "sysinfo_shape"
SYSINFO_ERROR = "sysinfo_error"


class MeshCentralSysInfoReadFailure(Exception):
    """A wire-stage failure carrying only a value-free reason code.

    The exception's sole argument is its code. The authenticated socket layer
    raises this instead of letting transport, deadline or refusal exceptions
    escape to the reporter, where they used to collapse into ``sysinfo_error``.
    """

    def __init__(self, code: str) -> None:
        if code not in SYSINFO_REASON_CODES:
            raise ValueError("an unknown sysinfo failure code is not allowed")
        super().__init__(code)
        self.code = code


class MeshCentralSysInfoRefused(ValueError):
    """A malformed request; never carries a node value or a credential."""

    def __init__(self, message: str, code: str = SYSINFO_NODEID) -> None:
        super().__init__(message)
        self.code = code


def _checked_node_ref(node_ref: Any) -> str:
    if not is_pc_device_id(node_ref):
        raise MeshCentralSysInfoRefused("node_ref is not a device identity")
    return node_ref


def _checked_tag(tag: Any) -> str:
    if (not isinstance(tag, str) or not tag.startswith(SYSINFO_TAG_PREFIX)
            or len(tag) > 128 or any(ord(char) < 33 or ord(char) > 126 for char in tag)):
        raise MeshCentralSysInfoRefused("tag is not a bounded sysinfo tag", SYSINFO_SHAPE)
    return tag


def sysinfo_frame(node_ref: str, tag: str) -> dict[str, Any]:
    """The server-DB read, with ``nodeinfo`` for the stored node document.

    ``tag`` is added only so the echoed frame can be matched to this request.
    No PC command field, response id or write verb is present.

    Verified against MeshCentral's ``meshuser.js``
    ``serverCommandGetSysInfo`` (upstream master): the reply keeps
    ``action: 'getsysinfo'``, echoes ``tag`` and spreads the stored
    ``si<nodeid>`` document at the top level; ``nodeinfo: true`` adds ``node``
    and ``rights``. The handler does **not** echo ``responseid``, so sending
    one and matching on it would never correlate - ``tag`` is the only
    correlation key. A refusal answers ``noinfo: true, result: ...`` with the
    same action and tag.
    """
    return {
        "action": GETSYSINFO_ACTION,
        "nodeid": _checked_node_ref(node_ref),
        "tag": _checked_tag(tag),
        "nodeinfo": True,
    }


def new_sysinfo_tag() -> str:
    return SYSINFO_TAG_PREFIX + secrets.token_hex(8)


def _utc_stamp(moment: datetime) -> str:
    utc = moment.astimezone(timezone.utc)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"


def normalize_agent_commit_date(raw: Any) -> str | None:
    """Convert a known build-date form to the shared format, or refuse it.

    The stored value is normally already the bounded UTC stamp. A Mesh agent
    also writes an ISO-8601 instant with an offset (the console's own
    ``new Date(versions.commitDate).toISOString()`` path) or the Windows build
    stamp from its version resource. Only those three closed forms are
    converted; any other text is refused rather than guessed at. The result
    always passes the shared ``pc_helper_ready`` validator.
    """
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    direct = validate_mesh_agent_version(text)
    if direct is not None:
        return direct
    candidate = None
    if _ISO_STAMP.fullmatch(text):
        try:
            parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
            if parsed.tzinfo is not None:
                candidate = _utc_stamp(parsed)
        except (ValueError, OverflowError):
            return None
    else:
        match = _BUILD_STAMP.fullmatch(text)
        if match is not None:
            year, month, day, hour, minute, second, sign, offset_hour, offset_minute = match.groups()
            if month not in _MONTHS:
                return None
            try:
                offset = timedelta(hours=int(offset_hour), minutes=int(offset_minute))
                if sign == "-":
                    offset = -offset
                built = datetime(int(year), _MONTHS[month], int(day), int(hour), int(minute),
                                 int(second), tzinfo=timezone(offset))
            except (ValueError, TypeError, OverflowError):
                return None
            candidate = _utc_stamp(built)
    return validate_mesh_agent_version(candidate)


def agent_version_from_sysinfo(answer: Any, tag: str) -> tuple[str | None, str]:
    """Take only ``hardware.agentvers.commitDate`` out of one correlated reply.

    The full node document can contain customer hardware detail. It is read
    here only to reach that one field; nothing else is forwarded or logged.
    """
    checked_tag = _checked_tag(tag)
    if answer is None:
        return None, "no_answer"
    if not isinstance(answer, Mapping):
        return None, "invalid_answer"
    if answer.get("action") != GETSYSINFO_ACTION:
        return None, "wrong_action"
    if answer.get("tag") != checked_tag:
        return None, "wrong_tag"
    if answer.get("noinfo") is True or isinstance(answer.get("result"), str):
        return None, "info_unavailable"
    hardware = answer.get("hardware")
    if not isinstance(hardware, Mapping):
        return None, "no_hardware"
    agentvers = hardware.get("agentvers")
    if not isinstance(agentvers, Mapping):
        return None, "no_agentvers"
    raw = agentvers.get("commitDate")
    if not isinstance(raw, str) or not raw.strip():
        return None, "no_commit_date"
    value = normalize_agent_commit_date(raw)
    if value is None:
        return None, "format_mismatch"
    return value, "observed"


def probe_sysinfo_absence(socket: Any, frame: Mapping[str, Any],
                          answer: Mapping[str, Any], deadline: float) -> str:
    """Disambiguate the upstream identical noinfo replies without a PC command.

    meshuser.js serverCommandGetSysInfo returns Invalid device id both when
    GetNodeWithRights/DEVICEDETAILS fails and when the si document is absent.
    serverCommandGetNetworkInfo has the same rights gate but returns netif:null
    even with no if document. Use that server-only read on this same session.
    Discard all network data; only a bounded reason code leaves this function.
    A failed probe is inconclusive, never evidence of missing information.
    """
    unresolved = "info_unavailable"
    if answer.get("noinfo") is not True or answer.get("result") != "Invalid device id":
        return unresolved
    requested, resolved = frame.get("nodeid"), answer.get("nodeid")
    if not is_pc_device_id(requested) or not is_pc_device_id(resolved):
        return unresolved
    if not resolved.startswith("node/"):
        return unresolved
    if requested != resolved and ("/" in requested or requested != resolved.rsplit("/", 1)[-1]):
        return unresolved
    tag = new_sysinfo_tag()
    try:
        if time.monotonic() >= deadline:
            return unresolved
        socket.send_text(json.dumps({
            "action": "getnetworkinfo", "nodeid": requested, "tag": tag,
        }, separators=(",", ":")))
        while time.monotonic() < deadline:
            message = socket.recv(deadline)
            if message is None:
                break
            opcode, payload = message
            if opcode != 0x1:
                continue
            reply = json.loads(payload.decode("utf-8"))
            if not isinstance(reply, dict) or reply.get("action") != "getnetworkinfo":
                continue
            if reply.get("nodeid") != resolved:
                continue
            if reply.get("noinfo") is True:
                if reply.get("tag") == tag and reply.get("result") == "Invalid device id":
                    return "info_node_unavailable"
                continue
            # Upstream successful getnetworkinfo does not echo tag. This is
            # the sole such request on the fresh socket; match the node and
            # response shape, and reject an explicit mismatching tag.
            if ("tag" not in reply or reply["tag"] == tag) and (
                    "netif" in reply and "netif2" in reply and "result" not in reply
                    and "noinfo" not in reply):
                return "info_not_stored"
    except Exception:
        pass
    return unresolved


def sysinfo_failure_code(exc: BaseException) -> str:
    """Classify a raised exception by type only, never by its text or target.

    ``MeshCentralSysInfoReadFailure`` already carries a bounded code from the
    socket layer. A bare timeout, connect or broken-pipe error is classified
    here as a backstop for injected transports that do not use that class.
    Anything else keeps the generic code, still with no value attached.
    """
    if isinstance(exc, (MeshCentralSysInfoReadFailure, MeshCentralSysInfoRefused)):
        return exc.code
    if isinstance(exc, TimeoutError):
        return SYSINFO_TIMEOUT
    if isinstance(exc, OSError):
        return SYSINFO_TRANSPORT
    return SYSINFO_ERROR


class MeshCentralSysInfoPort:
    """One bounded server-document read, over the caller's authenticated socket.

    ``send`` is a bound method of the executor's existing ``control.ashx``
    socket. This object builds the frame and discards the whole reply except
    the one bounded value and a stage code.
    """

    def __init__(self, *, send: Callable[[dict[str, Any]], Mapping[str, Any] | None]) -> None:
        if not callable(send):
            raise ValueError("a sysinfo socket send is required")
        self._send = send

    def read_commit_date(self, node_ref: str) -> tuple[str | None, str]:
        """Return the bounded build stamp and a value-free reason code.

        Each wire failure becomes its own code instead of a shared
        ``sysinfo_error``: an uncanonical node reference, an authentication or
        permission refusal, a private-tunnel transport fault, a deadline, a
        closed socket with no correlated reply, or a non-frame reply. Nothing
        from the exception or the answer reaches the log.
        """
        tag = new_sysinfo_tag()
        try:
            frame = sysinfo_frame(node_ref, tag)
        except MeshCentralSysInfoRefused as exc:
            return None, exc.code
        try:
            answer = self._send(frame)
        except Exception as exc:
            return None, sysinfo_failure_code(exc)
        if answer is None:
            return None, SYSINFO_NO_REPLY
        return agent_version_from_sysinfo(answer, tag)


__all__ = [
    "GETSYSINFO_ACTION", "SYSINFO_REASON_CODES",
    "SYSINFO_NODEID", "SYSINFO_DENIED", "SYSINFO_TRANSPORT",
    "SYSINFO_TIMEOUT", "SYSINFO_NO_REPLY", "SYSINFO_SHAPE", "SYSINFO_ERROR",
    "MeshCentralSysInfoPort", "MeshCentralSysInfoReadFailure",
    "MeshCentralSysInfoRefused", "agent_version_from_sysinfo",
    "new_sysinfo_tag", "normalize_agent_commit_date", "sysinfo_frame",
    "sysinfo_failure_code",
]
