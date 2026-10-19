"""Network-free argv-parity contract for the Engine Drive/OAuth read-only attestation (#3860).

The served Engine version id is echoed into the guard as an argv token. The canonical
version-id grammar (`cloudflare_served_version.SERVED_VERSION_ID_RE`) accepts a leading
hyphen, so the separated form `--active-version "${active_version}"` lets argparse read
the id as an *option* and abort with a usage error before the predicate is ever consulted
— a live attestation that can only ever fail on such an id. This contract pins the
equal-form, proves both forms against the real guard, and keeps the read-only posture:
no Cloudflare call, no secret value, no mutation.
"""

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
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "b54-engine-google-oauth-binding-readonly.yml"
GUARD_PATH = ROOT / ".github" / "scripts" / "b54_engine_served_version_guard.py"
SELF_PATH = pathlib.Path(__file__)

CANONICAL_ACTIVE_VERSION_ARGV = '--active-version="${active_version}"'
SEPARATED_ACTIVE_VERSION_ARGV = '--active-version "${active_version}"'
# Grammar-legal *and* hyphen-leading, which is exactly what the separated form cannot carry.
LEADING_HYPHEN_VERSION_ID = "-canonical-safe-v1"
PLAIN_VERSION_ID = "ver-active-01"

REGISTRY_V1 = "PADIEM_ENGINE_CALLER_REGISTRY_V1"
GRANTS = "ENGINE_CONNECTOR_GRANTS"
OAUTH = "CONTROL_PLANE_GOOGLE_OAUTH"
GRANTS_DATABASE_ID = "6b77ad02-bc27-488f-bb97-6325f6750cba"
OAUTH_SERVICE = "padiem-google-oauth-state"
SECRET_VALUE = "never-print-drive-binding-value"

CONTRACT_MARKERS = (
    "ENGINE_CONNECTOR_GRANTS_SERVED_BINDING=PRESENT:d1",
    "CONTROL_PLANE_GOOGLE_OAUTH_SERVED_BINDING=PRESENT:service",
    "DRIVE_RUNTIME_BINDINGS_VALIDATED=YES",
)


def workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _bindings() -> list[dict]:
    return [
        {"name": REGISTRY_V1, "type": "secret_text", "text": SECRET_VALUE},
        {"name": GRANTS, "type": "d1", "id": GRANTS_DATABASE_ID},
        {"name": OAUTH, "type": "service", "service": OAUTH_SERVICE},
    ]


def _payload(version_id: str, bindings: list[dict] | None = None) -> dict:
    return {
        "success": True,
        "result": {"id": version_id, "resources": {"bindings": bindings or _bindings()}},
    }


def _load_guard():
    spec = importlib.util.spec_from_file_location("b54_engine_served_version_guard", GUARD_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@contextlib.contextmanager
def _settings_file(payload: dict):
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "engine-version-detail.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        yield str(path)


def _run_guard_inprocess(argv: list[str]) -> tuple[int, str]:
    """Drive the real guard parser; argparse aborts with SystemExit before any predicate."""

    guard = _load_guard()
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = guard.main(argv)
        except SystemExit as exc:  # argparse usage error path
            code = exc.code if isinstance(exc.code, int) else 2
    return int(code), out.getvalue() + err.getvalue()


def _run_guard_subprocess(settings_path: str, version_arg: str) -> subprocess.CompletedProcess:
    """Real subprocess against the committed guard script; local file only, no network."""

    return subprocess.run(
        [
            sys.executable,
            str(GUARD_PATH),
            "verify",
            "--version-settings",
            settings_path,
            version_arg,
            "--require-drive-runtime-bindings",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )


class WorkflowArgvShapeTests(unittest.TestCase):
    def test_served_version_reaches_the_guard_as_one_equal_form_token(self) -> None:
        text = workflow_text()
        self.assertEqual(text.count(CANONICAL_ACTIVE_VERSION_ARGV), 1)
        self.assertNotIn(SEPARATED_ACTIVE_VERSION_ARGV, text)

    def test_read_only_attestation_contract_markers_are_preserved(self) -> None:
        text = workflow_text()
        for marker in (
            "/workers/scripts/${ENGINE_WORKER}",
            "${base}/versions/${active_version}",
            "b54_engine_served_version_guard.py resolve-active",
            "--require-drive-runtime-bindings",
            "RAW_VERSION_DETAIL_OUTPUT=0",
            "SECRET_VALUE_OUTPUT=0",
            "PRODUCTION_MUTATION=0",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)
        # The live GET job stays push-to-main only; a PR must never reach Cloudflare.
        self.assertIn("github.event_name == 'push'", text)
        self.assertIn('branches:\n      - main', text)

    def test_this_contract_runs_on_the_pr_exact_head_job(self) -> None:
        text = workflow_text()
        invocation = f"python .github/tests/{SELF_PATH.name}"
        self.assertIn(invocation, text)
        job_start = text.index("  source-contract:")
        invoke_at = text.index(invocation, job_start)
        # The step runs on the bare setup-python interpreter: no dependency install
        # may sit between the job start and this contract, or it silently stops running.
        self.assertNotIn("pip install", text[job_start:invoke_at])
        next_job = text.index("  served-binding-readonly:")
        self.assertLess(invoke_at, next_job, "the contract must live in the PR-side job")


class GuardArgvBehaviourTests(unittest.TestCase):
    def test_equal_form_with_a_hyphen_leading_version_id_passes(self) -> None:
        code, out = _run_guard_inprocess(
            [
                "verify",
                "--version-settings",
                str(self._settings),
                f"--active-version={LEADING_HYPHEN_VERSION_ID}",
                "--require-drive-runtime-bindings",
            ]
        )
        self.assertEqual(code, 0, out)
        for marker in CONTRACT_MARKERS:
            self.assertIn(marker, out)

    def test_separated_form_is_eaten_by_argparse_before_the_predicate(self) -> None:
        code, out = _run_guard_inprocess(
            [
                "verify",
                "--version-settings",
                str(self._settings),
                "--active-version",
                LEADING_HYPHEN_VERSION_ID,
                "--require-drive-runtime-bindings",
            ]
        )
        self.assertEqual(code, 2, out)
        self.assertIn("usage:", out)
        self.assertIn("expected one argument", out)
        self.assertNotIn("DRIVE_RUNTIME_BINDINGS_VALIDATED=YES", out)

    def test_mismatched_active_version_fails_closed(self) -> None:
        code, out = _run_guard_inprocess(
            [
                "verify",
                "--version-settings",
                str(self._settings),
                f"--active-version={PLAIN_VERSION_ID}",
                "--require-drive-runtime-bindings",
            ]
        )
        self.assertEqual(code, 1)
        self.assertIn("B54_ENGINE_SERVED_VERSION_GUARD=FAIL", out)
        self.assertNotIn("DRIVE_RUNTIME_BINDINGS_VALIDATED=YES", out)

    def test_binding_values_are_never_echoed(self) -> None:
        for argv in (
            f"--active-version={LEADING_HYPHEN_VERSION_ID}",
            f"--active-version={PLAIN_VERSION_ID}",
        ):
            code, out = _run_guard_inprocess(
                [
                    "verify",
                    "--version-settings",
                    str(self._settings),
                    argv,
                    "--require-drive-runtime-bindings",
                ]
            )
            with self.subTest(argv=argv, code=code):
                self.assertNotIn(SECRET_VALUE, out)
                self.assertNotIn(GRANTS_DATABASE_ID, out)

    @classmethod
    def setUpClass(cls) -> None:
        stack = contextlib.ExitStack()
        cls.addClassCleanup(stack.close)
        cls._settings = stack.enter_context(
            _settings_file(_payload(LEADING_HYPHEN_VERSION_ID))
        )


class RealSubprocessParityTests(unittest.TestCase):
    def test_committed_guard_script_accepts_the_workflow_form(self) -> None:
        with _settings_file(_payload(LEADING_HYPHEN_VERSION_ID)) as settings:
            done = _run_guard_subprocess(
                settings, f"--active-version={LEADING_HYPHEN_VERSION_ID}"
            )
        self.assertEqual(done.returncode, 0, done.stderr)
        for marker in CONTRACT_MARKERS:
            self.assertIn(marker, done.stdout)
        self.assertNotIn(SECRET_VALUE, done.stdout + done.stderr)

    def test_committed_guard_script_rejects_the_retired_form(self) -> None:
        with _settings_file(_payload(LEADING_HYPHEN_VERSION_ID)) as settings:
            done = _run_guard_subprocess(settings, "--active-version")
        self.assertNotEqual(done.returncode, 0)
        self.assertNotIn("DRIVE_RUNTIME_BINDINGS_VALIDATED=YES", done.stdout)


if __name__ == "__main__":
    unittest.main()
