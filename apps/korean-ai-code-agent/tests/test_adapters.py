from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kagent.adapters import DeterministicBusiness14Preview
from kagent.contracts import ExecutionMode
from kagent.core import AgentSession


class AdapterBoundaryTests(unittest.TestCase):
    def test_business14_preview_stays_backward_compatible_and_network_free(self):
        adapter = DeterministicBusiness14Preview()
        first = adapter.preview(task="로그인 오류를 분석해줘", route="business14/auto")
        second = adapter.preview(task="로그인 오류를 분석해줘", route="business14/auto")
        self.assertEqual(first, second)
        self.assertEqual(first["route"], "b14/auto")
        self.assertFalse(first["network_called"])
        self.assertEqual(first["status"], "resolved_not_called")
        self.assertNotIn("credential", first)
        self.assertNotIn("provider_secret", first)

    def test_phase1_session_projects_into_claw_intent_without_route_authority(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            session = AgentSession.open(
                root,
                "로그인 오류를 분석해줘",
                route="provider-specific-model-marker",
            )
            intent = session.task_intent(
                task_id="task_bridge_001",
                execution_mode=ExecutionMode.CLOUD,
                source_surface="cli",
                requested_revision="abc123",
            )
            rendered = intent.safe_dict()
            self.assertEqual(rendered["repository_ref"], str(root.resolve()))
            self.assertEqual(rendered["execution_mode"], "cloud")
            self.assertNotIn("route", rendered)
            self.assertNotIn("provider-specific-model-marker", str(rendered))


if __name__ == "__main__":
    unittest.main()
