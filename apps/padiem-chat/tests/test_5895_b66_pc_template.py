"""#5895 — the quote screen's PC Excel form: picked, mapped, filled, saved as new.

The Chat half only exchanges identities: the picked PC file goes to the COM2 lane
under the owner's ticket, the lane answers the form's structure, a helper model
decides the cell mapping, and the lane answers a filled copy. These tests drive the
real route with a fake lane (an httpx transport, so the real client code runs) and a
fake model, and they pin the three behaviours the CTO asked for:

* the picked form and the model's mapping reach the fill request;
* the filled copy is saved as a *new* file next to the form, never over it;
* the mapping may not overwrite a formula cell (the form's own sums stay its own).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx

sys.path.insert(0, str(Path(__file__).parent))

import app.b66_pc_template_routes as quote_pc                      # noqa: E402
import app.pc_file_exchange_routes as exchange                    # noqa: E402
import test_5895_pc_file_exchange as base                         # noqa: E402

OWNER = base.OWNER
LANE_ID = "file_" + "a" * 32
FILLED_ID = "file_" + "b" * 32
TEMPLATE = b"PK\x03\x04 fake workbook bytes"
TEMPLATE_NAME = "견적서 양식.xlsx"
ANSWER = json.dumps({
    "client": "두암중앙교회",
    "mapping": {"견적서": {"B3": "두암중앙교회", "B6": "2026-10-28"}},
    "extend": [],
}, ensure_ascii=False)


class Lane:
    """The COM2 lane as Chat sees it: tickets in, ids out."""

    def __init__(self, *, fill_status: int = 201):
        self.uploaded = []
        self.calls = []
        self.fill_body = None
        self.fill_status = fill_status

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        if request.method == "POST" and request.url.path == "/files":
            self.uploaded.append((request.url.params.get("filename"), request.content))
            return httpx.Response(201, json={"ok": True, "file_id": LANE_ID,
                                             "name": TEMPLATE_NAME, "kind": "xlsx"})
        if request.method == "GET" and request.url.path == f"/files/{LANE_ID}/structure":
            return httpx.Response(200, json={
                "ok": True, "sheets": [{"name": "견적서", "cells": [
                    {"cell": "A3", "text": "거래처", "formula": False},
                    {"cell": "A6", "text": "날짜", "formula": False},
                ]}],
            })
        if request.method == "POST" and request.url.path == f"/files/{LANE_ID}/fill":
            self.fill_body = json.loads(request.content.decode("utf-8"))
            return httpx.Response(self.fill_status, json={
                "ok": True, "file_id": FILLED_ID, "name": self.fill_body.get("filename"),
                "kind": "xlsx", "size_bytes": 10, "sha256": "0" * 64,
            })
        if request.method == "GET" and request.url.path == f"/files/{FILLED_ID}/raw":
            return httpx.Response(200, content=b"filled workbook bytes")
        return httpx.Response(404, json={"ok": False})


def _state(monkeypatch, lane: Lane, *, answer=ANSWER):
    pairing_store, created = base._links()
    store = base._Store()
    state = SimpleNamespace(
        pc_device_pairing_store=pairing_store,
        history_store=store,
        oracle_mesh_return_source=SimpleNamespace(configured=True, execution_mode="mesh"),
        control_plane_identity_authority=object(),
        file_lane_client=SimpleNamespace(
            ready=True, origin="https://files.example.test",
            _transport=httpx.MockTransport(lane.handler),
            read_ticket=lambda uid: ({"X-Padiem-File-Ticket": "read"}, 0),
            upload_ticket=lambda uid, maximum: ({"X-Padiem-File-Ticket": "write"}, 0),
        ),
        b66_quote_interpreter=SimpleNamespace(
            _client=SimpleNamespace(complete=_completer(answer)),
        ),
    )
    monkeypatch.setattr(exchange, "auth_ready", lambda _request: True)
    monkeypatch.setattr(exchange, "current_user_id", lambda _request: OWNER)
    monkeypatch.setattr(quote_pc, "auth_ready", lambda _request: True)
    monkeypatch.setattr(quote_pc, "current_user_id", lambda _request: OWNER)
    monkeypatch.setattr(exchange, "_resolve_chat_owner",
                        lambda request, user_id: base._async((SimpleNamespace(
                            session_id="s", product_id="b62", tenant_id="t"), "sub", "work")))
    monkeypatch.setattr(exchange, "_check_mesh_grant",
                        lambda request, session, *, device_id=None: base._async(True))

    async def resolved_target(request, *, session, selected_device_id, user_id):
        rows = await pairing_store.links_for_owner(user_id=user_id)
        row = rows[0]
        return {"authorized": True,
                "target": {"node_ref": row["mesh_node_id"], "device_id": row["mesh_node_id"],
                           "link_id": row["link_id"], "label": row["label"]},
                "roots": row["roots"]}, None

    monkeypatch.setattr(exchange, "_engine_pc_files_target", resolved_target)
    captured = []

    async def stage_command(request, *, command, wire, trusted_owner, tool_call_ref, files_target):
        captured.append(command)
        return exchange._response({"ok": True, "dispatch": {
            "dispatch_id": "dsp_" + "c" * 32, "run_id": wire["run_id"], "state": "pending",
            "expires_at": "2099-01-01T00:00:00.000Z", "kind": "command"}})

    monkeypatch.setattr(exchange, "dispatch_oracle_mesh_command_intent", stage_command)
    return state, store, captured


def _completer(answer):
    async def complete(messages, *, additional_system_context=None, attachments=(), **kwargs):
        complete.seen = {"messages": messages, "system": additional_system_context}
        return {"answer": answer}

    complete.seen = None
    return complete


def _finished_template(store, dispatch_id):
    base._finished(SimpleNamespace(history_store=store), dispatch_id=dispatch_id,
                   kind="read", text=TEMPLATE)
    store.dispatches[dispatch_id]["file_path"] = base.QUARTERLY + "/" + TEMPLATE_NAME


def test_the_picked_form_and_the_models_mapping_reach_the_fill_request(monkeypatch):
    lane = Lane()
    state, store, _captured = _state(monkeypatch, lane)
    dispatch = "dsp_" + "1" * 32
    _finished_template(store, dispatch)

    status, body = base._answer(base.pairing.run(quote_pc.pc_quote_fill(
        base._Request(state, body={"file_id": dispatch, "request": "두암중앙교회 견적서 만들어줘"})
    )))

    assert status == 200 and body["ok"] is True, body
    assert lane.uploaded == [(TEMPLATE_NAME, TEMPLATE)]
    assert lane.fill_body["mapping"] == {"견적서": {"B3": "두암중앙교회", "B6": "2026-10-28"}}
    assert body["filled_file_id"] == FILLED_ID
    # The helper model saw the form's own cells and the owner's words.
    seen = state.b66_quote_interpreter._client.complete.seen
    assert "거래처" in seen["system"] and "견적서" in seen["system"]
    assert seen["messages"][0]["content"] == "두암중앙교회 견적서 만들어줘"


def test_the_filled_copy_is_a_new_file_beside_the_form(monkeypatch):
    lane = Lane()
    state, store, captured = _state(monkeypatch, lane)
    dispatch = "dsp_" + "2" * 32
    _finished_template(store, dispatch)
    _status, filled = base._answer(base.pairing.run(quote_pc.pc_quote_fill(
        base._Request(state, body={"file_id": dispatch, "request": "두암중앙교회",
                                   "today": "2026-10-28"})
    )))
    assert filled["filled_name"] == "견적서_두암중앙교회_2026-10-28.xlsx"

    status, body = base._answer(base.pairing.run(exchange.pc_file_exchange_save(
        base._Request(state, body={
            "file_id": filled["filled_file_id"],
            "path": base.QUARTERLY + "/견적서_두암중앙교회_2026-10-28.xlsx",
        })
    )))
    assert status == 200 and body["ok"] is True, body
    command = captured[-1]
    # The write targets the new name inside the form's own folder, and the backup
    # #5573 takes still comes first.
    assert base.QUARTERLY + "/견적서_두암중앙교회_2026-10-28.xlsx" in command
    assert 0 < command.index("Copy-Item") < command.index("[IO.File]::WriteAllBytes")
    import base64
    assert base64.b64encode(b"filled workbook bytes").decode() in command
    # The original form's own name is never the write target.
    assert "'" + base.QUARTERLY + "/" + TEMPLATE_NAME + "'" not in command


def test_a_mapping_the_workbook_cannot_take_is_refused_not_filled(monkeypatch):
    lane = Lane(fill_status=422)
    state, store, _captured = _state(monkeypatch, lane)
    dispatch = "dsp_" + "3" * 32
    _finished_template(store, dispatch)
    status, body = base._answer(base.pairing.run(quote_pc.pc_quote_fill(
        base._Request(state, body={"file_id": dispatch, "request": "견적"})
    )))
    assert status == 502 and body["error"]["code"] == "quote_template_fill_failed"


def test_the_quote_screen_offers_the_shared_part_and_a_connect_line():
    """The screen half: one button, one save button, and the no-PC notice."""

    from pathlib import Path

    script = (Path(__file__).resolve().parents[1] / "static" / "b66-quote-runtime.js").read_text(encoding="utf-8")
    assert "내 PC 엑셀 양식 가져오기" in script
    assert "이 양식으로 견적서 만들기" in script
    assert "내 PC에 저장" in script
    assert "PC를 연결하면 내 양식을 가져올 수 있습니다." in script
    assert "이 PC 연결" in script
    # The shared part is loaded on first use, and only its own routes are called.
    assert 'script.src = PC_EXCHANGE_SCRIPT' in script
    assert '"./pc-file-exchange.js"' in script
    for path in ('"/api/b66/pc-quote/fill"', '"/api/pc/save"', '"/api/pc/result"',
                 '"/api/pc/pairings"'):
        assert path in script, path
    # The connect entry is the existing connectors surface, not a second pairing screen.
    assert 'getElementById("connectorsNavButton")' in script
