#!/usr/bin/env python3
"""Prevent a main push or an unapproved dispatch from creating a B62 Worker.

A missing Worker is NOT approval to deploy one. This is a source-policy and
isolated shell-guard test only; it never contacts Cloudflare or deploys code.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/b62-cloudflare-worker-deploy.yml"


def job_sections(source: str) -> tuple[str, str]:
    if source.count("\n  preflight:\n") != 1 or source.count("\n  deploy-mock:\n") != 1:
        raise AssertionError("B62 preflight/deploy job must each exist exactly once")
    _, rest = source.split("\n  preflight:\n", 1)
    before, deploy = rest.split("\n  deploy-mock:\n", 1)
    return before, deploy


def deploy_condition(deploy: str) -> str:
    match = re.search(r"(?m)^    if: >-\n((?:      [^\n]+\n)+)", deploy)
    if not match:
        raise AssertionError("missing explicit deploy-mock job-level condition")
    return match.group(1)


def guarded_script(deploy: str) -> str:
    anchor = "      - name: Guard initial Worker creation only\n"
    if deploy.count(anchor) != 1:
        raise AssertionError("guard step missing or duplicated")
    section = deploy.split(anchor, 1)[1].split("\n      - name:", 1)[0]
    if section.count("        run: |\n") != 1:
        raise AssertionError("guard step must contain exactly one executable shell block")
    lines = section.split("        run: |\n", 1)[1].splitlines()
    script = "\n".join(x[10:] for x in lines if x.startswith("          "))
    if not script.strip():
        raise AssertionError("guard script empty")
    return script + "\n"


class InitialMockRequiresManualConsent(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = WORKFLOW.read_text(encoding="utf-8")
        cls.preflight, cls.deploy = job_sections(cls.source)

    def test_auto_push_remains_read_only(self) -> None:
        self.assertIn("  push:\n    branches: [main]", self.source)
        self.assertIn("  pull_request:", self.source)
        self.assertIn("  workflow_dispatch:", self.source)
        self.assertIn("name: Read-only Cloudflare and B14 preflight", self.preflight)
        self.assertNotIn("uvx --from", self.preflight)
        condition = deploy_condition(self.deploy)
        self.assertIn("github.event_name == 'workflow_dispatch'", condition)
        self.assertNotIn("github.event_name == 'push'", condition)
        self.assertIn("github.ref == 'refs/heads/main'", condition)
        self.assertIn("inputs.allow_initial_mock_deploy == true", condition)
        self.assertIn("needs.preflight.outputs.worker_state == 'absent'", condition)

    def test_dispatch_defaults_to_no_deployment(self) -> None:
        dispatch = self.source.split("  workflow_dispatch:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertIn("allow_initial_mock_deploy:", dispatch)
        self.assertRegex(dispatch, r"(?m)^        type: boolean$")
        self.assertRegex(dispatch, r"(?m)^        required: true$")
        self.assertRegex(dispatch, r"(?m)^        default: false$")

    def test_guard_and_mock_only_deployment_are_preserved(self) -> None:
        self.assertIn("INIT_MOCK_APPROVED: " + "$" + "{{ inputs.allow_initial_mock_deploy }}", self.deploy)
        self.assertIn("WORKER_STATE: " + "$" + "{{ needs.preflight.outputs.worker_state }}", self.deploy)
        script = guarded_script(self.deploy)
        for key in ("GITHUB_EVENT_NAME", "GITHUB_REF", "INIT_MOCK_APPROVED", "WORKER_STATE"):
            self.assertIn(key, script)
        self.assertIn('if [ "$WORKER_STATE" != "absent" ]; then', script)
        self.assertIn("b62_cloudflare_mock_config_guard.py", self.deploy)
        self.assertEqual(self.deploy.count("pywrangler deploy"), 1)

    def test_actual_shell_guard_refuses_implicit_attempts(self) -> None:
        if os.name == "nt":
            # Windows System32/bash.exe is WSL, not Git Bash; it may hang
            # or reinterpret the process environment. Pin the installed
            # Git Bash next to the exact git executable instead.
            git = shutil.which("git")
            self.assertIsNotNone(git, "git.exe is required for the Windows runner")
            bash_path = Path(git).resolve().parent.parent / "bin" / "bash.exe"
            self.assertTrue(bash_path.is_file(), f"Git Bash unavailable: {bash_path}")
            bash = str(bash_path)
        else:
            bash = shutil.which("bash")
            self.assertIsNotNone(bash, "bash is required on the Linux runner")
        script = guarded_script(self.deploy)
        cases = [
            ("push", "refs/heads/main", "true", "absent", False),
            ("pull_request", "refs/heads/main", "true", "absent", False),
            ("workflow_dispatch", "refs/heads/topic", "true", "absent", False),
            ("workflow_dispatch", "refs/heads/main", "false", "absent", False),
            ("workflow_dispatch", "refs/heads/main", "", "absent", False),
            ("workflow_dispatch", "refs/heads/main", "true", "existing", False),
            ("workflow_dispatch", "refs/heads/main", "true", "absent", True),
        ]
        for event, ref, approved, worker, allowed in cases:
            with self.subTest(event=event, ref=ref, approved=approved, worker=worker):
                env = dict(os.environ)
                env.update(
                    GITHUB_EVENT_NAME=event,
                    GITHUB_REF=ref,
                    INIT_MOCK_APPROVED=approved,
                    WORKER_STATE=worker,
                )
                proc = subprocess.run(
                    [bash, "-c", script],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(proc.returncode == 0, allowed, proc.stderr)


if __name__ == "__main__":
    unittest.main()
