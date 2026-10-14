"""Identity Connector live activation is a negative-only, secret-redacted audit."""
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
import b62_connector_identity_activation_readonly as gate


def envelope(rows=()):
    return {"success": True, "result": {"bindings": list(rows)}}


def flag(name, text="false", binding_type="plain_text"):
    return {"name": name, "type": binding_type, "text": text}


class IdentityActivationReadOnlyTest(unittest.TestCase):
    def test_missing_flags_are_default_off_not_authority(self):
        x = gate.inspect_identity_activation(envelope([
            {"name": "CONTROL_PLANE_IDENTITY_LOOKUP_KEY",
             "type": "secret_text", "text": "NEVER_ECHO_CREDENTIAL"},
            {"name": "CONTROL_PLANE_ALLOWED_PRODUCTS",
             "type": "plain_text", "text": "b62,b54-padiem-claw"},
        ]))
        self.assertEqual(x["state"], "PASS_DEFAULT_OFF")
        self.assertEqual(x["activation_flags_explicitly_true_count"], 0)
        self.assertFalse(x["production_connector_activation_authorized"])
        self.assertFalse(x["deployed_identity_rpc_source_parity_proven"])
        self.assertNotIn("NEVER_ECHO_CREDENTIAL", json.dumps(x))

    def test_all_false_flags_are_negative_proof(self):
        rows = [flag(name) for name in gate.ALL_GATES]
        x = gate.inspect_identity_activation(envelope(rows))
        self.assertEqual(x["state"], "PASS_DEFAULT_OFF")
        self.assertFalse(x["schema_install_flag_true"])

    def test_any_staged_true_flag_holds_not_authorizes(self):
        for name in gate.ALL_GATES:
            with self.subTest(name=name):
                x = gate.inspect_identity_activation(envelope([flag(name, "true")]))
                self.assertEqual(x["state"], "HOLD_PARTIAL")
                self.assertFalse(x["production_connector_activation_authorized"])

    def test_fully_on_triplet_does_not_authorize(self):
        x = gate.inspect_identity_activation(envelope([
            flag(name, "true") for name in gate.REQUIRED_GATES
        ]))
        self.assertEqual(x["state"], "HOLD_ALL_THREE_ON")
        self.assertTrue(x["all_required_activation_gates_true"])
        self.assertFalse(x["production_connector_activation_authorized"])

    def test_unsupported_binding_type_and_secret_sentinel_denied_without_echo(self):
        for kind in ("secret_text", "secret", "service", "r2_bucket", "json"):
            with self.subTest(kind=kind):
                with self.assertRaises(ValueError):
                    gate.inspect_identity_activation(envelope([
                        flag(gate.REQUIRED_GATES[0], "NEVER_ECHO_SECRET", kind),
                    ]))
        with self.assertRaises(ValueError):
            gate.inspect_identity_activation(envelope([
                flag(gate.REQUIRED_GATES[0], "unexpected-not-a-bool")
            ]))

    def test_duplicate_unknown_and_malformed_envelopes_fail_closed(self):
        for bad in (
            None, [], {},
            {"success": True, "result": {}},
            envelope([flag(gate.REQUIRED_GATES[0]),
                      flag(gate.REQUIRED_GATES[0], "true")]),
            envelope([None]),
        ):
            with self.subTest(payload=str(type(bad))):
                with self.assertRaises(ValueError):
                    gate.inspect_identity_activation(bad)

    def test_live_api_get_exact_canonical_worker_and_sanitized_result(self):
        calls = []
        def requester(url, *, token):
            self.assertEqual(token, "synthetic-secret-token")
            calls.append(url)
            return 200, envelope([
                flag(gate.REQUIRED_GATES[0], "false"),
                {"name": "UNRELATED_SECRET", "type": "secret_text",
                 "text": "CREDENTIAL_NEVER_OUTPUT"},
            ])
        x = gate.audit(account_id="syntheticaccount123",
                       token="synthetic-secret-token", requester=requester)
        self.assertEqual(calls, [
            gate.API + "/accounts/syntheticaccount123/workers/scripts/" +
            "padiem-control-plane-identity/settings",
        ])
        self.assertNotIn("CREDENTIAL_NEVER_OUTPUT", json.dumps(x))
        self.assertNotIn("synthetic-secret-token", json.dumps(x))
        self.assertNotIn("syntheticaccount123", json.dumps(x))
        self.assertFalse(x["production_connector_activation_authorized"])
        with self.assertRaises(ValueError):
            gate.audit(account_id="syntheticaccount123", token="token",
                       requester=lambda *args, **kwargs: (403, {}))

    def test_main_unverified_and_on_staging_fail_ci_with_zero_mutation(self):
        for outcome in ("exception", "partial", "full"):
            with self.subTest(outcome=outcome):
                output = StringIO()
                with patch.dict("os.environ", {
                    "CLOUDFLARE_ACCOUNT_ID": "syntheticaccount123",
                    "CLOUDFLARE_API_TOKEN": "PRIVATE_DO_NOT_OUTPUT",
                }):
                    if outcome == "exception":
                        response = ValueError("CREDENTIAL_NEVER_OUTPUT")
                    elif outcome == "partial":
                        response = gate.inspect_identity_activation(envelope([
                            flag(gate.REQUIRED_GATES[0], "true"),
                        ]))
                    else:
                        response = gate.inspect_identity_activation(envelope([
                            flag(name, "true") for name in gate.REQUIRED_GATES
                        ]))
                    with patch.object(gate, "audit", side_effect=response if outcome=="exception" else None,
                                      return_value=None if outcome=="exception" else response):
                        with redirect_stdout(output):
                            code = gate.main()
                self.assertEqual(code, 1)
                self.assertIn("IDENTITY_CONNECTOR_ACTIVATION_READBACK=HOLD", output.getvalue())
                self.assertIn("PRODUCTION_MUTATION=0", output.getvalue())
                self.assertNotIn("PRIVATE_DO_NOT_OUTPUT", output.getvalue())
                self.assertNotIn("CREDENTIAL_NEVER_OUTPUT", output.getvalue())

    def test_main_safe_negative_returns_success_only_when_all_off(self):
        result = gate.inspect_identity_activation(envelope())
        with patch.object(gate, "audit", return_value=result):
            output = StringIO()
            with redirect_stdout(output):
                rc = gate.main()
        self.assertEqual(rc, 0)
        self.assertIn("IDENTITY_CONNECTOR_ACTIVATION_READBACK=PASS_DEFAULT_OFF",
                      output.getvalue())
        self.assertIn("PRODUCTION_MUTATION=0", output.getvalue())


if __name__ == "__main__":
    unittest.main()
