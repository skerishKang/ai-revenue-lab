from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest

from app.attachments import MAX_IMAGE_BYTES, parse_attachments
from app.config import Settings
from app.main import create_app


JPEG = b"\xff\xd8\xff\xe0phase8"
PNG = b"\x89PNG\r\n\x1a\nphase8"
WEBP = b"RIFF\x08\x00\x00\x00WEBPphase8"


def encoded(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def attachment(media_type="image/png", data=PNG, name="photo.png"):
    return {
        "type": "image",
        "name": name,
        "media_type": media_type,
        "base64": encoded(data),
    }


def b14_success(answer="이미지를 분석한 답변입니다."):
    return {
        "choices": [{"message": {"role": "assistant", "content": answer}}],
        "business14": {
            "request_id": "b14req_image",
            "route_mode": "auto",
            "selected_model": "google/gemini-2.5-flash",
            "selected_provider": "Google",
        },
    }


@pytest.mark.asyncio
async def test_no_attachment_keeps_text_chat_contract():
    seen = {}

    async def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=b14_success("텍스트 답변"))

    app = create_app(
        Settings(runtime_mode="b14", b14_base_url="https://b14.example"),
        transport=httpx.MockTransport(handler),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": "안녕"}], "mode": "auto"},
        )
    assert response.status_code == 200
    assert seen["body"]["messages"][1] == {"role": "user", "content": "안녕"}
    assert seen["body"]["business14"]["required_capabilities"] == ["free"]
    assert "attachments" not in response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("media_type", "data", "name"),
    [
        ("image/jpeg", JPEG, "photo.jpg"),
        ("image/png", PNG, "photo.png"),
        ("image/webp", WEBP, "photo.webp"),
    ],
)
async def test_valid_image_attachment_reaches_b14_as_latest_user_multimodal(media_type, data, name):
    seen = {}

    async def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=b14_success())

    app = create_app(
        Settings(runtime_mode="b14", b14_base_url="https://b14.example"),
        transport=httpx.MockTransport(handler),
    )
    history = [
        {"role": "user", "content": "이전 질문"},
        {"role": "assistant", "content": "이전 답변"},
        {"role": "user", "content": "이 사진을 설명해줘"},
    ]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/chat",
            json={
                "messages": history,
                "mode": "auto",
                "attachments": [attachment(media_type, data, name)],
            },
        )

    assert response.status_code == 200
    outbound = seen["body"]
    assert outbound["model"] == "b14/auto"
    assert outbound["business14"]["required_capabilities"] == ["free", "image"]
    assert outbound["messages"][1] == history[0]
    assert outbound["messages"][2] == history[1]
    latest = outbound["messages"][3]
    assert latest["role"] == "user"
    assert latest["content"][0] == {"type": "text", "text": "이 사진을 설명해줘"}
    assert latest["content"][1]["type"] == "image_url"
    assert latest["content"][1]["image_url"]["url"].startswith(f"data:{media_type};base64,")

    public = response.json()
    assert public["attachments"] == [{
        "type": "image",
        "name": name,
        "media_type": media_type,
        "byte_size": len(data),
    }]
    assert encoded(data) not in json.dumps(public)


@pytest.mark.asyncio
async def test_invalid_attachment_contract_fails_before_b14():
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=b14_success())

    app = create_app(
        Settings(runtime_mode="b14", b14_base_url="https://b14.example"),
        transport=httpx.MockTransport(handler),
    )
    base = {"messages": [{"role": "user", "content": "봐줘"}], "mode": "auto"}
    bad_cases = [
        [{"type": "file", "name": "x.pdf", "media_type": "application/pdf", "base64": "eA=="}],
        [{"type": "image", "name": "x.gif", "media_type": "image/gif", "base64": "R0lGODlh"}],
        [{"type": "image", "name": "x.png", "media_type": "image/png", "base64": "not base64!!"}],
        [attachment("image/jpeg", PNG, "fake.jpg")],
        [attachment(), attachment(name="second.png")],
        [{**attachment(), "url": "https://example.com/x.png"}],
    ]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for attachments in bad_cases:
            response = await client.post("/api/chat", json={**base, "attachments": attachments})
            assert response.status_code == 422
    assert calls == 0


@pytest.mark.asyncio
async def test_image_attachment_and_web_tool_combination_is_not_implicitly_supported():
    app = create_app(Settings(runtime_mode="mock", web_provider="mock"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/chat",
            json={
                "messages": [{"role": "user", "content": "찾아봐"}],
                "mode": "auto",
                "tool": "web_search",
                "attachments": [attachment()],
            },
        )
    assert response.status_code == 422


def test_decoded_image_over_4_mib_rejected_without_exposing_payload():
    too_large = b"\x89PNG\r\n\x1a\n" + (b"x" * MAX_IMAGE_BYTES)
    raw = [attachment("image/png", too_large, "large.png")]
    with pytest.raises(ValueError, match="4 MiB") as exc:
        parse_attachments(raw)
    assert raw[0]["base64"] not in str(exc.value)


@pytest.mark.asyncio
async def test_mock_runtime_acknowledges_image_but_never_claims_image_analysis():
    app = create_app(Settings(runtime_mode="mock"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/chat",
            json={
                "messages": [{"role": "user", "content": "이 사진 뭐야?"}],
                "mode": "auto",
                "attachments": [attachment()],
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["runtime"] == "mock"
    assert "실제 모델 호출이나 이미지 분석은 하지 않았습니다" in body["answer"]
    assert encoded(PNG) not in json.dumps(body)


def test_frontend_exposes_generic_file_control_without_losing_image_support():
    root = Path(__file__).resolve().parents[1]
    html = (root / "static/index.html").read_text(encoding="utf-8")
    js = (root / "static/app.js").read_text(encoding="utf-8")
    assert 'id="attachmentFileInput"' in html
    assert "image/jpeg,image/png,image/webp" in html
    assert "text/plain,text/markdown,text/csv,application/json" in html
    assert 'id="attachmentButton"' in html
    assert "<span>파일</span>" in html
    assert "문서와 대화" in html
    assert "TXT·Markdown·CSV·JSON" in html
    assert "PDF·Office 문서는 아직 지원하지 않습니다" in html
    assert "MAX_IMAGE_BYTES = 4 * 1024 * 1024" in js
    assert "MAX_DOCUMENT_BYTES = 96 * 1024" in js
    assert "ALLOWED_IMAGE_TYPES" in js
    assert "ALLOWED_DOCUMENT_TYPES" in js
    assert "URL.createObjectURL" in js
    assert "URL.revokeObjectURL" in js
    assert "innerHTML" not in js
    assert "selectedAttachment === retryAttachment" in js
    assert "clearAttachment();" in js


def test_phase1_styles_remain_byte_equal_and_attachment_css_is_additive():
    root = Path(__file__).resolve().parents[1]
    repo = root.parents[1]
    assert (root / "static/styles.css").read_bytes() == (
        repo / "reference/business-62-padiem-chat-v1/styles.css"
    ).read_bytes()
    assert (root / "static/attachments.css").is_file()
    assert (root / "static/documents.css").is_file()
    html = (root / "static/index.html").read_text(encoding="utf-8")
    assert '<link rel="stylesheet" href="./attachments.css" />' in html
    assert '<link rel="stylesheet" href="./documents.css" />' in html