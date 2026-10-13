"""Negative-only Broker State/Edge Cloudflare deployment revision readback tests."""
from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import json
import sys
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import b62_connector_broker_served_version_readonly as audit

STATE = "a97e08ee-c8cb-456e-b40c-532448bb191a"
EDGE = "f2e6049e-7a72-4c46-a7c0-e9aa74cdb8ba"


def deployments(version=STATE):
    return {"success": True, "result": {"deployments": [
        {"versions": [{"percentage": 100, "version_id": version}]},
    ]}}


def version_detail(version=STATE):
    return {"success": True, "result": {"id": version,
        "resources": {"script": {"etag": "synthetic-etag-not-source-proof"}}}}


class BrokerVersionReadbackTest(unittest.TestCase):
    def test_single_100_percent_served_version_required(self):
        self.assertEqual(audit.parse_served_version(deployments()), STATE)
        for bad in (
            {}, {"success": False, "result": {}},
            {"success": True, "result": {}},
            {"success": True, "result": {"deployments": []}},
            {"success": True, "result": {"deployments": [
                {"versions": [{"percentage": 50, "version_id": STATE},
                              {"percentage": 50, "version_id": EDGE}]},
            ]}},
            deployments("not-a-version"),
            {"success": True, "result": {"deployments": [
                {"versions": [{"percentage": True, "version_id": STATE}]},
            ]}},
        ):
            with self.assertRaises(ValueError):
                audit.parse_served_version(bad)

    def test_served_version_detail_never_proves_source_parity(self):
        proof = audit.validate_served_version_detail(version_detail(), STATE)
        self.assertTrue(proof["served_version_detail_readable"])
        self.assertTrue(proof["served_script_etag_present"])
        self.assertFalse(proof["reviewed_source_parity_attested"])
        self.assertFalse(proof["authenticated_broker_rpc_proven"])
        with self.assertRaises(ValueError):
            audit.validate_served_version_detail(version_detail(EDGE), STATE)

    def test_both_served_workers_readback_and_no_sensitive_identifiers_output(self):
        calls = []
        def requester(url, *, token):
            self.assertEqual(token, "private-synthetic-token")
            calls.append(url)
            if url.endswith("/padiem-local-agent-broker-state/deployments"):
                return 200, deployments(STATE)
            if url.endswith("/padiem-local-agent-broker-edge/deployments"):
                return 200, deployments(EDGE)
            if url.endswith("/versions/" + STATE):
                return 200, version_detail(STATE)
            if url.endswith("/versions/" + EDGE):
                return 200, version_detail(EDGE)
            raise AssertionError("unexpected Cloudflare request")
        proof = audit.audit(account_id="syntheticacct42", token="private-synthetic-token",
                            requester=requester)
        self.assertEqual(len(calls), 4)
        self.assertTrue(all(url.startswith("https://api.cloudflare.com/client/v4/") for url in calls))
        self.assertEqual(proof["served_worker_count"], 2)
        self.assertFalse(proof["deployed_source_parity_proven"])
        self.assertFalse(proof["production_rpc_release_authorized"])
        self.assertNotIn(STATE, json.dumps(proof))
        self.assertNotIn(EDGE, json.dumps(proof))
        self.assertNotIn("private-synthetic-token", json.dumps(proof))

    def test_missing_or_unavailable_version_response_fails_readback(self):
        with self.assertRaises(ValueError):
            audit.audit(account_id="syntheticacct42", token="private",
                        requester=lambda url, *, token: (403, {}))

    def test_holds_do_not_convert_into_release_authorization(self):
        output = StringIO()
        with patch.dict("os.environ", {"CLOUDFLARE_API_TOKEN": "secret-private-token",
                                        "CLOUDFLARE_ACCOUNT_ID": "syntheticacct42"}):
            with patch.object(audit, "audit", side_effect=ValueError("redacted")):
                with redirect_stdout(output):
                    code = audit.main()
        self.assertEqual(code, 0)  # non-release evidence cannot break existing B62 Chat
        self.assertIn("BROKER_SERVED_VERSION_READBACK=HOLD", output.getvalue())
        self.assertIn('"production_rpc_release_authorized": false', output.getvalue())
        self.assertNotIn("secret-private-token", output.getvalue())
        self.assertNotIn("syntheticacct42", output.getvalue())


if __name__ == "__main__":
    unittest.main()
