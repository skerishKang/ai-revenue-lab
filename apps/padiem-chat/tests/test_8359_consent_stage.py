"""#8359 — owner/consent 거부 단계 코드가 값 없이 남는지 고정한다."""
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest

from app import oracle_mesh_read_return_routes as routes
from app import pc_helper_maintenance_host as host

SUB = "subject_fixture"
DEVICE = "node//fixture"
# The connector's own enrollment device id, paired with the Mesh node in the
# deployment ownership map - the value a consent grant stores.
CONNECTOR = "connector_fixture"
SCOPE = {"owner_subject_id": SUB, "account_ref": "acct_fixture", "workspace_ref": "ws_fixture"}
CONSENT = {**SCOPE, "device_id": CONNECTOR, "withdrawn_at": None,
           "consent_id": "consent_fixture"}


def _source(node_ref=DEVICE):
    return routes.OracleMeshReturnSource(
        [{"account_ref": SCOPE["account_ref"], "device_id": CONNECTOR,
          "node_ref": node_ref, "root_ref": "pcroot_fixture",
          "path_relative": "fixture.txt", "file_path": "C:/fixture.txt",
          "command_exec": True}],
        "s" * 32, routes.EXECUTION_MODE_MESH)


def _request(source=None):
    return SimpleNamespace(app=SimpleNamespace(
        state=SimpleNamespace(control_plane_identity_authority=object(),
                              oracle_mesh_return_source=source or _source())))


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
        ("consent_device", SCOPE, _consent(device_id="other")),
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
        assert f"outcome=denied reason={stage}" in caplog.text, stage
        for value in (SUB, DEVICE, CONNECTOR, "acct_fixture", "ws_fixture", "consent_fixture",
                      "other_account", "other_workspace"):
            assert value not in caplog.text, (stage, value)


def test_missing_server_pair_has_its_own_stage(caplog, monkeypatch):
    """Without the map's device pin there is no consent key to look up; the
    refusal is staged and carries no device, account or workspace value."""
    caplog.clear()
    called = []

    async def read(identity, method, **kwargs):
        called.append(method)
        return SCOPE

    monkeypatch.setattr(host, "mode_connector_read", read)
    with caplog.at_level(logging.WARNING, logger=host.logger.name):
        result = asyncio.run(host._authorized(
            _request(_source(node_ref="node//other")), None, {"device_id": DEVICE},
            _session(), "user_fixture", None))
    assert result == (None, None, "owner_consent_missing")
    assert called == ["owner_scope"]
    assert "outcome=denied reason=consent_map_missing" in caplog.text
    for value in (SUB, DEVICE, CONNECTOR, "acct_fixture", "ws_fixture"):
        assert value not in caplog.text, value


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
    assert "outcome=denied reason=consent_read_error" in caplog.text
    assert "connector read failed" not in caplog.text


def test_owner_denial_codes_are_a_closed_value_free_set():
    assert host.OWNER_DENIAL_CODES == frozenset({
        "scope_missing", "consent_source_missing", "consent_reference_missing",
        "consent_account_invalid", "consent_node_invalid", "consent_map_missing",
        "consent_pin_ambiguous", "consent_pin_invalid", "consent_read_error",
        "scope_subject", "consent_missing", "consent_subject", "consent_device",
        "consent_withdrawn", "consent_id", "account_ref_mismatch",
        "workspace_ref_mismatch",
    })
    for code in host.OWNER_DENIAL_CODES:
        assert host._CLOSED_CODE.fullmatch(code)
        assert SUB not in code and DEVICE not in code and CONNECTOR not in code


@pytest.mark.parametrize("case", [
    "consent_node_invalid", "consent_map_missing",
    "consent_pin_ambiguous", "consent_pin_invalid",
])
def test_pre_consent_reference_codes_are_distinct_and_stop_before_the_read(caplog, monkeypatch, case):
    """A refused consent key is checked before the consent call, so a
    vanishing consent_read error does not mean the consent problem was fixed.
    """
    caplog.clear()
    calls = []

    async def read(identity, method, **kwargs):
        calls.append(method)
        return SCOPE if method == "owner_scope" else CONSENT

    monkeypatch.setattr(host, "mode_connector_read", read)
    if case == "consent_node_invalid":
        node = "node/bad"
        source = _source(node_ref=node)
        facts = {"device_id": node}
    elif case == "consent_map_missing":
        source = _source(node_ref="node//other")
        facts = {"device_id": DEVICE}
    elif case == "consent_pin_ambiguous":
        source = routes.OracleMeshReturnSource(
            [{"account_ref": SCOPE["account_ref"], "device_id": CONNECTOR,
              "node_ref": DEVICE, "root_ref": "pcroot_fixture",
              "path_relative": "a.txt", "file_path": "C:/a.txt", "command_exec": True},
             {"account_ref": SCOPE["account_ref"], "device_id": "connector_other",
              "node_ref": DEVICE, "root_ref": "pcroot_fixture",
              "path_relative": "b.txt", "file_path": "C:/b.txt", "command_exec": True}],
            "s" * 32, routes.EXECUTION_MODE_MESH)
        facts = {"device_id": DEVICE}
    else:
        source = routes.OracleMeshReturnSource(
            [{"account_ref": SCOPE["account_ref"], "device_id": "device/bad",
              "node_ref": DEVICE, "root_ref": "pcroot_fixture",
              "path_relative": "a.txt", "file_path": "C:/a.txt", "command_exec": True}],
            "s" * 32, routes.EXECUTION_MODE_MESH)
        facts = {"device_id": DEVICE}
    with caplog.at_level(logging.WARNING, logger=host.logger.name):
        result = asyncio.run(host._authorized(
            _request(source), None, facts, _session(), "user_fixture", None))
    assert result == (None, None, "owner_consent_missing")
    assert calls == ["owner_scope"]
    assert f"outcome=denied reason={case}" in caplog.text
    for value in (SUB, DEVICE, CONNECTOR, "connector_other", "device/bad"):
        assert value not in caplog.text, (case, value)


def test_missing_source_and_non_string_scope_have_their_own_codes(caplog, monkeypatch):
    async def read(identity, method, **kwargs):
        return _scope(account_ref=123) if method == "owner_scope" else CONSENT

    monkeypatch.setattr(host, "mode_connector_read", read)
    for code, source in (("consent_account_invalid", _source()),
                         ("consent_source_missing", None)):
        caplog.clear()
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
            control_plane_identity_authority=object(), oracle_mesh_return_source=source)))
        with caplog.at_level(logging.WARNING, logger=host.logger.name):
            result = asyncio.run(host._authorized(
                request, None, {"device_id": DEVICE}, _session(), "user_fixture", None))
        assert result == (None, None, "owner_consent_missing")
        assert f"outcome=denied reason={code}" in caplog.text


def test_repeated_denial_is_logged_once_per_device_and_code(caplog, monkeypatch):
    caplog.clear()

    async def read(identity, method, **kwargs):
        return SCOPE

    monkeypatch.setattr(host, "mode_connector_read", read)
    request = _request(_source(node_ref="node//other"))
    with caplog.at_level(logging.WARNING, logger=host.logger.name):
        for _ in range(3):
            assert asyncio.run(host._authorized(
                request, None, {"device_id": DEVICE}, _session(), "user_fixture", None)) == (
                    None, None, "owner_consent_missing")
    text = caplog.text
    assert text.count("pc_maintenance_owner_authority outcome=denied") == 1
    assert "reason=consent_map_missing" in text
    # A different closed code still logs once; the throttle does not hide a
    # distinct cause or a different device.
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=host.logger.name):
        asyncio.run(host._authorized(
            request, None, {"device_id": DEVICE}, _session(), "user_fixture", None))
    assert caplog.text == ""


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
    assert "outcome=denied reason=" not in caplog.text
