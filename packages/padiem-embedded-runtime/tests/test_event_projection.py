"""Focused contract tests: public-safe event projection (S2)."""

import unittest

from padiem_embedded_runtime import SidecarContractError, project_event


class EventProjectionTests(unittest.TestCase):
    def test_public_notice_projects(self):
        event = project_event(
            "notice.posted", "evt-host-01", 2, "Panel ready", {"engine_ok": "True"}
        )
        public = event.to_public_dict()
        self.assertEqual(public["type"], "notice.posted")
        self.assertEqual(public["seq"], 2)
        import json

        json.dumps(public)

    def test_rejects_unknown_types(self):
        with self.assertRaises(SidecarContractError):
            project_event("tool.result", "h", 0, "output")

    def test_rejects_non_public_material(self):
        with self.assertRaises(SidecarContractError):
            project_event("notice.posted", "h", 0, "internal reasoning trace")
        with self.assertRaises(SidecarContractError):
            project_event("notice.posted", "h", 0, "ok", {"tool_args": "{}"})
        with self.assertRaises(SidecarContractError):
            project_event("notice.posted", "h", 0, "ok", {"note": "raw terminal stdout"})
        with self.assertRaises(SidecarContractError):
            project_event("notice.posted", "h", 0, "api_key visible")

    def test_rejects_bad_seq_and_bounds(self):
        with self.assertRaises(SidecarContractError):
            project_event("notice.posted", "h", -1, "ok")
        with self.assertRaises(SidecarContractError):
            project_event("notice.posted", "h", True, "ok")
        with self.assertRaises(SidecarContractError):
            project_event("notice.posted", "h", 0, "x" * 281)


if __name__ == "__main__":
    unittest.main()
