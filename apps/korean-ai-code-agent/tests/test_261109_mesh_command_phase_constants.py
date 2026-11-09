"""Command journal phase names are one vocabulary, byte-identical output.

``docs/operations/PC_COMMAND_LIFECYCLE_20261109.md`` §5 PR-1: the phase names
were string literals scattered across the executor and the command port. They
now live in ``kagent.local_agent_mesh_command_phases``. Two things must not
move:

* the printed names — ``scripts/ops/pc_read_measure.py`` matches the journal
  line ``oracle-mesh-command phase=<name> ts=... elapsed_ms=...`` and pins its
  stage breakdown on ``claimed`` and ``submit``, and operators grep these
  names on the hosts. The frozen literals below are copied from the source
  before the constants existed; if a constant's value drifts, this file says
  so instead of a host journal discovering it.
* the line shape — the same regex must keep parsing a line the executor
  actually prints today.
"""
from __future__ import annotations

import base64
import contextlib
import importlib.util
import io
import json
import re
import unittest
from pathlib import Path

from kagent import local_agent_mesh_command_phases as phases
from kagent.local_agent_oracle_mesh_executor import (
    OracleMeshDispatch,
    OracleMeshExecutor,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

#: The phase vocabulary exactly as it was before the constants existed.
#: Source of truth: the pre-refactor literals in
#: ``local_agent_oracle_mesh_executor.py`` (``_trace_command`` call sites) and
#: ``local_agent_meshcentral_command_port.py`` (``phase(...)`` call sites).
FROZEN_PHASE_NAMES = frozenset({
    "claimed", "start", "spawn", "reply", "result", "refused", "error",
    "persisted", "submit", "timeout", "cancel", "silent_timeout", "idle_reap",
    "idle_reap_refused", "idle_reap_cleared", "line_stalled", "line_retry",
    "line_gate_closed", "line_gate_busy", "line_probe", "line_probe_refused",
    "line_probe_unobserved", "line_cleared", "line_running", "session_lane",
    "session_fallback", "session_open_refused", "session_open_timeout",
    "cancel_kill", "cancel_kill_unverified", "cancel_kill_refused",
})


def _dispatch(**extra) -> OracleMeshDispatch:
    fields = dict(
        dispatch_id="dsp_" + "a" * 32,
        nonce="n",
        node_ref="node-ref-261109",
        file_path="command",
        command_id="cmd-261109",
        run_id="run-261109",
        kind="command",
        command_text="whoami",
    )
    fields.update(extra)
    return OracleMeshDispatch(**fields)


class _PhasePort:
    """Plays the command port: fires the observed phases, then answers."""

    def __init__(self, phases_to_fire=("spawn", "reply")) -> None:
        self.phases_to_fire = tuple(phases_to_fire)
        self.calls = []

    def run_command(self, **kwargs):
        self.calls.append(kwargs)
        observer = kwargs.get("phase_observer")
        for name in self.phases_to_fire:
            if callable(observer):
                observer(name)
        out = type("O", (), {})()
        out.termination = "exited"
        out.exit_code = 0
        out.output = b"ok"
        out.line_blocked = 0
        out.line_cleared = 0
        return out


def _executor(port) -> OracleMeshExecutor:
    ex = object.__new__(OracleMeshExecutor)
    ex._command_port = port
    ex._desktop_port = None
    ex._poll_url = ex._submit_url = ex._busy_url = ex._cancel_url = ""
    ex._line_blocked = ex._line_cleared = 0
    ex._post = lambda *a, **k: (200, {"ok": True, "working": True})
    ex._cancel_probe = lambda d: (lambda: False)
    ex._line_guard = lambda d: (lambda: False)
    ex.active_dispatch_ids = lambda: ()
    return ex


def _phases(journal: str) -> list[str]:
    return [
        line.split(" phase=")[1].split(" ")[0]
        for line in journal.splitlines() if " phase=" in line
    ]


class TestPhaseConstants(unittest.TestCase):
    def test_every_constant_equals_its_pre_refactor_literal(self):
        frozen = {
            "CLAIMED": "claimed", "START": "start", "SPAWN": "spawn",
            "REPLY": "reply", "RESULT": "result", "REFUSED": "refused",
            "ERROR": "error", "PERSISTED": "persisted", "SUBMIT": "submit",
            "TIMEOUT": "timeout", "CANCEL": "cancel",
            "CANCEL_KILL_PREFIX": "cancel_kill_", "CANCEL_KILL": "cancel_kill",
            "CANCEL_KILL_UNVERIFIED": "cancel_kill_unverified",
            "CANCEL_KILL_REFUSED": "cancel_kill_refused",
            "SILENT_TIMEOUT": "silent_timeout", "IDLE_REAP": "idle_reap",
            "IDLE_REAP_REFUSED": "idle_reap_refused",
            "IDLE_REAP_CLEARED": "idle_reap_cleared",
            "LINE_STALLED": "line_stalled", "LINE_RETRY": "line_retry",
            "LINE_GATE_CLOSED": "line_gate_closed",
            "LINE_GATE_BUSY": "line_gate_busy", "LINE_PROBE": "line_probe",
            "LINE_PROBE_REFUSED": "line_probe_refused",
            "LINE_PROBE_UNOBSERVED": "line_probe_unobserved",
            "LINE_CLEARED": "line_cleared", "LINE_RUNNING": "line_running",
            "SESSION_LANE": "session_lane",
            "SESSION_FALLBACK": "session_fallback",
            "SESSION_OPEN_REFUSED": "session_open_refused",
            "SESSION_OPEN_TIMEOUT": "session_open_timeout",
            "COMMAND_JOURNAL_MARKER": "oracle-mesh-command",
        }
        for name, literal in frozen.items():
            self.assertEqual(getattr(phases, name), literal, name)

    def test_all_phases_covers_the_frozen_vocabulary_exactly(self):
        self.assertEqual(frozenset(phases.ALL_PHASES), FROZEN_PHASE_NAMES)

    def test_no_phase_literal_is_left_at_a_call_site(self):
        for rel in ("local_agent_oracle_mesh_executor.py",
                    "local_agent_meshcentral_command_port.py"):
            src = (REPO_ROOT / "apps/korean-ai-code-agent/src/kagent" / rel
                   ).read_text(encoding="utf-8")
            self.assertNotIn('phase("', src, rel)
            self.assertNotIn('_trace_command(dispatch, "', src, rel)


class TestJournalOutputUnchanged(unittest.TestCase):
    def test_a_system_round_prints_the_same_names_in_the_same_shape(self):
        port = _PhasePort(phases_to_fire=(phases.SPAWN, phases.REPLY))
        ex = _executor(port)
        journal = io.StringIO()
        with contextlib.redirect_stderr(journal):
            ex.execute(_dispatch())
        seen = _phases(journal.getvalue())
        # claimed is traced by run_once, not execute; start..result is the
        # execute() span. Names and order are exactly what the hosts grep.
        self.assertEqual(seen, ["start", "spawn", "reply", "result"])
        for line in journal.getvalue().splitlines():
            self.assertTrue(
                re.match(r"oracle-mesh-command phase=\S+ ts=\S+ "
                         r"elapsed_ms=\d+ dispatch_id=\S+", line), line)

    def test_the_claim_and_submit_phases_keep_their_names(self):
        port = _PhasePort()
        ex = _executor(port)
        journal = io.StringIO()
        with contextlib.redirect_stderr(journal):
            ex._trace_command(_dispatch(), phases.CLAIMED, 0.0)
            ex._trace_command(_dispatch(), phases.SUBMIT, 0.0)
        seen = _phases(journal.getvalue())
        self.assertEqual(seen, ["claimed", "submit"])

    def test_user_mode_round_journals_the_same_spine(self):
        helper = json.dumps({
            "request_id": "req_" + "0" * 32, "status": "ok", "exit_code": 0,
            "stdout_b64": base64.b64encode(b"limone\r\n").decode(),
            "stderr_b64": "", "duration_ms": 5,
        }).encode()
        port = _PhasePort(phases_to_fire=(phases.SPAWN, phases.REPLY))
        port.__class__ = type("P", (_PhasePort,), {})  # keep the same fake
        ex = _executor(port)
        journal = io.StringIO()
        with contextlib.redirect_stderr(journal):
            ex.execute(_dispatch(user_mode=True, device_id="dev_" + "c" * 32,
                                 command_text=json.dumps({
                                     "shell": "whoami", "command": "whoami",
                                     "cwd": None, "timeout_seconds": 30,
                                     "distro": None})))
        seen = _phases(journal.getvalue())
        self.assertEqual(seen, ["start", "spawn", "reply", "result"])


class TestMeasureParserStillReadsTheLine(unittest.TestCase):
    def test_pc_read_measure_phase_regex_parses_a_line_built_from_constants(self):
        spec = importlib.util.spec_from_file_location(
            "pc_read_measure",
            REPO_ROOT / "scripts/ops/pc_read_measure.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        port = _PhasePort(phases_to_fire=(phases.SPAWN,))
        ex = _executor(port)
        journal = io.StringIO()
        with contextlib.redirect_stderr(journal):
            ex._trace_command(_dispatch(), phases.START, 0.0)
        line = next(l for l in journal.getvalue().splitlines()
                    if " phase=" in l)

        match = module._PHASE_RE.search(line)
        self.assertIsNotNone(match, line)
        self.assertEqual(match.group(1), phases.START)
        self.assertEqual(match.group(3).isdigit(), True)

        # The stage breakdown pins "claimed" and "submit" by exact name; the
        # constants must keep producing those names.
        for pinned in (phases.CLAIMED, phases.SUBMIT):
            probe = (f"{phases.COMMAND_JOURNAL_MARKER} phase={pinned} "
                     "ts=2026-11-09T00:00:00+00:00 elapsed_ms=7")
            m = module._PHASE_RE.search(probe)
            self.assertIsNotNone(m, probe)
            self.assertEqual(m.group(1), pinned)


if __name__ == "__main__":
    unittest.main()
