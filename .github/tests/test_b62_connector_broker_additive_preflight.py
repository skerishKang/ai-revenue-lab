"""#4139 candidate-only Broker Service Binding preservation and refusal tests."""
from __future__ import annotations
from pathlib import Path
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import b62_connector_broker_additive_preflight as planner
from b62_cloudflare_production_deploy_config import ProductionConfigError

PUBLIC = "https://chat.padiem.net"


def live():
    return {"success": True, "result": {"bindings": [
        {"type": "assets", "name": "ASSETS"},
        {"type": "service", "name": "B14_SERVICE", "service": "ai-revenue-korean-ai-platform"},
        {"type": "service", "name": "IDENTITY_AUTHORITY_SERVICE",
         "service": "padiem-control-plane-identity"},
        {"type": "d1", "name": "PADIEM_CHAT_DB", "id": "702bb62b-36f5-41a0-973f-c4f663ee01e6"},
        {"type": "secret_text", "name": "PADIEM_CHAT_QUOTA_SALT"},
        {"type": "plain_text", "name": "PADIEM_CHAT_RUNTIME_MODE", "text": "b14"},
        {"type": "plain_text", "name": "PADIEM_CHAT_LIVE_ENABLED", "text": "true"},
        {"type": "plain_text", "name": "PADIEM_CHAT_PUBLIC_BASE_URL", "text": PUBLIC},
        {"type": "plain_text", "name": "PADIEM_CHAT_TIMEOUT_SECONDS", "text": "30"},
    ]}}


class CandidatePlanTest(unittest.TestCase):
    def test_repository_plan_uses_source_targets_without_mutating_live(self):
        payload = live()
        original = json.dumps(payload, sort_keys=True)
        proof = planner.candidate_preservation(payload)
        self.assertEqual(proof["status"], "REPOSITORY_BINDING_PLAN_STRUCTURAL_PASS")
        self.assertEqual(json.dumps(payload, sort_keys=True), original)
        self.assertFalse(proof["deploy_authorized"])
        self.assertFalse(proof["existing_secret_values_read"])
        self.assertTrue(any(x["name"] == "CF_VERSION_METADATA" for x in proof["binding_diff"]["added"]))

    def test_source_rpc_contract_pins_state_worker_not_edge(self):
        planner.verify_broker_source_rpc_contract()
        proof = planner.candidate_preservation(live())
        self.assertTrue(proof["broker_private_rpc_source_contract_proven"])
        self.assertFalse(proof["deployed_rpc_revision_proven"])
        self.assertFalse(proof["deploy_authorized"])

    def test_rpc_source_drift_is_fail_closed(self):
        worker_source = planner.BROKER_WORKER_MODULE.read_text(encoding="utf-8")
        real_forward = "return await self._stub().gateway_bootstrap_rpc(payload)"
        self.assertIn(real_forward, worker_source)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            altered = root / "local_agent_broker_worker.py"
            altered.write_text(
                worker_source.replace(
                    real_forward,
                    "return await self._stub().get_enrollment_binding(payload)",
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ProductionConfigError):
                planner.verify_broker_source_rpc_contract(worker_module=altered)
            # A state Worker silently renamed to Edge must never pass.
            config = json.loads(planner.BROKER_STATE_CONFIG.read_text(encoding="utf-8"))
            config["name"] = "padiem-local-agent-broker-edge"
            altered_cfg = root / "wrong-broker.jsonc"
            altered_cfg.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaises(ProductionConfigError):
                planner.verify_broker_source_rpc_contract(state_config=altered_cfg)
            # Private RPC implementation removal must not pass just because
            # WorkerEntrypoint still declares the forwarding method.
            rpc_code = planner.BROKER_RPC_MODULE.read_text(encoding="utf-8")
            self.assertIn("async def gateway_bootstrap_rpc(", rpc_code)
            altered_rpc = root / "canonical_broker_pairing_rpc.py"
            altered_rpc.write_text(
                rpc_code.replace(
                    "async def gateway_bootstrap_rpc(",
                    "async def missing_gateway_bootstrap_rpc(",
                    1,
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ProductionConfigError):
                planner.verify_broker_source_rpc_contract(rpc_module=altered_rpc)


    def test_identity_consent_private_rpc_source_contract(self):
        planner.verify_identity_source_rpc_contract()
        plan = planner.candidate_preservation(live())
        self.assertTrue(plan["identity_consent_rpc_source_contract_proven"])
        self.assertFalse(plan["deployed_rpc_revision_proven"])
        self.assertFalse(plan["deploy_authorized"])

    def test_identity_private_consent_rpc_misrouting_and_gate_drift_rejected(self):
        worker = planner.IDENTITY_WORKER_MODULE.read_text(encoding="utf-8")
        rpc = planner.IDENTITY_RPC_MODULE.read_text(encoding="utf-8")
        config = json.loads(planner.IDENTITY_CONFIG.read_text(encoding="utf-8"))
        original = "return await self._stub().authorize_connector_enrollment_redeem(payload)"
        self.assertIn(original, worker)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            worker_copy = root / "identity_authority_worker.py"
            worker_copy.write_text(worker.replace(
                original,
                "return await self._stub().bind_connector_enrollment_challenge(payload)",
                1,
            ), encoding="utf-8")
            with self.assertRaises(ProductionConfigError):
                planner.verify_identity_source_rpc_contract(identity_worker=worker_copy)
            config["name"] = "padiem-local-agent-broker-edge"
            cfg_copy = root / "wrangler.identity-authority.jsonc"
            cfg_copy.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaises(ProductionConfigError):
                planner.verify_identity_source_rpc_contract(identity_config=cfg_copy)
            # Dropping the schema-installed authority MUST be caught.
            rpc_copy = root / "canonical_connector_enrollment_consent_rpc.py"
            self.assertIn('"CONTROL_PLANE_CONNECTOR_ENROLLMENT_SCHEMA_INSTALLED"', rpc)
            rpc_copy.write_text(rpc.replace(
                '"CONTROL_PLANE_CONNECTOR_ENROLLMENT_SCHEMA_INSTALLED"',
                '"CONTROL_PLANE_CONNECTOR_ENROLLMENT_SCHEMA_BYPASS"',
            ), encoding="utf-8")
            with self.assertRaises(ProductionConfigError):
                planner.verify_identity_source_rpc_contract(identity_rpc=rpc_copy)

    def test_failed_live_preservation_is_not_a_green_ci(self):
        # A well-formed HTTP 200 with an incomplete live inventory is HOLD.
        # No token, settings JSON or secret should appear in stdout.
        with patch.dict("os.environ", {
            "CLOUDFLARE_API_TOKEN": "test-token-secret-never-print",
            "CLOUDFLARE_ACCOUNT_ID": "syntheticaccount123",
        }):
            with patch.object(planner, "get_json", return_value=(200, {
                "success": True, "result": {"bindings": []},
            })):
                output = io.StringIO()
                with redirect_stdout(output):
                    rc = planner.main()
        self.assertEqual(rc, 1)
        self.assertIn("CONNECTOR_BROKER_PRESERVATION=HOLD", output.getvalue())
        self.assertIn("PRODUCTION_MUTATION=0", output.getvalue())
        self.assertNotIn("test-token-secret-never-print", output.getvalue())
        self.assertNotIn("syntheticaccount123", output.getvalue())

    def test_no_mutating_cloudflare_or_public_worker_path_is_reachable(self):
        script = (SCRIPTS / "b62_connector_broker_additive_preflight.py").read_text(encoding="utf-8")
        self.assertIn('method="GET"', (SCRIPTS / "b62_cloudflare_connector_binding_readonly.py").read_text(encoding="utf-8"))
        self.assertNotIn("urlopen(Request(", script)
        self.assertNotIn("deploy(", script)
        self.assertNotIn("POST", script.split("def main() -> int:")[1])
        workflow = (SCRIPTS.parent / "workflows" / "b62-cloudflare-worker-deploy.yml").read_text(encoding="utf-8")
        self.assertIn("b62_connector_broker_additive_preflight.py", workflow)


if __name__ == "__main__":
    unittest.main()
