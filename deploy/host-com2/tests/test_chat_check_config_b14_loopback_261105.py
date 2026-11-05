"""#6920/#6926 follow-up: the pre-start config check must accept the loopback
B14 position the application already accepts, and nothing looser.

unittest only: the deploy-from-main packaging job runs this directory without
pytest installed."""
from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path
from unittest import mock

_PATH = Path(__file__).resolve().parents[1] / "chat" / "check_config.py"
_spec = importlib.util.spec_from_file_location("chat_check_config_under_test", str(_PATH))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

SECRET = "s" * 32
_B14_NAMES = (
    "PADIEM_CHAT_RUNTIME_MODE", "B14_UPSTREAM_MODE", "B14_UPSTREAM_URL",
    "PADIEM_B14_SERVICE_PROOF_SECRET",
)


def _consistent(mode, url, secret=SECRET):
    env = {n: v for n, v in os.environ.items() if n not in _B14_NAMES}
    env.update({
        "PADIEM_CHAT_RUNTIME_MODE": "b14",
        "B14_UPSTREAM_MODE": mode,
        "B14_UPSTREAM_URL": url,
        "PADIEM_B14_SERVICE_PROOF_SECRET": secret,
    })
    with mock.patch.dict(os.environ, env, clear=True):
        return _mod._b14_consistent()


class B14LoopbackConfigCheck(unittest.TestCase):
    def test_https_origin_still_passes(self):
        self.assertIs(_consistent("https", "https://b14.padiem.net"), True)

    def test_loopback_origin_passes(self):
        for url in ("http://127.0.0.1:8789", "http://localhost:8789", "http://127.0.0.1"):
            with self.subTest(url=url):
                self.assertIs(_consistent("loopback", url), True)

    def test_anything_else_still_fails(self):
        cases = (
            ("loopback", "http://b14.padiem.net"),
            ("loopback", "https://127.0.0.1:8789"),
            ("loopback", "http://127.0.0.1.evil.example"),
            ("https", "http://127.0.0.1:8789"),
            ("binding", ""),
            ("", ""),
        )
        for mode, url in cases:
            with self.subTest(mode=mode, url=url):
                self.assertIs(_consistent(mode, url), False)

    def test_a_short_proof_secret_fails_in_loopback_too(self):
        self.assertIs(_consistent("loopback", "http://127.0.0.1:8789", secret="short"), False)

    def test_mock_runtime_mode_is_not_checked(self):
        with mock.patch.dict(os.environ, {"PADIEM_CHAT_RUNTIME_MODE": "mock"}, clear=False):
            self.assertIs(_mod._b14_consistent(), True)


if __name__ == "__main__":
    unittest.main()