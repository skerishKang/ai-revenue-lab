"""261105 — every refused relay read has to say which refusal it was.

The guard's three refusals shared one fixed trace string, so the 11-05 outage
(a check that never ran) could not be told from a real link hit: the journal
said "reparse point below the granted root" six times and nothing else.
``_pc_reparse_check`` now returns ``(hit, reason, detail)`` and the trace carries
``local_hit`` / ``pc_hit`` / ``pc_no_marker`` / ``pc_check_error``.

The port fastens the same two shapes main already accepts: a run that exited,
and the cmdlet-only run where PowerShell leaves ``$LASTEXITCODE`` empty and the
port reports ``no_exit_code`` (measured on the real PC, 11-05 16:20). Both must
carry a verdict; anything else stays fail closed.

These tests build the *real* ``MeshCentralCommandOutcome``, so the field drift
that caused the outage (a slots dataclass has no ``body``) fails here first.
"""
from __future__ import annotations

import base64
import contextlib
import io
import json
import time
import unittest
from unittest import mock

from kagent.local_agent_meshcentral_command_port import MeshCentralCommandOutcome
from kagent.local_agent_oracle_mesh_executor import (
    OracleMeshDispatch, OracleMeshExecutor, PC_FILE_LINK_REFUSED_MARKER,
)

SECRET = "deployment-channel-secret-value-261105"
NODE = "k0pVCZx5VqYn8P9FW23CaqTNZWHGSlLASVKF1tqJTPRjRGBOhcTfgZbmfi$D62t1"
ROOT = "C:\\"
FILE_PATH = "C:\\Windows\\win.ini"
BODY = b"file-bytes-that-must-not-cross-on-a-refusal"


def _marker(hit: bool) -> bytes:
    payload = base64.b64encode(json.dumps({"hit": hit}).encode()).decode()
    return ("PADIEM_PC_REPARSE=" + payload + "\n").encode()


class _ReadPort:
    """The real read port answers with bytes when the guard lets a read pass."""

    def __init__(self, body: bytes = BODY):
        self.body = body
        self.calls = 0

    def read_bytes(self, *, node_ref, file_path, timeout_seconds=60, max_bytes=None):  # noqa: D102
        del node_ref, file_path, timeout_seconds, max_bytes
        self.calls += 1
        return self.body


class _CommandPort:
    """Answers with a genuine ``MeshCentralCommandOutcome``, as the port does."""

    def __init__(self, *, output=b"", termination="exited", raises=None, delay=0.0):
        self.output = output
        self.termination = termination
        self.raises = raises
        self.delay = delay
        self.script = None
        self.timeout = None

    def run_command(self, *, node_ref, command, timeout_seconds=30, **kwargs):  # noqa: D102
        del node_ref, kwargs
        self.script = command
        self.timeout = timeout_seconds
        if self.delay:
            time.sleep(self.delay)
        if self.raises is not None:
            raise self.raises
        return MeshCentralCommandOutcome(
            termination=self.termination,
            exit_code=0 if self.termination == "exited" else None,
            output=self.output,
        )


class PcReparseReasonTests(unittest.TestCase):
    """One relay read with only the guard's answer varied."""

    def _dispatch(self) -> OracleMeshDispatch:
        return OracleMeshDispatch(
            dispatch_id="dsp_pc_reparse_1",
            nonce="nonce-261105",
            node_ref=NODE,
            file_path=FILE_PATH,
            command_id="cmd.pc.reparse.1",
            run_id="chat_pcq_925cfc301234567890abcdef12345678",
            granted_root=ROOT,
        )

    def _run(self, command_port, read_port=None):
        read_port = read_port or _ReadPort()
        executor = OracleMeshExecutor(
            chat_origin="https://chat.padiem.net",
            channel_secret=SECRET,
            read_port=read_port,
            command_port=command_port,
        )
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            outcome = executor.execute(self._dispatch())
        return outcome, stderr.getvalue(), read_port

    def _refused(self, outcome):
        return outcome.body == PC_FILE_LINK_REFUSED_MARKER.encode("utf-8")

    def test_the_command_outcome_has_output_and_no_body(self):
        """The shape the guard must read, asserted on the real class itself."""
        outcome = MeshCentralCommandOutcome(termination="exited", exit_code=0,
                                           output=b"x")
        self.assertTrue(hasattr(outcome, "output"))
        self.assertFalse(hasattr(outcome, "body"))

    def test_an_exited_clear_walk_lets_the_read_through(self):
        outcome, trace, read_port = self._run(_CommandPort(output=_marker(False)))
        self.assertEqual(outcome.body, BODY)
        self.assertEqual(read_port.calls, 1)
        self.assertNotIn("phase=link_refused", trace)

    def test_a_no_exit_code_clear_walk_lets_the_read_through(self):
        """Real PC shape: cmdlets only, so ``$LASTEXITCODE`` is empty."""
        outcome, trace, read_port = self._run(
            _CommandPort(output=_marker(False), termination="no_exit_code"))
        self.assertEqual(outcome.body, BODY)
        self.assertEqual(read_port.calls, 1)
        self.assertNotIn("phase=link_refused", trace)

    def test_a_hit_refuses_as_a_pc_hit(self):
        outcome, trace, read_port = self._run(_CommandPort(output=_marker(True)))
        self.assertTrue(self._refused(outcome))
        self.assertEqual(read_port.calls, 0, "다운로드가 먼저 나가면 안 된다")
        self.assertIn("phase=link_refused", trace)
        self.assertIn("reason=pc_hit", trace)

    def test_a_no_exit_code_hit_still_refuses_as_a_pc_hit(self):
        outcome, trace, _ = self._run(
            _CommandPort(output=_marker(True), termination="no_exit_code"))
        self.assertTrue(self._refused(outcome))
        self.assertIn("reason=pc_hit", trace)

    def test_a_missing_marker_refuses_as_pc_no_marker(self):
        outcome, trace, _ = self._run(_CommandPort(output=b"some other console line\n"))
        self.assertTrue(self._refused(outcome))
        self.assertIn("reason=pc_no_marker", trace)

    def test_a_marker_without_a_verdict_refuses_as_pc_check_error(self):
        payload = base64.b64encode(json.dumps({"hit": "yes"}).encode()).decode()
        outcome, trace, _ = self._run(
            _CommandPort(output=("PADIEM_PC_REPARSE=" + payload + "\n").encode()))
        self.assertTrue(self._refused(outcome))
        self.assertIn("reason=pc_check_error", trace)
        self.assertIn("detail=hit_not_bool", trace)

    def test_a_scrambled_marker_refuses_as_pc_check_error(self):
        outcome, trace, _ = self._run(
            _CommandPort(output=b"PADIEM_PC_REPARSE=not-base64!\n"))
        self.assertTrue(self._refused(outcome))
        self.assertIn("reason=pc_check_error", trace)

    def test_a_channel_exception_refuses_with_its_class(self):
        outcome, trace, _ = self._run(_CommandPort(raises=ValueError("channel down")))
        self.assertTrue(self._refused(outcome))
        self.assertIn("reason=pc_check_error", trace)
        self.assertIn("detail=ValueError", trace)

    def test_a_console_that_never_finished_fails_closed(self):
        outcome, trace, _ = self._run(
            _CommandPort(output=_marker(False), termination="no_reply"))
        self.assertTrue(self._refused(outcome))
        self.assertIn("reason=pc_check_error", trace)
        self.assertIn("detail=termination=no_reply", trace)

    def test_a_local_hit_is_named_local_hit(self):
        """The executor's own filesystem answered: no PC check, own reason."""
        with mock.patch(
            "kagent.local_agent_oracle_mesh_executor.walk_hits_reparse_point",
            return_value=True,
        ):
            outcome, trace, read_port = self._run(_CommandPort(output=_marker(False)))
        self.assertTrue(self._refused(outcome))
        self.assertEqual(read_port.calls, 0)
        self.assertIn("reason=local_hit", trace)

    def test_the_refusal_trace_carries_the_walk_time(self):
        """The guard's own cost has to reach the line; it used to read 0 ms."""
        outcome, trace, _ = self._run(_CommandPort(output=_marker(True), delay=0.05))
        self.assertTrue(self._refused(outcome))
        elapsed = [part for part in trace.split() if part.startswith("elapsed_ms=")]
        self.assertTrue(elapsed, trace)
        self.assertGreaterEqual(int(elapsed[0].split("=", 1)[1]), 10, trace)

    def test_the_walk_is_bounded_and_names_the_pc_node(self):
        port = _CommandPort(output=_marker(False))
        self._run(port)
        self.assertEqual(port.timeout, 30)
        self.assertIn("PADIEM_PC_REPARSE", port.script)
        self.assertIn("$root = 'C:\\';", port.script)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
