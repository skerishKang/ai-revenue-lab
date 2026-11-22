"""#8193 — the installer's self-heal task definition, built as data only.

No task store, Windows API or real process is touched. #8223 only needs to
call ``task_definition`` + ``register_script`` from the installer; these tests
pin the exact shape it will register.
"""
from __future__ import annotations

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
    task_definition,
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


if __name__ == "__main__":
    unittest.main()
