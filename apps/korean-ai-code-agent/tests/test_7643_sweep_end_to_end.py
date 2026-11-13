"""#7643 - the whole abandoned sweep, run once on real Windows PowerShell.

The PowerShell verdict functions already run against made-up inputs in
``test_7564_executor_marker_validation.py``. This file runs what was rewritten
around them end to end - the process table, the marker scan, the owner gate,
the verdict application and the answer frame - because a string assertion cannot
show that the assembled script still parses and does what it says.

Only the ``abandoned`` scope runs here: it ends a process only when a marker in
the isolated temp folder names it, and every marker is written by this test for
a process this test spawned. ``held`` and ``idle_console`` are never run - the
child scope ends processes the agent spawned, which is exactly what a test must
not do to the machine it runs on.

(가) trusted marker, matching start time: the process ends and the marker goes.
(나) trusted marker, different start time: the process survives, the marker goes.
(다) untrusted marker owner: neither the process nor the marker is touched.
(라) the ``__PADIEM_SWEEP__`` frame parses with the right found/killed values.
(마) an old two-line marker (no start time) is handled like (가).

(가)(나)(마) need the marker file to be owned by SYSTEM or Administrators, which
is the case on an elevated CI runner; where the owner is the ordinary user those
three skip, and (다) is the case that runs. The chosen cases are printed so the
CI log shows which half ran.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kagent import local_agent_meshcentral_command_port as cp

POWERSHELL = shutil.which("powershell") if sys.platform == "win32" else None
HOST_TAG = "7643-e2e-host"
# The sweep is issued for its own dispatch; the markers it finds belong to older
# dispatches, so none of them is in the keep set.
SWEEP_DISPATCH = "dsp_" + "a" * 32
MARKER_DISPATCH = "dsp_" + "b" * 32
OLD_MARKER_DISPATCH = "dsp_" + "c" * 32
STALE_MARKER_DISPATCH = "dsp_" + "d" * 32
UNTRUSTED_MARKER_DISPATCH = "dsp_" + "e" * 32


def _ps(command, timeout=90, environment=None):
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-Command", command],
        capture_output=True, text=True, timeout=timeout, env=environment,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _owner_sid(path):
    driver = cp.SWEEP_OWNER_SID_PS + "\nWrite-Output (__padiemSid '" + path.replace("'", "''") + "')"
    return _ps(driver).stdout.strip()


def _creation_filetime(pid):
    for _ in range(50):
        out = _ps(
            "(Get-CimInstance Win32_Process -Filter 'ProcessId=%d')"
            ".CreationDate.ToFileTime()" % pid
        ).stdout.strip()
        if out.isdigit():
            return out
        time.sleep(0.1)
    raise AssertionError("the spawned process never appeared in the process table")


class SweepScriptBudgetTests(unittest.TestCase):
    """Every allowed shape must fit the terminal queue before it reaches a PC."""

    TARGET_BYTES = 3700

    # Production mints a dispatch id as "dsp_" + uuid4().hex (history.py), so the
    # real id is 36 characters; the grammar admits 64 hex. The review's bound is
    # checked at the production shape, and the grammar's widest shape must still
    # stay inside the terminal queue.
    PRODUCTION_ID = "dsp_" + "a" * 32
    WIDEST_ID = "dsp_" + "a" * 64

    def _shapes(self):
        keep = ["dsp_%032x" % (index + 1) for index in range(cp.LINE_SWEEP_KEEP_LIMIT)]
        for mode in cp.SWEEP_MODES:
            for extra in (0, 1, cp.LINE_SWEEP_KEEP_LIMIT):
                for tag in (None, "h" * 64):
                    yield mode, extra, tag, keep[:extra]

    def test_every_mode_keep_and_tag_shape_fits(self):
        for mode, extra, tag, keep in self._shapes():
            script = cp.sweep_script(
                dispatch_id=self.PRODUCTION_ID, keep_dispatch_ids=keep,
                mode=mode, host_tag=tag,
            )
            size = len(script.encode("utf-8"))
            self.assertLess(size, cp.TERMINAL_SCRIPT_BUDGET_BYTES, (mode, extra, tag))
            self.assertLessEqual(size, self.TARGET_BYTES, (mode, extra, tag))

    def test_the_widest_grammar_shape_stays_in_the_queue(self):
        keep = ["dsp_%064x" % (index + 1) for index in range(cp.LINE_SWEEP_KEEP_LIMIT)]
        for mode in cp.SWEEP_MODES:
            script = cp.sweep_script(
                dispatch_id=self.WIDEST_ID, keep_dispatch_ids=keep, mode=mode, host_tag="h" * 64,
            )
            self.assertLess(len(script.encode("utf-8")), cp.TERMINAL_SCRIPT_BUDGET_BYTES, mode)

    def test_cancel_kill_command_fits(self):
        script = cp.cancel_kill_command("dsp_" + "a" * 64)
        self.assertLess(len(script.encode("utf-8")), cp.TERMINAL_SCRIPT_BUDGET_BYTES)
        self.assertLessEqual(len(script.encode("utf-8")), self.TARGET_BYTES)


@unittest.skipIf(POWERSHELL is None,
                 "the sweep's SYSTEM lane runs only on Windows PowerShell 5.1")
class AbandonedSweepEndToEndTests(unittest.TestCase):
    """The abandoned scope, whole, against processes this test spawned."""

    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="padiem-7643-")
        self.spawned = []
        probe = os.path.join(self.directory, "owner-probe.txt")
        with open(probe, "w", encoding="ascii") as stream:
            stream.write("probe")
        self.owner = _owner_sid(probe)
        self.trusted = self.owner in cp.TRUSTED_MARKER_SIDS

    def tearDown(self):
        for process in self.spawned:
            if process.poll() is None:
                process.kill()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    pass
        shutil.rmtree(self.directory, ignore_errors=True)

    # ---- fixtures ---------------------------------------------------------

    def _sleeper(self):
        process = subprocess.Popen(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", "Start-Sleep -Seconds 600"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.spawned.append(process)
        return process

    def _marker(self, dispatch, lines):
        path = os.path.join(self.directory, cp.PC_CANCEL_PID_FILE_PREFIX + dispatch + ".pid")
        with open(path, "w", encoding="ascii", newline="\r\n") as stream:
            stream.write("\n".join(str(line) for line in lines) + "\n")
        return path

    def _run(self):
        script = cp.sweep_script(
            dispatch_id=SWEEP_DISPATCH, keep_dispatch_ids=(), mode="abandoned",
            host_tag=HOST_TAG,
        )
        path = os.path.join(self.directory, "sweep.ps1")
        with open(path, "w", encoding="utf-8-sig") as stream:
            stream.write(script)
        environment = dict(os.environ)
        environment["TEMP"] = self.directory
        environment["TMP"] = self.directory
        completed = subprocess.run(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", path],
            capture_output=True, timeout=180, env=environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return completed, cp.parse_sweep_reply(completed.stdout)

    def _alive(self, process):
        return process.poll() is None

    def _require_trusted(self):
        if not self.trusted:
            self.skipTest("marker owner here is %r, not SYSTEM/Administrators" % self.owner)

    # ---- cases ------------------------------------------------------------

    def test_trusted_marker_with_matching_start_time_kills(self):
        self._require_trusted()
        process = self._sleeper()
        marker = self._marker(
            MARKER_DISPATCH,
            (process.pid, HOST_TAG, _creation_filetime(process.pid)),
        )
        completed, frame = self._run()
        self.assertIsNotNone(frame, completed.stdout[-400:])
        self.assertEqual(frame["mode"], "abandoned")
        self.assertIs(frame["running"], False)
        self.assertEqual(frame["killed"], [process.pid])
        self.assertFalse(os.path.exists(marker))
        deadline = time.monotonic() + 15
        while self._alive(process) and time.monotonic() < deadline:
            time.sleep(0.2)
        self.assertFalse(self._alive(process), "the marker's process did not end")

    def test_trusted_marker_with_another_start_time_keeps_the_process(self):
        self._require_trusted()
        process = self._sleeper()
        marker = self._marker(
            STALE_MARKER_DISPATCH,
            (process.pid, HOST_TAG, int(_creation_filetime(process.pid)) + 1),
        )
        completed, frame = self._run()
        self.assertIsNotNone(frame, completed.stdout[-400:])
        # A stale marker is a bare cleanup: the verdict frame reports only the
        # kills, so the process staying alive and the marker going away is the
        # whole observable result.
        self.assertEqual(frame["killed"], [])
        self.assertEqual(frame["found"], [])
        self.assertFalse(os.path.exists(marker))
        self.assertTrue(self._alive(process))

    def test_untrusted_marker_owner_is_untouched(self):
        if self.trusted:
            self.skipTest("everything this process creates is owned by %r here" % self.owner)
        process = self._sleeper()
        marker = self._marker(
            UNTRUSTED_MARKER_DISPATCH,
            (process.pid, HOST_TAG, _creation_filetime(process.pid)),
        )
        completed, frame = self._run()
        self.assertIsNotNone(frame, completed.stdout[-400:])
        self.assertEqual(frame["killed"], [])
        self.assertEqual(frame["found"], [])
        self.assertTrue(os.path.exists(marker))
        self.assertTrue(self._alive(process))

    def test_old_two_line_marker_is_handled_like_a_new_one(self):
        self._require_trusted()
        process = self._sleeper()
        marker = self._marker(OLD_MARKER_DISPATCH, (process.pid, HOST_TAG))
        completed, frame = self._run()
        self.assertIsNotNone(frame, completed.stdout[-400:])
        self.assertEqual(frame["killed"], [process.pid])
        self.assertFalse(os.path.exists(marker))
        deadline = time.monotonic() + 15
        while self._alive(process) and time.monotonic() < deadline:
            time.sleep(0.2)
        self.assertFalse(self._alive(process), "the old-format marker's process did not end")


if __name__ == "__main__":
    unittest.main()
