"""#8953 2/5: an edit is verified as a mutation, never a successful refusal.

Synthetic signed-transport seam only: no real PC, network or user files.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json

import pytest

from app import claw_pc_query_step_driver as driver
from app.pc_action_verification import mutation_observation, verify_pc_action

RUN = "run_8953_edit"
DISPATCH = "dsp_" + "e" * 32
OWNER = ("subject", RUN, "padiem-chat", "fixture-device")
SOURCE = b"before\nchanged\nlast\n"
AFTER = b"before\nNEW\nlast\n"
DIGEST = hashlib.sha256(AFTER).hexdigest()


def _account(*, ok=True, reason=None, digest=DIGEST):
    return {
        "ok": ok, "op": "edit", "reason": reason, "target": "notes.txt",
        "backup": "backup/notes.txt", "bytes": len(AFTER),
        "line_start": 2, "line_end": 2, "before_context": "before\nchanged\nlast",
        "after_context": "before\nNEW\nlast", "replacement_count": 1,
        "truncated": False, "newline_converted": False,
        "edit_expected_sha256": DIGEST,
        "verification": {"version": 1, "status": "observed",
            "source_exists": True, "target_exists": True, "target_is_file": True,
            "target_bytes": len(AFTER), "target_sha256": digest,
            "backup_exists": True, "backup_is_file": True,
            "edit_verified": True},
    }


def _verify(account, state="done"):
    return verify_pc_action(
        operation="edit", path="notes.txt",
        extra={"old_text": "changed", "new_text": "NEW", "replace_all": False},
        account=account, state=state, termination="no_exit_code", exit_code=None,
    )


def test_verified_edit_provides_bounded_context_and_readback_evidence():
    account = _account()
    verified = _verify(account)
    assert verified["status"] == "verified" and verified["reason"] == "postconditions_match"
    result = mutation_observation(
        verification=verified, account=account, final={"termination": "no_exit_code"},
        dispatch_id=DISPATCH,
    )
    assert result["ok"] is True and result["execution_confirmed"] is True
    assert result["line_start"] == result["line_end"] == 2
    assert result["before_context"] == "before\nchanged\nlast"
    assert result["after_context"] == "before\nNEW\nlast"
    assert result["replacement_count"] == 1 and result["truncated"] is False
    assert result["backup"] == "backup/notes.txt"
    assert json.loads(result["output"])["after_context"] == result["after_context"]


@pytest.mark.parametrize("reason", [
    "edit_not_found", "edit_not_unique", "edit_conflict",
    "edit_encoding_unsupported", "edit_verification_failed",
])
def test_pc_refusal_never_becomes_successful_edit(reason):
    account = _account(ok=False, reason=reason)
    result = _verify(account)
    assert result["status"] == "failed" and result["reason"] == reason
    projected = mutation_observation(
        verification=result, account=account, final={"termination": "no_exit_code"},
        dispatch_id=DISPATCH,
    )
    assert projected["ok"] is False and projected["execution_confirmed"] is False
    assert "after_context" not in projected
    assert "after_context" not in json.loads(projected["output"])


@pytest.mark.parametrize("mutation", ["wrong_digest", "missing_readback", "huge_preview", "bad_backup", "failed_execution"])
def test_postconditions_cannot_be_reported_verified_without_reliable_readback(mutation):
    account = _account()
    if mutation == "wrong_digest":
        account["verification"]["target_sha256"] = "0" * 64
    elif mutation == "missing_readback":
        account["verification"]["edit_verified"] = False
    elif mutation == "huge_preview":
        account["after_context"] = "x" * 4097
    elif mutation == "bad_backup":
        account["verification"]["backup_exists"] = False
    result = _verify(account, state="failed" if mutation == "failed_execution" else "done")
    assert result["status"] != "verified"


@pytest.mark.parametrize("reason,expected", [
    ("edit_not_unique", "edit_not_unique"),
    ("edit_conflict", "edit_conflict"),
    (None, "postconditions_match"),
])
def test_edit_handler_returns_verified_observation_instead_of_raw_finished_command(
        monkeypatch, reason, expected):
    token = driver._PC_QUERY_OWNER.set(OWNER)
    calls = []

    async def normalize(path, **kwargs):
        return path, ()

    async def signed(**kwargs):
        mode = kwargs["mode"]
        calls.append((mode, kwargs.get("payload")))
        if mode == "dispatch":
            return {"dispatch": {"dispatch_id": DISPATCH, "run_id": RUN, "kind": "command"}}
        if mode == "command_status":
            return {"dispatch": {"dispatch_id": DISPATCH, "run_id": RUN,
                                 "kind": "command", "state": "done"}}
        if mode == "result":
            account = _account(ok=reason is None, reason=reason)
            encoded = base64.b64encode(json.dumps(account).encode()).decode("ascii")
            return {"dispatch": {"dispatch_id": DISPATCH, "run_id": RUN,
                "kind": "command", "output": driver.PC_WRITE_ACCOUNT_PREFIX + encoded,
                "termination": "no_exit_code", "exit_code": None}}
        raise AssertionError(mode)

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(driver, "_pc_normalize_path", normalize)
    monkeypatch.setattr(driver, "_signed_files_call", signed)
    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    try:
        handler = driver._make_pc_file_handler(
            tool_id=driver.PC_EDIT_FILE_TOOL_ID, op="edit", service=object(),
            request_factory=lambda *args, **kwargs: None, secret="test",
        )
        result = asyncio.run(handler({"path": "notes.txt", "old_text": "changed",
                                      "new_text": "NEW", "replace_all": False}))
        assert result["action_verification"]["reason"] == expected
        assert result["ok"] is (reason is None)
        assert result["execution_confirmed"] is (reason is None)
        assert [mode for mode, _ in calls] == ["dispatch", "command_status", "result"]
    finally:
        driver._PC_QUERY_OWNER.reset(token)


def test_two_different_edits_to_the_same_path_have_distinct_receipts(monkeypatch):
    token = driver._PC_QUERY_OWNER.set(OWNER)
    dispatched = []
    async def normalize(path, **kwargs):
        return path, ()
    async def signed(**kwargs):
        mode = kwargs["mode"]
        if mode == "dispatch":
            dispatched.append(kwargs["payload"]["tool_call_ref"])
            return {"dispatch": {"dispatch_id": DISPATCH, "run_id": RUN, "kind": "command"}}
        if mode == "command_status":
            return {"dispatch": {"dispatch_id": DISPATCH, "run_id": RUN,
                                 "kind": "command", "state": "pending"}}
        raise AssertionError(mode)
    async def no_sleep(_):
        return None
    monkeypatch.setattr(driver, "_pc_normalize_path", normalize)
    monkeypatch.setattr(driver, "_signed_files_call", signed)
    monkeypatch.setattr(driver, "_pc_files_wait_seconds", lambda: 0.0)
    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    try:
        handler = driver._make_pc_file_handler(
            tool_id=driver.PC_EDIT_FILE_TOOL_ID, op="edit", service=object(),
            request_factory=lambda *args, **kwargs: None, secret="test",
        )
        for text in ("NEW", "DIFFERENT"):
            result = asyncio.run(handler({"path": "notes.txt", "old_text": "changed",
                                          "new_text": text, "replace_all": False}))
            assert result["status"] == "running"
        assert len(dispatched) == 2 and dispatched[0] != dispatched[1]
    finally:
        driver._PC_QUERY_OWNER.reset(token)


def test_canonical_single_edit_plan_is_admitted_without_widening_pc_authority():
    from app.orchestration_service import (
        _parse_agent_plan, _canonical_pc_plan, OrchestrationEngineService,
        ServiceContractError,
    )

    plan = _parse_agent_plan({"agent_id": "agent:padiem:chat-pc-query@1",
        "steps": [{"step_id": "edit_file", "tool_id": "claw.pc.edit_file",
                   "objective": "Edit one exact piece of text"}]})
    assert _canonical_pc_plan("padiem-chat", plan) is not None
    assert _canonical_pc_plan("unrelated-app", plan) is None
    # Tool selection stays limited to one exact canonical step.
    extra = _parse_agent_plan({"agent_id": "agent:padiem:chat-pc-query@1",
        "steps": [
            {"step_id": "edit_file", "tool_id": "claw.pc.edit_file",
             "objective": "Edit"},
            {"step_id": "delete_file", "tool_id": "claw.pc.delete_file",
             "objective": "Delete"},
        ]})
    assert _canonical_pc_plan("padiem-chat", extra) is None
    device = "dev_" + "a" * 32
    OrchestrationEngineService._validate_pc_plan_tool_arguments(
        plan, {"files_write": {"device_id": device}})
    with pytest.raises(ServiceContractError):
        OrchestrationEngineService._validate_pc_plan_tool_arguments(
            plan, {"files_edit": {"device_id": device}})
