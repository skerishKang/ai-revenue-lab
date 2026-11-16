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
    def test_a_dispatch_deadline_caps_the_configured_bound(self):
        now = 1_800_000_000.0
        # 30 s left, 600 s configured -> 30 s.
        bound = dispatch_silent_wait_seconds(
            "2027-01-15T08:00:30Z", base_seconds=600.0, now=now,
        )
        self.assertAlmostEqual(bound, 30.0, places=3)

    def test_the_longer_remaining_time_keeps_the_configured_bound(self):
        now = 1_800_000_000.0
        bound = dispatch_silent_wait_seconds(
            "2027-01-15T09:00:00Z", base_seconds=600.0, now=now,
        )
        self.assertEqual(bound, 600.0)

    def test_no_deadline_keeps_the_older_600s_bound(self):
        self.assertEqual(dispatch_silent_wait_seconds(None, base_seconds=600.0), 600.0)
        self.assertEqual(
            dispatch_silent_wait_seconds("not-a-time", base_seconds=600.0), 600.0)
        self.assertEqual(
            dispatch_silent_wait_seconds(
                "2027-01-15T08:00:00Z", base_seconds=600.0, now=1_800_000_000.0),
            600.0,
            "an already-expired deadline must not become the 0=forever value",
        )

    def test_remaining_time_is_read_from_the_poll_deadline(self):
        self.assertAlmostEqual(
            dispatch_remaining_seconds("2027-01-15T08:00:30Z", now=1_800_000_000.0),
            30.0, places=3,
        )
        self.assertIsNone(dispatch_remaining_seconds(None))
        self.assertIsNone(dispatch_remaining_seconds("junk"))

    def test_a_short_dispatch_window_ends_the_silent_wait_at_that_window(self):
        children = []

        def popen(argv, **kwargs):
            child = _SilentChild()
            children.append(child)
            return child

        expires_at = datetime.now(timezone.utc).timestamp() + 0.2
        stamp = datetime.fromtimestamp(expires_at, timezone.utc).isoformat()
        started = time.monotonic()
        outcome, phases = _run(
            _port(popen),
            dispatch_expires_at=stamp,
        )
        elapsed = time.monotonic() - started

        self.assertEqual(outcome.termination, "timed_out")
        self.assertIsNone(outcome.exit_code)
        self.assertEqual(outcome.output, SILENT_TIMEOUT_REASON.encode("ascii"))
        self.assertIn("silent_timeout", phases)
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
