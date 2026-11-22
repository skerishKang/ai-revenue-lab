"""#8193 — the installer's self-heal task definition, built as data only.

No task store, Windows API or real process is touched. #8223 only needs to
call ``task_definition`` + ``register_script`` from the installer; these tests
pin the exact shape it will register.
"""
from __future__ import annotations

import base64
import gzip
import re
import unittest

from kagent.pc_self_heal_task import (
    ENABLE_FLAG,
    INTERVAL_MINUTES,
    LOGON_TYPE_SERVICE,
    MODULE,
    RESTART_FLAG,
    RUN_LEVEL_HIGHEST,
    TASK_FOLDER,
    TASK_NAME,
    TRIGGER_TIMER,
    build_launch,
    register_script,
    render_watcher_command,
    task_definition,
    unregister_script,
    watcher_script,
)


class SelfHealTaskDefinitionTests(unittest.TestCase):
    def setUp(self):
        self.launch = build_launch(python_executable=r"C:\Python311\python.exe")
        self.definition = task_definition(launch=self.launch)

    def test_task_is_system_and_runs_the_watcher_module(self):
        self.assertEqual(self.definition["TaskName"], TASK_NAME)
        self.assertEqual(self.definition["TaskPath"], TASK_FOLDER)
        self.assertEqual(self.definition["Principal"]["UserId"], "SYSTEM")
        self.assertEqual(self.definition["Principal"]["LogonType"], LOGON_TYPE_SERVICE)
        self.assertEqual(self.definition["Principal"]["RunLevel"], RUN_LEVEL_HIGHEST)
        self.assertIn("-m", self.launch.arguments)
        self.assertIn(MODULE, self.launch.arguments)

    def test_trigger_is_a_short_repeating_interval(self):
        self.assertEqual(self.definition["Trigger"]["Type"], TRIGGER_TIMER)
        self.assertEqual(self.definition["Trigger"]["Interval"], "PT%dM" % INTERVAL_MINUTES)
        self.assertLessEqual(INTERVAL_MINUTES, 10)

    def test_enable_and_restart_flags_are_declared(self):
        env = self.definition["Environment"]
        self.assertEqual(env[ENABLE_FLAG], "on")
        self.assertEqual(env[RESTART_FLAG], "on")

    def test_registration_script_registers_only_the_owned_task(self):
        script = register_script(self.definition)
        self.assertIn("New-ScheduledTaskAction", script)
        self.assertIn("Register-ScheduledTask", script)
        self.assertIn(TASK_NAME, script)
        self.assertIn(TASK_FOLDER, script)
        self.assertNotIn("Mesh Agent", script.replace(self.definition["Description"], ""))
        # The flags run_loop needs are set at machine scope so the SYSTEM task
        # inherits them when it starts.
        self.assertIn("'" + ENABLE_FLAG + "'", script)
        self.assertIn("'" + RESTART_FLAG + "'", script)
        self.assertIn("'Machine'", script)

    def test_identifier_validation_refuses_hostile_paths(self):
        with self.assertRaises(ValueError):
            build_launch(python_executable="")
        with self.assertRaises(ValueError):
            build_launch(python_executable="python.exe", module='bad"module')


class InstallerPayloadTests(unittest.TestCase):
    """The fixed payload both installers embed; no task store is touched."""

    def test_watcher_script_registers_the_owned_system_task(self):
        script = watcher_script()
        self.assertTrue(script.startswith("param([string]$PythonExecutable, [switch]$Unregister)"))
        self.assertIn("'" + TASK_NAME + "'", script)
        self.assertIn("'" + TASK_FOLDER + "'", script)
        self.assertIn("-UserId 'SYSTEM'", script)
        self.assertIn("-LogonType '" + LOGON_TYPE_SERVICE + "'", script)
        self.assertIn("-RunLevel '" + RUN_LEVEL_HIGHEST + "'", script)
        self.assertIn("-Execute $PythonExecutable", script)
        self.assertIn("-Argument '-m " + MODULE + "'", script)
        self.assertIn("-Force", script)
        self.assertIn("'PADIEM_PC_SELF_HEAL'", script)
        self.assertIn("'PADIEM_PC_SELF_HEAL_RESTART'", script)
        self.assertIn("'Machine'", script)
        self.assertIn("PT%dM" % INTERVAL_MINUTES, script)

    def test_watcher_script_has_no_machine_name_exception(self):
        # #8225 removed the single-host exclusion; every managed PC registers.
        script = watcher_script().upper()
        self.assertNotIn("COMPUTERNAME", script)
        self.assertNotIn("CGI", script)

    def test_removal_script_unregisters_only_the_owned_task(self):
        script = unregister_script()
        self.assertIn("Unregister-ScheduledTask", script)
        self.assertIn("'" + TASK_NAME + "'", script)
        self.assertIn("'" + TASK_FOLDER + "'", script)
        self.assertNotIn("Register-ScheduledTask", script)

    def test_watcher_script_removal_branch_unregisters_the_owned_task(self):
        script = watcher_script()
        self.assertIn("if ($Unregister)", script)
        self.assertIn("Unregister-ScheduledTask -TaskPath $taskPath -TaskName $taskName", script)
        self.assertIn("exit 0", script)

    def test_commands_carry_only_the_fixed_payload(self):
        for unregister in (False, True):
            command = render_watcher_command(unregister=unregister)
            self.assertLess(len(command), 32767)
            payload = re.search(r"FromBase64String\('([^']+)'\)", command)[1]
            self.assertEqual(gzip.decompress(base64.b64decode(payload)).decode(), watcher_script())
            self.assertTrue(command.endswith(
                "-Unregister" if unregister else "-PythonExecutable $PythonExecutable"))
            self.assertNotIn("Invoke-Expression", command)
            self.assertNotIn("http", command)


if __name__ == "__main__":
    unittest.main()
