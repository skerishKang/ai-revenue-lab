"""#4139 Windows operator acceptance: no argv secret, canonical CLI and WSS."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from claw_connect import __main__ as cli
from claw_connect import operator_wss_enrollment as gate


def test_operator_review_refused_without_windows_or_operator_and_credential_dir(monkeypatch, capsys):
    monkeypatch.setenv(gate._REVIEW_OPERATOR_ENV, gate._REVIEW_OPERATOR_VALUE)
    monkeypatch.delenv(gate._CANONICAL_CREDENTIAL_DIR_ENV, raising=False)
    rc = cli.main(["enroll", "challenge.123", "--operator-wss-review"])
    assert rc == 1
    result = json.loads(capsys.readouterr().out)
    assert result["blocked"] is True and result["ok"] is False
    assert gate.operator_review_admitted() is False


def test_operator_wss_rejects_before_loading_kagent(monkeypatch):
    monkeypatch.setattr(gate.os, "name", "posix")
    monkeypatch.setenv(gate._REVIEW_OPERATOR_ENV, gate._REVIEW_OPERATOR_VALUE)
    monkeypatch.setenv(gate._CANONICAL_CREDENTIAL_DIR_ENV, "/synthetic/test/store")
    with pytest.raises(gate.DeviceSessionRefused, match="operator_wss_acceptance_not_configured"):
        asyncio.run(gate.enroll_via_operator_wss_review(
            enrollment=object(), challenge_id="challenge", pairing_code="a" * 32,
        ))


def test_old_enroll_still_does_not_use_review_wss():
    parser = cli.build_parser()
    original = parser.parse_args(["enroll", "challenge", "a" * 32])
    assert original.operator_wss_review is False
    explicit = parser.parse_args(["enroll", "challenge", "--operator-wss-review"])
    assert explicit.operator_wss_review is True and explicit.enroll_code is None


def test_review_argv_secret_denied_before_wss(monkeypatch, capsys):
    monkeypatch.setattr(gate, "operator_review_admitted", lambda: True)
    monkeypatch.setattr(cli, "ConnectApp", lambda: SimpleNamespace(enrollment=object()))
    secret = "secret-never-leak-on-output"
    assert cli.main(["enroll", "challenge", secret, "--operator-wss-review"]) == 2
    output = capsys.readouterr().out
    assert secret not in output
    assert json.loads(output)["blocked"] is True


def test_review_requires_an_interactive_terminal(monkeypatch, capsys):
    monkeypatch.setattr(gate, "operator_review_admitted", lambda: True)
    monkeypatch.setattr(cli, "ConnectApp", lambda: SimpleNamespace(enrollment=object()))
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: False))
    assert cli.main(["enroll", "challenge", "--operator-wss-review"]) == 1
    assert json.loads(capsys.readouterr().out)["blocked"] is True


def _mock_hidden_code(monkeypatch, secret):
    monkeypatch.setattr(gate, "operator_review_admitted", lambda: True)
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: secret)


def test_review_cli_secrets_never_projected_on_runtime_failure(monkeypatch, capsys):
    _mock_hidden_code(monkeypatch, "deadbeef" * 4)
    app = SimpleNamespace(enrollment=object())
    monkeypatch.setattr(cli, "ConnectApp", lambda: app)
    async def fail(**kwargs):
        raise RuntimeError("CREDENTIAL_SECRET_SHOULD_NEVER_SHOW")
    monkeypatch.setattr(gate, "enroll_via_operator_wss_review", fail)
    assert cli.main(["enroll", "challenge", "--operator-wss-review"]) == 1
    printed = capsys.readouterr().out
    assert "CREDENTIAL_SECRET_SHOULD_NEVER_SHOW" not in printed
    assert "deadbeef" not in printed
    assert json.loads(printed)["blocked"] is True


def test_operator_wss_can_use_existing_review_wss_without_autostart(monkeypatch, capsys):
    _mock_hidden_code(monkeypatch, "deadbeef" * 4)
    calls = []
    response = SimpleNamespace(safe_dict=lambda: {"raw_device_credential": False})
    app = SimpleNamespace(
        enrollment=object(), connector_status=lambda: SimpleNamespace(value="offline"),
        reconcile_autostart=lambda: calls.append("autostart"),
    )
    monkeypatch.setattr(cli, "ConnectApp", lambda: app)
    async def paired(**kwargs):
        calls.append(("wss", kwargs["pairing_code"]))
        return response
    monkeypatch.setattr(gate, "enroll_via_operator_wss_review", paired)
    assert cli.main(["enroll", "challenge", "--operator-wss-review"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True and data["enrollment"]["raw_device_credential"] is False
    assert data["autostart"] == "unavailable"
    assert calls == [("wss", "deadbeef" * 4)]


def test_review_login_opens_fixed_owner_page_and_returns_only_device_id(monkeypatch, capsys):
    _mock_hidden_code(monkeypatch, "unused")
    web_calls = []
    import webbrowser
    monkeypatch.setattr(webbrowser, "open", lambda url: web_calls.append(url))
    app = SimpleNamespace(enrollment=SimpleNamespace(record=lambda: SimpleNamespace(device_id="device.local.1")))
    monkeypatch.setattr(cli, "ConnectApp", lambda: app)
    assert cli.main(["login", "--operator-wss-review"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["device_id"] == "device.local.1"
    assert data["device_connected"] is False
    assert web_calls == ["https://chat.padiem.net/api/claw/connector/enrollments/setup"]
    assert "device.local.1" not in web_calls[0]


def test_offer_refused_without_operator_gates(monkeypatch, capsys):
    monkeypatch.setenv(gate._REVIEW_OPERATOR_ENV, gate._REVIEW_OPERATOR_VALUE)
    monkeypatch.delenv(gate._CANONICAL_CREDENTIAL_DIR_ENV, raising=False)
    assert cli.main(["offer", "--operator-wss-review"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["blocked"] is True and result["ok"] is False
    assert cli.main(["offer"]) == 1


def test_offer_drives_pending_offer_then_auto_enrolls_without_typed_secrets(monkeypatch, capsys):
    monkeypatch.setattr(gate, "operator_review_admitted", lambda: True)
    response = SimpleNamespace(
        safe_dict=lambda: {"device_id": "device.local.1", "raw_device_credential": False},
    )
    app = SimpleNamespace(
        enrollment=object(), connector_status=lambda: SimpleNamespace(value="unregistered"),
    )
    monkeypatch.setattr(cli, "ConnectApp", lambda: app)
    async def approved(**kwargs):
        assert set(kwargs) == {"enrollment"}
        return response
    monkeypatch.setattr(gate, "enroll_via_pending_pc_offer", approved)
    assert cli.main(["offer", "--operator-wss-review"]) == 0
    printed = capsys.readouterr().out
    data = json.loads(printed)
    assert data["ok"] is True and data["enrollment"]["raw_device_credential"] is False
    assert data["autostart"] == "unavailable"


def test_offer_parser_requires_no_secret_positionals():
    parser = cli.build_parser()
    parsed = parser.parse_args(["offer", "--operator-wss-review"])
    assert parsed.command == "offer" and parsed.operator_wss_review is True
    assert parser.parse_args(["offer"]).operator_wss_review is False
