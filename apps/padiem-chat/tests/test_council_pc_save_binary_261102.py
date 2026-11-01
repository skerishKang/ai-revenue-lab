"""2026-11-02 — 의원 앱 문서를 내 PC에 저장한다: pc/save의 project_file_id 소스.

The council app builds HWPX·DOCX in the browser, uploads them to the owner's
own project (the binary route now carries the result kind, doc_kind), and moves
those exact bytes to the owner's PC through /api/pc/save's project_file_id
source. This file owns what the council harness cannot reach:

- 정상 저장: the owner's own project file reaches the staged write command
  byte-for-byte, under the same #5573 backup-first contract.
- 소유자+프로젝트 범위: another owner's project file — and a guessed id — is a
  404 that stages nothing. The row is read like the /original route: this
  owner AND this project, never a bare id.
- 형식 거부: a stored row that is not a document or photo kind is not a save
  source. (크기 거부는 업로드 입구의 413으로 이미 고정돼 있다 —
  test_project_file_binary_upload.py::test_oversized_base64_rejected_413.
  pc/save는 이미 저장된 바이트만 옮기므로 자체 상한을 다시 두지 않는다.)
- doc_kind 확장: the binary upload route accepts the council app's result-kind
  header, refuses an unknown kind, and stamps the kind on the row.

The lane identity/staging is replaced by recorders exactly like
test_5895_pc_file_exchange.py — nothing here dispatches to a PC or a provider.
The account-isolation sweep registers the same surface at the HTTP layer in
test_6446_account_isolation_sweep.py.
"""
from __future__ import annotations

import base64
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import app.pc_file_exchange_routes as exchange                      # noqa: E402
import test_5573_pc_device_pairing as pairing                       # noqa: E402
import test_5895_pc_file_exchange as base                           # noqa: E402
import test_project_file_binary_upload as binary_base               # noqa: E402
from app.main import create_app                                     # noqa: E402
from app.project_file_routes import _project_original_object_key    # noqa: E402

OWNER = base.OWNER
OUTSIDER = base.OUTSIDER
PID = "proj_" + "a" * 32
FID = "file_" + "a" * 32
HWPX_MEDIA = "extracted/hwpx"
DOCX_MEDIA = binary_base.DOCX_MEDIA
DOC = b"PK\x03\x04 hwpx bytes the council app built"


class _ProjectFiles:
    """owner+project keyed rows — exactly the scope get_file answers for."""

    def __init__(self, rows):
        self.rows = rows

    async def get_file(self, user_id, project_id, file_id):
        return self.rows.get((user_id, project_id, file_id))


class _Body:
    """The R2 object body shape the route reads: an async chunk iterator."""

    def __init__(self, data: bytes):
        self._data = data

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._data:
            raise StopAsyncIteration
        chunk, self._data = self._data[:3], self._data[3:]
        return chunk


class _Originals:
    def __init__(self, objects):
        self.objects = objects

    async def get(self, key):
        return self.objects.get(key)


def _state_with_source(monkeypatch, *, rows, objects, uid=OWNER):
    state, captured, link_id, _ = base._state(monkeypatch, uid=uid)
    state.project_file_store = _ProjectFiles(rows)
    state.workspace_document_store = SimpleNamespace(r2_bucket=_Originals(objects))
    return state, captured, link_id


def _save(state, body):
    return base._answer(pairing.run(exchange.pc_file_exchange_save(
        base._Request(state, body=body)
    )))


# ── 정상 저장: 소유자 자신의 프로젝트 파일이 그대로 PC 쓰기로 간다 ─────────────


def test_the_owners_project_file_reaches_the_pc_write_byte_for_byte(monkeypatch):
    rows = {(OWNER, PID, FID): SimpleNamespace(media_type=HWPX_MEDIA)}
    objects = {_project_original_object_key(OWNER, PID, FID): SimpleNamespace(body=_Body(DOC))}
    state, captured, link_id = _state_with_source(monkeypatch, rows=rows, objects=objects)
    status, body = _save(state, {
        "path": "축사.hwpx", "project_id": PID, "project_file_id": FID,
        "link_id": link_id,
    })
    assert status == 200 and body["ok"] is True, body
    assert body["name"] == "축사.hwpx"
    # The exact stored bytes move: the staged write carries their base64.
    assert base64.b64encode(DOC).decode("ascii") in captured[0]["command"]
    # Same #5573 contract: the undoable copy happens before the write.
    assert ".padiem-backup" in captured[0]["command"]
    assert 0 < captured[0]["command"].index("Copy-Item") \
        < captured[0]["command"].index("[IO.File]::WriteAllBytes")


# ── 범위: 남의 파일·추측 id는 404이고 아무것도 준비되지 않는다 ─────────────────


def test_another_owners_project_file_is_not_a_source(monkeypatch):
    rows = {(OUTSIDER, PID, FID): SimpleNamespace(media_type=HWPX_MEDIA)}
    objects = {_project_original_object_key(OUTSIDER, PID, FID): _Body(DOC)}
    state, captured, link_id = _state_with_source(monkeypatch, rows=rows, objects=objects)
    for body in (
        # The file exists — but under another owner's project scope, which this
        # owner's read must not see.
        {"path": "축사.hwpx", "project_id": PID, "project_file_id": FID,
         "link_id": link_id},
        # A guessed id that shapes like one belongs to nobody.
        {"path": "축사.hwpx", "project_id": "proj_" + "f" * 32,
         "project_file_id": "file_" + "9" * 32, "link_id": link_id},
    ):
        status, answer = _save(state, body)
        assert status == 404, (body, status, answer)
        assert answer["error"]["code"] == "pc_project_file_not_found", (body, answer)
    assert captured == []


def test_a_row_that_is_not_a_document_or_photo_is_not_a_source(monkeypatch):
    rows = {(OWNER, PID, FID): SimpleNamespace(media_type="text/plain")}
    state, captured, link_id = _state_with_source(monkeypatch, rows=rows, objects={})
    status, answer = _save(state, {
        "path": "메모.txt", "project_id": PID, "project_file_id": FID,
        "link_id": link_id,
    })
    assert status == 404 and answer["error"]["code"] == "pc_project_file_not_found"
    assert captured == []


def test_a_missing_project_or_object_is_a_404_never_a_guess(monkeypatch):
    rows = {(OWNER, PID, FID): SimpleNamespace(media_type=HWPX_MEDIA)}
    state, captured, link_id = _state_with_source(monkeypatch, rows=rows, objects={})
    for body in (
        # No project named: the row is scoped by owner+project, so there is
        # nothing to read — not "whichever project has this id".
        {"path": "축사.hwpx", "project_file_id": FID, "link_id": link_id},
        # The row exists but its original object is gone.
        {"path": "축사.hwpx", "project_id": PID, "project_file_id": FID,
         "link_id": link_id},
        # A project id that is not even a string.
        {"path": "축사.hwpx", "project_id": 123, "project_file_id": FID,
         "link_id": link_id},
        # A file id that is not shaped like one.
        {"path": "축사.hwpx", "project_id": PID, "project_file_id": "file_lik",
         "link_id": link_id},
    ):
        status, answer = _save(state, body)
        assert status == 404, (body, status, answer)
        assert answer["error"]["code"] == "pc_project_file_not_found", (body, answer)
    assert captured == []


# ── project_file_routes 확장: 결과 종류(doc_kind)가 실린 이진 업로드 ──────────


class _DocKindFiles(binary_base.MemoryProjectFileStore):
    """The memory store plus the doc_kind column the binary route now fills."""

    async def create_file(self, user_id, project_id, name, media_type, text,
                          *, doc_kind="", **kwargs):
        rec = await super().create_file(user_id, project_id, name, media_type, text, **kwargs)
        stored = replace(rec, doc_kind=doc_kind)
        # The record is frozen, so the row the store keeps must be swapped for
        # the stamped one — otherwise the store would remember a kindless row
        # while the response claimed the kind.
        self.files[(user_id, project_id)][-1] = stored
        return stored


async def _council_app(owner_id: str):
    store = _DocKindFiles()
    history = binary_base.MemoryProjectStore()
    owner = await history.add_user(owner_id)
    project = await history.create_project(owner.id, "문서", "")
    app = create_app(binary_base.settings(), history_store=history, project_file_store=store)
    return app, store, owner, project


def _binary_post(project_id: str, *, name: str, media_type: str, body: bytes, doc_kind: str):
    headers = {
        "Content-Type": "application/octet-stream",
        "X-Padiem-Filename": quote(name, safe=""),
        "X-Padiem-Media-Type": media_type,
    }
    if doc_kind:
        headers["X-Padiem-Doc-Kind"] = doc_kind
    return {"url": f"/api/projects/{project_id}/files", "content": body, "headers": headers}


@pytest.mark.asyncio
async def test_the_council_upload_names_its_result_kind():
    app, store, owner, project = await _council_app("owner-doc-kind")
    client = await binary_base.client_with_session(app, binary_base.user_profile(owner.id))
    try:
        call = _binary_post(project.id, name="축사.docx", media_type=DOCX_MEDIA,
                            body=base64.b64decode(binary_base._make_docx_base64()),
                            doc_kind="speech")
        response = await client.post(**call)
        assert response.status_code == 201, response.text
        assert response.json()["file"]["doc_kind"] == "speech"
        rows = store.files[(owner.id, project.id)]
        assert [row.doc_kind for row in rows] == ["speech"]
        # 결과 종류가 없던 기존 업로더는 오늘과 같다(빈 헤더는 언제나 옳다).
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_an_unknown_result_kind_is_refused_at_the_door():
    app, store, owner, project = await _council_app("owner-doc-kind-bad")
    client = await binary_base.client_with_session(app, binary_base.user_profile(owner.id))
    try:
        call = _binary_post(project.id, name="축사.docx", media_type=DOCX_MEDIA,
                            body=base64.b64decode(binary_base._make_docx_base64()),
                            doc_kind="not-a-kind")
        response = await client.post(**call)
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "invalid_document"
        assert store.files.get((owner.id, project.id), []) == []
    finally:
        await client.aclose()
