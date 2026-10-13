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
        self.assertEqual(len(calls), 6)
        self.assertEqual(sum(url.endswith("/deployments") for url in calls), 4)
        self.assertTrue(all(url.startswith("https://api.cloudflare.com/client/v4/") for url in calls))
        self.assertEqual(proof["served_worker_count"], 2)
        self.assertFalse(proof["deployed_source_parity_proven"])
        self.assertFalse(proof["production_rpc_release_authorized"])
        self.assertNotIn(STATE, json.dumps(proof))
        self.assertNotIn(EDGE, json.dumps(proof))
        self.assertNotIn("private-synthetic-token", json.dumps(proof))

    def test_served_runtime_metadata_compared_to_pinned_source_configs(self):
        # Cloudflare script_runtime is metadata, never deployed code proof.
        for worker in audit.WORKERS:
            detail = version_detail()
            detail["result"]["resources"]["script_runtime"] = {
                "compatibility_date": "2026-09-04",
                "compatibility_flags": ["disable_python_external_sdk", "python_workers"],
            }
            result = audit.compare_served_runtime_config(detail, worker)
            self.assertTrue(result["served_runtime_metadata_complete"])
            self.assertTrue(result["served_runtime_configuration_matches_reviewed_source"])
            detail["result"]["resources"]["script_runtime"]["compatibility_flags"] = [
                "python_workers", "unexpected_flag",
            ]
            result = audit.compare_served_runtime_config(detail, worker)
            self.assertTrue(result["served_runtime_metadata_complete"])
            self.assertFalse(result["served_runtime_configuration_matches_reviewed_source"])
            detail["result"]["resources"]["script_runtime"]["compatibility_flags"] = [
                "python_workers", "python_workers",
            ]
            self.assertFalse(audit.compare_served_runtime_config(
                detail, worker)["served_runtime_configuration_matches_reviewed_source"])
            del detail["result"]["resources"]["script_runtime"]
            result = audit.compare_served_runtime_config(detail, worker)
            self.assertFalse(result["served_runtime_metadata_complete"])
            self.assertFalse(result["served_runtime_configuration_matches_reviewed_source"])
        with self.assertRaises(ValueError):
            audit.compare_served_runtime_config(version_detail(), "unreviewed-worker")

    def test_served_export_types_are_not_a_source_or_rpc_attestation(self):
        expected = {
            "padiem-local-agent-broker-state": "LocalAgentBrokerDurableObject",
            "padiem-local-agent-broker-edge": None,
        }
        for worker, do_name in expected.items():
            d = version_detail()
            exports = {"default": {"type": "worker", "state": "created"}}
            if do_name:
                exports[do_name] = {"type": "durable-object", "storage": "sqlite"}
            d["result"]["resources"]["script_runtime"] = {"exports": exports}
            result = audit.compare_served_worker_exports(d, worker)
            self.assertTrue(result["served_export_metadata_complete"])
            self.assertTrue(result["served_export_types_match_reviewed_source"])
            self.assertEqual(result["served_default_entrypoint_shape"], "worker")
            self.assertEqual(result["served_canonical_do_shape"],
                             "sqlite" if do_name else "not_applicable")
            exports["default"]["type"] = "durable-object"
            # Python implicit WorkerEntrypoint is not guaranteed to appear
            # in version declarative exports; never treat that omission alone
            # as a concrete deployed source mismatch.
            diagnostic = audit.compare_served_worker_exports(d, worker)
            self.assertEqual(diagnostic["served_default_entrypoint_shape"], "other")
            self.assertTrue(diagnostic["served_export_types_match_reviewed_source"])
            exports["default"]["type"] = "worker"
            exports["UnexpectedDO"] = {"type": "durable-object", "storage": "sqlite"}
            self.assertFalse(audit.compare_served_worker_exports(
                d, worker)["served_export_types_match_reviewed_source"])
            del d["result"]["resources"]["script_runtime"]
            absent = audit.compare_served_worker_exports(d, worker)
            self.assertFalse(absent["served_export_metadata_complete"])
            self.assertFalse(absent["served_export_types_match_reviewed_source"])
        d = version_detail()
        d["result"]["resources"]["script_runtime"] = {
            "exports": {"default": {"type": "worker"}}
        }
        self.assertFalse(audit.compare_served_worker_exports(
            d, "padiem-local-agent-broker-state")["served_export_types_match_reviewed_source"])
        # The production Python API can omit the implicit default entrypoint
        # while still reporting the reviewed DO export precisely.
        d["result"]["resources"]["script_runtime"]["exports"] = {
            "LocalAgentBrokerDurableObject": {
                "type": "durable-object", "storage": "sqlite"
            }
        }
        no_default = audit.compare_served_worker_exports(d, "padiem-local-agent-broker-state")
        self.assertTrue(no_default["served_export_types_match_reviewed_source"])
        self.assertEqual(no_default["served_default_entrypoint_shape"], "absent")
        with self.assertRaises(ValueError):
            audit.compare_served_worker_exports(d, "unknown-target")

    def test_deployment_changed_between_two_reads_fails_closed(self):
        calls = {}
        def requester(url, *, token):
            if url.endswith("/deployments"):
                n = calls.get(url, 0) + 1
                calls[url] = n
                if url.endswith("/padiem-local-agent-broker-state/deployments"):
                    return 200, deployments(STATE if n == 1 else EDGE)
                return 200, deployments(EDGE)
            if url.endswith("/versions/" + STATE):
                return 200, version_detail(STATE)
            if url.endswith("/versions/" + EDGE):
                return 200, version_detail(EDGE)
            raise AssertionError("unexpected GET")
        with self.assertRaisesRegex(ValueError, "drifted during readback"):
            audit.audit(account_id="syntheticacct42", token="private", requester=requester)
        self.assertEqual(calls.get(next(k for k in calls if "broker-state" in k)), 2)

    def test_invalid_canonical_envelope_fails_without_guessing_a_version(self):
        # The canonical resolver accepts only the documented Cloudflare
        # deployment envelope, never a raw list or an invented shortcut.
        for payload in (
            [{"versions": [{"percentage": 100, "version_id": STATE}]}],
            {"success": True, "result": {"versions": [
                {"percentage": 100, "version_id": STATE},
            ]}},
            {"success": True, "result": {"deployments": [
                {"versions": [{"percentage": 100.0, "version_id": STATE}]},
            ]}},
        ):
            if isinstance(payload, dict) and payload.get("result", {}).get("deployments"):
                # Canonical resolver intentionally accepts 100.0 == 100; it
                # is still a single full-traffic version, not a split.
                self.assertEqual(audit.parse_served_version(payload), STATE)
            else:
                with self.assertRaises(ValueError):
                    audit.parse_served_version(payload)

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
