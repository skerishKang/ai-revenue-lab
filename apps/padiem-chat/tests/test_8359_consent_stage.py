"""#8359 — owner/consent 거부 단계 코드가 값 없이 남는지 고정한다."""
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest

from app import pc_helper_maintenance_host as host

SUB = "subject_fixture"
DEVICE = "node//fixture"
SCOPE = {"owner_subject_id": SUB, "account_ref": "acct_fixture", "workspace_ref": "ws_fixture"}
CONSENT = {**SCOPE, "device_id": DEVICE, "withdrawn_at": None, "consent_id": "consent_fixture"}


def _request():
    return SimpleNamespace(app=SimpleNamespace(
        state=SimpleNamespace(control_plane_identity_authority=object())))


def _session():
    return SimpleNamespace(session_id="session_fixture",
                           subject=SimpleNamespace(subject_id=SUB))


def _consent(**changes):
    return {**CONSENT, **changes}


def _scope(**changes):
    return {**SCOPE, **changes}


def test_denial_stage_codes_are_value_free(caplog, monkeypatch):
    cases = [
        ("scope_missing", None, CONSENT),
        ("scope_subject", _scope(owner_subject_id="other_subject"), CONSENT),
        ("consent_missing", SCOPE, None),
        ("consent_subject", SCOPE, _consent(owner_subject_id="other_subject")),
        ("consent_device", SCOPE, _consent(device_id="node//other")),
        ("consent_withdrawn", SCOPE, _consent(withdrawn_at="2026-11-23T00:00:00Z")),
        ("consent_id", SCOPE, _consent(consent_id=None)),
        ("account_ref_mismatch", SCOPE, _consent(account_ref="other_account")),
        ("workspace_ref_mismatch", SCOPE, _consent(workspace_ref="other_workspace")),
    ]
    for stage, scope, consent in cases:
        caplog.clear()

        async def read(identity, method, **kwargs):
            return scope if method == "owner_scope" else consent

        monkeypatch.setattr(host, "mode_connector_read", read)
        with caplog.at_level(logging.WARNING, logger=host.logger.name):
            result = asyncio.run(host._authorized(
                _request(), None, {"device_id": DEVICE}, _session(), "user_fixture", None))
        assert result == (None, None, "owner_consent_missing"), stage
        assert f"outcome=denied stage={stage}" in caplog.text, stage
        for value in (SUB, DEVICE, "acct_fixture", "ws_fixture", "consent_fixture",
                      "other_account", "other_workspace"):
            assert value not in caplog.text, (stage, value)


def test_consent_read_error_has_its_own_stage(caplog, monkeypatch):
    caplog.clear()

    async def read(identity, method, **kwargs):
        if method == "owner_scope":
            return SCOPE
        raise RuntimeError("connector read failed")

    monkeypatch.setattr(host, "mode_connector_read", read)
    with caplog.at_level(logging.WARNING, logger=host.logger.name):
        result = asyncio.run(host._authorized(
            _request(), None, {"device_id": DEVICE}, _session(), "user_fixture", None))
    assert result == (None, None, "owner_consent_missing")
    assert "outcome=denied stage=consent_read_error" in caplog.text
    assert "connector read failed" not in caplog.text


def test_valid_consent_does_not_emit_a_denial_stage(caplog, monkeypatch):
    caplog.clear()

    async def read(identity, method, **kwargs):
        return SCOPE if method == "owner_scope" else CONSENT

    async def resolver(*args, **kwargs):
        raise AssertionError("resolver reached")

    monkeypatch.setattr(host, "mode_connector_read", read)
    with caplog.at_level(logging.WARNING, logger=host.logger.name):
        try:
            asyncio.run(host._authorized(
                _request(), None, {"device_id": DEVICE}, _session(), "user_fixture", resolver))
        except AssertionError:
            pass
    assert "outcome=denied stage=" not in caplog.text
