"""Identity Worker active-version proof is read-only, race-safe, not RPC authority."""
from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import b62_connector_identity_served_version_readonly as proof


ACTIVE = "b84a02e7-1997-48c1-9076-79f60a34b5cd"
REPLACEMENT = "ee451dda-3a62-4d24-8d1d-56d846acbcf4"


def deployment(version=ACTIVE):
    return {"success": True, "result": {"deployments": [
        {"versions": [{"version_id": version, "percentage": 100}]}
    ]}}


def detail(version=ACTIVE, *, source="wrangler"):
    return {"success": True, "result": {
        "id": version,
        "metadata": {"source": source},
        "resources": {"script": {"etag": "opaque-script-etag"}},
    }}


class IdentityVersionAuditTest(unittest.TestCase):
    def test_served_version_is_checked_before_and_after_detail(self):
        calls = []
        def requester(url, *, token):
            self.assertEqual(token, "synthetic-secret-token")
            calls.append(url)
            if url.endswith("/deployments"):
                return 200, deployment()
            if url.endswith("/versions/" + ACTIVE):
                return 200, detail()
            raise AssertionError("unreviewed API operation")
        p = proof.audit(account_id="syntheticaccount123",
                        token="synthetic-secret-token", requester=requester)
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0], calls[2])
        self.assertEqual(
            calls[0],
            proof.API + "/accounts/syntheticaccount123/workers/scripts/" +
            "padiem-control-plane-identity/deployments",
        )
        self.assertTrue(p["served_version_stable_during_readback"])
        self.assertTrue(p["served_script_etag_present"])
        self.assertTrue(p["upload_origin_recognized"])
        self.assertFalse(p["exact_git_commit_or_bundle_digest_attested"])
        self.assertFalse(p["deployed_identity_consent_rpc_proven"])
        self.assertFalse(p["identity_enrollment_authorized"])
        self.assertEqual(p["production_mutation"], 0)
        self.assertNotIn(ACTIVE, json.dumps(p))
        self.assertNotIn("synthetic-secret-token", json.dumps(p))
        self.assertNotIn("syntheticaccount123", json.dumps(p))

    def test_served_runtime_config_is_only_narrow_metadata_parity(self):
        d = detail()
        runtime = {
            "compatibility_date": "2026-09-04",
            "compatibility_flags": ["python_workers", "disable_python_external_sdk"],
        }
        d["result"]["resources"]["script_runtime"] = runtime
        result = proof.inspect_identity_version_detail(d, ACTIVE)
        self.assertTrue(result["served_runtime_metadata_complete"])
        self.assertTrue(result["served_runtime_configuration_matches_reviewed_source"])
        self.assertFalse(result["exact_git_commit_or_bundle_digest_attested"])
        self.assertFalse(result["deployed_identity_consent_rpc_proven"])
        runtime["compatibility_date"] = "2025-01-01"
        self.assertFalse(proof.inspect_identity_version_detail(
            d, ACTIVE)["served_runtime_configuration_matches_reviewed_source"])
        del d["result"]["resources"]["script_runtime"]
        result = proof.inspect_identity_version_detail(d, ACTIVE)
        self.assertFalse(result["served_runtime_metadata_complete"])
        self.assertFalse(result["served_runtime_configuration_matches_reviewed_source"])

    def test_identity_served_entrypoint_and_sqlite_do_metadata(self):
        d = detail()
        exports = {
            "default": {"type": "worker"},
            "CanonicalIdentityDurableObject": {"type": "durable-object", "storage": "sqlite"},
        }
        d["result"]["resources"]["script_runtime"] = {"exports": exports}
        result = proof.inspect_identity_version_detail(d, ACTIVE)
        self.assertTrue(result["served_export_metadata_complete"])
        self.assertTrue(result["served_export_types_match_reviewed_source"])
        self.assertFalse(result["exact_git_commit_or_bundle_digest_attested"])
        self.assertFalse(result["deployed_identity_consent_rpc_proven"])
        exports["CanonicalIdentityDurableObject"]["storage"] = "legacy-kv"
        self.assertFalse(proof.inspect_identity_version_detail(
            d, ACTIVE)["served_export_types_match_reviewed_source"])
        exports["CanonicalIdentityDurableObject"]["storage"] = "sqlite"
        exports["CanonicalIdentityDurableObject"]["state"] = "renamed"
        self.assertFalse(proof.inspect_identity_version_detail(
            d, ACTIVE)["served_export_types_match_reviewed_source"])
        del d["result"]["resources"]["script_runtime"]
        absent = proof.inspect_identity_version_detail(d, ACTIVE)
        self.assertFalse(absent["served_export_metadata_complete"])
        self.assertFalse(absent["served_export_types_match_reviewed_source"])

    def test_deployment_race_is_not_a_consistent_snapshot(self):
        num = 0
        def requester(url, *, token):
            nonlocal num
            if url.endswith("/deployments"):
                num += 1
                return 200, deployment(ACTIVE if num == 1 else REPLACEMENT)
            return 200, detail()
        with self.assertRaisesRegex(ValueError, "changed during audit"):
            proof.audit(account_id="syntheticaccount123", token="token",
                        requester=requester)
        self.assertEqual(num, 2)

    def test_active_split_or_noncanonical_version_is_rejected(self):
        for bad in (
            {"success": True, "result": {"deployments": [
                {"versions": [
                    {"version_id": ACTIVE, "percentage": 50},
                    {"version_id": REPLACEMENT, "percentage": 50},
                ]}
            ]}},
            {"success": True, "result": {"deployments": [
                {"versions": [{"version_id": "version-unsafe", "percentage": 100}]}
            ]}},
        ):
            with self.assertRaises(ValueError):
                proof.audit(account_id="syntheticaccount123", token="token",
                            requester=lambda *a, **kw: (200, bad))

    def test_version_detail_must_correlate_to_active_id(self):
        with self.assertRaises(ValueError):
            proof.inspect_identity_version_detail(detail(REPLACEMENT), ACTIVE)
        for malformed in (None, {}, {"success": False, "result": {"id": ACTIVE}}):
            with self.assertRaises(ValueError):
                proof.inspect_identity_version_detail(malformed, ACTIVE)

    def test_untrusted_upload_origin_never_becomes_parity(self):
        for source in ("unreviewed-origin", "wrangler", None, "api"):
            result = proof.inspect_identity_version_detail(detail(source=source), ACTIVE)
            self.assertEqual(result["upload_origin_recognized"],
                             source in ("wrangler", "api"))
            self.assertFalse(result["exact_git_commit_or_bundle_digest_attested"])
            self.assertFalse(result["deployed_identity_consent_rpc_proven"])

    def test_http_denial_does_not_attempt_other_calls(self):
        calls = []
        def denied(url, *, token):
            calls.append(url)
            return 403, {}
        with self.assertRaises(ValueError):
            proof.audit(account_id="syntheticaccount123", token="token", requester=denied)
        self.assertEqual(len(calls), 1)

    def test_any_live_provenance_hold_fails_ci_without_leaking(self):
        output = io.StringIO()
        with patch.dict("os.environ", {
            "CLOUDFLARE_ACCOUNT_ID": "syntheticaccount123",
            "CLOUDFLARE_API_TOKEN": "SHOULD_NOT_PRINT_TOKEN",
        }):
            with patch.object(proof, "audit", side_effect=ValueError("DO_NOT_PRINT_SECRET")):
                with redirect_stdout(output):
                    rc = proof.main()
        self.assertEqual(rc, 1)
        self.assertIn("IDENTITY_SERVED_VERSION_READBACK=HOLD", output.getvalue())
        self.assertIn("PRODUCTION_MUTATION=0", output.getvalue())
        for forbidden in ("SHOULD_NOT_PRINT_TOKEN", "syntheticaccount123", "DO_NOT_PRINT_SECRET"):
            self.assertNotIn(forbidden, output.getvalue())


if __name__ == "__main__":
    unittest.main()
