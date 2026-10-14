"""No-secret/no-mutation Cloudflare metadata inventory on synthetic API payloads."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / "scripts" / "b62_cloudflare_connector_binding_readonly.py"
spec = importlib.util.spec_from_file_location("connector_bindings_readonly", PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class DeployedBindingAuditTest(unittest.TestCase):
    def test_absent_is_not_an_assumed_service_name(self):
        requested = []
        def fetch(url):
            requested.append(url)
            return 200, {"success": True, "result": {"bindings": [
                {"name": "B14_SERVICE", "type": "service",
                 "service": "ai-revenue-korean-ai-platform"},
                {"name": "PADIEM_CHAT_DB", "type": "d1", "database_id": "hidden"},
                {"name": "TOKEN", "type": "secret_text", "text": "DO_NOT_EXPOSE"},
            ]}}
        result = module.inspect_deployed_gateway_bindings(
            account_id="testaccount1234", token="fixture", requester=fetch)
        self.assertEqual([x.status for x in result], ["absent", "absent"])
        self.assertEqual(len(requested), 1)
        self.assertNotIn("DO_NOT_EXPOSE", str(result))

    def test_target_is_read_from_actual_metadata_not_guesswork(self):
        requested = []
        def fetch(url):
            requested.append(url)
            if url.endswith("/padiem-chat/settings"):
                return 200, {"success": True, "result": {"bindings": [
                    {"name": "IDENTITY_AUTHORITY_SERVICE", "type": "service",
                     "service": "canonical-identity"},
                    {"name": "LOCAL_AGENT_BROKER_AUTHORITY_SERVICE", "type": "service",
                     "service": "canonical-broker"},
                ]}}
            return 200, {"success": True, "result": {"bindings": []}}
        result = module.inspect_deployed_gateway_bindings(
            account_id="testaccount1234", token="fixture", requester=fetch)
        self.assertEqual([x.status for x in result], ["target_settings_readable"] * 2)
        self.assertEqual([x.target for x in result], ["canonical-identity", "canonical-broker"])
        self.assertEqual(len(requested), 3)
        self.assertTrue(all("/workers/scripts/" in x for x in requested))
        self.assertTrue(all(x.startswith(module.API + "/") for x in requested))

    def test_wrong_type_or_invalid_target_does_not_issue_outbound_get(self):
        calls = []
        def fetch(url):
            calls.append(url)
            return 200, {"success": True, "result": {"bindings": [
                {"name": "IDENTITY_AUTHORITY_SERVICE", "type": "plain_text",
                 "text": "secret-value"},
                {"name": "LOCAL_AGENT_BROKER_AUTHORITY_SERVICE", "type": "service",
                 "service": "https://other.example/"},
            ]}}
        result = module.inspect_deployed_gateway_bindings(
            account_id="testaccount1234", token="fixture", requester=fetch)
        self.assertEqual([x.status for x in result], ["invalid_type_or_target"] * 2)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("secret-value", str(result))

    def test_duplicate_and_missing_bindings_field_fail_closed(self):
        for result in (
            {"success": False, "result": {"bindings": []}},
            {"success": True, "result": {}},
            {"success": True, "result": {"bindings": [
                {"name": "IDENTITY_AUTHORITY_SERVICE", "type": "service", "service": "a"},
                {"name": "IDENTITY_AUTHORITY_SERVICE", "type": "service", "service": "b"},
            ]}},
        ):
            with self.assertRaises(ValueError):
                module.parse_deployed_settings(result)

    def test_readonly_get_never_includes_secrets_in_user_output(self):
        from unittest.mock import patch
        calls = []
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, limit):
                return b'{"success":true,"result":{"bindings":[]}}'
        def transport(request, *, timeout):
            calls.append(request)
            return Response()
        code, data = module.get_json(
            module.API + "/accounts/abc/workers/scripts/padiem-chat/settings",
            token="do-not-log-this", transport=transport)
        self.assertEqual(code, 200)
        self.assertEqual(calls[0].get_method(), "GET")
        self.assertNotIn("do-not-log-this", str(data))
        self.assertEqual(len(calls), 1)
        self.assertEqual(len([x for x in calls if x.get_method() != "GET"]), 0)


if __name__ == "__main__":
    unittest.main()



class BrokerSourceWorkerAuditTest(unittest.TestCase):
    def test_broker_worker_candidates_match_checked_in_control_plane_jsonc(self):
        import json
        root = Path(__file__).resolve().parents[2] / "packages" / "padiem-control-plane"
        for candidate, filename in (
            ("padiem-local-agent-broker-state", "wrangler.local-agent-broker.jsonc"),
            ("padiem-local-agent-broker-edge", "wrangler.local-agent-broker-edge.jsonc"),
        ):
            config = json.loads((root / filename).read_text(encoding="utf-8"))
            self.assertEqual(config["name"], candidate)

    def test_broker_source_absence_is_not_interpreted_as_deployed(self):
        urls = []
        def request(url):
            urls.append(url)
            return 404, {}
        rows = module.inspect_deployed_broker_workers(
            account_id="testaccount1234", token="fixture", requester=request)
        self.assertEqual(len(urls), 2)
        self.assertEqual([x["settings_readable"] for x in rows], [False, False])
        self.assertFalse(any(x.get("broker_state_do_binding_present", False) for x in rows))
        self.assertFalse(any(x.get("private_state_worker_binding_present", False) for x in rows))

    def test_existing_broker_workers_require_exact_private_shape(self):
        def request(url):
            if url.endswith("/padiem-local-agent-broker-state/settings"):
                return 200, {"success": True, "result": {"bindings": [
                    {"name": "LOCAL_AGENT_BROKER_STATE", "type": "durable_object_namespace"},
                    {"name": "LOCAL_AGENT_BROKER_PEPPER", "type": "secret_text", "text": "DO_NOT_REPORT"},
                ]}}
            if url.endswith("/padiem-local-agent-broker-edge/settings"):
                return 200, {"success": True, "result": {"bindings": [
                    {"name": "LOCAL_AGENT_BROKER_SERVICE", "type": "service",
                     "service": "padiem-local-agent-broker-state"},
                ]}}
            raise AssertionError("Unapproved metadata path")
        rows = module.inspect_deployed_broker_workers(
            account_id="testaccount1234", token="fixture", requester=request)
        self.assertEqual([x["settings_readable"] for x in rows], [True, True])
        self.assertTrue(rows[0]["broker_state_do_binding_present"])
        self.assertTrue(rows[0]["broker_pepper_binding_present"])
        self.assertTrue(rows[1]["private_state_worker_binding_present"])
        self.assertNotIn("DO_NOT_REPORT", str(rows))

