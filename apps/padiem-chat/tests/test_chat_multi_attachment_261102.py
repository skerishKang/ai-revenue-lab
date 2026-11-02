"""#261102 — Chat 메시지 다중 첨부(서버 계약·모델 입력·합계 예산·화면 계약).

작업 계약(아스트라9 한도 점검 2차 "상향 제안 1"):
- env PADIEM_CHAT_MAX_ATTACHMENTS_PER_MESSAGE(기본 5, 상한 10). 1이면 기존 동작.
- 여러 [{type:"file", file_id}]가 각각 기존 추출 경로로 처리되고, 모델 입력은
  파일별로 구분된다(파일명 + 본문/요약).
- 합계는 기존 6MB 모델 요청 봉투 안에 있어야 하고, 넘으면 큰 파일은 기존
  저장-요약 형태(파일명 + 앞부분 발췌 + file_id 보관 참조)로 요약된다.
- 다른 계정의 file_id가 섞이면 메시지 전체가 기존 단일 첨부 거부 코드로 거부된다.
- 화면은 다중 선택·드래그, 칩 목록 + 개별 제거, 칩별 거부 표시, tus 업로드 그대로.
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.attachments import (
    AttachmentValidationError,
    MAX_ATTACHMENTS_PER_MESSAGE_CEILING,
    MAX_ATTACHMENTS_PER_MESSAGE_ENV,
    max_attachments_per_message,
    parse_attachments,
    parse_attachments_async,
)
from app.config import Settings
from app.documents import (
    MAX_ATTACHMENTS_CONTEXT_TOTAL_BYTES,
    DocumentAttachment,
    build_document_context,
    build_documents_context,
)
from app.history import UserProfile
from app.main import create_app
from app.model_policy import DEFAULT_B14_MODEL_ID
from app.claw_attachment_context import parse_claw_turn_attachments_async

ROOT = Path(__file__).resolve().parents[1]
USER = "usr_" + "a" * 32


def make_file_id(seed: str) -> str:
    body = (seed * 16)[:32].encode().hex()[:32]
    return "file_" + body


def document(name: str, text: str, media_type: str = "text/plain", file_id: str | None = None) -> DocumentAttachment:
    return DocumentAttachment(name=name, media_type=media_type, text=text, byte_size=len(text.encode()), file_id=file_id)


class LaneStub:
    """The existing lane contract, canned: owner-scoped resolve, per-id refusal."""

    def __init__(self, documents: dict[str, DocumentAttachment], *, foreign: set[str] | None = None):
        self.documents = documents
        self.foreign = foreign or set()
        self.resolved: list[str] = []
        self.ready = True

    async def resolve(self, user_id: str, item: dict) -> DocumentAttachment:
        assert user_id == USER
        file_id = item["file_id"]
        if file_id in self.foreign:
            # The lane's own not-found/foreign answer, reused verbatim.
            raise AttachmentValidationError("첨부 파일을 찾을 수 없거나 읽을 권한이 없습니다.")
        self.resolved.append(file_id)
        doc = self.documents[file_id]
        # The real lane answers with the id it just resolved stamped on.
        return replace(doc, file_id=file_id) if doc.file_id is None else doc


class Adapter:
    """B14 capture adapter: records each model-call request body."""

    def __init__(self):
        self.calls: list[dict] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(json.loads(request.content))
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": "답변"}}],
            "business14": {
                "request_id": "b14req_multi",
                "route_mode": "manual",
                "selected_model": DEFAULT_B14_MODEL_ID,
                "selected_provider": "Agnes AI",
            },
        })

    def system_context(self, call: int = 0) -> str:
        """The one composed system message the model actually reads."""
        return "\n".join(
            str(item.get("content", ""))
            for item in self.calls[call].get("messages", [])
            if item.get("role") == "system"
        )


class History:
    """The one store call the authenticated attachment path needs."""

    async def get_user(self, user):
        return UserProfile(user, "offline@example.test", "Offline", "") if user == USER else None

    async def append_exchange(self, *args, **kwargs):
        return "chat_" + "c" * 32


def b14_settings() -> Settings:
    # Offline fixture constants only — no real credential exists in this suite.
    return Settings.from_values(
        runtime_mode="b14",
        b14_base_url="https://b14.example",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="offline.apps.googleusercontent.com",
        google_client_secret="offline-multi-attach-google-fixture-0001",
        session_secret="offline-multi-attach-session-fixture-0001",
    )


def session_cookies(settings: Settings) -> dict[str, str]:
    return {SESSION_COOKIE: create_session_token(settings, USER)}


def b14_app(adapter: Adapter, lane) -> create_app:  # noqa: N803 (test fixture helper)
    return create_app(
        b14_settings(),
        transport=httpx.MockTransport(adapter),
        history_store=History(),
        file_lane_client=lane,
    )


def files_payload(count: int, prefix: str = "doc") -> list[dict[str, str]]:
    return [{"type": "file", "file_id": make_file_id(f"{prefix}{index}")} for index in range(count)]


# ---------------------------------------------------------------- 개수 한도


def test_default_limit_is_five_and_ceiling_is_ten():
    assert max_attachments_per_message() == 5
    assert MAX_ATTACHMENTS_PER_MESSAGE_CEILING == 10


@pytest.mark.parametrize("value,expected", [
    ("3", 3), ("10", 10), ("1", 1),
    ("0", 1), ("-4", 1), ("99", 10),
    ("abc", 5), ("", 5),
])
def test_env_values_are_clamped_or_defaulted(monkeypatch, value, expected):
    monkeypatch.setenv(MAX_ATTACHMENTS_PER_MESSAGE_ENV, value)
    assert max_attachments_per_message() == expected


def test_env_absent_keeps_default(monkeypatch):
    monkeypatch.delenv(MAX_ATTACHMENTS_PER_MESSAGE_ENV, raising=False)
    assert max_attachments_per_message() == 5


def test_one_three_and_five_attachments_parse(monkeypatch):
    monkeypatch.delenv(MAX_ATTACHMENTS_PER_MESSAGE_ENV, raising=False)
    items = [
        {"type": "document", "name": f"n{index}.txt", "media_type": "text/plain", "text": f"내용 {index}"}
        for index in range(5)
    ]
    for count in (1, 3, 5):
        parsed = parse_attachments(items[:count])
        assert len(parsed) == count


def test_six_attachments_are_refused_by_default(monkeypatch):
    monkeypatch.delenv(MAX_ATTACHMENTS_PER_MESSAGE_ENV, raising=False)
    items = [
        {"type": "document", "name": f"n{index}.txt", "media_type": "text/plain", "text": f"내용 {index}"}
        for index in range(6)
    ]
    with pytest.raises(AttachmentValidationError, match="최대 5개"):
        parse_attachments(items)


def test_env_one_keeps_the_exact_single_attachment_contract(monkeypatch):
    monkeypatch.setenv(MAX_ATTACHMENTS_PER_MESSAGE_ENV, "1")
    single = [{"type": "document", "name": "a.txt", "media_type": "text/plain", "text": "x"}]
    assert len(parse_attachments(single)) == 1
    pair = single + [{"type": "document", "name": "b.txt", "media_type": "text/plain", "text": "y"}]
    with pytest.raises(AttachmentValidationError, match="한 번에 하나"):
        parse_attachments(pair)


def test_env_ten_accepts_ten_and_ignores_higher_values(monkeypatch):
    monkeypatch.setenv(MAX_ATTACHMENTS_PER_MESSAGE_ENV, "10")
    items = [
        {"type": "document", "name": f"n{index}.txt", "media_type": "text/plain", "text": f"내용 {index}"}
        for index in range(10)
    ]
    assert len(parse_attachments(items)) == 10
    monkeypatch.setenv(MAX_ATTACHMENTS_PER_MESSAGE_ENV, "25")
    with pytest.raises(AttachmentValidationError, match="최대 10개"):
        parse_attachments(items + [items[0]])


@pytest.mark.asyncio
async def test_multi_file_items_each_resolve_through_the_existing_path(monkeypatch):
    monkeypatch.delenv(MAX_ATTACHMENTS_PER_MESSAGE_ENV, raising=False)
    docs = {make_file_id("doc0"): document("a.txt", "A"), make_file_id("doc1"): document("b.md", "B", "text/markdown")}
    lane = LaneStub(docs)
    calls: list[dict] = []

    async def resolver(item):
        calls.append(item)
        return await lane.resolve(USER, item)

    parsed = await parse_attachments_async(
        [{"type": "file", "file_id": make_file_id("doc1")}, {"type": "file", "file_id": make_file_id("doc0")}],
        file_resolver=resolver,
    )
    assert [item.name for item in parsed] == ["b.md", "a.txt"]
    assert calls == [{"type": "file", "file_id": make_file_id("doc1")}, {"type": "file", "file_id": make_file_id("doc0")}]


# ---------------------------------------------------------------- 계정 격리


@pytest.mark.asyncio
async def test_foreign_file_id_refuses_the_whole_message(monkeypatch):
    adapter = Adapter()
    valid = make_file_id("doc0")
    lane = LaneStub({valid: document("mine.txt", "내 파일")}, foreign={make_file_id("other")})
    app = b14_app(adapter, lane)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
        cookies=session_cookies(b14_settings()),
    ) as client:
        response = await client.post(
            "/api/chat",
            headers={"Origin": "https://chat.example.test"},
            json={
                "messages": [{"role": "user", "content": "읽어줘"}],
                "attachments": [{"type": "file", "file_id": valid}, {"type": "file", "file_id": make_file_id("other")}],
            },
        )
    assert response.status_code == 422
    assert "찾을 수 없거나 읽을 권한이 없습니다" in response.json()["error"]["message"]
    assert adapter.calls == []  # no model call, no partial send
    # The owned file went through the one existing path before the foreign
    # refusal stopped the whole message.
    assert lane.resolved == [valid]


# ---------------------------------------------------------------- 모델 입력


def test_single_document_context_stays_byte_identical():
    doc = document("report.txt", "본문 " * 30)
    assert build_documents_context([doc]) == build_document_context(doc)


def test_three_documents_are_named_and_separated_per_file():
    docs = [document("a.txt", "알파"), document("b.txt", "베타"), document("c.txt", "감마")]
    context = build_documents_context(docs)
    assert "[첨부 파일 1/3]" in context and "[첨부 파일 2/3]" in context and "[첨부 파일 3/3]" in context
    assert "파일 이름: a.txt" in context and "알파" in context
    assert "파일 이름: b.txt" in context and "베타" in context
    assert "파일 이름: c.txt" in context and "감마" in context
    assert "파일별로 구분" in context
    assert "신뢰되지 않은 참고 데이터" in context
    # The separator header is the first thing the model reads.
    assert context.startswith("첨부 문서 데이터 규칙:")


def test_over_budget_largest_file_is_summarized_with_its_stored_reference():
    small = document("small.txt", "작은 본문", file_id=make_file_id("small"))
    large = document("large.txt", "큰 " * 4_000, file_id=make_file_id("large"))
    context = build_documents_context([small, large], max_total_bytes=8_000)
    assert "[첨부 파일 1/2]" in context and "[첨부 파일 2/2]" in context
    # The large file is the summarized one: identity + summary marker + stored id.
    assert "파일 이름: large.txt" in context
    assert "문서 요약" in context
    assert f"file_id: {make_file_id('large')}" in context
    # Its full body is gone; only the documented bounded head excerpt remains,
    # and the smaller file keeps its full text.
    assert "큰 " * 4_000 not in context
    assert "문서 내용(앞부분)" in context
    assert "작은 본문" in context
    assert len(context.encode("utf-8")) <= 8_000 + 64


def test_over_budget_summaries_stay_bounded_for_many_files():
    # The real contract is the transport envelope: five large files together
    # exceed it, so the LARGEST full bodies come back as stored summaries —
    # only as many as the bound needs — and the total stays inside the same
    # bound the production path uses (no explicit override).
    docs = [document(f"big{index}.txt", "내용 " * 300_000, file_id=make_file_id(f"big{index}")) for index in range(5)]
    context = build_documents_context(docs)
    assert len(context.encode("utf-8")) <= MAX_ATTACHMENTS_CONTEXT_TOTAL_BYTES
    summaries = context.count("문서 요약")
    assert 1 <= summaries < 5
    for index in range(5):
        assert f"파일 이름: big{index}.txt" in context
    # Each summary block carries exactly one stored-file reference.
    stored = sum(1 for index in range(5) if f"file_id: {make_file_id(f'big{index}')}" in context)
    assert stored == summaries


def test_budget_derives_from_the_existing_transport_envelope():
    from app.local_engine_transport import MAX_ENGINE_MODEL_REQUEST_BYTES

    # The existing 6MB model-request envelope stays untouched; the attachment
    # budget is the Chat-side conversation bound inside it.
    assert MAX_ENGINE_MODEL_REQUEST_BYTES == 6_000_000
    assert MAX_ATTACHMENTS_CONTEXT_TOTAL_BYTES <= MAX_ENGINE_MODEL_REQUEST_BYTES


def test_inline_document_summary_says_nothing_about_a_stored_file_id():
    # An inline (non-stored) oversized document is summarized next to a stored
    # one; its summary block carries no stored-file reference of any kind.
    inline = document("large.txt", "내용 " * 4_000, file_id=None)
    stored = document("small.txt", "작은 본문", file_id=make_file_id("small"))
    context = build_documents_context([inline, stored], max_total_bytes=8_000)
    assert "문서 요약" in context
    assert "file_id" not in context


# ---------------------------------------------------------------- /api/chat 전체 경로


@pytest.mark.asyncio
async def test_chat_answers_with_three_file_attachments_in_one_named_context(monkeypatch):
    monkeypatch.delenv(MAX_ATTACHMENTS_PER_MESSAGE_ENV, raising=False)
    adapter = Adapter()
    ids = [make_file_id(f"doc{index}") for index in range(3)]
    lane = LaneStub({
        ids[0]: document("report.txt", "보고서 본문"),
        ids[1]: document("notes.md", "회의 메모", "text/markdown"),
        ids[2]: document("data.csv", "열,값\n1,2", "text/csv"),
    })
    app = b14_app(adapter, lane)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
        cookies=session_cookies(b14_settings()),
    ) as client:
        response = await client.post(
            "/api/chat",
            headers={"Origin": "https://chat.example.test"},
            json={
                "messages": [{"role": "user", "content": "세 파일을 요약해줘"}],
                "attachments": [{"type": "file", "file_id": file_id} for file_id in ids],
            },
        )
    assert response.status_code == 200, response.text
    assert len(adapter.calls) == 1
    context = adapter.system_context()
    for name in ("report.txt", "notes.md", "data.csv"):
        assert name in context
    assert "[첨부 파일 1/3]" in context and "[첨부 파일 3/3]" in context
    assert "보고서 본문" in context and "회의 메모" in context
    assert lane.resolved == ids  # every file went through the one existing path
    public = response.json()["attachments"]
    assert [item["name"] for item in public] == ["report.txt", "notes.md", "data.csv"]
    assert all(item["file_id"] for item in public)


@pytest.mark.asyncio
async def test_chat_refuses_over_limit_attachments_before_any_model_call(monkeypatch):
    adapter = Adapter()
    lane = LaneStub({})
    app = b14_app(adapter, lane)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test") as client:
        response = await client.post(
            "/api/chat",
            json={
                "messages": [{"role": "user", "content": "읽어줘"}],
                "attachments": files_payload(6, "doc"),
            },
        )
    assert response.status_code == 422
    assert "최대 5개" in response.json()["error"]["message"]
    assert adapter.calls == []
    assert lane.resolved == []


@pytest.mark.asyncio
async def test_chat_env_one_restores_the_single_attachment_refusal(monkeypatch):
    monkeypatch.setenv(MAX_ATTACHMENTS_PER_MESSAGE_ENV, "1")
    adapter = Adapter()
    app = b14_app(adapter, LaneStub({}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test") as client:
        response = await client.post(
            "/api/chat",
            json={
                "messages": [{"role": "user", "content": "읽어줘"}],
                "attachments": files_payload(2, "doc"),
            },
        )
    assert response.status_code == 422
    assert "한 번에 하나" in response.json()["error"]["message"]


# ---------------------------------------------------------------- Claw 경계


@pytest.mark.asyncio
async def test_claw_turn_carries_every_document_file_by_file(monkeypatch):
    monkeypatch.delenv(MAX_ATTACHMENTS_PER_MESSAGE_ENV, raising=False)
    ids = [make_file_id(f"doc{index}") for index in range(3)]
    lane = LaneStub({
        ids[0]: document("one.txt", "첫째"),
        ids[1]: document("two.txt", "둘째"),
        ids[2]: document("three.txt", "셋째"),
    })
    async def resolver(item):
        return await lane.resolve(USER, item)

    context, images = await parse_claw_turn_attachments_async(
        [{"type": "file", "file_id": file_id} for file_id in ids],
        file_resolver=resolver,
    )
    assert images == ()
    for name in ("one.txt", "two.txt", "three.txt"):
        assert name in context
    assert "[첨부 파일 1/3]" in context and "[첨부 파일 3/3]" in context


# ---------------------------------------------------------------- 화면 계약


def test_frontend_selects_and_drops_multiple_files_with_per_chip_removal():
    html = (ROOT / "static/index.html").read_text(encoding="utf-8")
    app_js = (ROOT / "static/app.js").read_text(encoding="utf-8")
    css = (ROOT / "static/attachments.css").read_text(encoding="utf-8")
    # 여러 개 선택 + 드래그
    assert 'type="file" multiple' in html
    assert 'id="attachmentChipList"' in html
    assert 'composerForm.addEventListener("drop"' in app_js
    assert 'composerForm.addEventListener("dragover"' in app_js
    # 칩 목록 + 개별 제거
    assert "function addAttachmentFiles(" in app_js
    assert "function removeAttachmentItem(" in app_js
    assert "function renderAttachmentChips(" in app_js
    assert 'data-locale-aria-label", "attachment-remove"' in app_js
    assert ".attachment-chip" in css and ".attachment-chip-invalid" in css
    # 파일별 거부는 그 칩에만: 오류 칩은 페이로드에서 제외된다
    assert "uiT(\"attachment-raw-single\")" in app_js
    assert "uiT(\"attachment-count-limit\"" in app_js
    assert ".filter((item) => item && !item.invalid)" in app_js
    # 프레임 표시 DOM 제거 + 구현 고정 회귀 방지
    assert 'id="attachmentThumb"' not in html
    assert 'id="removeAttachment"' not in html
    assert "innerHTML" not in app_js


def test_frontend_locale_keys_exist_for_both_languages():
    locale_js = (ROOT / "static/locale.js").read_text(encoding="utf-8")
    for token in (
        "attachment-count-limit",
        "attachment-raw-single",
        "메시지 하나에는 파일을 최대 {count}개",
        "사진·원본 문서는 한 번에 하나만",
    ):
        assert token in locale_js


def test_file_lane_upload_contract_is_untouched_for_every_file():
    lane_js = (ROOT / "static/file-lane.js").read_text(encoding="utf-8")
    # tus(#6584) 경로 그대로: 조각 업로드는 공용 tus 모듈이 담당한다.
    assert "TUS_ENDPOINT = \"/api/chat/attachments/tus\"" in lane_js
    assert "window.PadiemTusUpload.upload" in lane_js
    assert "RESUMABLE" in lane_js
    # 역량 응답의 개수 한도를 미리 반영한다(서버가 최종 판정).
    assert "setMaxPerMessage?.(data?.max_per_message)" in lane_js
    app_js = (ROOT / "static/app.js").read_text(encoding="utf-8")
    # 전송 시 칩마다 기존 업로드 경로를 그대로 호출한다(동일 abort signal).
    assert "window.PadiemFileLane.upload(current.file, controller.signal," in app_js
    caps_js = (ROOT / "static/attachment-capabilities.js").read_text(encoding="utf-8")
    assert "setMaxPerMessage" in caps_js
