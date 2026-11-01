"""Web XLSX lane over the shared tus core (#6579 step 2, item 1).

Pins the three things this lane adds on top of the protocol it reuses: the 1 GiB
web-XLSX ceiling (not a new number), the hand-off into the unchanged
``put_web_xlsx`` flow, and the rule that another account's upload behaves like a
missing one.
"""
from __future__ import annotations

import base64

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from app import tus_web_xlsx_upload as lane_module
from app.workspace_storage import MAX_WEB_XLSX_BYTES, XLSX_MEDIA_TYPE

CHUNK = "application/offset+octet-stream"


class FakeStore:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.raise_value_error = False

    async def put_web_xlsx(self, **kwargs):
        self.calls.append(kwargs)
        if self.raise_value_error:
            raise ValueError("invalid or unsafe XLSX workbook")
        return {"document_id": "doc_" + "a" * 32,
                "filename": kwargs["filename"],
                "size_bytes": len(kwargs["body"]),
                "expires_at": "2026-11-02T00:00:00Z"}


def _metadata(filename="보고서.xlsx", media_type=XLSX_MEDIA_TYPE) -> str:
    return ("filename " + base64.b64encode(filename.encode()).decode()
            + ",filetype " + base64.b64encode(media_type.encode()).decode())


@pytest.fixture()
def lane(tmp_path, monkeypatch):
    monkeypatch.setenv("PADIEM_TUS_UPLOAD_DIR", str(tmp_path / "tus"))
    store = FakeStore()
    current = {"user": "owner-a", "workspace": "ws-a"}

    monkeypatch.setattr(lane_module, "auth_ready", lambda request: True)
    monkeypatch.setattr(lane_module, "current_user_id", lambda request: current["user"])

    async def workspace(request, owner):
        return current["workspace"] if current["workspace"] else None

    monkeypatch.setattr(lane_module, "_resolve_memory_workspace", workspace)

    app = Starlette(routes=[
        Route(lane_module.WEB_XLSX_TUS_COLLECTION_PATH,
              lane_module.web_xlsx_tus_collection, methods=["POST", "OPTIONS"]),
        Route(lane_module.WEB_XLSX_TUS_ITEM_PATH,
              lane_module.web_xlsx_tus_item, methods=["HEAD", "PATCH", "GET"]),
    ])
    app.state.workspace_document_store = store
    return TestClient(app), store, current


def _create(client, length, metadata=None):
    return client.post(
        lane_module.WEB_XLSX_TUS_COLLECTION_PATH,
        headers={"Tus-Resumable": "1.0.0", "Upload-Length": str(length),
                 "Upload-Metadata": metadata if metadata is not None else _metadata()},
    )


def _patch(client, upload_id, offset, body):
    return client.patch(
        lane_module.WEB_XLSX_TUS_ITEM_PATH.replace("{upload_id}", upload_id),
        headers={"Tus-Resumable": "1.0.0", "Upload-Offset": str(offset),
                 "Content-Type": CHUNK},
        content=body,
    )


def test_the_ceiling_is_the_existing_web_xlsx_constant(lane):
    client, _store, _current = lane
    options = client.options(lane_module.WEB_XLSX_TUS_COLLECTION_PATH)
    assert options.headers["Tus-Max-Size"] == str(MAX_WEB_XLSX_BYTES)
    assert MAX_WEB_XLSX_BYTES == 1024 * 1024 * 1024
    # A whole gigabyte is accepted; one byte more is refused before any body.
    assert _create(client, MAX_WEB_XLSX_BYTES).status_code == 201
    assert _create(client, MAX_WEB_XLSX_BYTES + 1).status_code == 413


def test_chunks_assemble_and_hand_off_to_the_existing_save_flow(lane):
    client, store, _current = lane
    created = _create(client, 6).json()
    upload_id = created["upload_id"]
    assert _patch(client, upload_id, 0, b"abc").status_code == 204
    assert client.head(
        lane_module.WEB_XLSX_TUS_ITEM_PATH.replace("{upload_id}", upload_id),
    ).headers["Upload-Offset"] == "3"
    assert _patch(client, upload_id, 3, b"def").status_code == 204
    call = store.calls[-1]
    assert call["body"] == b"abcdef"
    assert call["filename"] == "보고서.xlsx"
    assert call["owner_id"] == "owner-a" and call["workspace_id"] == "ws-a"
    picked = client.get(
        lane_module.WEB_XLSX_TUS_ITEM_PATH.replace("{upload_id}", upload_id))
    assert picked.status_code == 201
    assert picked.json()["file"]["size_bytes"] == 6
    assert picked.json()["p01_approved"] is False


def test_an_interrupted_upload_resumes_without_duplicating_bytes(lane):
    client, store, _current = lane
    upload_id = _create(client, 8).json()["upload_id"]
    assert _patch(client, upload_id, 0, b"1234").status_code == 204
    assert _patch(client, upload_id, 0, b"1234").status_code == 409
    assert _patch(client, upload_id, 4, b"5678").status_code == 204
    assert store.calls[-1]["body"] == b"12345678"


def test_another_account_cannot_see_or_append_to_the_upload(lane):
    client, store, current = lane
    upload_id = _create(client, 4).json()["upload_id"]
    assert _patch(client, upload_id, 0, b"ab").status_code == 204
    current["user"] = "owner-b"
    path = lane_module.WEB_XLSX_TUS_ITEM_PATH.replace("{upload_id}", upload_id)
    assert client.head(path).status_code == 404
    assert client.get(path).status_code == 404
    assert _patch(client, upload_id, 2, b"cd").status_code == 404
    assert all(call["owner_id"] == "owner-a" for call in store.calls)


def test_a_foreign_workspace_is_refused_even_for_the_same_user(lane):
    client, _store, current = lane
    upload_id = _create(client, 4).json()["upload_id"]
    current["workspace"] = "ws-other"
    assert client.head(
        lane_module.WEB_XLSX_TUS_ITEM_PATH.replace("{upload_id}", upload_id),
    ).status_code == 404


def test_a_non_workbook_is_refused_at_creation(lane):
    client, _store, _current = lane
    assert _create(client, 10, _metadata(media_type="text/plain")).status_code == 422


def test_an_invalid_workbook_is_reported_through_the_one_time_pickup(lane):
    client, store, _current = lane
    store.raise_value_error = True
    upload_id = _create(client, 3).json()["upload_id"]
    assert _patch(client, upload_id, 0, b"bad").status_code == 204
    picked = client.get(
        lane_module.WEB_XLSX_TUS_ITEM_PATH.replace("{upload_id}", upload_id))
    assert picked.status_code == 422
    assert picked.json()["error"]["code"] == "invalid_web_xlsx_file"


def test_a_missing_workspace_or_store_fails_closed(lane):
    client, _store, current = lane
    current["workspace"] = None
    assert _create(client, 10).status_code == 503
