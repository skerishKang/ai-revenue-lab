"""#7447/#7473: only a projected image read reports note-based content fields.

The Chat gateway projects one image envelope into a short note plus one
``_pc_image`` block. When it does, ``content_bytes``/``content_sha256`` must
describe the body the Engine actually receives (the note), because the Engine
validates both against the returned text. Every other lane keeps the stored
original's values: the large stored-output reference pins ``content_bytes`` to
the reference size (#7473 review) and the plain text read never rewrites.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json

from app import oracle_mesh_read_return_routes as routes
from test_5015_pc_read_dispatch import (
    _History, _SignedRequest, _state,
    OWNER, SUBJECT, RUN, DEVICE, READ_CALL,
)
from test_pc_remote_limits_callbacks import FILES_SCOPE, OutputHistory


def call(state, mode, **values):
    # The result leg is addressed by dispatch id only; a device hint is a
    # malformed body there (exact key set).
    payload = {"subject_id": SUBJECT, "run_id": RUN, "mode": mode, **values}
    if mode == "job_start":
        payload["device_id"] = DEVICE
    request = _SignedRequest(state, payload, scope=FILES_SCOPE)
    response = asyncio.run(routes.oracle_mesh_engine_chat_files_call(request))
    return response.status_code, json.loads(response.body)


def finish(history, job_id, text):
    row = history.rows[job_id]
    row.update(state="done", termination="exited", exit_code=0,
               result_sha256=hashlib.sha256(text.encode()).hexdigest())
    history.originals[job_id] = text.encode()


# A valid 1×1 PNG, same fixture style as test_3782_pc_browser_routes.py.
# No Pillow dependency: the projection's PIL step is optional and its
# fallback note is what the content fields must describe either way.
_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZlJkAAAAASUVORK5CYII=")


def _png_envelope():
    encoded = base64.b64encode(_PNG_1X1).decode("ascii")
    return "PADIEM_IMAGE_CONTENT:image/png:" + encoded


def test_projected_image_read_reports_note_digest_and_length(monkeypatch):
    """The projected note is the body, so its digest/length must be reported."""
    history = _History()
    state = _state(monkeypatch, history)
    _, body = call(state, "job_start",
                   operation={"op": "read", "path": "shot.png"}, tool_call_ref=READ_CALL)
    job_id = body["result"]["job_id"]
    envelope = _png_envelope()
    finish(history, job_id, envelope)

    status, body = call(state, "result", dispatch_id=job_id)
    assert status == 200, body
    result = body["dispatch"]
    assert result["_pc_image"]["type"] == "image"
    note = result["output"]
    assert note != envelope and "PADIEM_IMAGE_CONTENT:" not in note
    assert result["content_sha256"] == hashlib.sha256(note.encode("utf-8")).hexdigest()
    assert result["content_bytes"] == len(note.encode("utf-8"))
    # Guard against a trivial pass: the stored envelope's values differ.
    assert result["content_sha256"] != hashlib.sha256(envelope.encode("utf-8")).hexdigest()
    assert result["content_bytes"] != len(envelope.encode("utf-8"))


def test_large_stored_read_keeps_original_digest_and_bytes(monkeypatch):
    """The stored-output reference lane keeps the stored original's values."""
    history = OutputHistory()
    state = _state(monkeypatch, history)
    _, body = call(state, "job_start",
                   operation={"op": "read", "path": "notes.txt"}, tool_call_ref=READ_CALL)
    job_id = body["result"]["job_id"]
    finish(history, job_id, "x" * 15000)

    status, body = call(state, "result", dispatch_id=job_id)
    assert status == 200, body
    result = body["dispatch"]
    assert result["output_ref"]["size"] == 15000
    assert len(result["output"]) < 4096
    assert result["content_sha256"] == hashlib.sha256(b"x" * 15000).hexdigest()
    assert result["content_bytes"] == 15000


def test_small_text_read_keeps_original_digest_and_bytes(monkeypatch):
    """A plain text read never rewrites the stored original's values."""
    history = _History()
    state = _state(monkeypatch, history)
    _, body = call(state, "job_start",
                   operation={"op": "read", "path": "notes.txt"}, tool_call_ref=READ_CALL)
    job_id = body["result"]["job_id"]
    text = "hello\n" * 10
    finish(history, job_id, text)

    status, body = call(state, "result", dispatch_id=job_id)
    assert status == 200, body
    result = body["dispatch"]
    assert "output_ref" not in result and "_pc_image" not in result
    assert result["output"] == text
    assert result["content_sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert result["content_bytes"] == len(text.encode("utf-8"))


def test_job_output_reread_carries_the_projected_image_block(monkeypatch):
    """A job_output re-read answers with the same image block the direct
    result carried (#7447/#7078 follow-up): the caller that resumes a long
    pc_read by job_id receives the picture, not only the note."""
    history = OutputHistory()
    state = _state(monkeypatch, history)
    _, body = call(state, "job_start",
                   operation={"op": "read", "path": "shot.png"}, tool_call_ref=READ_CALL)
    job_id = body["result"]["job_id"]
    envelope = _png_envelope()
    finish(history, job_id, envelope)

    status, body = call(state, "job_output", job_id=job_id, offset=0,
                        length=4096, device_id=DEVICE)
    assert status == 200, body
    result = body["result"]
    assert result["_pc_image"]["type"] == "image"
    assert result["_pc_image"]["mimeType"] == "image/png"
    assert result["_pc_image"]["data"]
    assert "PADIEM_IMAGE_CONTENT:" not in json.dumps(result)
