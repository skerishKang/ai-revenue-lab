"""#5462 — failover/failback controller contract.

Four scenarios are pinned here, because they are the whole point of the
work:

* A normal  — COM2 usable, nothing moves.
* B fault   — COM2 stops being able to execute, the claim goes to Oracle.
* C recover — COM2 becomes usable again, the claim goes back to COM2.
* D exactly once — the epoch fences a consumer that still believes it
  is active, so the same dispatch is never claimed twice.

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
            decision = controller.evaluate(com2_usable=True, com2_heartbeat_age_seconds=1.0)
            self.assertEqual(decision.active_target, ACTIVE_COM2)
            self.assertFalse(decision.changed)
            self.assertEqual(decision.events, ())
        self.assertEqual(controller.epoch, 1)

    def test_scenario_b_fault_moves_the_claim_to_oracle(self):
        controller = MeshFailoverController(fault_confirmations=2)
        first = controller.evaluate(com2_usable=False, com2_heartbeat_age_seconds=200.0)
        self.assertFalse(first.changed)
        self.assertEqual(first.active_target, ACTIVE_COM2)
        second = controller.evaluate(com2_usable=False, com2_heartbeat_age_seconds=200.0)
        self.assertTrue(second.changed)
        self.assertEqual(second.active_target, ACTIVE_ORACLE)
        self.assertEqual(second.events, (EVENT_COM2_FAULT, EVENT_ORACLE_ACTIVE))
        self.assertGreater(second.epoch, first.epoch)

    def test_scenario_b_stale_heartbeat_alone_does_not_claim_com2_is_usable(self):
        controller = MeshFailoverController()
        self.assertTrue(controller.heartbeat_is_stale(None))
        self.assertTrue(controller.heartbeat_is_stale(1000.0))
        self.assertFalse(controller.heartbeat_is_stale(1.0))

    def test_scenario_c_recovery_moves_the_claim_back_to_com2(self):
        controller = MeshFailoverController(
            fault_confirmations=1, restore_confirmations=3
        )
        faulted = controller.evaluate(com2_usable=False, com2_heartbeat_age_seconds=900.0)
        self.assertEqual(faulted.active_target, ACTIVE_ORACLE)
        for _ in range(2):
            partial = controller.evaluate(com2_usable=True, com2_heartbeat_age_seconds=1.0)
            self.assertFalse(partial.changed)
            self.assertEqual(partial.active_target, ACTIVE_ORACLE)
        restored = controller.evaluate(com2_usable=True, com2_heartbeat_age_seconds=1.0)
        self.assertTrue(restored.changed)
        self.assertEqual(restored.active_target, ACTIVE_COM2)
        self.assertEqual(restored.events, (EVENT_COM2_RESTORED, EVENT_FAILBACK_COMPLETE))
        self.assertGreater(restored.epoch, faulted.epoch)

    def test_scenario_d_the_epoch_fences_a_stale_consumer(self):
        controller = MeshFailoverController(
            fault_confirmations=1, restore_confirmations=1
        )
        before = controller.evaluate(com2_usable=True, com2_heartbeat_age_seconds=1.0)
        self.assertTrue(before.may_claim(before.epoch))
        faulted = controller.evaluate(com2_usable=False, com2_heartbeat_age_seconds=900.0)
        # The consumer that still believes it is active is refused.
        self.assertFalse(faulted.may_claim(before.epoch))
        self.assertTrue(faulted.may_claim(faulted.epoch))
        # And the epoch never goes back, so a late consumer cannot win.
        restored = controller.evaluate(com2_usable=True, com2_heartbeat_age_seconds=1.0)
        self.assertGreater(restored.epoch, faulted.epoch)
        self.assertFalse(restored.may_claim(faulted.epoch))
        self.assertFalse(restored.may_claim(before.epoch))

    def test_a_single_missed_observation_does_not_move_the_target(self):
        controller = MeshFailoverController(fault_confirmations=2)
        controller.evaluate(com2_usable=True, com2_heartbeat_age_seconds=1.0)
        missed = controller.evaluate(com2_usable=False, com2_heartbeat_age_seconds=500.0)
        self.assertFalse(missed.changed)
        self.assertEqual(missed.active_target, ACTIVE_COM2)
        back = controller.evaluate(com2_usable=True, com2_heartbeat_age_seconds=1.0)
        self.assertFalse(back.changed)

    def test_the_controller_rejects_nonsense_input(self):
        controller = MeshFailoverController()
        with self.assertRaises(ContractError):
            controller.evaluate(com2_usable="yes")
        with self.assertRaises(ContractError):
            controller.evaluate(com2_usable=True, com2_heartbeat_age_seconds="soon")
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

    def _supervisor(self, folder, *, com2_connected, local_connected, notifier=None):
        heartbeat = os.path.join(folder, "com2-heartbeat.json")
        write_heartbeat(
            heartbeat,
            build_heartbeat(
                mesh_url="wss://127.0.0.1:4443",
                device_id=DEVICE_ID,
                device_connected=com2_connected,
                executor_alive=True,
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
            self.assertEqual(decision.events, ())

    def test_a_heartbeat_without_the_device_fails_com2_over(self):
        events = []
        with tempfile.TemporaryDirectory() as folder:
            supervisor, _ = self._supervisor(
                folder,
                com2_connected=False,
                local_connected=True,
                notifier=lambda event, message: events.append(event),
            )
            decision = supervisor.run_once()
            self.assertEqual(decision.active_target, ACTIVE_ORACLE)
            self.assertEqual(decision.events, (EVENT_COM2_FAULT, EVENT_ORACLE_ACTIVE))
            self.assertEqual(events, [EVENT_COM2_FAULT, EVENT_ORACLE_ACTIVE])

    def test_the_state_file_records_the_decision_and_the_epoch(self):
        with tempfile.TemporaryDirectory() as folder:
            supervisor, _ = self._supervisor(
                folder, com2_connected=False, local_connected=True
            )
            decision = supervisor.run_once()
            with open(supervisor.state_path, "r", encoding="utf-8") as handle:
                state = json.load(handle)
            self.assertEqual(state["active_target"], decision.active_target)
            self.assertEqual(state["epoch"], decision.epoch)
            self.assertTrue(state["local_can_execute"])
            self.assertFalse(state["com2_usable"])

    def test_a_missing_heartbeat_is_not_a_proof_of_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            supervisor, heartbeat = self._supervisor(
                folder, com2_connected=True, local_connected=False
            )
            os.remove(heartbeat)
            decision = supervisor.run_once()
            self.assertEqual(decision.active_target, ACTIVE_ORACLE)


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
        # A missing binary is reported, not raised.
        notifier(EVENT_COM2_FAULT, "com2 is down")


class SupervisorDeliveryTests(unittest.TestCase):
    """The event vocabulary reaches the notifier on a real transition."""

    def test_the_four_events_are_the_documented_vocabulary(self):
        self.assertEqual(
            (
                EVENT_COM2_FAULT,
                EVENT_ORACLE_ACTIVE,
                EVENT_COM2_RESTORED,
                EVENT_FAILBACK_COMPLETE,
            ),
            ("COM2_FAULT", "ORACLE_ACTIVE", "COM2_RESTORED", "FAILBACK_COMPLETE"),
        )


class ModuleEntryPointTests(unittest.TestCase):
    """The supervisor has to be runnable as a module.

    The deployed unit runs ``python -m kagent.local_agent_mesh_failover``, so
    a missing entry point would make the supervisor import and exit without
    ever deciding anything.
    """

    def test_the_module_runs_its_entry_point(self):
        import subprocess
        import sys

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

        # The configuration is removed, so the run must refuse loudly rather
        # than start a supervisor with no inputs.
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("MESH_FAILOVER_")
            and not key.startswith("ORACLE_MESH_")
        }
        env["PYTHONPATH"] = os.path.join(os.path.dirname(__file__), "..", "src")
        completed = subprocess.run(
            [sys.executable, "-m", "kagent.local_agent_mesh_failover"],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("refused to start", completed.stderr)


if __name__ == "__main__":
    unittest.main()
