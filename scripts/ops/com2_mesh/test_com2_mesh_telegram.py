import importlib.util
import json
from pathlib import Path
from unittest import mock

import pytest

SOURCE = Path(__file__).with_name("com2-mesh-telegram.py")
spec = importlib.util.spec_from_file_location("recovery_telegram", SOURCE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def config(tmp_path):
    (tmp_path / ".env").write_text("TELEGRAM_BOT_TOKEN=dummy-token\n", encoding="utf-8")
    (tmp_path / "config.yaml").write_text("telegram:\n  home_channel: 12345\n", encoding="utf-8")


def test_read_existing_hermes_config(tmp_path):
    config(tmp_path)
    assert mod.read_config(tmp_path, {}) == ("dummy-token", "12345")


def test_missing_token_fails_closed(tmp_path):
    with pytest.raises(mod.NotifyFailure, match="TELEGRAM_TOKEN_MISSING"):
        mod.read_config(tmp_path, {})


def test_missing_chat_fails_closed(tmp_path):
    config(tmp_path)
    (tmp_path / "config.yaml").write_text("telegram: {}\n", encoding="utf-8")
    with pytest.raises(mod.NotifyFailure, match="TELEGRAM_CHAT_MISSING"):
        mod.read_config(tmp_path, {})


def test_send_uses_existing_target_and_checks_telegram_response():
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit): return b'{"ok":true}'
    with mock.patch.object(mod.request, "urlopen", return_value=Response()) as send:
        mod.send_message("dummy-token", "12345", "test")
    req = send.call_args.args[0]
    assert json.loads(req.data) == {"chat_id": "12345", "text": "test"}
    assert req.get_header("User-agent") == "padiem-com1-recovery/1.0"


def test_http_failure_exposes_only_status():
    exc = mod.error.HTTPError("https://example.invalid/secret", 403, "secret", None, None)
    with mock.patch.object(mod.request, "urlopen", side_effect=exc):
        with pytest.raises(mod.NotifyFailure) as raised:
            mod.send_message("dummy-token", "12345", "test")
    assert str(raised.value) == "TELEGRAM_HTTP_403"
