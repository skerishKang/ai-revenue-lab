"""#8036 — network shares are reported as candidates and approved one at a time.

The UNC spelling from #8041 is preserved. A mapped drive letter is an alias for
the approved share address, never a grant on its own. Credentials never enter
this lane: they remain in the PC's user session.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from app import mcp_gateway_execution as execution
from app.d1_sqlite import SqliteD1
from app.history import D1HistoryStore
from app.local_cpython import apply_migrations
from app.pc_device_pairing_store import (
    D1PcPairingStore,
    PcPairingError,
    pc_name_from_agent_name,
    share_candidate,
    shares_from_agent_name,
)
from padiem_ai_engine_client import EngineTransportResponse, PadiemAiEngineClient

OWNER = "usr_" + "a" * 32
NODE = "node//mesh-share-pc"
SHARE = "//fileserver/sharename"
OTHER = "//fileserver/other"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pairing_store(tmp_path):
    connection = sqlite3.connect(str(tmp_path / "pairing.sqlite3"), isolation_level=None)
    connection.row_factory = sqlite3.Row
    apply_migrations(connection)
    connection.execute(
        "INSERT INTO users (id, auth_provider, provider_subject, email, display_name, "
        "picture_url, created_at, updated_at) VALUES (?, 'google', 'sub_8036', "
        "'owner@example.test', '', '', '2026-11-19T00:00:00Z', '2026-11-19T00:00:00Z')",
        (OWNER,),
    )
    return D1PcPairingStore(SqliteD1(connection)), connection


def _claim(store, agent_name):
    issued = asyncio.run(store.issue_code(user_id=OWNER, issued_at=_now() - timedelta(minutes=1)))
    return asyncio.run(store.complete_claim_from_observation(
        agent_name=agent_name.replace("{tag}", issued["install_tag"]),
        mesh_node_id=NODE, now=_now(),
    ))


def test_a_mapped_drive_and_a_share_are_reported_as_candidates():
    assert share_candidate("Z:=" + SHARE) == {
        "path": SHARE, "mapped_drive": "Z:", "label": "sharename"}
    assert share_candidate(SHARE) == {
        "path": SHARE, "mapped_drive": None, "label": "sharename"}
    # A bare server or a folder outside the share unit is not a candidate.
    assert share_candidate("//fileserver") is None
    assert share_candidate("Z:=" + SHARE + "/../other") is None
    reported = shares_from_agent_name("pd-1234abcd [C D] {Z:=" + SHARE + ";" + OTHER + "} MACHINE")
    assert reported == [
        {"path": SHARE, "mapped_drive": "Z:", "label": "sharename"},
        {"path": OTHER, "mapped_drive": None, "label": "other"},
    ]
    assert pc_name_from_agent_name("pd-1234abcd [C D] {Z:=" + SHARE + "} MACHINE") == "MACHINE"


def _public_link(store, link_id):
    return next(row for row in asyncio.run(store.list_links(user_id=OWNER))
                if row["link_id"] == link_id)


def test_candidates_are_stored_but_never_granted_before_approval(tmp_path):
    store, db = _pairing_store(tmp_path)
    try:
        link = _claim(store, "{tag} [C D] {Z:=" + SHARE + "} MACHINE")
        candidate = next(
            row for row in _public_link(store, link["link_id"])["share_candidates"]
            if row["path"] == SHARE)
        assert candidate["mapped_drive"] == "Z:"
        live = asyncio.run(store.link_for(user_id=OWNER, mesh_node_id=NODE))
        assert SHARE not in [root["path"] for root in live["roots"]]
        # A second report of the same share adds no duplicate candidate.
        asyncio.run(store.seed_share_candidates(
            owner=OWNER, link=live,
            candidates=shares_from_agent_name("pd-1234abcd [C] {Z:=" + SHARE + "} MACHINE"),
            moment=_now().isoformat().replace("+00:00", "Z"),
        ))
        assert len([row for row in _public_link(store, link["link_id"])["share_candidates"]
                    if row["path"] == SHARE]) == 1
    finally:
        db.close()


def test_approving_one_share_grants_only_that_share_unit(tmp_path):
    store, db = _pairing_store(tmp_path)
    try:
        link = _claim(store, "{tag} [C] {Z:=" + SHARE + ";" + OTHER + "} MACHINE")
        ref = next(row["root_ref"] for row in _public_link(store, link["link_id"])["share_candidates"]
                   if row["path"] == SHARE)
        approved = asyncio.run(store.approve_share_candidate(
            user_id=OWNER, link_id=link["link_id"], root_ref=ref, now=_now()))
        assert approved["path"] == SHARE and approved["state"] == "active"
        assert approved["mapped_drive"] == "Z:"
        live = asyncio.run(store.link_for(user_id=OWNER, mesh_node_id=NODE))
        assert [root["path"] for root in live["roots"]] == ["C:", SHARE]
        # A share nobody reported and nobody approved cannot be approved by a
        # guessed reference; the other reported candidate stays a candidate
        # until an administrator picks it separately.
        with pytest.raises(PcPairingError):
            asyncio.run(store.approve_share_candidate(
                user_id=OWNER, link_id=link["link_id"],
                root_ref="pcroot_" + "0" * 16, now=_now()))
        unapproved = _public_link(store, link["link_id"])["share_candidates"]
        assert any(row["path"] == OTHER for row in unapproved)
    finally:
        db.close()


def test_mapped_letter_is_translated_to_the_share_for_both_paths():
    roots = [{"name": "sharename", "path": SHARE, "mapped_drive": "Z:"},
             {"name": "work", "path": "C:/work"}]
    relative, where = execution._pc_relative_inside_roots("Z:/sub/file.txt", roots)
    assert where == "inside" and relative == "sharename/sub/file.txt"
    # A different share is outside even when it sits on the same server.
    assert execution._pc_relative_inside_roots(OTHER + "/file.txt", roots) == (None, "outside")
    # Drive regression: a local drive keeps its old behaviour.
    assert execution._pc_relative_inside_roots("C:/work/report.txt", roots) == (
        "work/report.txt", "inside")


class _Transport:
    def __init__(self):
        self.calls = []

    async def request(self, **kwargs):
        self.calls.append(kwargs)
        return EngineTransportResponse(status=200, headers={}, body=json.dumps({
            "ok": True,
            "orchestration": {
                "events": [{"event_id": "e", "run_id": "r", "trace_id": "t",
                            "app_id": "padiem-chat", "kind": "run_completed", "sequence": 1}],
                "execution": {"answer": json.dumps({"status": "completed", "answer": "ok"})},
            },
        }).encode())


def test_connector_stages_the_share_address_for_a_mapped_drive(monkeypatch, tmp_path):
    history, db = _pairing_store(tmp_path)

    class _Bucket:
        def __init__(self):
            self.objects = {}

        def put(self, key, body, httpMetadata=None):
            self.objects[key] = bytes(body)

        def delete(self, key):
            self.objects.pop(key, None)

        def get(self, key):
            return self.objects.get(key)


    history = D1HistoryStore(SqliteD1(db), full_context_bucket=_Bucket())

    async def owner(request, uid):
        return SimpleNamespace(session_id="session_fixture"), "sub_" + "a" * 32, "ws-8048"

    async def context(request, **kwargs):
        return SimpleNamespace(selected_confirmed=True, tool_available=True, selection_offline=False,
                               selected_device_id="dev_" + "c" * 32,
                               execution_device_id="dev_" + "c" * 32)

    async def grant(request, session, **kwargs):
        return True

    async def delegation(request, uid):
        return {"version": 1, "rules": []}

    async def notice(*args, **kwargs):
        return True

    async def folders(request, **kwargs):
        return [{"name": "sharename", "path": SHARE, "mapped_drive": "Z:"}]

    monkeypatch.setattr(execution, "_resolve_chat_owner", owner)
    monkeypatch.setattr(execution, "resolve_pc_work_context", context)
    monkeypatch.setattr(execution, "_check_mesh_grant", grant)
    monkeypatch.setattr(execution, "load_pc_delegation", delegation)
    monkeypatch.setattr(execution, "_append_lane_notice", notice)
    monkeypatch.setattr(execution, "_registered_pc_folders", folders)
    transport = _Transport()
    bridge = execution.B62EngineOrchestrationBridge(
        client=PadiemAiEngineClient(transport=transport, app_id="padiem-chat",
                                    caller_id="padiem-chat", credential="fixture" * 8),
        store=object())
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        orchestration_bridge=bridge, history_store=history)))
    principal = {"owner_id": OWNER, "device_id": "dev_" + "c" * 32,
                 "token_id": "mcp_token_fixture"}
    result = asyncio.run(execution.execute_mcp_pc_tool(
        request, principal, "pc_list", {"path": "Z:/sub"}))
    assert result["status"] == "completed"
    sent = json.loads(transport.calls[0]["body"])
    assert sent["pc_gateway"]["arguments"]["path"] == "sharename/sub"
    db.close()


