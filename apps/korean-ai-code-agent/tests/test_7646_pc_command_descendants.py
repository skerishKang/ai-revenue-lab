"""#7646 — a stopped or abandoned PC command ends the tree it started, not just its pid.

Three claims are checked here, and each is checked the way the lane can actually be
checked without a customer PC:

* the command's wrapper joins a **named** kill-on-close job before it runs the body, so
  every descendant is a member by inheritance and the job - not the parent chain - is
  what a stop addresses;
* the stop ends that job by name, and the name is derived from the dispatch id alone, so
  it can only ever reach a container this lane created;
* a dispatch that never created a job (every command from before this change) opens
  nothing, ends nothing, and keeps the recorded-pid behaviour it had.

Nothing here ends a process this suite did not start. The PowerShell drivers below run
the real kernel calls on a job and a process **this test creates itself**, and every
process they start is ended by the test. The rest is script shape and pure Python.
"""
from __future__ import annotations

import json
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kagent import local_agent_meshcentral_command_port as cp
from kagent import local_agent_meshcentral_dispatch_job as jobs
from kagent.contracts import ContractError

#: The PC's SYSTEM lane interpreter is Windows PowerShell 5.1, so the drivers that touch
#: kernel32 run only where it exists and skip on the ubuntu CI leg.
POWERSHELL = shutil.which("powershell") if sys.platform == "win32" else None

DISPATCH = "dsp_" + "ab" * 8
OTHER_DISPATCH = "dsp_" + "cd" * 8


def _run_ps(script_path: str, timeout: float = 180.0) -> dict:
    completed = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
         "Bypass", "-File", script_path],
        capture_output=True, timeout=timeout,
    )
    out = completed.stdout.decode("utf-8", errors="replace")
    start = out.find("{")
    if start < 0:
        raise AssertionError(
            "PowerShell driver produced no JSON: %r / %r"
            % (out, completed.stderr.decode("utf-8", errors="replace"))
        )
    return json.loads(out[start:])


def _run_ps_silent(script_path: str, timeout: float = 180.0) -> None:
    """Run a driver that answers nothing on purpose - a stop, not a report."""
    subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
         "Bypass", "-File", script_path],
        capture_output=True, timeout=timeout, check=True,
    )


def _read_text(path: str) -> str:
    """One small file's text, closed. The pid files this test writes are tiny."""
    with io.open(path, encoding="utf-8") as stream:
        return stream.read()


def _pid_alive(pid: int) -> bool:
    """Whether a pid this test started is still running. Read-only."""
    completed = subprocess.run(
        ["tasklist", "/FI", "PID eq %d" % pid, "/NH"],
        capture_output=True, timeout=60,
    )
    return str(pid) in completed.stdout.decode("utf-8", errors="replace")


def _write_driver(body: str) -> str:
    handle, path = tempfile.mkstemp(suffix=".ps1")
    with os.fdopen(handle, "w", encoding="utf-8-sig") as stream:
        stream.write(body)
    return path


class DispatchJobNameTests(unittest.TestCase):
    """The name is the identity, so it is the first thing to pin. Runs on both legs."""

    def test_name_is_derived_from_the_dispatch_id_alone(self):
        self.assertEqual(
            jobs.job_name(DISPATCH), "padiem-dispatch-job-" + DISPATCH,
        )
        # Two dispatches never share a name, and the same dispatch always gets the same
        # one - which is what lets a stop address a job it did not create.
        self.assertNotEqual(jobs.job_name(DISPATCH), jobs.job_name(OTHER_DISPATCH))
        self.assertEqual(jobs.job_name(DISPATCH), jobs.job_name(DISPATCH))

    def test_a_name_that_is_not_a_dispatch_is_refused(self):
        for bad in (
            "", "dsp_", "dsp_zzzz", "dsp_" + "a" * 15, "dsp_" + "a" * 65,
            "dsp_" + "a" * 8 + "\\..\\other", "dsp_" + "a" * 8 + "/x",
            "../padiem-dispatch-job-" + DISPATCH, None, 7,
        ):
            with self.assertRaises(ContractError, msg=repr(bad)):
                jobs.job_name(bad)

    def test_a_job_name_round_trips_to_its_dispatch(self):
        self.assertEqual(jobs.job_name_of(jobs.job_name(DISPATCH)), DISPATCH)
        # A name this lane did not build carries no dispatch, so a sweep that reads one
        # off a machine cannot turn it into a target.
        for foreign in (
            "padiem-dispatch-job-", "padiem-dispatch-job-notadispatch",
            "padiem-dispatch-" + DISPATCH, "other-" + DISPATCH, "",
        ):
            self.assertIsNone(jobs.job_name_of(foreign), foreign)

    def test_a_job_name_is_a_kernel_object_name(self):
        # A kernel object name may not carry a path separator; the grammar is the guard.
        for bad in ("padiem-dispatch-job-a\\b", "padiem-dispatch-job-a/b",
                    "padiem-dispatch-job-" + "a" * 97, "x" * 200, None):
            with self.assertRaises(ContractError, msg=repr(bad)):
                jobs.checked_job_name(bad)
        self.assertEqual(
            jobs.checked_job_name(jobs.job_name(DISPATCH)), jobs.job_name(DISPATCH)
        )


class CommandJoinsItsOwnJobTests(unittest.TestCase):
    """The command side: the wrapper must be in the job before the body runs."""

    def test_the_console_wrapper_joins_the_job_before_the_body(self):
        script = cp._wrap("Write-Output hi", DISPATCH, "test-host")
        create = script.find("CreateJobObjectW")
        assign = script.find("AssignProcessToJobObject")
        body = script.find("& { Write-Output hi }")
        self.assertGreater(create, -1)
        self.assertGreater(assign, create)
        self.assertGreater(body, assign, "the body must run inside the job")

    def test_the_staged_file_wrapper_joins_the_job_before_the_child(self):
        script = cp._file_dispatch_console_script(
            "Write-Output hi", DISPATCH, "test-host")
        assign = script.find("AssignProcessToJobObject")
        child = script.find("-File $__fp")
        self.assertGreater(assign, -1)
        self.assertGreater(child, assign, "the -File child must start inside the job")

    def test_the_job_is_named_by_the_dispatch_and_carries_kill_on_close(self):
        for script in (
            cp._wrap("Write-Output hi", DISPATCH, "test-host"),
            cp._file_dispatch_console_script("Write-Output hi", DISPATCH, "test-host"),
        ):
            self.assertIn("padiem-dispatch-job-" + DISPATCH, script)
            # The flag is written into the buffer at its real offset; a marshalled
            # PowerShell object silently drops it (measured 2026-11-15).
            self.assertIn("WriteInt32($__padiem_buf,16,8192)", script)
            self.assertIn("SetInformationJobObject", script)
            self.assertIn("144", script)

    def test_a_command_without_a_dispatch_creates_no_job(self):
        # The read lanes carry no dispatch id, so they carry no marker and no job.
        script = cp._wrap("Write-Output hi")
        self.assertNotIn("CreateJobObjectW", script)
        self.assertNotIn("padiem-dispatch-job-", script)

    def test_the_wrapper_keeps_the_job_handle_for_its_whole_life(self):
        # Kill-on-close is only a guarantee while a handle is open: the wrapper must not
        # close it before the body finishes, or the tree would end early.
        script = cp._wrap("Write-Output hi", DISPATCH, "test-host")
        self.assertIn("$__padiem_job=$__padiem_jh", script)
        self.assertNotIn("CloseHandle($__padiem_jh)", script)


class StopEndsTheJobTests(unittest.TestCase):
    """The stop side: the job is ended by name, and the old path is kept."""

    def test_the_stop_ends_the_job_by_the_dispatch_name(self):
        script = cp.cancel_kill_command(DISPATCH)
        self.assertIn("OpenJobObjectW", script)
        self.assertIn("padiem-dispatch-job-" + DISPATCH, script)
        self.assertIn("TerminateJobObject", script)
        # The job end comes before the recorded-pid path, so a reparented descendant is
        # reached even when the recorded pid is already gone.
        self.assertLess(script.find("OpenJobObjectW"), script.find("taskkill"))

    def test_the_stop_still_ends_the_recorded_pid_tree(self):
        # #7673's protection is untouched: the recorded pid is ended only when its record
        # still names a PowerShell host with the marker's own start time.
        script = cp.cancel_kill_command(DISPATCH)
        self.assertIn("System32\\taskkill.exe /T /F /PID $__padiem_kill", script)
        self.assertIn(
            "[string]$__padiem_r.CreationDate.ToFileTime() -eq $__padiem_st", script)
        self.assertIn("'S-1-5-18','S-1-5-32-544' -contains (__padiemSid", script)

    def test_the_stop_only_opens_a_job_it_could_have_created(self):
        # The access mask is terminate+query, never ALL_ACCESS: a stop ends and reads,
        # and a narrower handle cannot be turned into a general container handle.
        script = cp.cancel_kill_command(DISPATCH)
        self.assertIn("OpenJobObjectW(%d,$false," % jobs.JOB_OBJECT_TERMINATE_ACCESS,
                      script)
        self.assertNotIn("OpenJobObjectW(2031619", script)  # JOB_OBJECT_ALL_ACCESS
        self.assertNotIn("CreateJobObjectW", script)

    def test_the_job_only_stop_carries_no_pid_path(self):
        # Used where another lane already ended the pid: this must not be a second way
        # to end a process by number.
        script = cp.cancel_job_command(DISPATCH)
        self.assertIn("OpenJobObjectW", script)
        self.assertNotIn("taskkill", script)
        self.assertNotIn("Get-CimInstance", script)

    def test_every_stop_script_stays_inside_the_terminal_budget(self):
        for script in (cp.cancel_kill_command(DISPATCH), cp.cancel_job_command(DISPATCH)):
            self.assertLess(len(script.encode("utf-8")),
                            cp.TERMINAL_SCRIPT_BUDGET_BYTES)
        # The sweep is untouched by this change, and still fits.
        for mode in ("abandoned", "idle_console", "held"):
            self.assertLess(
                len(cp.sweep_script(dispatch_id=DISPATCH, keep_dispatch_ids=(),
                                    mode=mode, host_tag="h").encode("utf-8")),
                cp.TERMINAL_SCRIPT_BUDGET_BYTES, mode,
            )

    def test_no_bare_name_system_executables_in_the_new_scripts(self):
        for script in (cp.cancel_kill_command(DISPATCH), cp.cancel_job_command(DISPATCH),
                       cp._wrap("Write-Output hi", DISPATCH, "h"),
                       cp._file_dispatch_console_script("Write-Output hi", DISPATCH, "h")):
            self.assertEqual(script.count("taskkill"),
                             script.count("System32\\taskkill.exe"))


class JobPrimitivePowerShellTests(unittest.TestCase):
    """The real kernel calls, on a job and processes this test creates and ends itself.

    Runs on the KAgent windows-latest CI leg (Windows PowerShell 5.1, the interpreter the
    PC's SYSTEM lane uses) and skips where no Windows PowerShell exists.
    """

    @unittest.skipIf(POWERSHELL is None, "Windows PowerShell is not available")
    def test_kill_on_close_is_really_set_and_reaps_a_reparented_grandchild(self):
        # The whole fix rests on two facts a script-shape test cannot prove: the limit is
        # actually on, and a descendant that outlived its parent is still a member. Both
        # are measured here, on a job and processes this test creates and ends itself.
        #
        # Two processes, because the wrapper has to die for the question to be asked: a
        # HOLDER creates the job, joins it, starts a child that starts a grandchild and
        # then exits, and waits. The OBSERVER reads the flag back, kills the holder, and
        # reports whether the reparented grandchild went with it.
        name = jobs.job_name(DISPATCH)
        scratch = tempfile.mkdtemp(prefix="padiem-7646-")
        holder_path = os.path.join(scratch, "holder.ps1")
        child_pid_file = os.path.join(scratch, "c.pid")
        grand_pid_file = os.path.join(scratch, "g.pid")
        holder_pid_file = os.path.join(scratch, "h.pid")
        declarations = jobs.DISPATCH_JOB_DECLARATIONS_PS.replace("'", "''")
        with io.open(holder_path, "w", encoding="utf-8-sig") as stream:
            stream.write("\n".join([
                "$ErrorActionPreference='Stop'",
                "Add-Type -Namespace P7646 -Name J -MemberDefinition '" + declarations + "'",
                "$h=[P7646.J]::CreateJobObjectW([IntPtr]::Zero,'" + name + "')",
                "$b=[Runtime.InteropServices.Marshal]::AllocHGlobal(144)",
                "for($i=0;$i -lt 144;$i++){[Runtime.InteropServices.Marshal]::WriteByte($b,$i,0)}",
                "[Runtime.InteropServices.Marshal]::WriteInt32($b,16,8192)",
                "[P7646.J]::SetInformationJobObject($h,9,$b,144)|Out-Null",
                "[Runtime.InteropServices.Marshal]::FreeHGlobal($b)",
                "$me=Get-Process -Id $PID",
                "[P7646.J]::AssignProcessToJobObject($h,$me.Handle)|Out-Null",
                "Set-Content -LiteralPath '" + holder_pid_file.replace("'", "''")
                + "' -Value $PID",
                # The child starts a grandchild and exits at once, so the grandchild is
                # reparented - the shape no pid walk can follow.
                "$inner='$g=Start-Process -FilePath powershell -NoNewWindow -PassThru"
                " -ArgumentList ''-NoProfile'',''-Command'',''Start-Sleep -Seconds 120'';"
                "Set-Content -LiteralPath ''" + grand_pid_file.replace("'", "''")
                + "'' -Value $g.Id'",
                "$c=Start-Process -FilePath 'powershell' -NoNewWindow -PassThru"
                " -ArgumentList '-NoProfile','-Command',$inner",
                "Set-Content -LiteralPath '" + child_pid_file.replace("'", "''")
                + "' -Value $c.Id",
                "$c.WaitForExit(30000) | Out-Null",
                "Start-Sleep -Seconds 120",
            ]))
        holder = subprocess.Popen(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
             "Bypass", "-File", holder_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        try:
            deadline = time.time() + 60
            while time.time() < deadline:
                if (os.path.exists(grand_pid_file) and os.path.exists(child_pid_file)
                        and os.path.exists(holder_pid_file)):
                    break
                time.sleep(0.25)
            time.sleep(2)
            grand_pid = int(_read_text(grand_pid_file).strip())
            child_pid = int(_read_text(child_pid_file).strip())
            child_gone = not _pid_alive(child_pid)
            grand_before = _pid_alive(grand_pid)

            observer = "\n".join([
                "$ErrorActionPreference='Stop'",
                "Add-Type -Namespace P7646 -Name J -MemberDefinition '"
                + declarations
                + "[DllImport(\"kernel32.dll\")] public static extern bool"
                " QueryInformationJobObject(IntPtr j,int c,IntPtr b,uint l,IntPtr r);'",
                "$h=[P7646.J]::CreateJobObjectW([IntPtr]::Zero,'" + name + "')",
                "$q=[Runtime.InteropServices.Marshal]::AllocHGlobal(144)",
                "$qok=[P7646.J]::QueryInformationJobObject($h,9,$q,144,[IntPtr]::Zero)",
                "$flags=[Runtime.InteropServices.Marshal]::ReadInt32($q,16)",
                "[Runtime.InteropServices.Marshal]::FreeHGlobal($q)",
                "[P7646.J]::CloseHandle($h) | Out-Null",
                "@{queryOk=$qok; flags=$flags} | ConvertTo-Json",
            ])
            path = _write_driver(observer)
            try:
                observed = _run_ps(path)
            finally:
                os.unlink(path)

            # The wrapper dies. It was the only holder of the job handle.
            subprocess.run(
                [os.path.join(os.environ["SystemRoot"], "System32", "taskkill.exe"),
                 "/F", "/PID", str(holder.pid)],
                capture_output=True, timeout=60,
            )
            deadline = time.time() + 30
            while time.time() < deadline and _pid_alive(grand_pid):
                time.sleep(0.25)
            grand_after = _pid_alive(grand_pid)
        finally:
            if holder.poll() is None:
                holder.kill()
            holder.communicate(timeout=30)
            for pid in (locals().get("grand_pid"), locals().get("child_pid")):
                if isinstance(pid, int) and _pid_alive(pid):
                    subprocess.run(
                        [os.path.join(os.environ["SystemRoot"], "System32",
                                      "taskkill.exe"), "/F", "/PID", str(pid)],
                        capture_output=True, timeout=60,
                    )
            shutil.rmtree(scratch, ignore_errors=True)

        self.assertTrue(observed["queryOk"], "the job limit could not be read back")
        # 0x2000 read back from the kernel: the flag is on, not merely requested.
        self.assertEqual(observed["flags"], 8192)
        # The premise: the grandchild really was reparented and really was running.
        self.assertTrue(child_gone, "the child did not exit as arranged")
        self.assertTrue(grand_before, "the grandchild was not running")
        # And it was still reaped: membership, not the parent chain, reached it.
        self.assertFalse(grand_after, "the reparented grandchild outlived its job")


class StopReachesOnlyItsOwnJobTests(unittest.TestCase):
    """The real kernel calls again, this time on two dispatches at once.

    Two claims no script-shape test can prove: a stop addresses one job and never a
    neighbour's, and a stop reaches a descendant whose own parent has already exited
    while the wrapper that created the job is still alive - the case a parent-chain walk
    cannot answer at all. The job, the holder and every process it starts are this
    test's own, and every one of them is ended by this test.
    """

    @unittest.skipIf(POWERSHELL is None, "Windows PowerShell is not available")
    def test_a_stop_ends_its_own_reparented_grandchild_and_no_other_job(self):
        name = jobs.job_name(DISPATCH)
        scratch = tempfile.mkdtemp(prefix="padiem-7646b-")
        holder_path = os.path.join(scratch, "holder.ps1")
        child_pid_file = os.path.join(scratch, "c.pid")
        grand_pid_file = os.path.join(scratch, "g.pid")
        declarations = jobs.DISPATCH_JOB_DECLARATIONS_PS.replace("'", "''")
        # The holder joins the job, starts a child that starts a grandchild and exits at
        # once, then waits. The grandchild is therefore a member whose parent is gone.
        inner = (
            "$g=Start-Process -FilePath powershell -NoNewWindow -PassThru"
            " -ArgumentList ''-NoProfile'',''-Command'',''Start-Sleep -Seconds 120'';"
            "Set-Content -LiteralPath ''" + grand_pid_file.replace("'", "''")
            + "'' -Value $g.Id"
        )
        with io.open(holder_path, "w", encoding="utf-8-sig") as stream:
            stream.write("\n".join([
                "$ErrorActionPreference='Stop'",
                "Add-Type -Namespace P7646 -Name J -MemberDefinition '" + declarations + "'",
                "$h=[P7646.J]::CreateJobObjectW([IntPtr]::Zero,'" + name + "')",
                "$b=[Runtime.InteropServices.Marshal]::AllocHGlobal(144)",
                "for($i=0;$i -lt 144;$i++){[Runtime.InteropServices.Marshal]::WriteByte($b,$i,0)}",
                "[Runtime.InteropServices.Marshal]::WriteInt32($b,16,8192)",
                "[P7646.J]::SetInformationJobObject($h,9,$b,144)|Out-Null",
                "[Runtime.InteropServices.Marshal]::FreeHGlobal($b)",
                "$me=Get-Process -Id $PID",
                "[P7646.J]::AssignProcessToJobObject($h,$me.Handle)|Out-Null",
                "$c=Start-Process -FilePath 'powershell' -NoNewWindow -PassThru"
                " -ArgumentList '-NoProfile','-Command','" + inner + "'",
                "Set-Content -LiteralPath '" + child_pid_file.replace("'", "''")
                + "' -Value $c.Id",
                "$c.WaitForExit(30000) | Out-Null",
                "Start-Sleep -Seconds 120",
            ]))
        holder = subprocess.Popen(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
             "Bypass", "-File", holder_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        grand_pid = None
        child_pid = None
        try:
            deadline = time.time() + 60
            while time.time() < deadline:
                if os.path.exists(grand_pid_file) and os.path.exists(child_pid_file):
                    break
                time.sleep(0.25)
            grand_pid = int(_read_text(grand_pid_file).strip())
            child_pid = int(_read_text(child_pid_file).strip())
            time.sleep(2)
            # The premise: the child is gone, and the grandchild outlived it.
            self.assertFalse(_pid_alive(child_pid), "the child did not exit as arranged")
            self.assertTrue(_pid_alive(grand_pid), "the grandchild was not running")

            # A stop for a different dispatch: the name is not this job's, so the kernel
            # opens nothing and the grandchild is untouched.
            other = _write_driver(jobs.dispatch_job_stop_ps(OTHER_DISPATCH))
            try:
                _run_ps_silent(other)
            finally:
                os.unlink(other)
            self.assertTrue(_pid_alive(grand_pid),
                            "a stop ended a job it does not name")

            # The stop for this dispatch, while the holder is still alive: the parent
            # chain would reach the dead child and stop there, the job does not.
            mine = _write_driver(jobs.dispatch_job_stop_ps(DISPATCH))
            try:
                _run_ps_silent(mine)
            finally:
                os.unlink(mine)
            deadline = time.time() + 30
            while time.time() < deadline and _pid_alive(grand_pid):
                time.sleep(0.25)
            self.assertFalse(_pid_alive(grand_pid),
                             "the reparented grandchild outlived its job's stop")
        finally:
            for pid in (grand_pid, child_pid):
                if isinstance(pid, int) and _pid_alive(pid):
                    subprocess.run(
                        [os.path.join(os.environ["SystemRoot"], "System32",
                                      "taskkill.exe"), "/F", "/PID", str(pid)],
                        capture_output=True, timeout=60,
                    )
            if holder.poll() is None:
                holder.kill()
            holder.communicate(timeout=30)
            shutil.rmtree(scratch, ignore_errors=True)


class JobOnlyStopTests(unittest.TestCase):
    """The carrier's own shape: what ``end_dispatch_job`` sends, and what it reports."""

    def _port(self, answer):
        class _Port(cp.MeshCentralCliCommandPort):
            def __init__(self):
                self.sent = []

            def _run_shell_session(self, node_ref, script, *, answer=None,
                                   wait_seconds=None):
                self.sent.append((node_ref, script))
                return self._answer

        port = _Port()
        port._answer = answer
        return port

    def test_the_job_stop_names_this_dispatch_and_nothing_else(self):
        port = self._port(cp.STOP_EVIDENCE.encode("ascii"))
        self.assertTrue(port.end_dispatch_job(node_ref="node-1", dispatch_id=DISPATCH))
        node_ref, script = port.sent[0]
        self.assertEqual(node_ref, "node-1")
        self.assertIn("padiem-dispatch-job-" + DISPATCH, script)
        self.assertIn("OpenJobObjectW", script)
        self.assertNotIn("taskkill", script)
        self.assertNotIn(OTHER_DISPATCH, script)

    def test_a_session_that_proves_nothing_is_not_a_stop(self):
        port = self._port(b"")
        self.assertFalse(port.end_dispatch_job(node_ref="node-1", dispatch_id=DISPATCH))

    def test_a_session_that_cannot_be_opened_is_not_a_stop(self):
        class _Port(cp.MeshCentralCliCommandPort):
            def __init__(self):
                self.sent = 0

            def _run_shell_session(self, node_ref, script, *, answer=None,
                                   wait_seconds=None):
                self.sent += 1
                raise OSError("the PC did not answer")

        port = _Port()
        self.assertFalse(port.end_dispatch_job(node_ref="node-1", dispatch_id=DISPATCH))
        self.assertEqual(port.sent, 1)

    def test_a_name_this_lane_does_not_issue_is_refused(self):
        port = self._port(cp.STOP_EVIDENCE.encode("ascii"))
        with self.assertRaises(cp.MeshCentralCommandRefused):
            port.end_dispatch_job(node_ref="node-1", dispatch_id="not-a-dispatch")
        self.assertEqual(port.sent, [], "nothing is sent for a name we did not issue")

    def test_the_phase_observer_hears_the_outcome(self):
        seen = []
        port = self._port(cp.STOP_EVIDENCE.encode("ascii"))
        self.assertTrue(port.end_dispatch_job(
            node_ref="node-1", dispatch_id=DISPATCH, phase_observer=seen.append))
        self.assertEqual(seen, [cp.phases.CANCEL_KILL])
        port = self._port(b"")
        self.assertFalse(port.end_dispatch_job(
            node_ref="node-1", dispatch_id=DISPATCH, phase_observer=seen.append))
        self.assertEqual(seen, [cp.phases.CANCEL_KILL, cp.phases.CANCEL_KILL_UNVERIFIED])


class UserModeStopEndsTheJobTests(unittest.TestCase):
    """The executor's own cancelled user-session path asks the port for the job."""

    def test_the_cancelled_branch_ends_the_job_before_it_returns(self):
        source = io.open(
            os.path.join(os.path.dirname(__file__), "..", "src", "kagent",
                         "local_agent_oracle_mesh_executor.py"),
            encoding="utf-8",
        ).read()
        cancelled = source.index('if term == "cancelled":')
        ender = source.index("self._end_user_mode_job(dispatch, phase)", cancelled)
        returns = source.index("termination=\"cancelled\"", cancelled)
        self.assertLess(ender, returns,
                        "the job is ended before the cancelled outcome is returned")


class BackwardCompatibilityTests(unittest.TestCase):
    """A command from before this change keeps the behaviour it had."""

    def test_a_dispatch_with_no_job_ends_nothing_and_says_so(self):
        # The stop's job step reports its own outcome, so a missing job is a false and
        # not an error: the recorded-pid path below still runs.
        script = cp.cancel_kill_command(DISPATCH)
        self.assertIn("$__padiem_jobended=$false", script)
        self.assertIn("catch{$__padiem_jobended=$false}", script)
        # Nothing in the job step can raise: it is wrapped whole.
        self.assertLess(script.find("$__padiem_jobended=$false"),
                        script.find("$__padiem_marker") if "$__padiem_marker" in script
                        else script.find("$__padiem_stop"))

    def test_the_job_step_never_refuses_a_command(self):
        # The wrapper's job creation is best effort: a PC that cannot create a job is
        # still a PC whose command must run, so the failure is swallowed and the body
        # runs regardless.
        script = cp._wrap("Write-Output hi", DISPATCH, "test-host")
        self.assertIn("}catch{$__padiem_job=[IntPtr]::Zero};", script)
        self.assertGreater(script.find("& { Write-Output hi }"),
                           script.find("}catch{$__padiem_job=[IntPtr]::Zero};"))


if __name__ == "__main__":
    unittest.main()
