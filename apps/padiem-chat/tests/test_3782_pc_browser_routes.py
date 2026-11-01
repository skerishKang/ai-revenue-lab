"""Real ASGI/proof/owner/dispatch path; identity and PC receipts are fakes."""
from __future__ import annotations
import asyncio
import base64
import hashlib
import hmac
import json
import re
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent))
import test_5015_pc_read_dispatch as fixtures
from app import claw_pc_browser_routes as browser
from app import oracle_mesh_read_return_routes as mesh
from app.auth import SESSION_COOKIE, create_session_token
from app.claw_pc_browser_command import PC_BROWSER_OPS, browser_arguments, browser_scope_claim
from app.config import Settings


class History(fixtures._History):
    async def create_oracle_mesh_dispatch(self, **fields):
        row = await super().create_oracle_mesh_dispatch(**fields)
        self.rows.pop(row["dispatch_id"])
        row["dispatch_id"] = "dsp_" + format(self._seq, "032x")
        self.rows[row["dispatch_id"]] = row
        return dict(row)

    async def store_pc_output(self, **_):
        raise AssertionError("typed browser JSON must not be text-previewed")


@pytest.fixture
def lane(monkeypatch):
    state = fixtures._state(monkeypatch, History())
    state.settings = Settings.from_values(runtime_mode="mock", auth_mode="password",
                                         public_base_url="https://chat.example.com",
                                         session_secret="synthetic-browser-test-session-secret")
    app = Starlette(routes=[
        Route("/internal/chat/engine-pc-browser", browser.oracle_mesh_engine_chat_browser_call, methods=["POST"]),
        Route("/internal/claw/engine-pc-browser", browser.oracle_mesh_engine_claw_browser_call, methods=["POST"]),
        Route(browser.BROWSER_CAPTURE_PATH, browser.browser_capture),
    ])
    for key, value in vars(state).items():
        setattr(app.state, key, value)
    with TestClient(app) as client:
        yield client, state


def claim(product="chat", **changes):
    return {"version": 1, "requested": "browser", "admitted": "browser", "source": "declared",
            "ops": list(PC_BROWSER_OPS), "app_id": "padiem-chat" if product == "chat" else "b54-padiem-claw",
            **changes}


def dispatch(op="browser_open", **changes):
    return {"subject_id": fixtures.SUBJECT, "run_id": fixtures.RUN, "device_id": fixtures.DEVICE,
            "mode": "dispatch", "op": op, "arguments": {"url": "https://example.com"} if op == "browser_open" else {},
            "page_url": None if op == "browser_open" else "https://example.com/",
            "tool_call_ref": "pc_browser_" + "a" * 64, **changes}


def signed(client, payload, *, product="chat", scope="default", headers=None):
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    stamp = str(int(time.time()))
    proof = hmac.new(fixtures.SECRET.encode(), stamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    values = {"Content-Type": "application/json", "X-Claw-Engine-Time": stamp, "X-Claw-Engine-Proof": proof}
    if scope is not None:
        encoded = json.dumps(claim(product) if scope == "default" else scope, sort_keys=True, separators=(",", ":"))
        values["X-Claw-PC-Scope"] = encoded
        values["X-Claw-PC-Scope-Proof"] = hmac.new(fixtures.SECRET.encode(),
            stamp.encode() + b"." + raw + b"." + encoded.encode(), hashlib.sha256).hexdigest()
    values.update(headers or {})
    return client.post(f"/internal/{product}/engine-pc-browser", content=raw, headers=values)


def finish(state, dispatched, result):
    dispatch_id = dispatched.json()["dispatch"]["dispatch_id"]
    original = json.dumps({"ok": "true", "result": result}, ensure_ascii=False).encode()
    state.history_store.originals[dispatch_id] = original
    state.history_store.rows[dispatch_id].update(state="done", termination="exited", exit_code=0,
        result_sha256=hashlib.sha256(original).hexdigest(), result_bytes=len(original))
    return {"subject_id": fixtures.SUBJECT, "run_id": fixtures.RUN,
            "mode": "result", "dispatch_id": dispatch_id}


@pytest.mark.parametrize("product", ["chat", "claw"])
def test_signed_open_status_read_and_result_roundtrip(lane, product):
    client, state = lane
    opened = signed(client, dispatch(), product=product)
    assert opened.status_code == 200, opened.text
    row = next(iter(state.history_store.rows.values()))
    assert row["device_id"] == fixtures.DEVICE
    assert row["tool_request_ref"].startswith("pc_browser:browser_open:")
    encoded = re.search(r"FromBase64String\('([^']+)'\)", row["command_text"]).group(1)
    assert json.loads(base64.b64decode(encoded))["arguments"] == {"url": "https://example.com/"}
    query = {"subject_id": fixtures.SUBJECT, "run_id": fixtures.RUN, "mode": "command_status",
             "dispatch_id": row["dispatch_id"]}
    assert signed(client, query, product=product).json()["dispatch"]["state"] == "pending"
    query = finish(state, opened, {"state": "opened", "url": "https://example.com/", "title": "Example Domain"})
    output = signed(client, query, product=product)
    assert output.status_code == 200, output.text
    assert json.loads(output.json()["dispatch"]["output"])["result"]["title"] == "Example Domain"
    read = signed(client, dispatch("browser_read", tool_call_ref="pc_browser_" + "b" * 64), product=product)
    assert read.status_code == 200 and len(state.history_store.rows) == 2


def test_context_is_device_only_and_does_not_resolve_file_roots(lane, monkeypatch):
    client, _ = lane
    async def forbidden(*_, **__):
        raise AssertionError("file resolver must not run")
    monkeypatch.setattr(mesh, "_engine_pc_files_target", forbidden)
    observed = signed(client, {"subject_id": fixtures.SUBJECT, "run_id": fixtures.RUN,
                              "device_id": fixtures.DEVICE, "mode": "context"})
    assert observed.status_code == 200
    assert observed.json()["device"]["device_id"] == fixtures.DEVICE
    assert "roots" not in observed.json()
    assert signed(client, dispatch()).status_code == 200


def test_composed_mesh_device_uses_shared_identity_grammar(lane):
    client, state = lane
    device = "node/" + "domain" * 8 + "/" + "n" * 100
    mapping = fixtures._mapping()
    mapping[0].update(device_id=device, node_ref=device)
    source = mesh.build_oracle_mesh_return_source(mapping, fixtures.CHANNEL_SECRET, mesh.EXECUTION_MODE_MESH)
    assert source is not None
    client.app.state.oracle_mesh_return_source = source
    response = signed(client, dispatch(device_id=device))
    assert response.status_code == 200, response.text
    assert response.json()["dispatch"]["device_id"] == device


@pytest.mark.parametrize("scope", [None, claim(requested="files", admitted="files", ops=["read"]),
    claim(ops=["browser_open", "read"]), claim(ops=[{}]), claim(app_id="b54-padiem-claw")])
def test_missing_wrong_product_or_mixed_scope_never_dispatches(lane, scope):
    client, state = lane
    response = signed(client, dispatch(), scope=scope)
    assert response.status_code in (401, 403, 422)
    assert not state.history_store.rows


@pytest.mark.parametrize("headers", [{"X-Claw-Engine-Proof": "0" * 64}, {"X-Claw-PC-Scope-Proof": "0" * 64}])
def test_body_and_scope_proofs_are_both_required(lane, headers):
    client, state = lane
    assert signed(client, dispatch(), headers=headers).status_code == 401
    assert not state.history_store.rows


@pytest.mark.parametrize("changes", [{"device_id": "other-device"}, {"subject_id": "sub_other"},
    {"run_id": "run_other"}, {"op": "read"}, {"arguments": {"url": "http://127.0.0.1"}},
    {"arguments": {"url": "https://example.com", "cookie": "never-dispatch"}}])
def test_foreign_targets_and_closed_argument_shape_refused(lane, changes):
    client, state = lane
    assert signed(client, dispatch(**changes)).status_code in (401, 403, 404, 422)
    assert not state.history_store.rows


def test_scope_is_frozen_and_other_lane_results_unreadable(lane):
    client, state = lane
    opened = signed(client, dispatch())
    query = finish(state, opened, {"state": "opened", "title": "Example Domain"})
    assert signed(client, query, scope=claim(ops=["browser_open"])).status_code == 403
    state.history_store.rows[query["dispatch_id"]]["tool_request_ref"] = "file_call"
    assert signed(client, query).status_code == 404


def test_large_korean_receipt_keeps_json_and_existing_pc_handle(lane):
    client, state = lane
    opened = signed(client, dispatch("browser_read"))
    result = {"state": "read", "url": "https://example.com/", "title": "예제",
              "text": "긴 페이지 " * 2000, "output_handle": "a" * 64, "truncated": True}
    output = signed(client, finish(state, opened, result))
    assert output.status_code == 200, output.text
    assert json.loads(output.json()["dispatch"]["output"])["result"] == result


def test_confirmation_is_private_signed_metadata(lane):
    client, state = lane
    action = {"action": "click", "name": "게시"}
    receipt = {"action": "click", "target": "게시", "url": "https://example.com/"}
    response = signed(client, dispatch("browser_act", arguments=action, confirmation=receipt))
    assert response.status_code == 200
    command = next(iter(state.history_store.rows.values()))["command_text"]
    encoded = re.search(r"FromBase64String\('([^']+)'\)", command).group(1)
    assert base64.b64decode(encoded).isascii()  # Windows PowerShell 5 pipes ASCII by default.
    envelope = json.loads(base64.b64decode(encoded))
    assert envelope["confirmation"] == receipt and "confirmation" not in envelope["arguments"]
    assert signed(client, dispatch("browser_act", arguments={**action, "confirmation": receipt})).status_code == 422


def test_type_confirmation_binds_exact_value(lane):
    client, state = lane
    arguments = {"action": "type", "name": "메시지", "value": "검토한 문구"}
    receipt = {"action": "type", "target": "메시지", "url": "https://example.com/", "value": "검토한 문구"}
    assert signed(client, dispatch("browser_act", arguments=arguments,
                                  confirmation={**receipt, "value": "다른 문구"})).status_code == 422
    assert signed(client, dispatch("browser_act", arguments=arguments,
                                  confirmation={key: value for key, value in receipt.items() if key != "value"})).status_code == 422
    assert not state.history_store.rows
    response = signed(client, dispatch("browser_act", arguments=arguments, confirmation=receipt))
    assert response.status_code == 200, response.text


def test_screenshot_projection_owner_fetch_and_mcp_device_pin(lane):
    client, state = lane
    image = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZlJkAAAAASUVORK5CYII=")
    digest = hashlib.sha256(image).hexdigest()
    opened = signed(client, dispatch("browser_screenshot"))
    query = finish(state, opened, {"state": "captured", "path": "C:/private/generated.png", "capture": {
        "mime_type": "image/png", "data": base64.b64encode(image).decode(), "sha256": digest, "bytes": len(image)}})
    projected = signed(client, query)
    assert projected.status_code == 200, projected.text
    result = json.loads(projected.json()["dispatch"]["output"])["result"]
    assert "data" not in result["capture"] and "path" not in result
    url = result["capture"]["url"]
    assert client.get(url).status_code == 401
    client.cookies.set(SESSION_COOKIE, create_session_token(state.settings, fixtures.OWNER))
    shown = client.get(url)
    assert shown.status_code == 200 and shown.content == image
    assert shown.headers["content-type"] == "image/png"
    assert shown.headers["x-padiem-browser-capture-sha256"] == digest
    client.cookies.set(SESSION_COOKIE, create_session_token(state.settings, "usr_other"))
    assert client.get(url).status_code == 404
    with pytest.raises(ValueError):
        asyncio.run(browser.read_browser_capture(state.history_store, user_id=fixtures.OWNER,
            dispatch_id=query["dispatch_id"], device_id="other-device"))
    state.history_store.originals[query["dispatch_id"]] += b"tamper"
    assert signed(client, query).status_code == 503


def test_malformed_builder_inputs_are_bounded_refusals():
    assert browser_scope_claim({"version": 1, "requested": "browser", "admitted": "browser",
                                "source": "declared", "ops": [{}]}) is False
    with pytest.raises(ValueError):
        browser_arguments([], {})
    assert browser_arguments("browser_act", {"action": "click", "text": "Next", "role": None}) == {
        "action": "click", "text": "Next"}


def test_real_history_pins_browser_scope():
    import test_5015_dispatch_tool_call_scope as sql
    from app.history import D1HistoryStore, is_multi_command_action
    db = sql._database(with_forward=True)
    store = D1HistoryStore(sql._DB(db))
    asyncio.run(store.pin_pc_run_scope(user_id=sql.USER, run_id=sql.RUN, claim=claim()))
    assert asyncio.run(store.get_pc_run_scope(user_id=sql.USER, run_id=sql.RUN)) == claim()
    assert is_multi_command_action("pc_browser_query")
    reference = "pc_browser:browser_open:pc_browser_" + "1" * 64
    row = asyncio.run(store.create_oracle_mesh_dispatch(**sql._tool_call_arguments(reference)))
    owned = asyncio.run(store.get_oracle_mesh_dispatch_for_owner(user_id=sql.USER, dispatch_id=row["dispatch_id"]))
    assert owned["tool_request_ref"] == reference and owned["device_id"] == "device-1"
    assert asyncio.run(store.get_oracle_mesh_dispatch_for_owner(user_id=sql.OTHER_USER, dispatch_id=row["dispatch_id"])) is None
    db.close()


def test_app_factory_mounts_browser_with_existing_owner_mesh_composition(lane, monkeypatch):
    from app.app_factory import create_app
    from app import connector_owner_runtime_mount
    _, state = lane
    # Owner port composition is covered by its own contract; exercise the real
    # application middleware and route mounting with already-composed ports.
    monkeypatch.setattr(connector_owner_runtime_mount, "reviewed_owner_enrollment_routes", lambda _: ())
    app = create_app(settings=state.settings, history_store=state.history_store,
                     control_plane_identity_authority=state.control_plane_identity_authority,
                     oracle_mesh_return_source=state.oracle_mesh_return_source,
                     connector_owner_enrollment=SimpleNamespace(identity=state.control_plane_identity_authority,
                                                                host=None, csrf=None),
                     claw_engine_desktop_secret=fixtures.SECRET)
    with TestClient(app) as client:
        response = signed(client, dispatch())
        assert response.status_code == 200, response.text
        assert client.get("/api/claw/connector/browser-captures/dsp_" + "1" * 32).status_code == 401
