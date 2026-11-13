"""#6923: what the executor submits is what the result route accepts; a 400 names its rule.

11-04 21:44 and 11-05 15:12 KST ``POST /api/claw/connector/mesh-reads/result``
answered ``400 oracle_mesh_invalid_body`` while the executor and Chat ran
different versions, and the results were quarantined. Both sides live in this
repository, so one test builds the body with the executor's own ``submit()``
and hands the bytes to the route: on a bare app the route must get past body
validation (it answers ``503 oracle_mesh_unconfigured`` there, never 400).
When the route does refuse a body, the journal now says which rule.
"""
from __future__ import annotations

import hashlib
import json
import logging
from types import SimpleNamespace

import pytest
from starlette.applications import Starlette
from starlette.requests import Request

from app import oracle_mesh_read_return_routes as routes
from app import request_telemetry as telemetry
from app.request_telemetry import _SAFE_STAGE, _SAFE_VALUE
from kagent.local_agent_oracle_mesh_executor import (
    RESULT_PATH,
    OracleMeshDispatch,
    OracleMeshExecutionOutcome,
    OracleMeshExecutor,
)

SECRET = "contract-test-channel-secret-not-a-credential-6923"
CHAT = "https://chat.example.test"
MARKER = "private-file-content-marker-6923"


@pytest.fixture(autouse=True)
def _traced_request():
    # The route is called directly, so the request-id middleware is not in
    # the path; the stage journal only writes inside a traced request.
    token = telemetry._CURRENT_REQUEST_ID.set("req_6923" + "a" * 20)
    try:
        yield
    finally:
        telemetry._CURRENT_REQUEST_ID.reset(token)


class _Port:
    def read_bytes(self, *, node_ref, file_path, timeout_seconds):
        raise AssertionError("the contract test never reads a PC")

    def run_command(self, **kwargs):
        raise AssertionError("the contract test never runs a command")

    def run_desktop_op(self, **kwargs):
        raise AssertionError("the contract test never drives a desktop")


def _executor(sent: list) -> OracleMeshExecutor:
    def transport(path, payload):
        sent.append((path, payload))
        return 200, {"ok": True}

    return OracleMeshExecutor(
        chat_origin=CHAT, channel_secret=SECRET, read_port=_Port(),
        command_port=_Port(), desktop_port=_Port(), transport=transport,
    )


def _dispatch(kind: str = "read") -> OracleMeshDispatch:
    return OracleMeshDispatch(
        dispatch_id="dsp_" + "a" * 32, nonce="nonce_" + "b" * 32,
        node_ref="node//abcDEF$012", file_path="C:/work/notes.txt",
        command_id="cmd_6923", run_id="run_6923", kind=kind,
        command_text="Get-ChildItem" if kind == "command" else None,
    )


def _scope(body: bytes, content_type: str, app: Starlette) -> dict:
    return {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "POST", "scheme": "https",
        "path": RESULT_PATH, "raw_path": RESULT_PATH.encode(), "query_string": b"",
        "headers": [
            (b"host", b"chat.example.test"),
            (b"content-type", content_type.encode()),
            (b"content-length", str(len(body)).encode()),
        ],
        "client": ("127.0.0.1", 40000), "server": ("chat.example.test", 443),
        "app": app,
    }


def _request(body: bytes, content_type: str, app: Starlette | None = None) -> Request:
    delivered = False

    async def receive():
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(_scope(body, content_type, app or Starlette()), receive)


def _wire(payload) -> tuple[bytes, str]:
    """The exact bytes and media type the executor's HTTPS leg would send."""
    if isinstance(payload, (bytes, bytearray)):
        return bytes(payload), "application/octet-stream"
    return json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json"


async def _result_route(body: bytes, content_type: str, app: Starlette | None = None):
    response = await routes.oracle_mesh_read_result(_request(body, content_type, app))
    return response.status_code, json.loads(response.body)


def _past_validation(status: int, data: dict) -> bool:
    # A bare app has no mesh source: a body that passes validation reaches the
    # source check and is answered 503; a refused body never gets that far.
    return status == 503 and data["error"]["code"] == "oracle_mesh_unconfigured"


# --- the executor's bodies pass the route -----------------------------------

TEXT_OUTCOMES = [
    ("read", "exited", 0, b"hello\n"),
    ("read", "exited", 0, b""),                      # a 0-byte file is a result too
    ("read", "exited", 0, "한글 내용 \u2014 UTF-8".encode("utf-8")),
    ("command", "exited", 0, b"Directory: C:\\work\n"),
    ("command", "exited", 1, b"error output\n"),
    ("command", "no_exit_code", None, b"cmdlet output\n"),
    ("command", "timed_out", None, b"partial\n"),
    ("command", "no_reply", None, b""),
    ("command", "not_executed", None, b""),
    ("command", "output_too_large", None, b""),
    ("command", "cancelled", None, b""),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind, termination, exit_code, body", TEXT_OUTCOMES)
async def test_every_text_outcome_the_executor_submits_passes_the_route(kind, termination, exit_code, body):
    sent: list = []
    executor = _executor(sent)
    report = executor.submit(_dispatch(kind), OracleMeshExecutionOutcome(
        termination=termination, exit_code=exit_code, body=body))
    assert report == {"ok": True}
    assert len(sent) == 1 and sent[0][0] == RESULT_PATH
    payload = sent[0][1]
    assert set(payload) == routes._RESULT_KEYS | {"node_ref"}
    assert payload["content_sha256"] == hashlib.sha256(body).hexdigest()

    status, data = await _result_route(*_wire(payload))
    assert _past_validation(status, data), (status, data)


DESKTOP_OUTCOMES = [
    ("captured", b"\xff\xd8\xff\xe0" + b"\x00" * 200, "screen captured"),
    ("acted", b"", "clicked the button"),
    ("desktop_unavailable", b"", "no desktop session"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("termination, blob, note", DESKTOP_OUTCOMES)
async def test_every_desktop_outcome_the_executor_submits_passes_the_route(termination, blob, note):
    sent: list = []
    executor = _executor(sent)
    report = executor.submit(_dispatch("desktop"), OracleMeshExecutionOutcome(
        termination=termination, exit_code=None, body=blob, note=note))
    assert report == {"ok": True}
    payload = sent[0][1]
    if blob:
        assert isinstance(payload, bytes)                    # the #4379 binary frame
        header_size = int.from_bytes(payload[:4], "big")
        header = json.loads(payload[4:4 + header_size])
        assert routes._RESULT_KEYS < set(header) <= routes._RESULT_KEYS | routes._RESULT_OPTIONAL_KEYS
    else:
        assert set(payload) == routes._RESULT_KEYS | {"node_ref"}

    status, data = await _result_route(*_wire(payload))
    assert _past_validation(status, data), (status, data)


def test_the_executor_and_the_route_name_the_same_terminations():
    # Every termination the executor can produce is one the route lists; the
    # list is read out of the route source so a rename on either side shows.
    import inspect
    source = inspect.getsource(routes.oracle_mesh_read_result)
    for kind, termination, _code, _body in TEXT_OUTCOMES:
        assert '"%s"' % termination in source, termination
    for termination, _blob, _note in DESKTOP_OUTCOMES:
        assert '"%s"' % termination in source, termination


# --- a refused body names its rule in the journal ---------------------------


def _attach(caplog):
    logger = logging.getLogger("padiem_chat.request")
    logger.addHandler(caplog.handler)
    return logger


def _stage_lines(caplog, stage: str):
    lines = []
    for record in caplog.records:
        text = record.getMessage()
        if '"event":"ai_stage"' not in text:
            continue
        line = json.loads(text)
        if line.get("stage") == stage:
            lines.append(line)
    return lines


def _good_payload() -> dict:
    body = MARKER.encode("utf-8")
    return {
        "dispatch_id": "dsp_" + "a" * 32, "nonce": "nonce_" + "b" * 32,
        "termination": "exited", "exit_code": 0, "content_utf8": MARKER,
        "content_sha256": hashlib.sha256(body).hexdigest(), "content_bytes": len(body),
    }


def _json(payload) -> tuple[bytes, str]:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json"


REFUSALS = [
    ("termination", _json({**_good_payload(), "termination": "vanished"})),
    ("exit_code_missing", _json({**_good_payload(), "exit_code": None})),
    ("exit_code_type", _json({**_good_payload(), "exit_code": "0"})),
    ("exit_code_type", _json({**_good_payload(), "exit_code": True})),
    ("dispatch_id", _json({**_good_payload(), "dispatch_id": "has spaces " + MARKER})),
    ("nonce", _json({**_good_payload(), "nonce": ""})),
    ("keys_missing", _json({k: v for k, v in _good_payload().items() if k != "nonce"})),
    ("keys_unknown", _json({**_good_payload(), "result_version": 2})),
    ("json_decode", (b"{" + MARKER.encode(), "application/json")),
    ("body_shape", _json([MARKER])),
    ("content_type", (json.dumps(_good_payload()).encode(), "text/plain")),
    ("frame_size", (b"\x00\x00\x00\x01a", "application/octet-stream")),
    ("frame_header_size", (b"\x00\x00\x00\x40" + b"abcdefgh", "application/octet-stream")),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("reason, wire", REFUSALS)
async def test_a_refused_result_names_its_rule_and_never_the_body(caplog, reason, wire):
    logger = _attach(caplog)
    try:
        with caplog.at_level(logging.INFO, logger="padiem_chat.request"):
            status, data = await _result_route(*wire)
    finally:
        logger.removeHandler(caplog.handler)

    assert status == 400
    assert data == {"ok": False, "error": {"code": "oracle_mesh_invalid_body"}}
    stages = _stage_lines(caplog, "mesh.result.validate")
    assert [line["code"] for line in stages] == [reason], caplog.text
    assert stages[0]["outcome"] == "error"
    assert _SAFE_STAGE.fullmatch(stages[0]["stage"]) and _SAFE_VALUE.fullmatch(reason)
    assert MARKER not in caplog.text


@pytest.mark.asyncio
async def test_an_accepted_body_leaves_no_refusal_line(caplog):
    logger = _attach(caplog)
    try:
        with caplog.at_level(logging.INFO, logger="padiem_chat.request"):
            status, data = await _result_route(*_json(_good_payload()))
    finally:
        logger.removeHandler(caplog.handler)
    assert _past_validation(status, data)
    assert _stage_lines(caplog, "mesh.result.validate") == []


@pytest.mark.asyncio
async def test_the_owner_read_request_names_its_rule_too(caplog):
    app = Starlette()
    app.state.oracle_mesh_return_source = SimpleNamespace(configured=True)
    body = json.dumps({"device_id": "pc-1", "run_id": "run_1", "root_ref": "root_1",
                       "path_relative": "notes.txt", "confirmed": False}).encode()
    logger = _attach(caplog)
    try:
        with caplog.at_level(logging.INFO, logger="padiem_chat.request"):
            response = await routes.oracle_mesh_read_request(_request(body, "application/json", app))
    finally:
        logger.removeHandler(caplog.handler)
    assert response.status_code == 400
    assert [line["code"] for line in _stage_lines(caplog, "mesh.read_request.validate")] == ["confirmed"]


@pytest.mark.asyncio
async def test_the_cancel_check_names_its_rule_too(caplog):
    app = Starlette()
    app.state.oracle_mesh_return_source = SimpleNamespace(
        configured=True, check_channel_secret=lambda presented: True)
    logger = _attach(caplog)
    try:
        with caplog.at_level(logging.INFO, logger="padiem_chat.request"):
            response = await routes.oracle_mesh_read_cancel_check(
                _request(b"not json " + MARKER.encode(), "application/json", app))
    finally:
        logger.removeHandler(caplog.handler)
    assert response.status_code == 400
    assert [line["code"] for line in _stage_lines(caplog, "mesh.cancel_check.validate")] == ["json_decode"]
    assert MARKER not in caplog.text


def test_no_refusal_site_is_left_unnamed():
    import inspect
    source = inspect.getsource(routes)
    assert source.count('_error(400, "oracle_mesh_invalid_body")') == 1   # inside _invalid_body only
