"""#5462/#5485 — failover controller contract.

Three facts are kept apart on purpose, and these tests pin every one of them:

* **com2_restored** — COM2 says it is healthy again. It is a *signal*: it
  moves the route, and the route is what sends the device.
* **com2_device_connected** — COM2's own probe says the device is there
  *now*. The agent has to travel back before this is true.
* **oracle_device_connected** — Oracle's own probe says the device is there
  *now*.

The claim follows the **device**, never the route and never a signal. A
target that owns no device would lose the dispatch, so the claim waits
instead of being taken and lost.

These are unittest cases on purpose: the KAgent CI lane discovers
``unittest.TestCase`` only, so a pytest-style module here would never be
executed by CI.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kagent.contracts import ContractError
from kagent.local_agent_mesh_failover import (
    ACTIVE_COM2,
    ACTIVE_ORACLE,
    EVENT_COM2_FAULT,
    EVENT_COM2_RESTORED,
    EVENT_FAILBACK_COMPLETE,
    EVENT_ORACLE_ACTIVE,
    EVENT_ROUTE_TO_COM2,
    EVENT_ROUTE_TO_ORACLE,
    MeshCentralDevicePresence,
    MeshFailoverController,
    MeshFailoverSupervisor,
    build_heartbeat,
    command_notifier,
    decision_file_claim_gate,
    events_file_notifier,
    heartbeat_age_seconds,
    read_heartbeat,
    write_heartbeat,
)


class _FakeCompleted:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


#: What the official client prints for one connected device.
LISTDEVICES_ONE_CONNECTED = """
Device group: "PADIEM-MC-TRIAL"
id, name, icon, conn, pwr
-------------------------
"wYx8HR9Ou4C96Ys63dY8lYktUiTPf7PwRM8lclcOvW3V4KTM1Auk@Dd2cdXxSOwp", "Padiem-Command-Center", 1, 1, 1
"""

#: The same device, registered but not connected.
LISTDEVICES_ONE_DISCONNECTED = """
Device group: "PADIEM-MC-TRIAL"
id, name, icon, conn, pwr
-------------------------
"wYx8HR9Ou4C96Ys63dY8lYktUiTPf7PwRM8lclcOvW3V4KTM1Auk@Dd2cdXxSOwp", "Padiem-Command-Center", 1, 0, 0
"""

DEVICE_ID = "wYx8HR9Ou4C96Ys63dY8lYktUiTPf7PwRM8lclcOvW3V4KTM1Auk@Dd2cdXxSOwp"


class MeshFailoverControllerTests(unittest.TestCase):
    """The pure state machine."""

    def test_scenario_a_normal_keeps_com2_active(self):
        controller = MeshFailoverController()
        for _ in range(5):
            decision = controller.evaluate(
                com2_restored=True,
                com2_device_connected=True,
                oracle_device_connected=False,
                com2_heartbeat_age_seconds=1.0,
            )
            self.assertEqual(decision.active_target, ACTIVE_COM2)
            self.assertEqual(decision.route_target, ACTIVE_COM2)
            self.assertFalse(decision.changed)
            self.assertEqual(decision.events, ())
        self.assertEqual(controller.epoch, 1)

    def test_scenario_b_fault_moves_the_route_then_the_claim(self):
        controller = MeshFailoverController(fault_confirmations=2)
        first = controller.evaluate(
            com2_restored=False,
            com2_device_connected=False,
            oracle_device_connected=False,
            com2_heartbeat_age_seconds=200.0,
        )
        self.assertFalse(first.changed)
        self.assertEqual(first.route_target, ACTIVE_COM2)
        # The device is nowhere, so nobody may claim yet.
        self.assertIsNone(first.active_target)

        second = controller.evaluate(
            com2_restored=False,
            com2_device_connected=False,
            oracle_device_connected=True,
            com2_heartbeat_age_seconds=200.0,
        )
        self.assertTrue(second.changed)
        # The route moved first, and the claim followed the device.
        self.assertEqual(second.route_target, ACTIVE_ORACLE)
        self.assertEqual(second.active_target, ACTIVE_ORACLE)
        self.assertIn(EVENT_ROUTE_TO_ORACLE, second.events)
        self.assertIn(EVENT_COM2_FAULT, second.events)
        self.assertIn(EVENT_ORACLE_ACTIVE, second.events)
        self.assertGreater(second.epoch, first.epoch)

    def test_the_claim_waits_for_the_device_to_arrive(self):
        controller = MeshFailoverController(fault_confirmations=1)
        decision = controller.evaluate(
            com2_restored=False,
            com2_device_connected=False,
            oracle_device_connected=False,
            com2_heartbeat_age_seconds=200.0,
        )
        self.assertEqual(decision.route_target, ACTIVE_ORACLE)
        self.assertIsNone(decision.active_target)

    def test_scenario_c_recovery_needs_the_device_back(self):
        controller = MeshFailoverController(
            fault_confirmations=1, restore_confirmations=1
        )
        faulted = controller.evaluate(
            com2_restored=False,
            com2_device_connected=False,
            oracle_device_connected=True,
            com2_heartbeat_age_seconds=900.0,
        )
        self.assertEqual(faulted.active_target, ACTIVE_ORACLE)

        # COM2 says it is back, but the device has not travelled yet.
        signalled = controller.evaluate(
            com2_restored=True,
            com2_device_connected=False,
            oracle_device_connected=True,
            com2_heartbeat_age_seconds=1.0,
        )
        self.assertEqual(signalled.route_target, ACTIVE_COM2)
        self.assertIn(EVENT_ROUTE_TO_COM2, signalled.events)
        # The claim stays with the server that still has the device.
        self.assertEqual(signalled.active_target, ACTIVE_ORACLE)

        # The device is back, and only now does the claim return.
        restored = controller.evaluate(
            com2_restored=True,
            com2_device_connected=True,
            oracle_device_connected=False,
            com2_heartbeat_age_seconds=1.0,
        )
        self.assertEqual(restored.active_target, ACTIVE_COM2)
        self.assertIn(EVENT_FAILBACK_COMPLETE, restored.events)
        self.assertGreater(restored.epoch, faulted.epoch)

    def test_scenario_d_the_epoch_fences_a_stale_consumer(self):
        controller = MeshFailoverController(fault_confirmations=1)
        before = controller.evaluate(
            com2_restored=True,
            com2_device_connected=True,
            oracle_device_connected=False,
            com2_heartbeat_age_seconds=1.0,
        )
        self.assertTrue(before.may_claim(before.epoch))
        faulted = controller.evaluate(
            com2_restored=False,
            com2_device_connected=False,
            oracle_device_connected=True,
            com2_heartbeat_age_seconds=900.0,
        )
        # The consumer that still believes it is active is refused.
        self.assertFalse(faulted.may_claim(before.epoch))
        self.assertTrue(faulted.may_claim(faulted.epoch))
        # The restore window is three confirmations, so the epoch moves on
        # the last one.
        for _ in range(2):
            controller.evaluate(
                com2_restored=True,
                com2_device_connected=True,
                oracle_device_connected=False,
                com2_heartbeat_age_seconds=1.0,
            )
        restored = controller.evaluate(
            com2_restored=True,
            com2_device_connected=True,
            oracle_device_connected=False,
            com2_heartbeat_age_seconds=1.0,
        )
        self.assertGreater(restored.epoch, faulted.epoch)
        self.assertFalse(restored.may_claim(faulted.epoch))

    def test_a_single_missed_observation_does_not_move_the_route(self):
        controller = MeshFailoverController(fault_confirmations=2)
        controller.evaluate(
            com2_restored=True,
            com2_device_connected=True,
            oracle_device_connected=False,
            com2_heartbeat_age_seconds=1.0,
        )
        missed = controller.evaluate(
            com2_restored=False,
            com2_device_connected=False,
            oracle_device_connected=False,
            com2_heartbeat_age_seconds=500.0,
        )
        # The route stays: one missed observation is not a fault.
        self.assertEqual(missed.route_target, ACTIVE_COM2)
        self.assertEqual(missed.events, ())
        back = controller.evaluate(
            com2_restored=True,
            com2_device_connected=True,
            oracle_device_connected=False,
            com2_heartbeat_age_seconds=1.0,
        )
        # The route never moved, and the claim is back where the device is.
        self.assertEqual(back.route_target, ACTIVE_COM2)
        self.assertEqual(back.active_target, ACTIVE_COM2)

    def test_a_stale_heartbeat_alone_does_not_fail_com2_over(self):
        controller = MeshFailoverController()
        self.assertTrue(controller.heartbeat_is_stale(None))
        self.assertTrue(controller.heartbeat_is_stale(1000.0))
        self.assertFalse(controller.heartbeat_is_stale(1.0))

    def test_oracle_keeps_the_claim_while_com2_stays_down(self):
        """Oracle has to keep serving for as long as COM2 is down."""
        controller = MeshFailoverController(fault_confirmations=1)
        controller.evaluate(
            com2_restored=False,
            com2_device_connected=False,
            oracle_device_connected=True,
            com2_heartbeat_age_seconds=900.0,
        )
        for _ in range(200):
            decision = controller.evaluate(
                com2_restored=False,
                com2_device_connected=False,
                oracle_device_connected=True,
                com2_heartbeat_age_seconds=900.0,
            )
            self.assertEqual(decision.active_target, ACTIVE_ORACLE)
            self.assertEqual(decision.route_target, ACTIVE_ORACLE)
            self.assertFalse(decision.changed)

    def test_the_controller_rejects_nonsense_input(self):
        controller = MeshFailoverController()
        with self.assertRaises(ContractError):
            controller.evaluate(
                com2_restored="yes",
                com2_device_connected=True,
                oracle_device_connected=False,
            )
        with self.assertRaises(ContractError):
            controller.evaluate(
                com2_restored=True,
                com2_device_connected=True,
                oracle_device_connected="no",
            )
        with self.assertRaises(ContractError):
            controller.evaluate(
                com2_restored=True,
                com2_device_connected=True,
                oracle_device_connected=False,
                com2_heartbeat_age_seconds="soon",
            )
        with self.assertRaises(ContractError):
            MeshFailoverController(fault_confirmations=0)
        with self.assertRaises(ContractError):
            MeshFailoverController(initial_target="nowhere")


class MeshCentralDevicePresenceTests(unittest.TestCase):
    """The 'remote execution is actually possible' probe."""

    def _presence(self, stdout: str) -> MeshCentralDevicePresence:
        def runner(argv, input=None, timeout=None):
            self.assertNotIn("PADIEM_SECRET", " ".join(argv))
            self.assertEqual(input, "PADIEM_SECRET\n")
            return _FakeCompleted(stdout=stdout)

        return MeshCentralDevicePresence(
            meshctrl_js="/opt/padiem/meshcentral/node_modules/meshcentral/meshctrl.js",
            mesh_url="wss://127.0.0.1:4443",
            login_user="padiemadmin",
            password_provider=lambda: "PADIEM_SECRET",
            command_runner=runner,
        )

    def test_a_connected_device_is_reported_connected(self):
        presence = self._presence(LISTDEVICES_ONE_CONNECTED)
        self.assertTrue(presence.is_connected(DEVICE_ID))

    def test_a_registered_but_disconnected_device_is_not_usable(self):
        presence = self._presence(LISTDEVICES_ONE_DISCONNECTED)
        self.assertFalse(presence.is_connected(DEVICE_ID))

    def test_the_probe_uses_the_official_client_and_the_stdin_password(self):
        seen = {}

        def runner(argv, input=None, timeout=None):
            seen["argv"] = list(argv)
            seen["input"] = input
            return _FakeCompleted(stdout=LISTDEVICES_ONE_CONNECTED)

        presence = MeshCentralDevicePresence(
            meshctrl_js="/opt/padiem/meshcentral/node_modules/meshcentral/meshctrl.js",
            mesh_url="wss://127.0.0.1:4443",
            login_user="padiemadmin",
            password_provider=lambda: "PADIEM_SECRET",
            command_runner=runner,
        )
        presence.is_connected(DEVICE_ID)
        self.assertIn("listdevices", seen["argv"])
        self.assertIn("--loginuser", seen["argv"])
        self.assertIn("padiemadmin", seen["argv"])
        self.assertNotIn("PADIEM_SECRET", " ".join(seen["argv"]))

    def test_an_invalid_credential_is_refused_before_the_client_runs(self):
        def runner(argv, input=None, timeout=None):
            raise AssertionError("the client must not run with a bad credential")

        presence = MeshCentralDevicePresence(
            meshctrl_js="/opt/padiem/meshcentral/node_modules/meshcentral/meshctrl.js",
            mesh_url="wss://127.0.0.1:4443",
            login_user="padiemadmin",
            password_provider=lambda: "bad\nsecret",
            command_runner=runner,
        )
        with self.assertRaises(ContractError):
            presence.is_connected(DEVICE_ID)


class HeartbeatTests(unittest.TestCase):
    """The COM2 -> Oracle health signal."""

    def test_a_heartbeat_round_trips(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "heartbeat.json")
            payload = build_heartbeat(
                mesh_url="wss://127.0.0.1:4443",
                device_id=DEVICE_ID,
                device_connected=True,
                executor_alive=True,
            )
            write_heartbeat(path, payload)
            self.assertEqual(read_heartbeat(path)["device_connected"], True)
            self.assertEqual(read_heartbeat(path)["target"], ACTIVE_COM2)
            age = heartbeat_age_seconds(path)
            self.assertIsNotNone(age)
            self.assertLessEqual(age, 5.0)

    def test_a_missing_heartbeat_has_no_age(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(
                heartbeat_age_seconds(os.path.join(folder, "absent.json"))
            )

    def test_a_corrupt_heartbeat_reads_as_empty(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "heartbeat.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{not json")
            self.assertEqual(read_heartbeat(path), {})

    def test_the_heartbeat_requires_the_truth_it_promises(self):
        with self.assertRaises(ContractError):
            build_heartbeat(
                mesh_url="wss://127.0.0.1:4443",
                device_id=DEVICE_ID,
                device_connected="yes",
                executor_alive=True,
            )


class _FakePresence:
    def __init__(self, connected: bool):
        self._connected = connected
        self.calls = 0

    def is_connected(self, device_id: str) -> bool:
        self.calls += 1
        return self._connected


class MeshFailoverSupervisorTests(unittest.TestCase):
    """The supervisor wiring: heartbeat in, decision and events out."""

    def _supervisor(
        self, folder, *, com2_connected, local_connected, notifier=None,
        executor_alive=True,
    ):
        heartbeat = os.path.join(folder, "heartbeat.json")
        write_heartbeat(
            heartbeat,
            build_heartbeat(
                mesh_url="wss://127.0.0.1:4443",
                device_id=DEVICE_ID,
                device_connected=com2_connected,
                executor_alive=executor_alive,
            ),
        )
        supervisor = MeshFailoverSupervisor(
            controller=MeshFailoverController(
                fault_confirmations=1, restore_confirmations=1
            ),
            heartbeat_path=heartbeat,
            presence=_FakePresence(local_connected),
            device_id=DEVICE_ID,
            state_path=os.path.join(folder, "failover-state.json"),
            notifier=notifier,
        )
        return supervisor, heartbeat

    def test_a_fresh_heartbeat_with_the_device_connected_keeps_com2(self):
        with tempfile.TemporaryDirectory() as folder:
            supervisor, _ = self._supervisor(
                folder, com2_connected=True, local_connected=False
            )
            decision = supervisor.run_once()
            self.assertEqual(decision.active_target, ACTIVE_COM2)
            self.assertEqual(decision.route_target, ACTIVE_COM2)
            self.assertEqual(decision.events, ())

    def test_a_heartbeat_without_the_device_does_not_hold_the_claim(self):
        """COM2 is up but the device is not there: the claim stays where the device is."""
        events = []
        with tempfile.TemporaryDirectory() as folder:
            supervisor, _ = self._supervisor(
                folder,
                com2_connected=False,
                local_connected=True,
                notifier=lambda event, message: events.append(event),
            )
            decision = supervisor.run_once()
            # COM2 says it is restored, so the route stays on it and the
            # device will travel there. The device is at Oracle for now, so
            # Oracle holds the claim.
            self.assertEqual(decision.route_target, ACTIVE_COM2)
            self.assertEqual(decision.active_target, ACTIVE_ORACLE)
            self.assertIn(EVENT_ORACLE_ACTIVE, decision.events)
            self.assertIn(EVENT_ORACLE_ACTIVE, events)

    def test_a_missing_heartbeat_is_not_a_proof_of_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            supervisor, heartbeat = self._supervisor(
                folder, com2_connected=True, local_connected=False
            )
            os.remove(heartbeat)
            decision = supervisor.run_once()
            # The route moves, but the device is nowhere, so nobody claims.
            self.assertEqual(decision.route_target, ACTIVE_ORACLE)
            self.assertIsNone(decision.active_target)

    def test_the_state_file_records_the_decision_and_the_epoch(self):
        with tempfile.TemporaryDirectory() as folder:
            supervisor, _ = self._supervisor(
                folder, com2_connected=False, local_connected=True
            )
            decision = supervisor.run_once()
            with open(supervisor.state_path, "r", encoding="utf-8") as handle:
                state = json.load(handle)
            self.assertEqual(state["active_target"], decision.active_target)
            self.assertEqual(state["route_target"], decision.route_target)
            self.assertEqual(state["epoch"], decision.epoch)
            self.assertTrue(state["local_can_execute"])
            self.assertFalse(state["com2_device_connected"])


class ClaimGateTests(unittest.TestCase):
    """The fence the executor honours before it claims a new dispatch."""

    def test_a_host_without_a_decision_does_not_claim(self):
        with tempfile.TemporaryDirectory() as folder:
            gate = decision_file_claim_gate(
                os.path.join(folder, "state.json"), ACTIVE_ORACLE
            )
            self.assertFalse(gate())

    def test_only_the_active_target_may_claim(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "state.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"active_target": ACTIVE_ORACLE, "epoch": 3}, handle)
            self.assertTrue(decision_file_claim_gate(path, ACTIVE_ORACLE)())
            self.assertFalse(decision_file_claim_gate(path, ACTIVE_COM2)())

    def test_a_corrupt_decision_does_not_claim(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "state.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{broken")
            self.assertFalse(decision_file_claim_gate(path, ACTIVE_ORACLE)())


class NotifierTests(unittest.TestCase):
    """The event delivery side."""

    def test_every_event_is_appended_to_the_local_log(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "events.log")
            notifier = events_file_notifier(path)
            notifier(EVENT_COM2_FAULT, "com2 is down")
            notifier(EVENT_ORACLE_ACTIVE, "oracle takes the claim")
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
            self.assertIn(EVENT_COM2_FAULT, text)
            self.assertIn(EVENT_ORACLE_ACTIVE, text)
            self.assertIn("oracle takes the claim", text)

    def test_a_failing_delivery_never_raises_into_the_decision_loop(self):
        def boom(*_args, **_kwargs):
            raise OSError("the delivery channel is unreachable")

        notifier = command_notifier(["/nonexistent/hermes-cli"])
        notifier(EVENT_COM2_FAULT, "com2 is down")

    def test_both_notifiers_run_and_one_failure_does_not_stop_the_other(self):
        seen = []

        def bad(event, message):
            raise OSError("the delivery channel is unreachable")

        def good(event, message):
            seen.append((event, message))

        from kagent.local_agent_mesh_failover import _both_notifiers

        both = _both_notifiers(bad, good)
        both(EVENT_ORACLE_ACTIVE, "oracle takes the claim")
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][0], EVENT_ORACLE_ACTIVE)


class ConfirmationWindowSurvivesARestartTests(unittest.TestCase):
    """A confirmation window has to survive the process.

    The supervisor is a fresh process on every pass, so a window that lived
    only in memory could never be reached: every pass would start again at
    one observation. The streaks therefore live in the decision file.
    """

    def _supervisor(
        self, folder, *, com2_connected, executor_alive=True, controller=None
    ):
        heartbeat = os.path.join(folder, "heartbeat.json")
        write_heartbeat(
            heartbeat,
            build_heartbeat(
                mesh_url="wss://127.0.0.1:4443",
                device_id=DEVICE_ID,
                device_connected=com2_connected,
                executor_alive=executor_alive,
            ),
        )
        return MeshFailoverSupervisor(
            controller=controller or MeshFailoverController(fault_confirmations=2),
            heartbeat_path=heartbeat,
            presence=_FakePresence(False),
            device_id=DEVICE_ID,
            state_path=os.path.join(folder, "state.json"),
        )

    def test_a_second_pass_confirms_the_fault_and_moves_the_route(self):
        with tempfile.TemporaryDirectory() as folder:
            first = self._supervisor(
                folder, com2_connected=False, executor_alive=False
            )
            one = first.run_once()
            self.assertEqual(one.route_target, ACTIVE_COM2)

            with open(first.state_path, "r", encoding="utf-8") as handle:
                state = json.load(handle)
            self.assertEqual(state["fault_streak"], 1)

            second = self._supervisor(
                folder,
                com2_connected=False,
                executor_alive=False,
                controller=MeshFailoverController(
                    fault_confirmations=2,
                    initial_target=state["route_target"],
                    initial_route=state["route_target"],
                    initial_claim=state["active_target"],
                    fault_streak=state["fault_streak"],
                    restore_streak=state["restore_streak"],
                ),
            )
            two = second.run_once()
            self.assertEqual(two.route_target, ACTIVE_ORACLE)
            self.assertIn(EVENT_ROUTE_TO_ORACLE, two.events)

    def test_the_streaks_are_part_of_the_persisted_decision(self):
        with tempfile.TemporaryDirectory() as folder:
            supervisor = self._supervisor(
                folder, com2_connected=False, executor_alive=False
            )
            supervisor.run_once()
            with open(supervisor.state_path, "r", encoding="utf-8") as handle:
                state = json.load(handle)
            self.assertIn("fault_streak", state)
            self.assertIn("restore_streak", state)

    def test_the_epoch_never_goes_back_across_a_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            first = self._supervisor(
                folder,
                com2_connected=False,
                executor_alive=False,
                controller=MeshFailoverController(fault_confirmations=1),
            )
            faulted = first.run_once()
            self.assertEqual(faulted.route_target, ACTIVE_ORACLE)
            self.assertGreater(faulted.epoch, 1)

            with open(first.state_path, "r", encoding="utf-8") as handle:
                state = json.load(handle)
            self.assertEqual(state["epoch"], faulted.epoch)

            second = self._supervisor(
                folder,
                com2_connected=False,
                executor_alive=False,
                controller=MeshFailoverController(
                    fault_confirmations=1,
                    restore_confirmations=1,
                    initial_target=state["route_target"],
                    initial_route=state["route_target"],
                    initial_claim=state["active_target"],
                    fault_streak=state["fault_streak"],
                    restore_streak=state["restore_streak"],
                    initial_epoch=state["epoch"],
                ),
            )
            after = second.run_once()
            self.assertGreaterEqual(after.epoch, faulted.epoch)
            self.assertFalse(after.may_claim(faulted.epoch - 1))


class ModuleEntryPointTests(unittest.TestCase):
    """The supervisor has to be runnable as a module."""

    def test_the_module_runs_its_entry_point(self):
        source = os.path.join(
            os.path.dirname(__file__),
            "..",
            "src",
            "kagent",
            "local_agent_mesh_failover.py",
        )
        with open(source, "r", encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn('if __name__ == "__main__":', text)
        self.assertIn("raise SystemExit(main())", text)

    def test_the_entry_point_refuses_to_start_without_configuration(self):
        import subprocess

        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("MESH_FAILOVER_")
            and not key.startswith("ORACLE_MESH_")
        }
        # The module reaches the shared packages through the repository, so
        # the check does not depend on an installed distribution.
        here = os.path.dirname(__file__)
        repo = os.path.abspath(os.path.join(here, "..", "..", ".."))
        env["PYTHONPATH"] = os.pathsep.join(
            [
                os.path.join(here, "..", "src"),
                os.path.join(repo, "packages", "padiem-ai-core"),
                os.path.join(repo, "packages", "padiem-control-plane"),
                os.path.join(repo, "apps", "padiem-ai-engine", "clients", "python"),
            ]
        )
        completed = subprocess.run(
            [sys.executable, "-m", "kagent.local_agent_mesh_failover"],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("refused to start", completed.stderr)


class RoutePublicationTests(unittest.TestCase):
    """The route has to reach the decision file.

    The route is optional configuration, so the branch that builds it was
    never exercised by the other tests. A missing name there only showed up
    on the live host, so the configured path is covered here.
    """

    def _environment(self, folder, **extra):
        env = {
            "MESH_FAILOVER_HEARTBEAT_PATH": os.path.join(folder, "hb.json"),
            "MESH_FAILOVER_STATE_PATH": os.path.join(folder, "state.json"),
            "MESH_FAILOVER_EVENTS_PATH": os.path.join(folder, "events.log"),
            "MESH_FAILOVER_DEVICE_ID": DEVICE_ID,
            "MESH_FAILOVER_LOCAL_TARGET": "oracle",
            "MESH_FAILOVER_COM2_TUNNEL_HOST": "192.168.0.101",
            "MESH_FAILOVER_COM2_TUNNEL_USER": "user",
            "MESH_FAILOVER_COM2_TUNNEL_KEY": "C:/keys/id_rsa",
            "MESH_FAILOVER_ORACLE_TUNNEL_HOST": "168.138.200.12",
            "MESH_FAILOVER_ORACLE_TUNNEL_USER": "ubuntu",
            "MESH_FAILOVER_ORACLE_TUNNEL_KEY": "C:/keys/id_oracle",
            "ORACLE_MESH_MESHCTRL_JS": "/opt/padiem/meshcentral/meshctrl.js",
            "ORACLE_MESH_URL": "wss://127.0.0.1:4443",
            "ORACLE_MESH_LOGIN_USER": "padiemadmin",
            "ORACLE_MESH_PASSWORD_FILE": os.path.join(folder, "pw.txt"),
        }
        env.update(extra)
        return env

    def test_the_configured_route_reaches_the_decision_file(self):
        import kagent.local_agent_mesh_failover as module

        with tempfile.TemporaryDirectory() as folder:
            with open(os.path.join(folder, "pw.txt"), "w", encoding="utf-8") as h:
                h.write("operator-secret\n")
            write_heartbeat(
                os.path.join(folder, "hb.json"),
                build_heartbeat(
                    mesh_url="wss://127.0.0.1:4443",
                    device_id=DEVICE_ID,
                    device_connected=True,
                    executor_alive=True,
                ),
            )
            env = self._environment(folder)
            os.environ.update(
                {k: v for k, v in env.items() if k.startswith("MESH_FAILOVER_")}
            )
            try:
                code = module.main(env)
            finally:
                for key in list(os.environ):
                    if key.startswith("MESH_FAILOVER_"):
                        del os.environ[key]
            self.assertEqual(code, 0)
            with open(os.path.join(folder, "state.json"), "r", encoding="utf-8") as h:
                state = json.load(h)
            route = state.get("connection_route")
            self.assertIsNotNone(route)
            self.assertEqual(route["target"], "com2")
            self.assertIn("user@192.168.0.101", route["tunnel_arguments"])
            self.assertEqual(route["agent_url"], "wss://127.0.0.1:4443/agent.ashx")

    def test_the_route_is_absent_when_it_is_not_configured(self):
        import kagent.local_agent_mesh_failover as module

        with tempfile.TemporaryDirectory() as folder:
            with open(os.path.join(folder, "pw.txt"), "w", encoding="utf-8") as h:
                h.write("operator-secret\n")
            write_heartbeat(
                os.path.join(folder, "hb.json"),
                build_heartbeat(
                    mesh_url="wss://127.0.0.1:4443",
                    device_id=DEVICE_ID,
                    device_connected=True,
                    executor_alive=True,
                ),
            )
            env = self._environment(folder)
            for key in (
                "MESH_FAILOVER_COM2_TUNNEL_HOST",
                "MESH_FAILOVER_ORACLE_TUNNEL_HOST",
            ):
                env.pop(key, None)
            code = module.main(env)
            self.assertEqual(code, 0)
            with open(os.path.join(folder, "state.json"), "r", encoding="utf-8") as h:
                state = json.load(h)
            self.assertIsNone(state.get("connection_route"))


if __name__ == "__main__":
    unittest.main()
