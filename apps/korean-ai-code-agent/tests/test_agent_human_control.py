from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from kagent.agent_human_control import (
    AGENT_ACTIONS_QUEUE_DURING_HUMAN_CONTROL,
    RAW_SECRET_ENTRY_STORED,
    AgentHumanControl,
    ControlHolder,
)
from kagent.contracts import ContractError


NOW = datetime(2026, 9, 3, 3, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.value = NOW

    def __call__(self):
        return self.value


class AgentHumanControlTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.control = AgentHumanControl("computer_1", now=self.clock)

    def test_help_request_expires_without_timing_out_active_human_control(self):
        state = self.control.request_help("Login requires MFA")
        self.assertTrue(state.help_requested)
        self.clock.value += timedelta(minutes=11)
        expired = self.control.get()
        self.assertFalse(expired.help_requested)
        self.assertEqual(expired.holder, ControlHolder.AGENT)

    def test_agent_actions_are_refused_while_human_drives_and_never_queued(self):
        self.control.request_help("Need person")
        self.control.take(control_session_ref="control_session_1")
        with self.assertRaises(ContractError):
            self.control.assert_agent_may_act()
        self.assertFalse(AGENT_ACTIONS_QUEUE_DURING_HUMAN_CONTROL)
        self.assertTrue(
            self.control.human_may_drive(control_session_ref="control_session_1")
        )

    def test_release_requires_exact_control_session(self):
        self.control.take(control_session_ref="control_session_1")
        with self.assertRaises(ContractError):
            self.control.release(control_session_ref="control_session_2")
        state = self.control.release(control_session_ref="control_session_1")
        self.assertEqual(state.holder, ControlHolder.AGENT)
        self.control.assert_agent_may_act()

    def test_secret_request_stores_reference_metadata_only(self):
        state = self.control.request_secret(
            label="password",
            field_ref="field_password",
            snapshot_ref="snapshot_1",
        )
        rendered = state.safe_dict()
        self.assertFalse(rendered["raw_secret_value"])
        self.assertFalse(rendered["pending_secret"]["secret_value_present"])
        self.assertEqual(rendered["pending_secret"]["field_ref"], "field_password")
        self.assertFalse(RAW_SECRET_ENTRY_STORED)

    def test_secret_request_is_cleared_only_after_success_marker(self):
        self.control.request_secret(
            label="MFA code",
            field_ref="field_mfa",
            snapshot_ref="snapshot_2",
        )
        self.assertIsNotNone(self.control.pending_secret())
        self.control.mark_secret_supplied()
        self.assertIsNone(self.control.pending_secret())

    def test_takeover_clears_pending_secret(self):
        self.control.request_secret(
            label="password",
            field_ref="field_password",
            snapshot_ref="snapshot_1",
        )
        state = self.control.take(control_session_ref="control_session_1")
        self.assertEqual(state.holder, ControlHolder.HUMAN)
        self.assertIsNone(state.pending_secret)

    def test_control_session_ref_cannot_contain_secret_material(self):
        with self.assertRaises(ContractError):
            self.control.take(control_session_ref="token=supersecretvalue")


if __name__ == "__main__":
    unittest.main()
