"""#4139 — the agent's own process verbs, as a stop lane (off until the socket exists).

MeshCentral's web UI ends a process without typing into a shell. Its Stop button sends
one structured frame and the agent answers in data:

    send   {action:'msg', type:'pskill', nodeid, value:'<pid>|<label>'}
                                                    (views/default.handlebars:11040)
    agent  case 'msg' -> case 'pskill' -> process.kill(parseInt(pid))
                                                    (agents/meshcore.js:1542-1550)
    list   {action:'msg', type:'ps'} -> reply {type:'ps', value: JSON.stringify(plist)}
                                                    (agents/meshcore.js:1498-1504)
    detail {action:'msg', type:'psinfo', pid} -> {type:'psinfo', pid, value:{...}}
                                                    (agents/meshcore.js:1505-1539)

Three properties are why this lane exists. It never touches ``mesh.cmdchild``, so a
console held by a wedged command cannot block it. Its answer is a field, not a text to be
grepped - which is what owner standard 4 asks for and what a terminal never gave. And the
authority is the one the desktop already uses: the server route requires
``MESHRIGHT_REMOTECONTROL || MESHRIGHT_REMOTEVIEWONLY`` (meshuser.js:288) and the agent
demands its AgentConsole bit only of the *text* console (agents/meshcore.js:1360).

What the read-only capture on CGI-1 (2026-10-30) settled, and what the rules below now
follow from it:

* ``ps`` answers an object keyed by pid whose records carry **``cmd`` and ``pid`` only**
  (546 and 551 processes in two reads). **There is no parent field**, in ``ps`` or in
  ``psinfo``, so no family of a process can be computed here and none is attempted: a stop
  addresses the pids it was given and says so. A child of an addressed pid may survive, and
  the report states that instead of the code pretending otherwise.
* A stop's target is therefore **the pid this dispatch recorded** (`recorded_pid`, the
  number the command wrote into its own marker file). Matching the marker *name* inside
  ``cmd`` is kept as the auxiliary means only, used when no recorded pid was supplied, and
  the report carries which of the two decided the target.
* ``ps`` is slow on a real PC: 3,994 ms and 15,283 ms for the same request. The wait for
  that answer has a floor here (`PS_WAIT_FLOOR_SECONDS`), and no ceiling of the kind #5895
  removed belongs on this path - it is a communication bound on a read, not a limit on work.
* ``psinfo`` answers the .NET process object: 42 fields, among them ``StartInfo``,
  ``MachineName``, ``Name`` and ``ProcessName``. Those can carry a customer's command line
  and account text, so this lane reads **only the listed scalars** and drops everything it
  did not ask for, and nothing from a detail record is a log line.
* ``pid`` 0 is the idle process and the agent's own handler skips a falsy pid - a request
  for it never answers. 0 and any negative number are refused rather than sent.

The socket is injected (``ask``), as every port in this package does: one request frame in,
the correlated reply out, or ``None`` when the caller's communication bound ended first.
Nothing in this module can reach a machine by itself. What is missing before the flag can
be turned on is that socket layer, not an observation.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from .contracts import ContractError

#: The only three verbs this lane may send. `pskill` is the one that changes anything on
#: the PC, and `stop()` reaches it only with a pid this dispatch recorded or, failing that,
#: a pid whose record names this dispatch's own marker.
PS_TYPE = "ps"
PSINFO_TYPE = "psinfo"
PSKILL_TYPE = "pskill"
ALLOWED_FRAME_TYPES = frozenset({PS_TYPE, PSINFO_TYPE, PSKILL_TYPE})
#: The label the agent appends to its log line. The web UI passes the process command line
#: here (views/default.handlebars:11039) - the agent uses only the part before the `|` for
#: anything that matters (agents/meshcore.js:1544-1547) - so a fixed word travels instead
#: of a customer's command.
PSKILL_LABEL = "padiem-dispatch"

#: The wait for a `ps` answer. Measured on CGI-1 on 2026-10-30: 3,994 ms and 15,283 ms for
#: one request. A socket that promises less than the observed worst case will report a
#: healthy PC as a silent one, so the floor is a rule, not a tuning value.
PS_WAIT_SECONDS = 20.0
PS_WAIT_FLOOR_SECONDS = 15.0
#: What a detail read costs on the same PC: 1,455 ms and 1,702 ms.
PSINFO_WAIT_SECONDS = 8.0

#: The only `psinfo` fields this lane keeps. Every name here is a number or a flag; the
#: fields it drops are the ones that can hold a command line, an account or a machine name.
PSINFO_SCALARS = (
    "Id", "SessionId", "CPU", "Responding", "HandleCount",
    "WorkingSet64", "PeakWorkingSet64", "PrivateMemorySize64", "StartTime",
)

#: What one stop produced. Only CONFIRMED says the PC is finished with.
CONFIRMED = "confirmed"
STILL_RUNNING = "still_running"
NO_TARGET = "no_target"
LANE_UNANSWERED = "lane_unanswered"
VERDICTS = frozenset({CONFIRMED, STILL_RUNNING, NO_TARGET, LANE_UNANSWERED})

#: How a stop decided what to address. Recorded first, marker second, and `none` when it
#: addressed nothing at all.
BASIS_RECORDED_PID = "recorded_pid"
BASIS_CMD_MARKER = "cmd_marker"
BASIS_NONE = "none"
BASES = frozenset({BASIS_RECORDED_PID, BASIS_CMD_MARKER, BASIS_NONE})

#: Said on every report that touched a process, because it is always true of this agent:
#: the records carry no parent field, so a descendant of the addressed pid was never
#: computable and may still be running.
NO_TREE_NOTE = ("the records carry no parent field, so only the addressed pid was touched "
                "and a child of it may still be running")

#: A pid, once assigned, is at most nine digits on Windows; a key that is not a positive
#: number cannot be addressed by `pskill` and is dropped where it is read.
_PID_KEY = re.compile(r"[1-9][0-9]{0,8}\Z")


class MeshCentralProcessLaneRefused(ValueError):
    """One refusal of this lane. Never carries a process record or a command line."""


@dataclass(frozen=True, slots=True)
class ProcessStopReport:
    """The stop as the lane saw it: which pids it addressed, and what came back."""

    verdict: str
    dispatch_id: str
    #: `recorded_pid`, `cmd_marker` or `none` - which authority chose the target.
    basis: str = BASIS_NONE
    targets: tuple[int, ...] = ()
    killed: tuple[int, ...] = ()
    remaining: tuple[int, ...] = ()
    notes: Sequence[str] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.verdict not in VERDICTS:
            raise ContractError("the stop verdict is one of four words")
        if self.basis not in BASES:
            raise ContractError("the stop basis is one of three words")

    @property
    def confirmed(self) -> bool:
        return self.verdict == CONFIRMED


def _checked_node_ref(node_ref: Any) -> str:
    if not isinstance(node_ref, str) or not node_ref.strip():
        raise MeshCentralProcessLaneRefused("node_ref is required")
    trimmed = node_ref.strip()
    if len(trimmed) > 256 or any(ord(char) < 33 or ord(char) > 126 for char in trimmed):
        raise MeshCentralProcessLaneRefused("node_ref is not a device identifier")
    return trimmed


def _checked_response_id(response_id: Any) -> str:
    if not isinstance(response_id, str) or not response_id or len(response_id) > 128:
        raise MeshCentralProcessLaneRefused("response_id is required and bounded")
    return response_id


def _checked_pid(pid: Any) -> int:
    """A process id, or a refusal. 0 and negatives never leave this function.

    0 is the idle process and the agent's handler skips a falsy pid, so a request naming it
    is a request that cannot answer; a negative is not a pid on this platform at all.
    """
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise MeshCentralProcessLaneRefused("a process id must be a positive number")
    return pid


def _checked_wait(seconds: Any, floor: float) -> float:
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        raise MeshCentralProcessLaneRefused("a wait must be a number of seconds")
    value = float(seconds)
    if not value >= floor:
        raise MeshCentralProcessLaneRefused(
            "a wait for a process answer must not be shorter than the observed answer time"
        )
    return value


def ps_frame(node_ref: str, response_id: str) -> dict[str, Any]:
    """Ask what is running. Reads nothing and changes nothing."""
    return {
        "action": "msg", "type": PS_TYPE,
        "nodeid": _checked_node_ref(node_ref),
        "responseid": _checked_response_id(response_id),
    }


def psinfo_frame(node_ref: str, pid: int, response_id: str) -> dict[str, Any]:
    return {
        "action": "msg", "type": PSINFO_TYPE,
        "nodeid": _checked_node_ref(node_ref), "pid": _checked_pid(pid),
        "responseid": _checked_response_id(response_id),
    }


def pskill_frame(node_ref: str, pid: int) -> dict[str, Any]:
    """End one pid, and only a pid this lane was given or read from the table.

    `stop()` takes its numbers from the dispatch's own record and from
    `parse_process_table` and nothing else, so a value that came from a log, a guess or
    customer text cannot be built here.
    """
    return {
        "action": "msg", "type": PSKILL_TYPE,
        "nodeid": _checked_node_ref(node_ref),
        "value": f"{_checked_pid(pid)}|{PSKILL_LABEL}",
    }


def parse_process_table(value: Any) -> dict[int, dict[str, Any]]:
    """Read the agent's answer into ``{pid: record}``, on the first-party shape.

    The web UI's parser is the specification: the value is a JSON object keyed by process
    id, every record an object, and a record that is not an object is skipped rather than
    trusted (`views/default.handlebars:10844-10849`). Keys that are not a positive number
    are dropped for the same reason - they cannot be addressed by `pskill`, and 0 is the
    idle process, which the agent does not answer about.
    """
    if isinstance(value, (bytes, bytearray)):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            raise MeshCentralProcessLaneRefused("the process table is not text") from None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            raise MeshCentralProcessLaneRefused("the process table is not JSON") from None
    if type(value) is not dict:
        raise MeshCentralProcessLaneRefused("the process table is not an object")

    table: dict[int, dict[str, Any]] = {}
    for key, record in value.items():
        text = str(key)
        if not _PID_KEY.match(text) or type(record) is not dict:
            continue
        table[int(text)] = record
    return table


def marker_matched_pids(table: Mapping[int, Mapping[str, Any]], dispatch_id: str) -> tuple[int, ...]:
    """The pids whose record names this dispatch's own marker file - the auxiliary means.

    This is what a stop falls back on when the dispatch recorded no pid, and nothing else:
    the recorded pid is the authority, and a number read out of `cmd` text is not. That
    marker name is the only thing matched here - this connector writes it
    (`padiem-dispatch-<dispatch_id>.pid`), the command stamps it as its first act, and it is
    not customer text. Start times, image names and command-line patterns, which would all
    "guess instead", are deliberately not implemented: on the observed agent `cmd` holds one
    string per process and nothing identifies a descendant.
    """
    needle = "padiem-dispatch-" + dispatch_id + ".pid"
    return tuple(sorted(
        pid for pid, record in table.items()
        if isinstance(record.get("cmd"), str) and needle in record["cmd"]
    ))


def selected_details(record: Any) -> dict[str, Any]:
    """The listed scalars of one detail record, and nothing else.

    The observed answer is the .NET process object: 42 fields, of which `StartInfo`,
    `MachineName`, `Name` and `ProcessName` can carry a customer's command line or account
    text. Reading a detail record is allowed to return less than the PC sent; it is not
    allowed to forward what this lane never asked for.
    """
    if type(record) is not dict:
        return {}
    chosen: dict[str, Any] = {}
    for name in PSINFO_SCALARS:
        if name not in record:
            continue
        value = record[name]
        if value is None or isinstance(value, (bool, int, float, str)):
            chosen[name] = value
    return chosen


class MeshCentralProcessLane:
    """`ps` / `pskill` / `ps`, with the verdict taken from the second `ps`.

    ``ask(frame)`` returns the correlated reply as a mapping, or ``None`` when the agent
    did not answer inside the caller's bound. Bounds belong to the socket layer, never
    invented here - what this class does is refuse a bound that is shorter than the answer
    has been observed to take.
    """

    def __init__(self, *, node_ref: str,
                 ask: Callable[[dict[str, Any]], Mapping[str, Any] | None],
                 response_id: str,
                 ps_wait_seconds: float = PS_WAIT_SECONDS,
                 psinfo_wait_seconds: float = PSINFO_WAIT_SECONDS) -> None:
        if not callable(ask):
            raise ContractError("the process lane needs an injected ask")
        self._node_ref = _checked_node_ref(node_ref)
        self._ask = ask
        self._response_id = _checked_response_id(response_id)
        self.ps_wait_seconds = _checked_wait(ps_wait_seconds, PS_WAIT_FLOOR_SECONDS)
        self.psinfo_wait_seconds = _checked_wait(psinfo_wait_seconds, 1.0)
        self.sent_types: list[str] = []

    def processes(self) -> dict[int, dict[str, Any]] | None:
        """The device's process table, or ``None`` when the lane answered nothing."""
        reply = self._send(ps_frame(self._node_ref, self._response_id))
        if reply is None:
            return None
        if reply.get("type") != PS_TYPE:
            raise MeshCentralProcessLaneRefused("the answer was not a process table")
        return parse_process_table(reply.get("value"))

    def details(self, pid: int) -> dict[str, Any] | None:
        """A few scalars of one pid's detail record, or ``None`` when nothing answered.

        The agent may answer with an empty object - its `psinfo` builds the detail set
        through a bundled module - so an empty answer is a possible truth rather than a
        transport fault (agents/meshcore.js:1505-1539).
        """
        reply = self._send(psinfo_frame(
            self._node_ref, _checked_pid(pid), self._response_id + "-info"))
        if reply is None:
            return None
        return selected_details(reply.get("value"))

    def stop(self, dispatch_id: str,
             recorded_pid: int | None = None) -> ProcessStopReport:
        """End this dispatch's process, and prove it by reading the table again.

        `recorded_pid` is the number the dispatch wrote into its own marker file, and it is
        the authority. With no recorded pid the lane falls back to the marker name inside
        `cmd`, and if that matches nothing it addresses nothing and answers `no_target` -
        ending what merely looks like a shell is how a connector ends a stranger's process.
        """
        wanted = None if recorded_pid is None else _checked_pid(recorded_pid)
        first = self.processes()
        if first is None:
            return ProcessStopReport(verdict=LANE_UNANSWERED, dispatch_id=dispatch_id,
                                     notes=("the lane answered nothing",))

        if wanted is not None:
            if wanted not in first:
                # The recorded pid is not on the PC any more. That is the dispatch being
                # finished with, read from the table - not a frame this lane sent.
                return ProcessStopReport(
                    verdict=CONFIRMED, dispatch_id=dispatch_id, basis=BASIS_RECORDED_PID,
                    notes=("the recorded pid was not in the table", NO_TREE_NOTE),
                )
            targets: tuple[int, ...] = (wanted,)
            basis = BASIS_RECORDED_PID
        else:
            targets = marker_matched_pids(first, dispatch_id)
            basis = BASIS_CMD_MARKER
            if not targets:
                return ProcessStopReport(
                    verdict=NO_TARGET, dispatch_id=dispatch_id,
                    notes=("no record named this dispatch",),
                )

        killed: list[int] = []
        for pid in targets:
            self._send(pskill_frame(self._node_ref, pid))
            killed.append(pid)

        second = self.processes()
        if second is None:
            return ProcessStopReport(
                verdict=LANE_UNANSWERED, dispatch_id=dispatch_id, basis=basis,
                targets=targets, killed=tuple(killed),
                notes=("the confirmation read answered nothing", NO_TREE_NOTE),
            )
        remaining = tuple(pid for pid in killed if pid in second)
        return ProcessStopReport(
            verdict=CONFIRMED if not remaining else STILL_RUNNING,
            dispatch_id=dispatch_id, basis=basis, targets=targets,
            killed=tuple(killed), remaining=remaining,
            notes=(NO_TREE_NOTE,),
        )

    def _send(self, frame: dict[str, Any]) -> Mapping[str, Any] | None:
        kind = frame.get("type")
        if kind not in ALLOWED_FRAME_TYPES:
            # There is no other door out of this class.
            raise MeshCentralProcessLaneRefused("the lane sends only its own three verbs")
        self.sent_types.append(str(kind))
        return self._ask(frame)
