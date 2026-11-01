"""#6579 3단계 — Chat 첨부 조각 업로드 레인의 저장·해석 계약.

여기서 고정하는 것은 레인의 세 가지 약속이다.

1. 완성된 조각 파일은 **파일째** 저장소로 넘어간다(같은 파일시스템이면 이동).
   1GiB 원본이 한 덩어리 bytes가 되어 메모리에 올라가지 않는다.
2. 해석은 소유자에게만 열린다 — 남의 계정·추측한 ID는 없는 것과 같다(None).
3. 바이너리 문서는 기존 파서 권위와 그 문구를 그대로 쓴다. 이 레인은 두 번째
   파서도, 두 번째 오류 문구도 만들지 않는다.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.attachments import AttachmentValidationError
from app.documents import DocumentAttachment
from app.local_r2 import ThreadedLocalDiskR2
from app.tus_chat_attachment import ACCEPTED_MEDIA, ChatAttachmentStore


def _store() -> ChatAttachmentStore:
    return ChatAttachmentStore(ThreadedLocalDiskR2(tempfile.mkdtemp(prefix="chat-attach-r2-")))


def _chunk(body: bytes) -> Path:
    path = Path(tempfile.mkdtemp(prefix="chat-attach-chunk-")) / "data.bin"
    path.write_bytes(body)
    return path


def test_accepted_media_is_the_existing_chat_document_vocabulary():
    assert {"text/plain", "text/markdown", "text/csv", "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"} <= ACCEPTED_MEDIA
    # 사진은 Chat이 base64 경로로만 다룬다 — 이 레인이 조용히 받아 주지 않는다.
    assert "image/png" not in ACCEPTED_MEDIA


@pytest.mark.asyncio
async def test_save_streams_the_file_and_the_owner_reads_it_back():
    store = _store()
    text = "사업계획 요약\n둘째 줄\n"
    chunk = _chunk(text.encode("utf-8"))
    size = chunk.stat().st_size

    saved = await store.save(user_id="user_a", name="계획.txt",
                             media_type="text/plain", source_path=chunk)

    assert saved["attachment_id"].startswith("file_")
    assert saved["size_bytes"] == size
    assert len(saved["sha256"]) == 64
    # 조각 파일은 저장소로 옮겨졌다: 원본을 복사해 남기지 않는다.
    assert not chunk.exists()

    resolved = await store.resolve("user_a", saved["attachment_id"])
    assert isinstance(resolved, DocumentAttachment)
    assert resolved.text == text
    assert resolved.byte_size == size
    assert resolved.file_id == saved["attachment_id"]
    assert resolved.sha256 == saved["sha256"]


@pytest.mark.asyncio
async def test_attachment_belongs_to_one_account_only():
    store = _store()
    saved = await store.save(user_id="user_a", name="계획.txt", media_type="text/plain",
                             source_path=_chunk(b"owner-only"))

    # 다른 계정: 존재를 부정한다(403이 아니라 "없음").
    assert await store.resolve("user_b", saved["attachment_id"]) is None
    # 추측한 ID, 형식이 틀린 ID.
    assert await store.resolve("user_a", "file_" + "0" * 32) is None
    assert await store.resolve("user_a", "../" + saved["attachment_id"]) is None
    # 정작 소유자에게는 있다.
    assert (await store.resolve("user_a", saved["attachment_id"])).text == "owner-only"


@pytest.mark.asyncio
async def test_binary_attachment_goes_through_the_existing_parser_authority():
    store = _store()
    saved = await store.save(user_id="user_a", name="보고서.pdf",
                             media_type="application/pdf",
                             source_path=_chunk(b"this is not a pdf at all"))

    with pytest.raises(AttachmentValidationError):
        await store.resolve("user_a", saved["attachment_id"])


@pytest.mark.asyncio
async def test_types_outside_the_chat_vocabulary_are_refused_before_storage():
    store = _store()
    with pytest.raises(ValueError):
        await store.save(user_id="user_a", name="사진.png", media_type="image/png",
                         source_path=_chunk(b"\x89PNG\r\n\x1a\n"))
