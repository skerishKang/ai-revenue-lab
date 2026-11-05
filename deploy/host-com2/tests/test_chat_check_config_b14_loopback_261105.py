"""#6920/#6926 follow-up: the pre-start config check must accept the loopback
B14 position the application already accepts, and nothing looser."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "chat" / "check_config.py"
_spec = importlib.util.spec_from_file_location("chat_check_config_under_test", str(_PATH))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

SECRET = "s" * 32


def _env(monkeypatch, **values):
    for name in ("PADIEM_CHAT_RUNTIME_MODE", "B14_UPSTREAM_MODE", "B14_UPSTREAM_URL",
                 "PADIEM_B14_SERVICE_PROOF_SECRET"):
        monkeypatch.delenv(name, raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_https_origin_still_passes(monkeypatch):
    _env(monkeypatch, PADIEM_CHAT_RUNTIME_MODE="b14", B14_UPSTREAM_MODE="https",
         B14_UPSTREAM_URL="https://b14.padiem.net", PADIEM_B14_SERVICE_PROOF_SECRET=SECRET)
    assert _mod._b14_consistent() is True


@pytest.mark.parametrize("url", ["http://127.0.0.1:8789", "http://localhost:8789", "http://127.0.0.1"])
def test_loopback_origin_passes(monkeypatch, url):
    _env(monkeypatch, PADIEM_CHAT_RUNTIME_MODE="b14", B14_UPSTREAM_MODE="loopback",
         B14_UPSTREAM_URL=url, PADIEM_B14_SERVICE_PROOF_SECRET=SECRET)
    assert _mod._b14_consistent() is True


@pytest.mark.parametrize("mode,url", [
    ("loopback", "http://b14.padiem.net"),
    ("loopback", "https://127.0.0.1:8789"),
    ("loopback", "http://127.0.0.1.evil.example"),
    ("https", "http://127.0.0.1:8789"),
    ("binding", ""),
    ("", ""),
])
def test_anything_else_still_fails(monkeypatch, mode, url):
    _env(monkeypatch, PADIEM_CHAT_RUNTIME_MODE="b14", B14_UPSTREAM_MODE=mode,
         B14_UPSTREAM_URL=url, PADIEM_B14_SERVICE_PROOF_SECRET=SECRET)
    assert _mod._b14_consistent() is False


def test_a_short_proof_secret_fails_in_loopback_too(monkeypatch):
    _env(monkeypatch, PADIEM_CHAT_RUNTIME_MODE="b14", B14_UPSTREAM_MODE="loopback",
         B14_UPSTREAM_URL="http://127.0.0.1:8789", PADIEM_B14_SERVICE_PROOF_SECRET="short")
    assert _mod._b14_consistent() is False