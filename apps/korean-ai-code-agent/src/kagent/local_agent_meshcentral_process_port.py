"""#4139 — the agent's own process verbs, as a stop lane (off until observed).

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

Two of its fields are still unobserved on a real PC - whether a record carries a parent
pid, and whether ``cmd`` is a command line or only an image name. That is why the flag
defaults off and why the rules below refuse to guess: see
docs/architecture/PADIEM_CONNECTOR_NATIVE_PROCESS_LANE_4139_20261029.md section 5, and the
read-only probe in scripts/ops/mesh_process_lane_probe.js.

The socket is injected (``ask``), as every port in this package does: one request frame in,
the correlated reply out, or ``None`` when the caller's communication bound ended first.
Nothing in this module can reach a machine by itself.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from .contracts import ContractError

#: The only three verbs this lane may send. `pskill` is the one that changes anything on
#: the PC, and `stop()` reaches it only with a pid that came from this lane's own `ps`.
PS_TYPE = "ps"
PSINFO_TYPE = "psinfo"
PSKILL_TYPE = "pskill"
ALLOWED_FRAME_TYPES = frozenset({PS_TYPE, PSINFO_TYPE, PSKILL_TYPE})
#: The label the agent appends to its log line. The web UI passes the process command line
#: here (views/default.handlebars:11039) - the agent uses only the part before the `|` for
#: anything that matters (agents/meshcore.js:1544-1547) - so a fixed word travels instead
#: of a customer's command.
PSKILL_LABEL = "padiem-dispatch"
#: Key names that would make a subtree computable. Matched against names only: a value on
#: a customer's PC is private text and is never inspected for a field name.
_PARENT_FIELD = re.compile(r"parent|ppid", re.IGNORECASE)

#: What one stop produced. Only CONFIRMED says the PC is finished with.
CONFIRMED = "confirmed"
STILL_RUNNING = "still_running"
NO_TARGET = "no_target"
LANE_UNANSWERED = "lane_unanswered"
VERDICTS = frozenset({CONFIRMED, STILL_RUNNING, NO_TARGET, LANE_UNANSWERED})


class MeshCentralProcessLaneRefused(ValueError):
    """One refusal of this lane. Never carries a process record or a command line."""


@dataclass(frozen=True, slots=True)
class ProcessStopReport:
    """The stop as the lane saw it: which pids it addressed, and what came back."""

    verdict: str
    dispatch_id: str
    targets: tuple[int, ...] = ()
    killed: tuple[int, ...] = ()
    remaining: tuple[int, ...] = ()
    #: False when the records carry no parent field, so only the matched pid was
    #: addressed and a child of it may still be running.
    tree: bool = True
    notes: Sequence[str] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.verdict not in VERDICTS:
            raise ContractError("the stop verdict is one of four words")

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
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise MeshCentralProcessLaneRefused("a process id must be a positive number")
    return pid


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
    """End one pid, and only a pid this lane's own `ps` produced.

    `stop()` takes its numbers from `parse_process_table` and nothing else, so a value
    that came from a log, a guess or customer text cannot be built here.
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
    trusted (`views/default.handlebars:10844-10849`). Keys that are not plain numbers are
    dropped for the same reason - they cannot be addressed by `pskill`.
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
        if not re.fullmatch(r"\d{1,9}", text) or type(record) is not dict:
            continue
        table[int(text)] = record
    return table


def parent_field(table: Mapping[int, Mapping[str, Any]]) -> str | None:
    """The key name a parent would be filed under, or ``None``.

    Whether such a field exists at all is one of the two open observations, so every
    caller must be able to act on ``None`` - `subtree_pids` does.
    """
    for record in table.values():
        for name in record:
            if _PARENT_FIELD.search(str(name)):
                return str(name)
    return None


def dispatch_target_pids(table: Mapping[int, Mapping[str, Any]], dispatch_id: str) -> tuple[int, ...]:
    """The pids whose record names this dispatch's own marker file.

    That marker name is the only thing this lane matches on: this connector writes it
    (`padiem-dispatch-<dispatch_id>.pid`), the command stamps it as its first act, and it
    is not customer text. If `cmd` turns out to carry only the image name, this finds
    nothing and the stop answers `no_target` - a truthful answer, not something to paper
    over with start times or process-name patterns.
    """
    needle = "padiem-dispatch-" + dispatch_id + ".pid"
    return tuple(sorted(
        pid for pid, record in table.items()
        if isinstance(record.get("cmd"), str) and needle in record["cmd"]
    ))


def subtree_pids(table: Mapping[int, Mapping[str, Any]], roots: Sequence[int],
                 field_name: str | None) -> tuple[tuple[int, ...], bool]:
    """Every pid descending from a root, deepest first - when a parent link exists.

    `pskill` is one pid (`process.kill(parseInt(pid))`, agents/meshcore.js:1548) while the
    terminal stop it replaces was ``taskkill /T /F``. Without a parent field the subtree
    cannot be computed, so this returns the roots alone and says ``tree=False``: the report
    then states that a child may still be running. The alternatives that would need
    customer text - start times, image names, command-line patterns - are deliberately not
    implemented.
    """
    if field_name is None:
        return tuple(sorted(set(roots), reverse=True)), False

    children: dict[int, list[int]] = {}
    for pid, record in table.items():
        try:
            parent = _checked_pid(record.get(field_name))
        except MeshCentralProcessLaneRefused:
            continue
        if parent != pid:
            children.setdefault(parent, []).append(pid)

    ordered: list[int] = []
    seen: set[int] = set()

    def walk(pid: int) -> None:
        if pid in seen:
            return
        seen.add(pid)
        for child in sorted(children.get(pid, ())):
            walk(child)
        ordered.append(pid)

    for root in sorted(set(roots)):
        walk(root)
    return tuple(ordered), True


class MeshCentralProcessLane:
    """`ps` / `pskill` / `ps`, with the verdict taken from the second `ps`.

    ``ask(frame)`` returns the correlated reply as a mapping, or ``None`` when the agent
    did not answer inside the caller's bound. Bounds belong to the socket layer, never
    invented here.
    """

    def __init__(self, *, node_ref: str,
                 ask: Callable[[dict[str, Any]], Mapping[str, Any] | None],
                 response_id: str) -> None:
        if not callable(ask):
            raise ContractError("the process lane needs an injected ask")
        self._node_ref = _checked_node_ref(node_ref)
        self._ask = ask
        self._response_id = _checked_response_id(response_id)
        self.sent_types: list[str] = []

    def processes(self) -> dict[int, dict[str, Any]] | None:
        """The device's process table, or ``None`` when the lane answered nothing."""
        reply = self._send(ps_frame(self._node_ref, self._response_id))
        if reply is None:
            return None
        if reply.get("type") != PS_TYPE:
            raise MeshCentralProcessLaneRefused("the answer was not a process table")
        return parse_process_table(reply.get("value"))

    def details(self, pid: int) -> Mapping[str, Any] | None:
        """One pid's detail record, or ``None`` when the lane answered nothing.

        The agent may answer with an empty object - its `psinfo` builds the detail set
        through a bundled module - so an empty answer is a possible truth rather than a
        transport fault (agents/meshcore.js:1505-1539).
        """
        reply = self._send(psinfo_frame(
            self._node_ref, _checked_pid(pid), self._response_id + "-info"))
        if reply is None:
            return None
        value = reply.get("value")
        return value if type(value) is dict else {}

    def stop(self, dispatch_id: str) -> ProcessStopReport:
        """End this dispatch's process, and prove it by reading the table again."""
        first = self.processes()
        if first is None:
            return ProcessStopReport(verdict=LANE_UNANSWERED, dispatch_id=dispatch_id,
                                     tree=False, notes=("the lane answered nothing",))

        targets = dispatch_target_pids(first, dispatch_id)
        if not targets:
            # Nothing matched, so nothing is killed. The alternative - ending what merely
            # looks like a shell - is how a connector ends a stranger's process.
            return ProcessStopReport(verdict=NO_TARGET, dispatch_id=dispatch_id, tree=False,
                                     notes=("no record named this dispatch",))

        ordered, tree = subtree_pids(first, targets, parent_field(first))
        killed: list[int] = []
        for pid in ordered:
            self._send(pskill_frame(self._node_ref, pid))
            killed.append(pid)

        second = self.processes()
        if second is None:
            return ProcessStopReport(
                verdict=LANE_UNANSWERED, dispatch_id=dispatch_id, targets=targets,
                killed=tuple(killed), tree=tree,
                notes=("the confirmation read answered nothing",),
            )
        remaining = tuple(pid for pid in killed if pid in second)
        notes: tuple[str, ...] = ()
        if not tree:
            notes = ("no parent field in the records, so only the matched pid was addressed",)
        return ProcessStopReport(
            verdict=CONFIRMED if not remaining else STILL_RUNNING,
            dispatch_id=dispatch_id, targets=targets, killed=tuple(killed),
            remaining=remaining, tree=tree, notes=notes,
        )

    def _send(self, frame: dict[str, Any]) -> Mapping[str, Any] | None:
        kind = frame.get("type")
        if kind not in ALLOWED_FRAME_TYPES:
            # There is no other door out of this class.
            raise MeshCentralProcessLaneRefused("the lane sends only its own three verbs")
        self.sent_types.append(str(kind))
        return self._ask(frame)
