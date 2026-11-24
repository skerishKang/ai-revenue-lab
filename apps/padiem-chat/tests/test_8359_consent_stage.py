"""#8359 — owner/consent 거부 코드가 값 없이 남는지 고정한다."""
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest

from app import pc_helper_maintenance_host as host

SUB = "subject_fixture"
DEVICE = "node//fixture"
# The connector's own enrollment device id, paired with the Mesh node in a
# server-owned dispatch record - the value a consent grant stores.
CONNECTOR = "connector_fixture"
SCOPE = {"owner_subject_id": SUB, "account_ref": "acct_fixture", "workspace_ref": "ws_fixture"}
CONSENT = {**SCOPE, "device_id": CONNECTOR, "withdrawn_at": None,
           "consent_id": "consent_fixture"}
OWNER = "usr_fixture"


def _request(*, key_result=(CONNECTOR, "observed"), with_history=True):
    history = None
    if with_history:
        async def consent_key_for_owner_node(**kw):
            return key_result
        history = SimpleNamespace(consent_key_for_owner_node=consent_key_for_owner_node)
    return SimpleNamespace(app=SimpleNamespace(
        state=SimpleNamespace(control_plane_identity_authority=object(),
                              history_store=history)))


def _session():
    return SimpleNamespace(session_id="session_fixture",
                           subject=SimpleNamespace(subject_id=SUB))


def _consent(**changes):
    return {**CONSENT, **changes}


def _scope(**changes):
    return {**SCOPE, **changes}


def _deny(caplog, monkeypatch, request, *, scope=SCOPE, consent=CONSENT, read=None):
    async def default_read(identity, method, **kwargs):
        return scope if method == "owner_scope" else consent

    monkeypatch.setattr(host, "mode_connector_read", read or default_read)
    with caplog.at_level(logging.WARNING, logger=host.logger.name):
        return asyncio.run(host._authorized(
            request, None, {"device_id": DEVICE}, _session(), OWNER, None))


def test_denial_stage_codes_are_value_free(caplog, monkeypatch):
    cases = [
        ("scope_missing", None, CONSENT),
        ("scope_subject", _scope(owner_subject_id="other_subject"), CONSENT),
        ("consent_missing", SCOPE, None),
        ("consent_subject", SCOPE, _consent(owner_subject_id="other_subject")),
        ("consent_device", SCOPE, _consent(device_id="other")),
        ("consent_withdrawn", SCOPE, _consent(withdrawn_at="2026-11-23T00:00:00Z")),
        ("consent_id", SCOPE, _consent(consent_id=None)),
        ("account_ref_mismatch", SCOPE, _consent(account_ref="other_account")),
        ("workspace_ref_mismatch", SCOPE, _consent(workspace_ref="other_workspace")),
    ]
    for stage, scope, consent in cases:
        caplog.clear()
        result = _deny(caplog, monkeypatch, _request(), scope=scope, consent=consent)
        assert result == (None, None, "owner_consent_missing"), stage
        assert f"outcome=denied reason={stage}" in caplog.text, stage
        for value in (SUB, DEVICE, CONNECTOR, "acct_fixture", "ws_fixture", "consent_fixture",
                      "other_account", "other_workspace"):
            assert value not in caplog.text, (stage, value)


@pytest.mark.parametrize("code", [
    "consent_key_record_missing", "consent_key_scope_mismatch",
    "consent_key_unpinned", "consent_key_ambiguous", "consent_key_invalid",
    "consent_key_invalid_request",
])
def test_missing_server_record_stops_before_the_consent_read(caplog, monkeypatch, code):
    """A refused consent-key lookup is checked before the consent call, so a
    vanishing consent_read error does not mean the consent problem was fixed.
    """
    caplog.clear()
    calls = []

    async def read(identity, method, **kwargs):
        calls.append(method)
        return SCOPE if method == "owner_scope" else CONSENT

    result = _deny(caplog, monkeypatch,
                   _request(key_result=(None, code)), read=read)
    assert result == (None, None, "owner_consent_missing")
    assert calls == ["owner_scope"]
    assert f"outcome=denied reason={code}" in caplog.text
    for value in (SUB, DEVICE, CONNECTOR):
        assert value not in caplog.text, value


def test_missing_history_store_and_foreign_account_have_their_own_codes(caplog, monkeypatch):
    caplog.clear()
    result = _deny(caplog, monkeypatch, _request(with_history=False))
    assert result == (None, None, "owner_consent_missing")
    assert "outcome=denied reason=consent_source_missing" in caplog.text


def test_consent_read_error_has_its_own_code(caplog, monkeypatch):
    caplog.clear()

    async def read(identity, method, **kwargs):
        if method == "owner_scope":
            return SCOPE
        raise RuntimeError("connector read failed")

    result = _deny(caplog, monkeypatch, _request(), read=read)
    assert result == (None, None, "owner_consent_missing")
    assert "outcome=denied reason=consent_read_error" in caplog.text
    assert "connector read failed" not in caplog.text


def test_owner_denial_codes_are_a_closed_value_free_set():
    assert host.OWNER_DENIAL_CODES == frozenset({
        "scope_missing", "consent_source_missing", "consent_reference_missing",
        "consent_account_invalid", "consent_node_invalid", "consent_map_missing",
        "consent_pin_ambiguous", "consent_pin_invalid", "consent_read_error",
        "scope_subject", "consent_missing", "consent_subject", "consent_device",
        "consent_withdrawn", "consent_id", "account_ref_mismatch",
        "workspace_ref_mismatch", "consent_key_invalid_request",
        "consent_key_record_missing", "consent_key_scope_mismatch",
        "consent_key_unpinned", "consent_key_ambiguous", "consent_key_invalid",
    })
    for code in host.OWNER_DENIAL_CODES:
        assert host._CLOSED_CODE.fullmatch(code)
        assert SUB not in code and DEVICE not in code and CONNECTOR not in code


def test_repeated_denial_is_logged_once_per_device_and_code(caplog, monkeypatch):
    caplog.clear()
    request = _request(key_result=(None, "consent_key_record_missing"))
    for _ in range(3):
        assert _deny(caplog, monkeypatch, request) == (None, None, "owner_consent_missing")
    text = caplog.text
    assert text.count("pc_maintenance_owner_authority outcome=denied") == 1
    assert "reason=consent_key_record_missing" in text
    caplog.clear()
    _deny(caplog, monkeypatch, request)
    assert caplog.text == ""


def test_valid_consent_does_not_emit_a_denial_stage(caplog, monkeypatch):
    caplog.clear()

    async def resolver(*args, **kwargs):
        raise AssertionError("resolver reached")

    monkeypatch.setattr(host, "mode_connector_read",
                        lambda identity, method, **kw: _async_value(
                            SCOPE if method == "owner_scope" else CONSENT))
    with caplog.at_level(logging.WARNING, logger=host.logger.name):
        try:
            asyncio.run(host._authorized(
                _request(), None, {"device_id": DEVICE}, _session(), OWNER, resolver))
        except AssertionError:
            pass
    assert "outcome=denied reason=" not in caplog.text


async def _async_value(value):
    return value
