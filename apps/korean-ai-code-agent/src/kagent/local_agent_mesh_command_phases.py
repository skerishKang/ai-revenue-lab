"""Command journal phase names — one source, byte-identical output.

The command journal line ``oracle-mesh-command phase=<name> ts=...`` is an
operational contract: ``scripts/ops/pc_read_measure.py`` matches it with
``oracle-mesh-(?:read|command) phase=(\\S+) ts=(\\S+) elapsed_ms=(\\d+)`` and
pins the stages on ``claimed`` and ``submit``, and operators grep these exact
names on the hosts. Before this module the names were string literals
scattered across the executor and the command port (recorded in
``docs/operations/PC_COMMAND_LIFECYCLE_20261109.md`` §5 PR-1), so a typo in
one call site would silently break the stage breakdown.

This module holds the names and nothing else. Every constant's value is the
literal that was already in the journal before the constants existed; the
contract test pins that equality so a rename here is a visible decision, not
a drift.
"""
from __future__ import annotations

#: The marker a command journal line starts with.
COMMAND_JOURNAL_MARKER = "oracle-mesh-command"

CLAIMED = "claimed"
START = "start"
SPAWN = "spawn"
REPLY = "reply"
RESULT = "result"
REFUSED = "refused"
ERROR = "error"
PERSISTED = "persisted"
SUBMIT = "submit"
TIMEOUT = "timeout"
CANCEL = "cancel"
CANCEL_KILL_PREFIX = "cancel_kill_"
CANCEL_KILL = "cancel_kill"
CANCEL_KILL_UNVERIFIED = "cancel_kill_unverified"
CANCEL_KILL_REFUSED = "cancel_kill_refused"
SILENT_TIMEOUT = "silent_timeout"
IDLE_REAP = "idle_reap"
IDLE_REAP_REFUSED = "idle_reap_refused"
IDLE_REAP_CLEARED = "idle_reap_cleared"
LINE_STALLED = "line_stalled"
LINE_RETRY = "line_retry"
LINE_GATE_CLOSED = "line_gate_closed"
LINE_GATE_BUSY = "line_gate_busy"
LINE_PROBE = "line_probe"
LINE_PROBE_REFUSED = "line_probe_refused"
LINE_PROBE_UNOBSERVED = "line_probe_unobserved"
LINE_CLEARED = "line_cleared"
LINE_RUNNING = "line_running"
SESSION_LANE = "session_lane"
SESSION_FALLBACK = "session_fallback"
SESSION_OPEN_REFUSED = "session_open_refused"
SESSION_OPEN_TIMEOUT = "session_open_timeout"

#: Every phase name the command journal may print, in one tuple so a test can
#: pin the whole vocabulary at once. ``CANCEL_KILL`` phases are composed:
#: the stop attempt appends the stop verdict to ``CANCEL_KILL_PREFIX``.
ALL_PHASES = (
    CLAIMED, START, SPAWN, REPLY, RESULT, REFUSED, ERROR, PERSISTED, SUBMIT,
    TIMEOUT, CANCEL, SILENT_TIMEOUT, IDLE_REAP, IDLE_REAP_REFUSED,
    IDLE_REAP_CLEARED, LINE_STALLED, LINE_RETRY, LINE_GATE_CLOSED,
    LINE_GATE_BUSY, LINE_PROBE, LINE_PROBE_REFUSED, LINE_PROBE_UNOBSERVED,
    LINE_CLEARED, LINE_RUNNING, SESSION_LANE, SESSION_FALLBACK,
    SESSION_OPEN_REFUSED, SESSION_OPEN_TIMEOUT, CANCEL_KILL,
    CANCEL_KILL_UNVERIFIED, CANCEL_KILL_REFUSED,
)
