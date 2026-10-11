from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "apps" / "padiem-ai-engine" / "scripts" / "a16_calendar_read_production_canary.py"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "b54-calendar-read-production-canary.yml"
SERVED_VERSION_GUARD_PATH = ROOT / ".github" / "scripts" / "b54_engine_served_version_guard.py"
SERVED_VERSION_RESOLVER_PATH = ROOT / ".github" / "scripts" / "cloudflare_served_version.py"

# #3807 (parent #3748): the resolved served version id must reach the canonical
# argparse surface as ONE token. The canonical grammar accepts a leading hyphen,
# so the separated form lets argparse consume the id as an option and abort with
# a usage error before the predicate is ever consulted.
CANONICAL_ACTIVE_VERSION_ARGV = '--active-version="${active_version}"'
SEPARATED_ACTIVE_VERSION_ARGV = '--active-version "${active_version}"'
CANONICAL_VERSION_ID_GRAMMAR = r"grep -Eq '^[A-Za-z0-9._-]{1,64}$'"
LEADING_HYPHEN_VERSION_ID = "-canonical-safe-v1"
REGISTRY_BINDING_NAME = "PADIEM_ENGINE_CALLER_REGISTRY_V1"
SENTINEL = "sentinel-secret-value-must-never-appear"

spec = importlib.util.spec_from_file_location("a16_calendar_read_production_canary", SCRIPT_PATH)
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


def workflow_document() -> dict:
    return yaml.safe_load(workflow_text())


def workflow_triggers() -> dict:
    document = workflow_document()
    return document.get("on", document.get(True))


def served_version_guard_run_bodies() -> list[str]:
    """Every step body in this workflow that invokes the canonical served-version guard."""
    document = workflow_document()
    return [
        str(step["run"])
        for job in document["jobs"].values()
        for step in job.get("steps", [])
        if "run" in step and "b54_engine_served_version_guard.py verify" in step["run"]
    ]


def assert_canonical_active_version_argv(run: str) -> None:
    """The #3807 contract: one canonical argv token, never a separated pair."""
    assert run.count("b54_engine_served_version_guard.py verify") == 1
    assert CANONICAL_ACTIVE_VERSION_ARGV in run
    assert SEPARATED_ACTIVE_VERSION_ARGV not in run


def leading_hyphen_version_detail() -> dict:
    """Minimal canonical version-detail payload whose id starts with a hyphen."""
    return {
        "success": True,
        "result": {
            "id": LEADING_HYPHEN_VERSION_ID,
            "resources": {
                "bindings": [
                    {"name": REGISTRY_BINDING_NAME, "type": "secret_text", "text": SENTINEL}
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


class CalendarReadProductionCanaryTests(unittest.TestCase):
    def _success_body(self) -> bytes:
        return json.dumps(
            {
                "ok": True,
                "tool": {
                    "canonical_tool_id": canary.TOOL_ID,
                    "status": "completed",
                    "output_truncated": False,
                    "output": {
                        "provider": "google_calendar",
                        "operation": "calendar.list_calendars",
                        "result_status": "OK",
                        "calendars": [
                            {
                                "calendar_id": "sensitive-calendar-id",
                                "name": "sensitive calendar name",
                                "time_zone": "Asia/Seoul",
                            }
                        ],
                        "calendar_count": 1,
                        "whole_account_dump": False,
                        "event_content_trusted": False,
                        "oauth_token_present": False,
                        "mints_approval_authority": False,
                        "write_capability_granted": False,
                        # Engine's generic redactor treats credential-shaped keys
                        # as secret-shaped even when their Core value is False.
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
        self.assertEqual(canary.CREDENTIAL_ENV, "PADIEM_ENGINE_CALENDAR_CANARY_CREDENTIAL")
        self.assertEqual(canary.MAX_RESULT_ITEMS, 128)
        self.assertEqual(
            canary.canonical_request_body(),
            {
                "app_id": "b54-padiem-claw-calendar",
                "agent_id": "agent:padiem:claw_calendar_reader@1",
                "tool_id": "tool:google:calendar.list@1",
                "arguments": {},
            },
        )
        self.assertEqual(canary.PROVIDER_READ_BUDGET_MAX, 2)

    def test_success_uses_exactly_one_transport_call_and_emits_only_aggregate_evidence(self) -> None:
        calls: list[tuple[dict[str, object], str]] = []
        credential = "super-secret-canary-credential"

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
        self.assertIn("CALENDAR_READ_CANARY=PASS", output)
        self.assertIn("CALENDAR_RESULT_ITEM_COUNT=1", output)
        self.assertIn("CALENDAR_RESULT_STATUS=OK", output)
        self.assertIn("ENGINE_TOOL_EXECUTE_POST_COUNT=1", output)
        self.assertIn("NETWORK_RETRY_COUNT=0", output)
        self.assertIn("CALENDAR_PROVIDER_READ_BUDGET_MAX=2", output)
        self.assertIn("ACCOUNT_IDENTITY_AMBIGUOUS=YES", output)
        for forbidden in (
            credential,
            "sensitive-calendar-id",
            "sensitive calendar name",
            "Asia/Seoul",
        ):
            self.assertNotIn(forbidden, output)

    def test_print_evidence_locks_every_calendar_write_and_mutation_surface(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = canary.run("credential", transport=lambda body, credential: (200, self._success_body()))
        output = stdout.getvalue()
        self.assertEqual(rc, 0)
        for marker in (
            "CALENDAR_WRITE=0",
            "CALENDAR_CREATE=0",
            "CALENDAR_UPDATE=0",
            "CALENDAR_DELETE=0",
            "CALENDAR_RESPOND=0",
            "OAUTH_CONNECT=0",
            "OAUTH_CALLBACK=0",
            "CALENDAR_ALLOWLIST_MUTATION=0",
            "CALENDAR_GRANT_SEED=0",
            "D1_MUTATION=0",
            "ENGINE_DEPLOY=0",
            "B14_DEPLOY=0",
            "SECRET_MUTATION=0",
            "RAW_BINDING_REF_OUTPUT=0",
            "RAW_ACTOR_REF_OUTPUT=0",
            "RAW_EVENT_ID_OUTPUT=0",
            "RAW_SUMMARY_OUTPUT=0",
            "RAW_DESCRIPTION_OUTPUT=0",
            "RAW_ATTENDEE_OUTPUT=0",
            "RAW_LOCATION_OUTPUT=0",
        ):
            self.assertIn(marker, output)

    def test_engine_node_bound_can_preserve_count_by_list_length(self) -> None:
        payload = json.loads(self._success_body().decode("utf-8"))
        payload["tool"]["output_truncated"] = True
        payload["tool"]["output"]["calendars"] = [None for _ in range(3)]
        payload["tool"]["output"]["calendar_count"] = None
        payload["tool"]["output"]["whole_account_dump"] = None
        payload["tool"]["output"]["event_content_trusted"] = None
        payload["tool"]["output"]["oauth_token_present"] = None
        payload["tool"]["output"]["mints_approval_authority"] = None
        payload["tool"]["output"]["write_capability_granted"] = None
        payload["tool"]["output"]["raw_credentials_present"] = None

        count, status, truncated = canary.classify_success(payload)
        self.assertEqual(count, 3)
        self.assertEqual(status, "OK")
        self.assertTrue(truncated)

    def test_oversized_core_projection_is_never_accepted_as_evidence(self) -> None:
        payload = json.loads(self._success_body().decode("utf-8"))
        payload["tool"]["output"] = {
            "provider": "google_calendar",
            "operation": "calendar.list_calendars",
            "result_status": "REVIEW_REQUIRED",
            "truncated": True,
            "reason": "bounded Calendar projection exceeded the Core tool output bound",
            "result_sha256": "0" * 64,
            "event_content_trusted": False,
            "oauth_token_present": False,
        }
        with self.assertRaises(ValueError):
            canary.classify_success(payload)

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = canary.run(
                "credential",
                transport=lambda body, credential: (
                    200,
                    json.dumps(payload, separators=(",", ":")).encode("utf-8"),
                ),
            )
        self.assertEqual(rc, 1)
        self.assertIn("CALENDAR_READ_CANARY=FAIL_NONCANONICAL_SUCCESS", stdout.getvalue())

    def test_headers_keep_credential_private(self) -> None:
        credential = "canary-credential-value"
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
        raw = b'{"ok":true,"tool":{"status":"completed","output":{"name":"private-name"}}}'
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = canary.run("credential", transport=lambda body, credential: (200, raw))
        output = stdout.getvalue()
        self.assertEqual(rc, 1)
        self.assertIn("CALENDAR_READ_CANARY=FAIL_NONCANONICAL_SUCCESS", output)
        self.assertNotIn("private-name", output)

    def test_result_list_bound_and_count_mismatch_fail_closed(self) -> None:
        payload = json.loads(self._success_body().decode("utf-8"))
        payload["tool"]["output"]["calendar_count"] = 2
        with self.assertRaises(ValueError):
            canary.classify_success(payload)
        payload["tool"]["output"]["calendar_count"] = 129
        payload["tool"]["output"]["calendars"] = [{} for _ in range(129)]
        with self.assertRaises(ValueError):
            canary.classify_success(payload)

    def test_missing_post_list_facts_require_engine_truncation(self) -> None:
        payload = json.loads(self._success_body().decode("utf-8"))
        payload["tool"]["output"]["whole_account_dump"] = None
        with self.assertRaises(ValueError):
            canary.classify_success(payload)

    def test_write_capability_or_token_projection_is_rejected(self) -> None:
        payload = json.loads(self._success_body().decode("utf-8"))
        payload["tool"]["output"]["write_capability_granted"] = True
        with self.assertRaises(ValueError):
            canary.classify_success(payload)
        payload = json.loads(self._success_body().decode("utf-8"))
        payload["tool"]["output"]["oauth_token_present"] = True
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
        self.assertIn("CALENDAR_READ_CANARY=FAIL_NETWORK", output)
        self.assertNotIn("sensitive transport failure", output)
        self.assertIn("NETWORK_RETRY_COUNT=0", output)

    def test_missing_credential_skips_without_a_post(self) -> None:
        calls = 0

        def transport(body: dict[str, object], credential: str) -> tuple[int, bytes]:
            nonlocal calls
            calls += 1
            return 200, self._success_body()

        original = dict(canary.os.environ)
        canary.os.environ.pop(canary.CREDENTIAL_ENV, None)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rc = canary.main()
        finally:
            canary.os.environ.clear()
            canary.os.environ.update(original)
        self.assertEqual(rc, 1)
        self.assertEqual(calls, 0)


class CalendarReadProductionCanaryWorkflowContractTests(unittest.TestCase):
    def test_dispatch_inputs_and_confirmation(self) -> None:
        inputs = workflow_triggers()["workflow_dispatch"]["inputs"]
        self.assertEqual(sorted(inputs), ["confirmation", "expected_engine_version", "target_sha"])
        for name in inputs:
            self.assertTrue(inputs[name].get("required"), name)
        text = workflow_text()
        self.assertIn("RUN_B54_CALENDAR_READ_CANARY_ONCE", text)

    def test_live_job_is_dispatch_only_and_production_scoped(self) -> None:
        document = workflow_document()
        job = document["jobs"]["live-calendar-read"]
        guard = " ".join(str(job["if"]).split())
        self.assertIn("github.event_name == 'workflow_dispatch'", guard)
        self.assertIn("github.event.inputs.confirmation == 'RUN_B54_CALENDAR_READ_CANARY_ONCE'", guard)
        self.assertNotIn("push", guard)
        self.assertEqual(job["environment"], "production")
        self.assertEqual(job["needs"], "source-contract")
        self.assertEqual(document["permissions"], {"contents": "read"})

    def test_expected_engine_version_guard_is_mandatory(self) -> None:
        text = workflow_text()
        self.assertIn("EXPECTED_ENGINE_VERSION: ${{ github.event.inputs.expected_engine_version }}", text)
        self.assertIn('test "${active_version}" = "${EXPECTED_ENGINE_VERSION}"', text)
        self.assertIn("ENGINE_EXPECTED_VERSION_ACTIVE=PASS", text)
        self.assertIn("ENGINE_VERSION_ID_OUTPUT=0", text)
        self.assertIn("b54_engine_served_version_guard.py", text)

    # --- #3807 (parent #3748): canonical version argv -------------------------

    def test_3807_canary_passes_the_active_version_as_one_canonical_argv_token(self) -> None:
        """The sole served-version guard call must use the `=` form."""

        runs = served_version_guard_run_bodies()
        self.assertEqual(len(runs), 1)
        run = runs[0]
        assert_canonical_active_version_argv(run)
        # The guard call itself is otherwise untouched: same payload, same silence.
        self.assertIn('--version-settings "${version_detail}"', run)
        self.assertIn(">/dev/null", run)

    def test_3807_canonical_predicate_and_version_equality_are_preserved(self) -> None:
        """The fix must not relax the grammar or the exact-version equality gate."""

        text = workflow_text()
        self.assertIn(CANONICAL_VERSION_ID_GRAMMAR, text)
        self.assertIn('test "${active_version}" = "${EXPECTED_ENGINE_VERSION}"', text)
        self.assertIn("ENGINE_EXPECTED_VERSION_ACTIVE=PASS", text)
        # The canonical grammar is the shared resolver's, not a local re-derivation.
        self.assertEqual(served_version.SERVED_VERSION_ID_RE.pattern, r"^[A-Za-z0-9._-]{1,64}$")
        self.assertTrue(served_version.is_safe_version_id(LEADING_HYPHEN_VERSION_ID))

    def test_3807_reintroducing_the_separated_argv_form_fails_the_contract(self) -> None:
        """Negative control: the pre-#3807 form can no longer satisfy the contract."""

        runs = served_version_guard_run_bodies()
        self.assertEqual(len(runs), 1)
        run = runs[0]
        # The shipped workflow must already carry the `=` form for this control to
        # mean anything; a reverted file fails here, before the mutation is built.
        assert_canonical_active_version_argv(run)
        broken = run.replace(CANONICAL_ACTIVE_VERSION_ARGV, SEPARATED_ACTIVE_VERSION_ARGV, 1)
        self.assertNotEqual(broken, run)
        self.assertNotIn(CANONICAL_ACTIVE_VERSION_ARGV, broken)
        self.assertIn(SEPARATED_ACTIVE_VERSION_ARGV, broken)
        with self.assertRaises(AssertionError):
            assert_canonical_active_version_argv(broken)

    def test_3807_real_guard_cli_accepts_a_leading_hyphen_id_only_in_the_equals_form(self) -> None:
        """CLI acceptance == is_safe_version_id() over an option-shaped id (#3748 item 2)."""

        with tempfile.TemporaryDirectory() as tmp:
            detail = pathlib.Path(tmp) / "calendar-canary-engine-version.json"
            detail.write_text(json.dumps(leading_hyphen_version_detail()), encoding="utf-8")

            # `=` form: argparse accepts the id, so the canonical predicate decides.
            accepted = run_guard_cli(
                [
                    "verify",
                    "--version-settings",
                    str(detail),
                    f"--active-version={LEADING_HYPHEN_VERSION_ID}",
                ]
            )
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            self.assertIn("B54_ENGINE_SERVED_VERSION_GUARD=PASS", accepted.stdout)
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
                ]
            )
            self.assertEqual(mismatch.returncode, 1)
            self.assertIn("B54_ENGINE_SERVED_VERSION_GUARD=FAIL", mismatch.stderr)
            self.assertNotIn("B54_ENGINE_SERVED_VERSION_GUARD=PASS", mismatch.stdout)
            self.assertNotIn(SENTINEL, mismatch.stdout + mismatch.stderr)

    def test_calendar_readiness_observation_is_name_type_only(self) -> None:
        text = workflow_text()
        self.assertIn('b.get("name") == "ENGINE_CALENDAR_ALLOWED_CALENDARS"', text)
        self.assertIn('allowlist[0].get("type") != "secret_text"', text)
        self.assertIn('b.get("name") == "CONTROL_PLANE_GOOGLE_OAUTH"', text)
        self.assertIn('control_plane[0].get("type") != "service"', text)
        self.assertIn("ENGINE_DIRECT_GOOGLE_CREDENTIAL_PRESENT=NO", text)
        for forbidden in (
            "ENGINE_GOOGLE_OAUTH_CLIENT_ID",
            "ENGINE_GOOGLE_OAUTH_CLIENT_SECRET",
            "ENGINE_GOOGLE_OAUTH_REFRESH_TOKEN",
        ):
            self.assertNotIn(forbidden, text)

    def test_execution_step_pins_budget_retry_and_read_only_markers(self) -> None:
        text = workflow_text()
        for marker in (
            "grep -qx 'CALENDAR_READ_CANARY=PASS'",
            "grep -qx 'ENGINE_TOOL_EXECUTE_POST_COUNT=1'",
            "grep -qx 'NETWORK_RETRY_COUNT=0'",
            "grep -qx 'CALENDAR_RESULT_BOUNDED=YES'",
            "grep -qx 'CALENDAR_RESULT_STATUS=OK'",
            "grep -qx 'CALENDAR_PROVIDER_READ_BUDGET_MAX=2'",
            "grep -qx 'CALENDAR_WRITE=0'",
            "grep -qx 'CALENDAR_CREATE=0'",
            "grep -qx 'CALENDAR_UPDATE=0'",
            "grep -qx 'CALENDAR_DELETE=0'",
            "grep -qx 'CALENDAR_RESPOND=0'",
            "grep -qx 'D1_MUTATION=0'",
            "grep -qx 'SECRET_MUTATION=0'",
        ):
            self.assertIn(marker, text)
        self.assertIn("ENGINE_TOOL_EXECUTE_POST_MAX=1", text)
        self.assertIn("READ_DOES_NOT_IMPLY_WRITE=YES", text)

    def test_no_provider_or_write_surface_is_reachable(self) -> None:
        text = workflow_text()
        for forbidden in (
            "googleapis.com",
            "oauth2.googleapis.com",
            "www.googleapis.com/calendar",
            "calendar/v3",
            "events.insert",
            "calendar.write",
            "calendar.events",
            "wrangler deploy",
            "wrangler d1",
            "d1/database",
            "secret put",
            "git push",
        ):
            self.assertNotIn(forbidden, text)

    def test_pull_request_trigger_covers_script_and_contract(self) -> None:
        paths = workflow_triggers()["pull_request"]["paths"]
        self.assertIn("apps/padiem-ai-engine/scripts/a16_calendar_read_production_canary.py", paths)
        self.assertIn(".github/tests/test_b54_calendar_read_production_canary.py", paths)
        self.assertIn(".github/workflows/b54-calendar-read-production-canary.yml", paths)

    def test_pinned_source_assertions_match_the_referenced_files(self) -> None:
        """Every grep -Fq pin in the workflow must exist in the file it names."""

        pairs = re.findall(r"grep -Fq '([^']+)' (\S+)", workflow_text())
        self.assertGreaterEqual(len(pairs), 10)
        for pattern, relative in pairs:
            target = ROOT / relative
            self.assertTrue(target.is_file(), relative)
            self.assertIn(pattern, target.read_text(encoding="utf-8"), pattern)

    def test_source_contract_job_runs_this_contract(self) -> None:
        text = workflow_text()
        self.assertIn("python .github/tests/test_b54_calendar_read_production_canary.py", text)
        self.assertIn("CALENDAR_CANARY_READ_ONLY_CONTRACT=PASS", text)

    def test_contract_dependencies_are_installed_before_this_contract_runs(self) -> None:
        """This test imports PyYAML, so the job must install it first."""

        text = workflow_text()
        install = "python -m pip install --disable-pip-version-check --quiet 'pyyaml>=6,<7'"
        self.assertIn(install, text)
        self.assertLess(
            text.index(install),
            text.index("python .github/tests/test_b54_calendar_read_production_canary.py"),
        )
        self.assertIn("CALENDAR_CANARY_CONTRACT_DEPS=INSTALLED", text)
        source = pathlib.Path(__file__).read_text(encoding="utf-8")
        self.assertIn("import yaml", source)


if __name__ == "__main__":
    unittest.main()
