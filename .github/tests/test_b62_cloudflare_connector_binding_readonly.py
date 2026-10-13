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
