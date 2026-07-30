"""Tests for audit_cloudflare_pages_credentials.py."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_cloudflare_pages_credentials.py"


class TestAuditSyntax(unittest.TestCase):
    def test_script_syntax(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(SCRIPT)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_fails_without_secrets(self) -> None:
        env = os.environ.copy()
        env.pop("CLOUDFLARE_API_TOKEN", None)
        env.pop("CLOUDFLARE_ACCOUNT_ID", None)
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            capture_output=True, text=True, timeout=15, env=env,
        )
        self.assertNotEqual(result.returncode, 0)

    def test_fails_with_empty_token(self) -> None:
        env = os.environ.copy()
        env["CLOUDFLARE_API_TOKEN"] = ""
        env["CLOUDFLARE_ACCOUNT_ID"] = "9be14bb7b8974e65d0afba647ab16932"
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            capture_output=True, text=True, timeout=15, env=env,
        )
        self.assertNotEqual(result.returncode, 0)

    def test_fails_with_empty_account_id(self) -> None:
        env = os.environ.copy()
        env["CLOUDFLARE_API_TOKEN"] = "cfoat_test1234567890"
        env["CLOUDFLARE_ACCOUNT_ID"] = ""
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            capture_output=True, text=True, timeout=15, env=env,
        )
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
