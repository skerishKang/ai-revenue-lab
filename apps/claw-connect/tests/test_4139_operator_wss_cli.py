"""#4139 Windows acceptance CLI must be explicit and fail before any network."""
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
    rc = cli.main(["enroll", "challenge.123", "a" * 32, "--operator-wss-review"])
    assert rc == 1
    result = json.loads(capsys.readouterr().out)
    assert result["blocked"] is True and result["ok"] is False
    assert "aaaa" not in str(result)
    assert "password" not in str(result)
    assert gate.operator_review_admitted() is False


def test_operator_wss_rejects_before_loading_kagent(monkeypatch):
    monkeypatch.setattr(gate.os, "name", "posix")
    monkeypatch.setenv(gate._REVIEW_OPERATOR_ENV, gate._REVIEW_OPERATOR_VALUE)
    monkeypatch.setenv(gate._CANONICAL_CREDENTIAL_DIR_ENV, "/synthetic/test/store")
    with pytest.raises(gate.DeviceSessionRefused, match="operator_wss_acceptance_not_configured"):
        asyncio.run(gate.enroll_via_operator_wss_review(
            enrollment=object(), challenge_id="challenge", pairing_code="a" * 32,
        ))


def test_old_enroll_still_does_not_use_review_wss(monkeypatch):
    parser = cli.build_parser()
    original = parser.parse_args(["enroll", "challenge", "a" * 32])
    assert original.operator_wss_review is False
    explicit = parser.parse_args(["enroll", "challenge", "a" * 32, "--operator-wss-review"])
    assert explicit.operator_wss_review is True


def test_review_cli_secrets_never_projected_on_runtime_failure(monkeypatch, capsys):
    # On source-only CI, replace the admission and app with synthetic ports;
    # no DPAPI store or WSS socket is opened.
    monkeypatch.setattr(gate, "operator_review_admitted", lambda: True)
    app = SimpleNamespace(enrollment=object())
    monkeypatch.setattr(cli, "ConnectApp", lambda: app)
    async def fail(**kwargs):
        raise RuntimeError("CREDENTIAL_SECRET_SHOULD_NEVER_SHOW")
    monkeypatch.setattr(gate, "enroll_via_operator_wss_review", fail)
    assert cli.main(["enroll", "challenge", "deadbeef" * 4, "--operator-wss-review"]) == 1
    printed = capsys.readouterr().out
    assert "CREDENTIAL_SECRET_SHOULD_NEVER_SHOW" not in printed
    assert "deadbeef" not in printed
    assert json.loads(printed)["blocked"] is True


def test_operator_wss_can_use_existing_review_wss_without_autostart(monkeypatch, capsys):
    monkeypatch.setattr(gate, "operator_review_admitted", lambda: True)
    calls = []
    response = SimpleNamespace(safe_dict=lambda: {"raw_device_credential": False})
    app = SimpleNamespace(
        enrollment=object(), connector_status=lambda: SimpleNamespace(value="offline"),
        reconcile_autostart=lambda: calls.append("autostart"),
    )
    monkeypatch.setattr(cli, "ConnectApp", lambda: app)
    async def paired(**kwargs):
        calls.append("wss")
        return response
    monkeypatch.setattr(gate, "enroll_via_operator_wss_review", paired)
    assert cli.main(["enroll", "challenge", "deadbeef" * 4, "--operator-wss-review"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True and data["enrollment"]["raw_device_credential"] is False
    assert data["autostart"] == "unavailable"
    assert calls == ["wss"]
