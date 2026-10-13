"""Operator-only exact second WSS target, no arbitrary host override."""
from __future__ import annotations

import json
from types import SimpleNamespace
import pytest

from claw_connect import __main__ as cli
from claw_connect import operator_wss_enrollment as op
from claw_connect.wss_target import (
    ACCEPTANCE_WSS_HOST, ACCEPTANCE_WSS_URL,
    REVIEW_WSS_URL, WssTargetNotApproved,
    review_only_pinned_wss_target,
)


def test_acceptance_requires_an_explicit_target_policy_pin():
    assert ACCEPTANCE_WSS_HOST == "connector-acceptance.padiem.net"
    assert review_only_pinned_wss_target(REVIEW_WSS_URL) == REVIEW_WSS_URL
    assert review_only_pinned_wss_target(ACCEPTANCE_WSS_URL, acceptance=True) == ACCEPTANCE_WSS_URL
    for target, acceptance in (
        (ACCEPTANCE_WSS_URL, False),
        (REVIEW_WSS_URL, True),
        (ACCEPTANCE_WSS_URL + "?code=secret", True),
        (ACCEPTANCE_WSS_URL.replace("wss://", "ws://"), True),
        (ACCEPTANCE_WSS_URL.replace(".padiem.net", ".padiem.net.evil.test"), True),
        (ACCEPTANCE_WSS_URL.replace("connector-acceptance.", "localhost."), True),
    ):
        with pytest.raises(WssTargetNotApproved):
            review_only_pinned_wss_target(target, acceptance=acceptance)


def test_operator_target_environment_rejects_any_unreviewed_host(monkeypatch):
    monkeypatch.delenv(op._TARGET_ENV, raising=False)
    assert op.operator_review_target_host() == "chat.padiem.net"
    monkeypatch.setenv(op._TARGET_ENV, ACCEPTANCE_WSS_HOST)
    assert op.operator_review_target_host() == ACCEPTANCE_WSS_HOST
    for x in ("evil.example", "chat.padiem.net:443",
              "https://connector-acceptance.padiem.net", "CHAT.PADIEM.NET"):
        monkeypatch.setenv(op._TARGET_ENV, x)
        with pytest.raises(op.DeviceSessionRefused, match="unreviewed_operator_wss_host"):
            op.operator_review_target_host()


def test_operator_login_targets_the_accepted_pinned_browser_origin(monkeypatch, capsys):
    monkeypatch.setenv(op._TARGET_ENV, ACCEPTANCE_WSS_HOST)
    monkeypatch.setattr(op, "operator_review_admitted", lambda: True)
    app = SimpleNamespace(enrollment=SimpleNamespace(
        record=lambda: SimpleNamespace(device_id="device.acceptance.1"),
    ))
    monkeypatch.setattr(cli, "ConnectApp", lambda: app)
    import webbrowser
    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda value: opened.append(value))
    assert cli.main(["login", "--operator-wss-review"]) == 0
    record = json.loads(capsys.readouterr().out)
    assert record["device_id"] == "device.acceptance.1"
    assert record["device_connected"] is False
    assert opened == ["https://connector-acceptance.padiem.net/api/claw/connector/enrollments/setup"]
    assert record["login_url"] == opened[0]
