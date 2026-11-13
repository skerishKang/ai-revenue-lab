"""Session discovery stays dark; input auditing never fingerprints its text."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
from pathlib import Path

import pytest

from app.config import ConfigError, Settings
from app.mcp_gateway_store import mcp_audit_arguments, mcp_request_digest
from app.mcp_gateway_transport import validate_tool_arguments
from test_mcp_gateway_transport import gateway, post, MODERN, LEGACY


JOB = "dsp_" + "a" * 32


def enable(gateway):
    settings = gateway.app.state.settings
    settings.mcp_pc_shell_enabled = True
    settings.mcp_pc_shell_user_mode_enabled = True
    settings.mcp_pc_session_enabled = True


@pytest.mark.parametrize("value", [None, "", "0", "false", False])
def test_session_flag_stays_off(value):
    assert Settings.from_values(mcp_pc_session_enabled=value).mcp_pc_session_enabled is False


@pytest.mark.parametrize("value", ["1", "true", True, " TRUE "])
def test_session_flag_explicitly_enables(value):
    assert Settings.from_values(mcp_pc_session_enabled=value).mcp_pc_session_enabled is True


def test_session_flag_rejects_a_typo_and_reads_its_environment(monkeypatch):
    with pytest.raises(ConfigError, match="PADIEM_MCP_PC_SESSION_ENABLED"):
        Settings.from_values(mcp_pc_session_enabled="yes")
    monkeypatch.delenv("PADIEM_MCP_PC_SESSION_ENABLED", raising=False)
    assert Settings().mcp_pc_session_enabled is False
    assert Settings.from_env().mcp_pc_session_enabled is False
    monkeypatch.setenv("PADIEM_MCP_PC_SESSION_ENABLED", "true")
    assert Settings.from_env().mcp_pc_session_enabled is True


@pytest.mark.parametrize("version", [MODERN, LEGACY])
def test_session_schema_is_added_only_after_all_three_switches(gateway, version):
    baseline = post(gateway, version=version).json()["result"]["tools"]
    gateway.app.state.settings.mcp_pc_session_enabled = True
    assert post(gateway, version=version).json()["result"]["tools"] == baseline
    enable(gateway)
    tools = {item["name"]: item for item in post(gateway, version=version).json()["result"]["tools"]}
    assert "pc_shell_input" in tools
    assert len(tools) == len(baseline) + 1
    start = tools["pc_shell_start"]["inputSchema"]["properties"]
    assert start["interactive"]["type"] == "boolean"
    assert start["command"].get("minLength", 0) == 0
    assert start["wait_ms"]["maximum"] == 10000
    assert "status_only" in tools["pc_shell_read"]["inputSchema"]["properties"]
    assert "offset" in tools["pc_shell_stop"]["inputSchema"]["properties"]
    gateway.app.state.settings.mcp_pc_session_enabled = False
    off = {item["name"]: item for item in post(gateway, version=version).json()["result"]["tools"]}
    assert "pc_shell_input" not in off
    assert "interactive" not in off["pc_shell_start"]["inputSchema"]["properties"]
    assert "wait_ms" not in off["pc_shell_read"]["inputSchema"]["properties"]
    assert "offset" not in off["pc_shell_stop"]["inputSchema"]["properties"]


@pytest.mark.parametrize("disabled", ["mcp_pc_shell_enabled", "mcp_pc_shell_user_mode_enabled", "mcp_pc_session_enabled"])
def test_input_named_directly_is_refused_without_every_switch(gateway, disabled):
    enable(gateway)
    setattr(gateway.app.state.settings, disabled, False)
    response = post(gateway, "tools/call", params={
        "name": "pc_shell_input", "arguments": {"job_id": JOB, "text": "hello"}})
    assert response.json()["error"]["data"]["code"] == "tool_not_enabled"
    assert gateway.calls == [] and gateway.store.records == []


def test_input_validation_has_a_closed_bounded_schema():
    options = {"user_mode_enabled": True, "session_enabled": True}
    valid = {"job_id": JOB, "text": "한글" * 2000, "wait_ms": 10000}
    assert validate_tool_arguments("pc_shell_input", valid, **options)
    assert not validate_tool_arguments("pc_shell_input", valid)
    for extra in ({"text": "a" * 4001}, {"wait_ms": 10001}, {"wait_ms": True},
                  {"text": "a\r"}, {"text": "a\0"}, {"text_b64": "eA=="},
                  {"unknown": 1}, {"length": 65537}):
        assert not validate_tool_arguments("pc_shell_input", {**valid, **extra}, **options)


@pytest.mark.parametrize("secret", [False, True])
def test_input_audit_and_log_have_length_but_neither_text_nor_text_hash(gateway, caplog, secret):
    enable(gateway)
    texts = ("first-input-가", "other-input-나")
    arguments = {"job_id": JOB, "secret": secret, "text": texts[0]}
    with caplog.at_level(logging.INFO, logger="padiem_chat.request"):
        result = post(gateway, "tools/call", params={"name": "pc_shell_input", "arguments": arguments})
    assert result.json()["result"]["structuredContent"]["status"] == "completed"
    assert gateway.calls[0][2] == arguments  # only the execution boundary receives text
    assert len(gateway.store.records) == 2
    expected = len(texts[0].encode("utf-8"))
    for record in gateway.store.records:
        assert record["command_bytes"] == expected
        assert record["arguments"] == {"job_id": JOB, "secret": secret, "text_bytes": expected}
    serialized = json.dumps(gateway.store.records, ensure_ascii=False) + caplog.text
    assert texts[0] not in serialized
    assert base64.b64encode(texts[0].encode()).decode() not in serialized
    assert hashlib.sha256(texts[0].encode()).hexdigest() not in serialized
    assert mcp_request_digest("pc_shell_input", arguments) == mcp_request_digest(
        "pc_shell_input", {**arguments, "text": texts[1]})
    safe = mcp_audit_arguments("pc_shell_input", {**arguments, "text_sha256": "private-digest"})
    assert "text_sha256" not in safe and "text" not in safe
    assert gateway.store.approvals == [] and gateway.store.consumed == []


def test_input_never_creates_an_approval_containing_raw_text(gateway):
    enable(gateway)

    async def uncertain(*args, **kwargs):
        return {"status": "confirmation_required"}

    gateway.app.state.mcp_gateway_executor = uncertain
    result = post(gateway, "tools/call", params={
        "name": "pc_shell_input", "arguments": {"job_id": JOB, "text": "private-input"}})
    assert result.json()["result"]["structuredContent"]["code"] == "pc_session_input_uncertain"
    assert gateway.store.approvals == []


def test_key_only_input_records_zero_text_bytes(gateway):
    enable(gateway)
    post(gateway, "tools/call", params={
        "name": "pc_shell_input", "arguments": {"job_id": JOB, "key": "enter"}})
    assert len(gateway.store.records) == 2
    assert all(record["command_bytes"] == 0 for record in gateway.store.records)


@pytest.mark.asyncio
async def test_real_audit_db_stores_input_length_without_granting_job_ownership():
    from test_mcp_gateway_account import setup, issued

    db, owner, _other, store = setup()
    migrations = Path(__file__).resolve().parents[1] / "migrations"
    for name in ("072_pc_device_pairing.sql", "103_pc_managed_links.sql"):
        db.conn.executescript((migrations / name).read_text(encoding="utf-8"))
    _token, identity = await issued(store, owner)
    text = "synthetic-private-input"
    await store.audit(identity=identity, tool_name="pc_shell_input",
                      arguments={"job_id": JOB, "text": text, "secret": True},
                      status="completed", command_bytes=len(text), job_receipt_id=JOB)
    assert await store.owns_job_receipt(identity=identity, job_id=JOB) is False
    rows = db.conn.execute("SELECT request_digest FROM padiem_mcp_audit WHERE tool_name='pc_shell_input'").fetchall()
    assert len(rows) == 1
    assert db.conn.execute("SELECT command_bytes FROM padiem_mcp_audit WHERE tool_name='pc_shell_input'").fetchone()[0] == len(text)
    assert rows[0][0] == mcp_request_digest("pc_shell_input", {
        "job_id": JOB, "text": "x" * len(text), "secret": True})
    dump = "\n".join(db.conn.iterdump())
    assert text not in dump and base64.b64encode(text.encode()).decode() not in dump
    assert hashlib.sha256(text.encode()).hexdigest() not in dump
