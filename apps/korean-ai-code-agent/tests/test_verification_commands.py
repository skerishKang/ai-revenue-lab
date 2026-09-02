from __future__ import annotations

import hashlib
import unittest

from kagent.contracts import ContractError
from kagent.sandbox_conformance import SandboxSecurityPolicy
from kagent.verification_commands import (
    ARBITRARY_SHELL_SUPPORTED,
    HOST_ENVIRONMENT_INHERITANCE_SUPPORTED,
    REAL_SUBPROCESS_EXECUTION_CONFIGURED,
    DeterministicFakeVerificationExecutor,
    UnconfiguredVerificationExecutor,
    VerificationCommandCatalog,
    VerificationCommandRequest,
    VerificationCommandRunner,
    VerificationCommandSpec,
    VerificationExecutionReceipt,
)


class VerificationCommandSpecTests(unittest.TestCase):
    def test_safe_server_owned_test_command_is_accepted(self):
        spec = VerificationCommandSpec(
            command_id="python_unittest",
            argv=("python", "-m", "unittest", "discover", "-s", "tests", "-v"),
            cwd="apps/korean-ai-code-agent",
            timeout_seconds=300,
            max_output_bytes=200_000,
        )
        rendered = spec.safe_dict()
        self.assertFalse(rendered["shell"])
        self.assertFalse(rendered["inherit_host_environment"])
        self.assertEqual(rendered["environment"], [])

    def test_shell_interpreters_are_rejected(self):
        for executable in ("sh", "bash", "zsh", "cmd", "powershell", "pwsh"):
            with self.subTest(executable=executable):
                with self.assertRaises(ContractError):
                    VerificationCommandSpec(command_id="bad", argv=(executable, "echo", "ok"))

    def test_network_clients_are_rejected(self):
        for executable in ("curl", "wget", "ssh", "scp", "nc", "telnet"):
            with self.subTest(executable=executable):
                with self.assertRaises(ContractError):
                    VerificationCommandSpec(command_id="bad", argv=(executable, "example.invalid"))

    def test_deployment_clients_are_rejected(self):
        for executable in ("wrangler", "vercel", "netlify", "kubectl", "helm", "terraform", "pulumi", "flyctl"):
            with self.subTest(executable=executable):
                with self.assertRaises(ContractError):
                    VerificationCommandSpec(command_id="bad", argv=(executable, "version"))

    def test_git_mutations_are_rejected_but_read_only_status_is_allowed(self):
        for subcommand in ("commit", "push", "merge", "rebase", "reset", "clean", "checkout", "switch", "fetch"):
            with self.subTest(subcommand=subcommand):
                with self.assertRaises(ContractError):
                    VerificationCommandSpec(command_id="git_bad", argv=("git", subcommand))
        spec = VerificationCommandSpec(command_id="git_status", argv=("git", "status", "--porcelain"))
        self.assertEqual(spec.argv[1], "status")

    def test_shell_metacharacters_are_rejected_even_without_shell_program(self):
        for token in ("ok;rm", "a&&b", "a||b", "$(whoami)", "`id`", ">out", "<in"):
            with self.subTest(token=token):
                with self.assertRaises(ContractError):
                    VerificationCommandSpec(command_id="bad", argv=("python", token))

    def test_cwd_must_remain_relative_inside_workspace(self):
        for cwd in ("/tmp", "../repo", "a/../../b", "C:\\repo"):
            with self.subTest(cwd=cwd):
                with self.assertRaises(ContractError):
                    VerificationCommandSpec(command_id="bad", argv=("python", "-V"), cwd=cwd)

    def test_environment_injection_is_not_supported(self):
        with self.assertRaises(ContractError):
            VerificationCommandSpec(
                command_id="bad",
                argv=("python", "-V"),
                environment=(("MODE", "test"),),
            )

    def test_timeout_and_output_must_fit_cloud_policy(self):
        policy = SandboxSecurityPolicy(max_ttl_seconds=120, max_terminal_output_bytes=4096)
        with self.assertRaises(ContractError):
            VerificationCommandCatalog(
                (VerificationCommandSpec(command_id="slow", argv=("python", "-V"), timeout_seconds=121),),
                policy=policy,
            )
        with self.assertRaises(ContractError):
            VerificationCommandCatalog(
                (VerificationCommandSpec(command_id="loud", argv=("python", "-V"), max_output_bytes=8192),),
                policy=policy,
            )


class VerificationCommandCatalogTests(unittest.TestCase):
    def make_catalog(self) -> VerificationCommandCatalog:
        return VerificationCommandCatalog(
            (
                VerificationCommandSpec(command_id="compile", argv=("python", "-m", "compileall", "-q", "src", "tests")),
                VerificationCommandSpec(command_id="unit", argv=("python", "-m", "unittest", "discover", "-s", "tests", "-v")),
            )
        )

    def test_request_contains_command_id_not_client_argv_or_environment(self):
        request = VerificationCommandRequest(
            request_id="verify_1",
            run_id="run_1",
            lease_id="lease_1",
            command_id="unit",
        )
        rendered = request.safe_dict()
        self.assertFalse(rendered["client_supplied_argv"])
        self.assertFalse(rendered["client_supplied_shell"])
        self.assertFalse(rendered["client_supplied_environment"])
        self.assertNotIn("argv", rendered)

    def test_unknown_command_id_fails_closed(self):
        catalog = self.make_catalog()
        with self.assertRaises(ContractError):
            catalog.resolve(VerificationCommandRequest("req", "run", "lease", "unknown"))

    def test_duplicate_command_ids_fail_closed(self):
        spec = VerificationCommandSpec(command_id="same", argv=("python", "-V"))
        with self.assertRaises(ContractError):
            VerificationCommandCatalog((spec, spec))

    def test_catalog_is_explicitly_server_owned(self):
        rendered = self.make_catalog().safe_dict()
        self.assertTrue(rendered["server_owned"])
        self.assertEqual([item["command_id"] for item in rendered["commands"]], ["compile", "unit"])


class VerificationCommandRunnerTests(unittest.TestCase):
    def make_runner(self, executor=None) -> VerificationCommandRunner:
        catalog = VerificationCommandCatalog(
            (VerificationCommandSpec(command_id="unit", argv=("python", "-m", "unittest"), max_output_bytes=4096),)
        )
        return VerificationCommandRunner(catalog, executor)

    def request(self) -> VerificationCommandRequest:
        return VerificationCommandRequest("req_1", "run_1", "lease_1", "unit")

    def test_default_executor_fails_closed(self):
        self.assertIsInstance(self.make_runner().executor, UnconfiguredVerificationExecutor)
        with self.assertRaises(ContractError):
            self.make_runner().run(self.request())

    def test_network_free_fake_returns_hash_only_receipt(self):
        fake = DeterministicFakeVerificationExecutor(output="tests passed", duration_ms=12)
        receipt = self.make_runner(fake).run(self.request())
        self.assertEqual(receipt.exit_code, 0)
        self.assertEqual(receipt.output_sha256, hashlib.sha256(b"tests passed").hexdigest())
        self.assertFalse(receipt.safe_dict()["raw_output_in_receipt"])
        self.assertEqual(len(fake.executed), 1)

    def test_fake_output_cannot_exceed_registered_bound(self):
        fake = DeterministicFakeVerificationExecutor(output="x" * 5000)
        with self.assertRaises(ContractError):
            self.make_runner(fake).run(self.request())

    def test_receipt_correlation_mismatch_fails_closed(self):
        class BadExecutor:
            def execute(self, request, spec):
                return VerificationExecutionReceipt(
                    request_id="other_req",
                    run_id=request.run_id,
                    lease_id=request.lease_id,
                    command_id=spec.command_id,
                    exit_code=0,
                    output_bytes=0,
                    output_sha256=hashlib.sha256(b"").hexdigest(),
                    duration_ms=1,
                )

        with self.assertRaises(ContractError):
            self.make_runner(BadExecutor()).run(self.request())

    def test_no_real_execution_or_shell_authority_is_claimed(self):
        self.assertFalse(REAL_SUBPROCESS_EXECUTION_CONFIGURED)
        self.assertFalse(ARBITRARY_SHELL_SUPPORTED)
        self.assertFalse(HOST_ENVIRONMENT_INHERITANCE_SUPPORTED)


if __name__ == "__main__":
    unittest.main()
