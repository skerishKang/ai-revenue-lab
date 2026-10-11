from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "apps" / "padiem-ai-engine" / "scripts" / "a15_telegram_read_production_canary.py"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "b54-telegram-read-production-canary.yml"
SERVED_VERSION_GUARD_PATH = ROOT / ".github" / "scripts" / "b54_engine_served_version_guard.py"
SERVED_VERSION_RESOLVER_PATH = ROOT / ".github" / "scripts" / "cloudflare_served_version.py"

# #3823 (parent #3748): the resolved served version id must reach the canonical
# argparse surface as ONE token. The canonical grammar accepts a leading hyphen,
# so the separated form lets argparse consume the id as an option and abort with
# a usage error before the predicate is ever consulted.
#
# This workflow's contract job does NOT install PyYAML, so the workflow is read
# as text here rather than parsed. The guard invocation is a single command line,
# with shell line-continuations joined when present.
CANONICAL_ACTIVE_VERSION_ARGV = '--active-version="${active_version}"'
SEPARATED_ACTIVE_VERSION_ARGV = '--active-version "${active_version}"'
LEADING_HYPHEN_VERSION_ID = "-canonical-safe-v1"
REGISTRY_BINDING_NAME = "PADIEM_ENGINE_CALLER_REGISTRY_V1"
CONNECTOR_GRANTS_BINDING_NAME = "ENGINE_CONNECTOR_GRANTS"
CONNECTOR_GRANTS_DATABASE_ID = "6b77ad02-bc27-488f-bb97-6325f6750cba"
GOOGLE_OAUTH_BINDING_NAME = "CONTROL_PLANE_GOOGLE_OAUTH"
GOOGLE_OAUTH_SERVICE = "padiem-google-oauth-state"
SENTINEL = "sentinel-secret-value-must-never-appear"

spec = importlib.util.spec_from_file_location("a15_telegram_read_production_canary", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
canary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(canary)

_resolver_spec = importlib.util.spec_from_file_location(
    "cloudflare_served_version", SERVED_VERSION_RESOLVER_PATH
)
assert _resolver_spec is not None and _resolver_spec.loader is not None
served_version = importlib.util.module_from_spec(_resolver_spec)
_resolver_spec.loader.exec_module(served_version)


def workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def served_version_guard_commands() -> list[str]:
    """Every command in this workflow that invokes the canonical served-version guard.

    Shell line-continuations are joined so a reformatted multi-line invocation is
    still measured as one command.
    """
    lines = workflow_text().splitlines()
    commands: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if "b54_engine_served_version_guard.py verify" not in line:
            index += 1
            continue
        chunk = [line]
        while chunk[-1].rstrip().endswith("\\") and index + 1 < len(lines):
            index += 1
            chunk.append(lines[index])
        commands.append("\n".join(chunk))
        index += 1
    return commands


def assert_canonical_active_version_argv(command: str) -> None:
    """The #3823 contract: one canonical argv token, never a separated pair."""
    assert command.count("b54_engine_served_version_guard.py verify") == 1
    assert CANONICAL_ACTIVE_VERSION_ARGV in command
    assert SEPARATED_ACTIVE_VERSION_ARGV not in command


def leading_hyphen_version_detail() -> dict:
    """Minimal canonical version-detail payload whose id starts with a hyphen.

    Carries exactly the bindings the real Telegram canary guard call requires, so
    the probe exercises the shipped `--require-drive-runtime-bindings` path too.
    """
    return {
        "success": True,
        "result": {
            "id": LEADING_HYPHEN_VERSION_ID,
            "resources": {
                "bindings": [
                    {"name": REGISTRY_BINDING_NAME, "type": "secret_text", "text": SENTINEL},
                    {
                        "name": CONNECTOR_GRANTS_BINDING_NAME,
                        "type": "d1",
                        "id": CONNECTOR_GRANTS_DATABASE_ID,
                    },
                    {
                        "name": GOOGLE_OAUTH_BINDING_NAME,
                        "type": "service",
                        "service": GOOGLE_OAUTH_SERVICE,
                    },
                ]
            },
        },
    }


def run_guard_cli(argv: list[str]) -> subprocess.CompletedProcess:
    """Invoke the real guard CLI as a subprocess. Never touches Cloudflare or a provider."""
    return subprocess.run(
        [sys.executable, str(SERVED_VERSION_GUARD_PATH), *argv],
        capture_output=True,
        text=True,
    )


class TelegramReadProductionCanaryTests(unittest.TestCase):
    def _success_body(self) -> bytes:
        return json.dumps(
            {
                "ok": True,
                "tool": {
                    "canonical_tool_id": canary.TOOL_ID,
                    "status": "completed",
                    "output_truncated": False,
                    "output": {
                        "provider": "telegram",
                        "operation": "telegram.get_bot_info",
                        "result_status": "OK",
                        "bot": {
                            "bot_id": "8657553095",
                            "username": "padiem_clawbot",
                            "first_name": "Padiem Claw",
                            "is_bot": True,
                            "personal_account": False,
                            "bot_token_present": False,
                        },
                        "telegram_content_trusted": False,
                        "bot_token_present": False,
                        "mints_approval_authority": False,
                        "write_capability_granted": False,
                        # Engine's generic redactor treats credential-shaped
                        # keys as secret-shaped even when their Core value is False.
                        "raw_credentials_present": "[redacted]",
                    },
                },
            },
            separators=(",", ":"),
        ).encode("utf-8")

    def test_fixed_canonical_request_contract(self) -> None:
        self.assertEqual(canary.ENGINE_BASE_URL, "https://engine.padiem.net")
        self.assertEqual(canary.TOOL_EXECUTE_PATH, "/internal/v1/tools/execute")
        self.assertEqual(canary.CALLER_ID, "b54-p01-overlay-20260914-a1")
        self.assertEqual(
            canary.canonical_request_body(),
            {
                "app_id": "b54-padiem-claw-telegram",
                "agent_id": "agent:padiem:claw_telegram_reader@1",
                "tool_id": "tool:telegram:bot.get_bot_info@1",
                "arguments": {},
            },
        )
        self.assertEqual(canary.PROVIDER_READ_BUDGET_MAX, 1)

    def test_success_uses_exactly_one_transport_call_and_emits_only_aggregate_evidence(self) -> None:
        calls: list[tuple[dict[str, object], str]] = []
        credential = "super-secret-caller-credential"

        def transport(body: dict[str, object], supplied_credential: str) -> tuple[int, bytes]:
            calls.append((body, supplied_credential))
            return 200, self._success_body()

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = canary.run(credential, transport=transport)

        self.assertEqual(rc, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], canary.canonical_request_body())
        self.assertEqual(calls[0][1], credential)
        output = stdout.getvalue()
        self.assertIn("TELEGRAM_READ_CANARY=PASS", output)
        self.assertIn("TELEGRAM_BOT_IDENTITY_PRESENT=YES", output)
        self.assertIn("TELEGRAM_GETME_BOUNDED=YES", output)
        self.assertIn("ENGINE_TOOL_EXECUTE_POST_COUNT=1", output)
        self.assertIn("NETWORK_RETRY_COUNT=0", output)
        self.assertIn("RAW_BOT_ID_OUTPUT=0", output)
        self.assertIn("RAW_BOT_USERNAME_OUTPUT=0", output)
        self.assertIn("RAW_BOT_NAME_OUTPUT=0", output)
        self.assertIn("RAW_CHAT_ID_OUTPUT=0", output)
        self.assertIn("RAW_BINDING_REF_OUTPUT=0", output)
        self.assertIn("RAW_ACTOR_REF_OUTPUT=0", output)
        self.assertIn("TELEGRAM_SEND=0", output)
        self.assertIn("D1_MUTATION=0", output)
        self.assertIn("SECRET_MUTATION=0", output)
        self.assertNotIn("8657553095", output)
        self.assertNotIn("padiem_clawbot", output)
        self.assertNotIn("Padiem Claw", output)
        self.assertNotIn(credential, output)

    def test_success_marks_truncated_output(self) -> None:
        payload = json.loads(self._success_body().decode("utf-8"))
        payload["tool"]["output_truncated"] = True
        payload["tool"]["output"]["raw_credentials_present"] = None

        present, truncated = canary.classify_success(payload)
        self.assertTrue(present)
        self.assertTrue(truncated)

    def test_headers_keep_credential_private(self) -> None:
        credential = "private-value"
        headers = canary._headers(credential)
        self.assertEqual(headers["x-padiem-engine-caller"], canary.CALLER_ID)
        self.assertEqual(headers["x-padiem-engine-credential"], credential)
        self.assertNotIn(credential, repr(canary.canonical_request_body()))

    def test_non_200_emits_only_bounded_error_code(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = canary.run(
                "credential",
                transport=lambda body, credential: (
                    503,
                    b'{"error":{"code":"connector_grants_unavailable","message":"private detail"}}',
                ),
            )
        output = stdout.getvalue()
        self.assertEqual(rc, 1)
        self.assertIn("ENGINE_ERROR_CODE=connector_grants_unavailable", output)
        self.assertNotIn("private detail", output)
        self.assertIn("ENGINE_TOOL_EXECUTE_POST_COUNT=1", output)
        self.assertIn("NETWORK_RETRY_COUNT=0", output)

    def test_malformed_success_fails_closed_without_raw_output(self) -> None:
        raw = b'{"ok":true,"tool":{"status":"completed","output":{"bot":{"first_name":"private-name"}}}}'
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = canary.run("credential", transport=lambda body, credential: (200, raw))
        output = stdout.getvalue()
        self.assertEqual(rc, 1)
        self.assertIn("TELEGRAM_READ_CANARY=FAIL_NONCANONICAL_SUCCESS", output)
        self.assertNotIn("private-name", output)

    def test_bot_identity_shape_mismatch_fails_closed(self) -> None:
        payload = json.loads(self._success_body().decode("utf-8"))
        payload["tool"]["output"]["bot"]["username"] = "private-username"
        with self.assertRaises(ValueError):
            canary.classify_success(payload)

    def test_non_getme_material_fails_closed(self) -> None:
        payload = json.loads(self._success_body().decode("utf-8"))
        payload["tool"]["output"]["chat_id"] = 123
        with self.assertRaises(ValueError):
            canary.classify_success(payload)

    def test_write_capability_projection_fails_closed(self) -> None:
        payload = json.loads(self._success_body().decode("utf-8"))
        payload["tool"]["output"]["write_capability_granted"] = True
        with self.assertRaises(ValueError):
            canary.classify_success(payload)

    def test_transport_exception_is_not_retried(self) -> None:
        calls = 0

        def transport(body: dict[str, object], credential: str) -> tuple[int, bytes]:
            nonlocal calls
            calls += 1
            raise RuntimeError("sensitive transport failure")

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = canary.run("credential", transport=transport)
        self.assertEqual(rc, 1)
        self.assertEqual(calls, 1)
        output = stdout.getvalue()
        self.assertIn("TELEGRAM_READ_CANARY=FAIL_NETWORK", output)
        self.assertNotIn("sensitive transport failure", output)
        self.assertIn("NETWORK_RETRY_COUNT=0", output)


class TelegramReadProductionCanaryWorkflowContractTests(unittest.TestCase):
    """#3823 (parent #3748): the canonical served-version argv contract."""

    def test_3823_telegram_canary_passes_the_active_version_as_one_canonical_argv_token(self) -> None:
        """The sole served-version guard call must use the `=` form."""

        commands = served_version_guard_commands()
        self.assertEqual(len(commands), 1)
        command = commands[0]
        assert_canonical_active_version_argv(command)
        # The guard call itself is otherwise untouched: same payload, same
        # reviewed binding requirement, same silence.
        self.assertIn('--version-settings "${version_detail}"', command)
        self.assertIn("--require-drive-runtime-bindings", command)
        self.assertIn(">/dev/null", command)

    def test_3823_canonical_predicate_and_version_equality_are_preserved(self) -> None:
        """The fix must not relax the grammar or the exact-version equality gate."""

        text = workflow_text()
        # This lane re-derives no local grammar grep: the canonical predicate is
        # applied inside the guard over the shared resolver grammar, so the
        # workflow only carries the fail-closed exact-version equality gate.
        self.assertNotIn("grep -Eq", text)
        self.assertIn('test "${active_version}" = "${EXPECTED_ENGINE_VERSION}"', text)
        self.assertIn("ENGINE_EXPECTED_VERSION_ACTIVE=PASS", text)
        # The canonical grammar is the shared resolver's, not a local re-derivation.
        self.assertEqual(served_version.SERVED_VERSION_ID_RE.pattern, r"^[A-Za-z0-9._-]{1,64}$")
        self.assertTrue(served_version.is_safe_version_id(LEADING_HYPHEN_VERSION_ID))
        guard_source = SERVED_VERSION_GUARD_PATH.read_text(encoding="utf-8")
        self.assertIn("is_safe_version_id(active_version)", guard_source)

    def test_3823_reintroducing_the_separated_argv_form_fails_the_contract(self) -> None:
        """Negative control: the pre-#3823 form can no longer satisfy the contract."""

        commands = served_version_guard_commands()
        self.assertEqual(len(commands), 1)
        command = commands[0]
        # The shipped workflow must already carry the `=` form for this control to
        # mean anything; a reverted file fails here, before the mutation is built.
        assert_canonical_active_version_argv(command)
        broken = command.replace(CANONICAL_ACTIVE_VERSION_ARGV, SEPARATED_ACTIVE_VERSION_ARGV, 1)
        self.assertNotEqual(broken, command)
        self.assertNotIn(CANONICAL_ACTIVE_VERSION_ARGV, broken)
        self.assertIn(SEPARATED_ACTIVE_VERSION_ARGV, broken)
        with self.assertRaises(AssertionError):
            assert_canonical_active_version_argv(broken)

    def test_3823_real_guard_cli_accepts_a_leading_hyphen_id_only_in_the_equals_form(self) -> None:
        """CLI acceptance == is_safe_version_id() over an option-shaped id (#3748 item 2)."""

        with tempfile.TemporaryDirectory() as tmp:
            detail = pathlib.Path(tmp) / "telegram-canary-engine-version.json"
            detail.write_text(json.dumps(leading_hyphen_version_detail()), encoding="utf-8")

            # `=` form: argparse accepts the id, so the canonical predicate decides.
            accepted = run_guard_cli(
                [
                    "verify",
                    "--version-settings",
                    str(detail),
                    f"--active-version={LEADING_HYPHEN_VERSION_ID}",
                    "--require-drive-runtime-bindings",
                ]
            )
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            self.assertIn("B54_ENGINE_SERVED_VERSION_GUARD=PASS", accepted.stdout)
            self.assertIn("DRIVE_RUNTIME_BINDINGS_VALIDATED=YES", accepted.stdout)
            self.assertNotIn("usage:", accepted.stderr.lower())
            self.assertNotIn(SENTINEL, accepted.stdout + accepted.stderr)

            # Separated form: argparse eats the id as an option and aborts first.
            rejected = run_guard_cli(
                [
                    "verify",
                    "--version-settings",
                    str(detail),
                    "--active-version",
                    LEADING_HYPHEN_VERSION_ID,
                    "--require-drive-runtime-bindings",
                ]
            )
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("usage:", rejected.stderr.lower())
            self.assertNotIn("B54_ENGINE_SERVED_VERSION_GUARD=PASS", rejected.stdout)

            # Mismatch: the parser accepted the id, but the guard still fails closed.
            mismatch = run_guard_cli(
                [
                    "verify",
                    "--version-settings",
                    str(detail),
                    "--active-version=-different-safe-v1",
                    "--require-drive-runtime-bindings",
                ]
            )
            self.assertEqual(mismatch.returncode, 1)
            self.assertIn("B54_ENGINE_SERVED_VERSION_GUARD=FAIL", mismatch.stderr)
            self.assertNotIn("B54_ENGINE_SERVED_VERSION_GUARD=PASS", mismatch.stdout)
            self.assertNotIn(SENTINEL, mismatch.stdout + mismatch.stderr)


if __name__ == "__main__":
    unittest.main()