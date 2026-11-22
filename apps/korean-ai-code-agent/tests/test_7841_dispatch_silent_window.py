"""#7841 — the executor's silent bound never outlives the dispatch it belongs to.

The poll response already carries the dispatch's own ``expires_at``. The console
wait is now ``min(configured 600 s, dispatch remaining)``; a dispatch with no
deadline keeps the configured bound, which is the older-server path.
"""
from __future__ import annotations

import io
import time
import unittest
from contextlib import redirect_stderr
from datetime import datetime, timezone
from unittest import mock

from kagent import local_agent_meshcentral_command_port as port_module
from kagent.local_agent_meshcentral_command_port import (
    SILENT_TIMEOUT_REASON,
    MeshCentralCliCommandPort,
)
from kagent.local_agent_mesh_silent_window import (
    dispatch_remaining_seconds,
    dispatch_silent_wait_seconds,
)
from kagent.local_agent_oracle_mesh_executor import (
    OracleMeshDispatch,
    _dispatch_deadline_kwargs,
)

MESHCTRL = "meshctrl.js"
PASSWORD = "p" * 40
DISPATCH = "dsp_" + "a" * 32


class _SilentChild:
    """A console child that never answers and never exits."""

    def __init__(self):
        self.stdin = io.BytesIO()
        self.stderr = io.BytesIO()
        self.stdout = _EmptyStream()
        self.exit_code = None
        self.killed = False

    def poll(self):
        return self.exit_code

    def kill(self):
        self.killed = True
        self.exit_code = -9


class _EmptyStream:
    def fileno(self):
        raise OSError("not an OS pipe: a test double")

    def read(self, _size):
        return b""


def _port(popen):
    return MeshCentralCliCommandPort(
        command_runner=lambda *a, **k: None,
        meshctrl_js=MESHCTRL, login_user="padiemadmin",
        password_provider=lambda: PASSWORD, url="wss://127.0.0.1:4443",
        popen_factory=popen, pty_factory=lambda payload: None,
    )


def _run(port, **extra):
    phases = []
    with redirect_stderr(io.StringIO()):
        outcome = port.run_command(
            node_ref="node//X", command="whoami", timeout_seconds=None,
            dispatch_id=DISPATCH, phase_observer=phases.append, **extra,
        )
    return outcome, phases


class SilentWindowContract(unittest.TestCase):
    """#7994: the silent bound is a 60 s output budget, not a TTL.

    A dispatch whose lease outlives the budget must not hold a worker that long,
    and a talking command restarts the clock on every byte. The dispatch's own
    deadline no longer shortens the wait.
    """

    def test_a_dispatch_deadline_no_longer_caps_the_bound(self):
        now = 1_800_000_000.0
        # 30 s left, 600 s configured -> still the 60 s silence cap.
        bound = dispatch_silent_wait_seconds(
            "2027-01-15T08:00:30Z", base_seconds=600.0, now=now,
        )
        self.assertEqual(bound, 60.0)

    def test_the_longer_remaining_time_caps_at_60s(self):
        now = 1_800_000_000.0
        bound = dispatch_silent_wait_seconds(
            "2027-01-15T09:00:00Z", base_seconds=600.0, now=now,
        )
        self.assertEqual(bound, 60.0)

    def test_no_deadline_caps_at_60s(self):
        self.assertEqual(dispatch_silent_wait_seconds(None, base_seconds=600.0), 60.0)
        self.assertEqual(
            dispatch_silent_wait_seconds("not-a-time", base_seconds=600.0), 60.0)
        self.assertEqual(
            dispatch_silent_wait_seconds(
                "2027-01-15T08:00:00Z", base_seconds=600.0, now=1_800_000_000.0),
            60.0,
            "an already-expired deadline must not become the 0=forever value",
        )

    def test_a_smaller_configured_bound_still_wins(self):
        self.assertEqual(dispatch_silent_wait_seconds(None, base_seconds=20.0), 20.0)

    def test_remaining_time_is_read_from_the_poll_deadline(self):
        self.assertAlmostEqual(
            dispatch_remaining_seconds("2027-01-15T08:00:30Z", now=1_800_000_000.0),
            30.0, places=3,
        )
        self.assertIsNone(dispatch_remaining_seconds(None))
        self.assertIsNone(dispatch_remaining_seconds("junk"))

    def test_a_silent_child_ends_at_the_configured_bound(self):
        # #7994: the silent bound is an output budget (env-configured here to a
        # short value so the test is fast), not the dispatch's own TTL. A silent
        # console is ended with the bounded reason, and the dispatch window does
        # not shorten or extend it.
        import os
        children = []

        def popen(argv, **kwargs):
            child = _SilentChild()
            children.append(child)
            return child

        expires_at = datetime.now(timezone.utc).timestamp() + 600
        stamp = datetime.fromtimestamp(expires_at, timezone.utc).isoformat()
        os.environ["PADIEM_MESH_SILENT_WAIT_SECONDS"] = "0.2"
        try:
            started = time.monotonic()
            outcome, phases = _run(
                _port(popen),
                dispatch_expires_at=stamp,
            )
            elapsed = time.monotonic() - started
        finally:
            os.environ.pop("PADIEM_MESH_SILENT_WAIT_SECONDS", None)

        self.assertEqual(outcome.termination, "timed_out")
        self.assertIsNone(outcome.exit_code)
        self.assertEqual(outcome.output, SILENT_TIMEOUT_REASON.encode("ascii"))
        self.assertIn("silent_timeout", phases)
        self.assertLess(elapsed, 5.0)
        self.assertTrue(children[0].killed)
        self.assertLess(elapsed, 2.0)

    def test_the_executor_hands_the_deadline_to_a_port_that_accepts_it(self):
        dispatch = OracleMeshDispatch(
            dispatch_id=DISPATCH, nonce="n", node_ref="node//X",
            file_path="f", command_id="c", run_id="r",
            kind="command", command_text="whoami",
            expires_at="2027-01-15T08:00:30Z",
        )

        class _ModernPort:
            def run_command(self, **kwargs):
                return None

        class _LegacyPort:
            def run_command(self, node_ref, command):
                return None

        assert _dispatch_deadline_kwargs(_ModernPort(), dispatch) == {
            "dispatch_expires_at": "2027-01-15T08:00:30Z",
        }
        # An older port keeps its exact call; no unknown keyword reaches it.
        assert _dispatch_deadline_kwargs(_LegacyPort(), dispatch) == {}


    def test_a_silent_timeout_ends_the_wedged_remote_shell(self):
        # #7994: a silent console's child can outlive the local client, so the
        # executor ends the remote shell (best effort) before closing here. The
        # next command then starts in a fresh session.
        import os
        children = []

        def popen(argv, **kwargs):
            child = _SilentChild()
            children.append(child)
            return child

        stopped = []
        os.environ["PADIEM_MESH_SILENT_WAIT_SECONDS"] = "0.2"
        try:
            port = _port(popen)
            with mock.patch.object(
                port, "kill_command_process",
                side_effect=lambda **kw: stopped.append(kw),
            ):
                outcome, phases = _run(port)
        finally:
            os.environ.pop("PADIEM_MESH_SILENT_WAIT_SECONDS", None)

        self.assertEqual(outcome.termination, "timed_out")
        self.assertIn("silent_timeout", phases)
        # The stop was asked for this dispatch's own node before the client died.
        self.assertEqual(len(stopped), 1)
        self.assertEqual(stopped[0]["dispatch_id"], DISPATCH)
        self.assertEqual(stopped[0]["node_ref"], "node//X")
        # The local client was still ended.
        self.assertTrue(children[0].killed)

    def test_no_deadline_keeps_the_configured_silent_wait(self):
        def popen(argv, **kwargs):
            return _SilentChild()

        with mock.patch.dict(
            "os.environ", {"PADIEM_MESH_SILENT_WAIT_SECONDS": "0.2"}
        ):
            outcome, phases = _run(_port(popen))

        self.assertEqual(outcome.termination, "timed_out")
        self.assertIn("silent_timeout", phases)
        # The reason code is present on this path too; the bound itself came
        # from the existing environment setting, not from a dispatch deadline.
        self.assertEqual(outcome.output, SILENT_TIMEOUT_REASON.encode("ascii"))


class RecursiveSearchSilentCapContract(unittest.TestCase):
    """#8048: a recursive search raises the silence cap above 60 s so the
    silence bound does not cut a legitimately long (180 s) walk in half."""

    def test_a_recursive_search_cap_raises_the_ceiling(self):
        bound = dispatch_silent_wait_seconds(
            None, base_seconds=600.0, cap_seconds=190.0)
        self.assertEqual(bound, 190.0)

    def test_the_default_cap_is_unchanged_without_an_override(self):
        self.assertEqual(
            dispatch_silent_wait_seconds(None, base_seconds=600.0), 60.0)

    def test_a_non_positive_cap_falls_back_to_the_default(self):
        self.assertEqual(
            dispatch_silent_wait_seconds(None, base_seconds=600.0, cap_seconds=0.0),
            60.0)
        self.assertEqual(
            dispatch_silent_wait_seconds(None, base_seconds=600.0, cap_seconds=-5.0),
            60.0)

    def test_a_smaller_configured_bound_still_wins_over_the_raised_cap(self):
        # The configured base is the floor; the cap only lowers it.
        self.assertEqual(
            dispatch_silent_wait_seconds(None, base_seconds=20.0, cap_seconds=190.0),
            20.0)


class StopPidFromTranscript(unittest.TestCase):
    """#8048: the stop must recover the console pid from the final read slice."""

    def test_handshake_in_the_final_chunk_is_recovered(self):
        from kagent.local_agent_meshcentral_pid_handshake import stop_pid_from_transcript
        from kagent.local_agent_meshcentral_pid_handshake import (
            PID_HANDSHAKE_PREFIX, checked_pid_token,
        )
        token = checked_pid_token("a" * 16)
        chunk = (PID_HANDSHAKE_PREFIX + token + "=4242\n").encode("ascii")
        self.assertEqual(
            stop_pid_from_transcript(None, [b"", chunk], token), 4242)

    def test_an_already_resolved_pid_is_kept(self):
        from kagent.local_agent_meshcentral_pid_handshake import stop_pid_from_transcript
        self.assertEqual(
            stop_pid_from_transcript(99, [b"anything"], "a" * 16), 99)

    def test_no_token_keeps_none(self):
        from kagent.local_agent_meshcentral_pid_handshake import stop_pid_from_transcript
        self.assertIsNone(stop_pid_from_transcript(None, [b"x"], None))
