"""Deterministic source tests for the #3283 Vercel parser runtime probe."""

from __future__ import annotations

import json
import unittest
from dataclasses import replace
from unittest import mock

from kagent.contracts import ContractError
from kagent.vercel_parser_live_gate import (
    VERCEL_PARSER_CENTRAL_CONFIRMATION,
)
from kagent.vercel_parser_probe_runtime import (
    VERCEL_PARSER_MAX_LOGICAL_PROVIDER_OPERATIONS,
    VERCEL_PARSER_TARGET_ENVIRONMENT,
    VercelParserProbeAuthorization,
    VercelPythonSdkProbeProvider,
    execute_authorized_vercel_parser_probe,
    live_probe_source_readiness,
)

MAIN = "4b9b8f31de08fd53d4d4b174e0753b751eec8f68"


def authorization(**overrides):
    values = dict(
        exact_main_sha=MAIN,
        central_confirmation=VERCEL_PARSER_CENTRAL_CONFIRMATION,
        owner_approval_ref="issue:3283/comment:owner-approved",
        owner_authorized=True,
        target_environment=VERCEL_PARSER_TARGET_ENVIRONMENT,
        parser_deadline_seconds=30,
        sandbox_ttl_seconds=120,
        max_sandbox_allocations=1,
        max_logical_provider_operations=VERCEL_PARSER_MAX_LOGICAL_PROVIDER_OPERATIONS,
    )
    values.update(overrides)
    return VercelParserProbeAuthorization(**values)


class Completed:
    def __init__(self, *, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode


class FakeProcess:
    def __init__(self, sandbox, token, *, auto_kill):
        self._sandbox = sandbox
        self._token = token
        self._auto_kill = auto_kill
        sandbox.tokens[token] = True

    def wait(self):
        if self._auto_kill:
            self._sandbox.tokens[self._token] = False
        return 0

    def kill(self):
        self._sandbox.tokens[self._token] = False
        return True


class FakeSandbox:
    name = "sbx-probe-1"

    def __init__(self, *, evidence):
        self.evidence = evidence
        self.tokens = {}
        self.stopped = False
        self.destroyed = False

    def run_process(self, command, args, **kwargs):
        script = args[1]
        if "response" in script and "evidence" in script:
            request = json.loads(__import__("base64").b64decode(args[2]).decode("utf-8"))
            payload = __import__("base64").b64decode(request["payload_b64"])
            response = {
                "type": "document",
                "name": request["name"],
                "media_type": request["media_type"],
                "text": "vercel-parser-runtime-probe",
                "byte_size": len(payload),
                "source_kind": "binary",
                "status": "complete",
                "warnings": [],
            }
            return Completed(
                stdout=json.dumps(
                    {"response": response, "evidence": self.evidence},
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
        if "token = sys.argv[1].encode" in script:
            token = args[2]
            return Completed(stdout="1" if self.tokens.get(token) else "0")
        raise AssertionError("unexpected fake run_process script")

    def create_process(self, command, args, **kwargs):
        token = args[2]
        auto_kill = kwargs.get("kill_after") == 30
        return FakeProcess(self, token, auto_kill=auto_kill)

    def stop(self):
        self.stopped = True
        return True

    def destroy(self):
        self.destroyed = True
        return True


class FakeProvider:
    def __init__(self, *, evidence):
        self.sandbox = FakeSandbox(evidence=evidence)
        self.create_calls = 0
        self.get_calls = 0

    def create(self, *, ttl_seconds):
        self.create_calls += 1
        if ttl_seconds != 120:
            raise AssertionError("unexpected ttl")
        return self.sandbox

    def get(self, *, name):
        self.get_calls += 1
        error = RuntimeError("sandbox absent")
        error.status_code = 404
        raise error


def passing_evidence(**overrides):
    values = {
        "network_external_denied": True,
        "metadata_link_local_denied": True,
        "host_credential_names_absent": True,
        "runtime_socket_hidden": True,
        "privileged_runtime_disabled": True,
        "cpu_cores": 1,
        "memory_mb": 2048,
        "disk_mb": 8192,
        "process_count": 128,
    }
    values.update(overrides)
    return values


class AuthorizationTests(unittest.TestCase):
    def test_exact_nonproduction_single_lineage_authorization_is_safe_to_project(self):
        safe = authorization().safe_dict()
        self.assertEqual(safe["exact_main_sha"], MAIN)
        self.assertEqual(safe["target_environment"], "non_production")
        self.assertEqual(safe["parser_deadline_seconds"], 30)
        self.assertEqual(safe["sandbox_ttl_seconds"], 120)
        self.assertEqual(safe["max_sandbox_allocations"], 1)
        self.assertEqual(
            safe["max_logical_provider_operations"],
            VERCEL_PARSER_MAX_LOGICAL_PROVIDER_OPERATIONS,
        )
        self.assertIsNone(safe["credential_value"])
        self.assertFalse(safe["production_binding"])

    def test_authorization_fails_closed_on_every_widening(self):
        invalid = (
            {"exact_main_sha": "main"},
            {"central_confirmation": "YES"},
            {"owner_authorized": False},
            {"target_environment": "production"},
            {"parser_deadline_seconds": 29},
            {"parser_deadline_seconds": 31},
            {"sandbox_ttl_seconds": 30},
            {"sandbox_ttl_seconds": 301},
            {"max_sandbox_allocations": 2},
            {"max_logical_provider_operations": VERCEL_PARSER_MAX_LOGICAL_PROVIDER_OPERATIONS + 1},
        )
        for overrides in invalid:
            with self.subTest(overrides=overrides):
                with self.assertRaises(ContractError):
                    authorization(**overrides)


class RuntimeProbeTests(unittest.TestCase):
    def test_one_fake_lineage_can_produce_full_safe_acceptance_evidence(self):
        provider = FakeProvider(evidence=passing_evidence())
        with mock.patch(
            "kagent.vercel_parser_probe_runtime.time.sleep", return_value=None
        ):
            evidence = execute_authorized_vercel_parser_probe(
                authorization(), provider=provider
            )

        self.assertTrue(evidence.accepted)
        self.assertEqual(evidence.sandbox_allocations, 1)
        self.assertEqual(
            evidence.logical_provider_operations,
            VERCEL_PARSER_MAX_LOGICAL_PROVIDER_OPERATIONS,
        )
        self.assertEqual(provider.create_calls, 1)
        self.assertEqual(provider.get_calls, 1)
        self.assertTrue(provider.sandbox.stopped)
        self.assertTrue(provider.sandbox.destroyed)
        safe = evidence.safe_dict()
        self.assertEqual(safe["VERCEL_PARSER_RUNTIME_CANDIDATE_ACCEPTED"], "YES")
        self.assertIsNone(safe["FALLBACK_CANDIDATE"])
        self.assertEqual(safe["RAW_PROVIDER_PAYLOAD_OUTPUT"], 0)
        self.assertEqual(safe["RAW_DOCUMENT_OUTPUT"], 0)
        self.assertEqual(safe["PROVIDER_CREDENTIAL_OUTPUT"], 0)
        self.assertFalse(safe["production_binding"])
        self.assertFalse(safe["production_ready_claim"])

    def test_resource_policy_mismatch_rejects_candidate_and_names_e2b_fallback(self):
        provider = FakeProvider(
            evidence=passing_evidence(disk_mb=65536, process_count=4096)
        )
        with mock.patch(
            "kagent.vercel_parser_probe_runtime.time.sleep", return_value=None
        ):
            evidence = execute_authorized_vercel_parser_probe(
                authorization(), provider=provider
            )

        self.assertFalse(evidence.cpu_memory_disk_process_limit_evidence)
        self.assertFalse(evidence.accepted)
        safe = evidence.safe_dict()
        self.assertEqual(safe["VERCEL_PARSER_RUNTIME_CANDIDATE_ACCEPTED"], "NO")
        self.assertEqual(safe["FALLBACK_CANDIDATE"], "E2B")

    def test_failed_metadata_negative_test_cannot_be_smoothed_into_acceptance(self):
        provider = FakeProvider(
            evidence=passing_evidence(metadata_link_local_denied=False)
        )
        with mock.patch(
            "kagent.vercel_parser_probe_runtime.time.sleep", return_value=None
        ):
            evidence = execute_authorized_vercel_parser_probe(
                authorization(), provider=provider
            )
        self.assertFalse(evidence.metadata_link_local_negative_test)
        self.assertFalse(evidence.accepted)

    def test_concrete_sdk_provider_construction_is_inert(self):
        provider = VercelPythonSdkProbeProvider()
        self.assertIsNotNone(provider)
        readiness = live_probe_source_readiness()
        self.assertEqual(readiness["provider_calls_at_import"], 0)
        self.assertEqual(readiness["sandbox_allocations_at_import"], 0)
        self.assertFalse(readiness["credential_values_in_source"])
        self.assertFalse(readiness["production_binding"])
        self.assertFalse(readiness["production_ready_claim"])


if __name__ == "__main__":
    unittest.main()
