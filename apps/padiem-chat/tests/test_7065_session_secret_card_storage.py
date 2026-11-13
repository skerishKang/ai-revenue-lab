"""Secret confirmation cards keep only one-shot references in real history."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
from types import SimpleNamespace

import pytest

from app import chat_pc_session as lane
from app.history import PRODUCT_SCOPE_CHAT
from test_7065_chat_pc_session_integration import _queue_module
from test_7603_confirmation_card_expiry import _fixture, UID, WORKSPACE


def _assert_no_value(value, surfaces):
    raw = value.encode()
    forbidden = (value, base64.b64encode(raw).decode(), hashlib.sha256(raw).hexdigest(),
                 hashlib.sha256(raw).hexdigest()[:8], json.dumps(value, ensure_ascii=True)[1:-1])
    for surface in surfaces:
        rendered = surface.decode("utf-8", errors="replace") if isinstance(surface, bytes) else str(surface)
        assert all(fragment not in rendered for fragment in forbidden)
        assert all(line not in rendered for line in value.splitlines() if len(line) > 16)


@pytest.mark.parametrize("value", [
    "fixture-secret-long-" + "q7" * 115,
    "첫째비밀줄-" + "가나다" * 250 + "\n둘째비밀줄-" + "라마바" * 250,
], ids=["long-line", "unicode-multiline"])
def test_real_history_secret_card_persists_only_reference_and_lengths(tmp_path, monkeypatch, caplog, value):
    caplog.set_level(logging.DEBUG)
    memory = _queue_module("desktop_text_store").DesktopTextStore()

    async def capability(*args, **kwargs):
        return None

    async def queue_call(method, **fields):
        return await getattr(memory, method)(**fields)

    monkeypatch.setattr(lane, "_secret_capability", capability)

    async def scenario():
        store, db = _fixture(tmp_path)
        try:
            request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
                history_store=store, queue_client=SimpleNamespace(call=queue_call))))
            owner = (UID, SimpleNamespace(session_id="fixture"), WORKSPACE)
            operation = {"op": "input", "job_id": "dsp_" + "a" * 32,
                         "text": value, "secret": True, "enter": False, "offset": 17}
            assert lane._needs_confirmation(operation, "PC 세션 비밀 입력")
            response = await lane._stage(request, owner=owner, operation=operation,
                conversation_id=None, device="device-1", user_text="비밀 입력: " + value)
            reply = json.loads(response.body)
            assert reply["decision_status"] == "pc_session_confirm"
            cid = reply["conversation_id"]
            row = (await store.list_recent_claw_runs(UID, workspace_id=WORKSPACE))[0]
            private = await store.read_pc_session_confirmation_turn(user_id=UID, run_id=row["run_id"])
            encoded = private.rsplit(lane._CARD_MARKER, 1)[1][:-3]
            payload = json.loads(base64.b64decode(encoded, validate=True))
            assert payload["operation"] == {k: v for k, v in operation.items() if k != "text"}
            assert set(payload["secret_input"]) == {"ref", "chars", "bytes"}
            metadata = payload["secret_input"]
            assert metadata["chars"] == len(value) and metadata["bytes"] == len(value.encode())
            pending = await lane._pending(request, owner=owner, conversation_id=cid)
            assert pending[1] == payload["operation"] and pending[4] == metadata
            assert await store.read_pc_session_confirmation_turn(user_id="foreign", run_id=row["run_id"]) is None

            public = await store.get_conversation(UID, cid, product_scope=PRODUCT_SCOPE_CHAT)
            model = await store.get_conversation_model_context(UID, cid, product_scope=PRODUCT_SCOPE_CHAT)
            search = await store.search_conversations(UID, "비밀", product_scope=PRODUCT_SCOPE_CHAT)
            visible = repr(public) + repr(model) + repr(search)
            assert "pc-session-confirm:" not in visible and metadata["ref"] not in visible
            surfaces = [response.body, repr(reply), private, repr(payload), repr(pending),
                        visible, repr(row), "\n".join(db.iterdump()),
                        (tmp_path / "chat.sqlite3").read_bytes(), repr(memory), caplog.text]
            surfaces.extend(store.full_context_bucket.objects.values())
            _assert_no_value(value, surfaces)

            assert await store.consume_pc_command_confirmation(UID, row["run_id"], action=row["action"])
            assert not await store.consume_pc_command_confirmation(UID, row["run_id"], action=row["action"])
            assert await store.read_pc_session_confirmation_turn(user_id=UID, run_id=row["run_id"]) is None
            assert await memory.take_desktop_text(ref=metadata["ref"]) == value
            assert await memory.take_desktop_text(ref=metadata["ref"]) is None
            assert not memory._entries
            _assert_no_value(value, ["\n".join(db.iterdump()), caplog.text])
        finally:
            db.close()

    asyncio.run(scenario())


def test_secret_deposit_exception_does_not_enter_real_history_or_logs(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    value = "fixture-rejected-secret-" + "x9" * 110

    async def capability(*args, **kwargs):
        return None

    async def fail_deposit(*args, **kwargs):
        raise RuntimeError(value + base64.b64encode(value.encode()).decode()
                           + hashlib.sha256(value.encode()).hexdigest())

    monkeypatch.setattr(lane, "_secret_capability", capability)

    async def scenario():
        store, db = _fixture(tmp_path)
        try:
            request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
                history_store=store, queue_client=SimpleNamespace(call=fail_deposit))))
            response = await lane._stage(request,
                owner=(UID, SimpleNamespace(session_id="fixture"), WORKSPACE),
                operation={"op": "input", "job_id": "dsp_" + "a" * 32, "text": value, "secret": True},
                conversation_id=None, device="device-1", user_text=value)
            assert response.status_code == 503
            assert json.loads(response.body)["error"]["code"] == "pc_session_unavailable"
            assert await store.list_recent_claw_runs(UID) == []
            assert not store.full_context_bucket.objects
            _assert_no_value(value, [response.body, repr(response), "\n".join(db.iterdump()),
                                   (tmp_path / "chat.sqlite3").read_bytes(), caplog.text])
        finally:
            db.close()

    asyncio.run(scenario())
