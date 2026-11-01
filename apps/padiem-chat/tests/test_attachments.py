from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest

from app.attachments import MAX_IMAGE_BYTES, parse_attachments
from app.config import Settings
from app.main import create_app
from app.model_policy import DEFAULT_B14_MODEL_ID, EXECUTABLE_B14_MODEL_IDS
from padiem_ai_core.dispatch_preinstruction import render_product_identity_instruction
from padiem_control_plane.product_tier_routes import (
    PRODUCT_TIER_ROUTES,
    ProductRouteStatus,
)


JPEG = b"\xff\xd8\xff\xe0phase8"
PNG = b"\x89PNG\r\n\x1a\nphase8"
WEBP = b"RIFF\x08\x00\x00\x00WEBPphase8"


def encoded(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def test_native_image_bytes_remain_raw_until_provider_data_url():
    from app.chat_routes import _decode_completed_binary_attachment

    metadata = {"attachments": [{"type": "image", "name": "photo.png", "media_type": "image/png"}]}
    header = json.dumps(metadata).encode("utf-8")
    frame = len(header).to_bytes(4, "big") + header + PNG
    parsed = _decode_completed_binary_attachment(frame)
    assert "raw_bytes" in parsed["attachments"][0]
    assert "base64" not in parsed["attachments"][0]
    image = parse_attachments(parsed["attachments"])[0]
    assert image.binary_data == PNG
    assert image.data_url.endswith(encoded(PNG))


def attachment(media_type="image/png", data=PNG, name="photo.png"):
    return {
        "type": "image",
        "name": name,
        "media_type": media_type,
        "base64": encoded(data),
    }


def b14_success(answer="Agnes 텍스트 답변입니다."):
    return {
        "choices": [{"message": {"role": "assistant", "content": answer}}],
        "business14": {
            "request_id": "b14req_text",
            "route_mode": "manual",
            "selected_model": DEFAULT_B14_MODEL_ID,
            "selected_provider": "Agnes AI",
        },
    }


@pytest.mark.asyncio
async def test_no_attachment_keeps_text_chat_contract_on_explicit_agnes():
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
            json={"messages": [{"role": "user", "content": "안녕"}]},
        )
    if DEFAULT_B14_MODEL_ID in EXECUTABLE_B14_MODEL_IDS:
        assert response.status_code == 200
        assert seen["body"]["model"] == DEFAULT_B14_MODEL_ID
        system_messages = [item for item in seen["body"]["messages"] if item["role"] == "system"]
        assert len(system_messages) == 1
        # #5347: the Chat identity instruction names the request's
        # server-authorized tier. The route bound the default "free" tier for
        # this request, so the neutral brand sentence is not the whole
        # instruction any more and the grade must reach the dispatch.
        assert render_product_identity_instruction("chat", "free") in system_messages[0]["content"]
        assert "PADIEM Chat의 PADIEM Free 모드" in system_messages[0]["content"]
        assert seen["body"]["messages"][-1] == {"role": "user", "content": "안녕"}
        assert "max_tokens" not in seen["body"]
        assert seen["body"]["business14"]["required_capabilities"] == ["chat"]
        # B5: the retired fallback knob no longer travels on the wire.
        assert "allow_external_fallback" not in seen["body"]["business14"]
        assert "max_attempts" not in seen["body"]["business14"]
        assert "attachments" not in response.json()
    else:
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "tier_unavailable"
        assert seen == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("media_type", "data", "name"),
    [
        ("image/jpeg", JPEG, "photo.jpg"),
        ("image/png", PNG, "photo.png"),
        ("image/webp", WEBP, "photo.webp"),
    ],
)
async def test_valid_live_image_attachment_fails_closed_without_primary_model(
    media_type, data, name
):
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
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
                "attachments": [attachment(media_type, data, name)],
            },
        )

    declared = frozenset(
        route.model_id
        for tier in PRODUCT_TIER_ROUTES
        for route in tier.routes
        if route.status is ProductRouteStatus.EXECUTABLE
    )
    assert EXECUTABLE_B14_MODEL_IDS == declared
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "image_model_unavailable"
    assert calls == 0


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
    base = {"messages": [{"role": "user", "content": "봐줘"}]}
    bad_cases = [
        [{"type": "file", "name": "x.pdf", "media_type": "application/pdf", "base64": "eA=="}],
        [{"type": "image", "name": "x.gif", "media_type": "image/gif", "base64": "R0lGODlh"}],
        [{"type": "image", "name": "x.png", "media_type": "image/png", "base64": "not base64!!"}],
        [attachment("image/jpeg", PNG, "fake.jpg")],
        # #261102: several items are now allowed, so the case pins the
        # multi-item property it always meant: one invalid item among several
        # still fails the whole message before any model call.
        [attachment(), {"type": "image", "name": "second.png", "media_type": "image/png"}],
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
                "tool": "web_search",
                "attachments": [attachment()],
            },
        )
    assert response.status_code == 422


def test_decoded_image_over_the_old_total_is_accepted():
    # #4379: a composer image carries no PADIEM byte total. The media type
    # and the magic bytes are still verified, and the platform request limit
    # is the only ceiling, so a payload over the former 1 GiB maximum parses.
    over_the_old_bound = b"\x89PNG\r\n\x1a\n" + (b"x" * (MAX_IMAGE_BYTES + 1))
    image = parse_attachments(
        [{"type": "image", "name": "large.png", "media_type": "image/png", "raw_bytes": over_the_old_bound}]
    )[0]
    assert image.byte_size == len(over_the_old_bound)


@pytest.mark.asyncio
async def test_mock_runtime_acknowledges_image_but_never_claims_image_analysis():
    app = create_app(Settings(runtime_mode="mock"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/chat",
            json={
                "messages": [{"role": "user", "content": "이 사진 뭐야?"}],
                "attachments": [attachment()],
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["runtime"] == "mock"
    assert "route" not in body
    assert "request_id" not in body
    assert DEFAULT_B14_MODEL_ID not in json.dumps(body)
    assert body["answer"].startswith("지금은 미리보기 환경입니다.")
    assert "사진 내용은 아직 분석하지 않습니다." in body["answer"]
    assert "모의" not in body["answer"]
    assert "모델" not in body["answer"]
    assert encoded(PNG) not in json.dumps(body)


def test_frontend_exposes_generic_file_control_without_losing_image_support():
    root = Path(__file__).resolve().parents[1]
    html = (root / "static/index.html").read_text(encoding="utf-8")
    js = (root / "static/app.js").read_text(encoding="utf-8")
    capabilities = (root / "static/attachment-capabilities.js").read_text(encoding="utf-8")
    assert 'id="attachmentFileInput"' in html
    assert 'script src="./attachment-capabilities.js"' in html
    for media_type in ["image/jpeg", "image/png", "image/webp", "text/plain", "text/markdown", "text/csv", "application/json"]:
        assert media_type in capabilities
    for label in ["JPEG", "PNG", "WebP", "TXT", "Markdown", "CSV", "JSON", "PDF", "DOCX", "PPTX", "XLSX"]:
        assert f'label: "{label}"' in capabilities
    assert 'id="attachmentButton"' in html
    assert "<span>파일</span>" in html
    assert "파일 업로드" in html
    assert "지원 형식" in html
    assert "MAX_IMAGE_BYTES" not in js
    assert "MAX_DOCUMENT_BYTES" not in js
    assert "MAX_DOCUMENT_CHARS" not in js
    assert "ALLOWED_IMAGE_TYPES" in js
    assert "ALLOWED_DOCUMENT_TYPES" in js
    assert "URL.createObjectURL" in js
    assert "URL.revokeObjectURL" in js
    assert "innerHTML" not in js
    # #261102: the selection is now a chip list; the pin keeps its intent —
    # the retry clears the composer only for its own unchanged snapshot.
    assert "selectedAttachments === retryAttachment" in js
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



def test_hwp_upload_guidance_is_shown_by_real_document_selection():
    import subprocess
    source = (Path(__file__).resolve().parents[1] / "static" / "app.js").read_text(encoding="utf-8")
    start = source.index("  async function readDocumentFile(file) {")
    end = source.index("  async function selectImage(file)", start)
    fn = source[start:end]
    script = """
const assert = require('node:assert/strict');
const extensionOf = name => String(name || '').toLowerCase().slice(String(name || '').lastIndexOf('.'));
const documentMediaType = () => null;
const uiT = key => key === 'hwp-save-hwpx' ? '한글에서 HWPX로 저장해 올리면 읽을 수 있어요.' : key;
const attachmentCopy = () => ({unsupportedFormat:'unsupported'});
""" + fn + """
(async () => {
  for (const name of ['old.hwp', 'OLD.HWP']) {
    await assert.rejects(readDocumentFile({name}), e =>
      e.message === '한글에서 HWPX로 저장해 올리면 읽을 수 있어요.' && e.uiMessageSafe === true);
  }
  await assert.rejects(readDocumentFile({name:'other.xyz'}), /unsupported/);
})().catch(e => { console.error(e); process.exit(1); });
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr


def test_visible_open_source_notice_links_renderer_source_and_agpl():
    root = Path(__file__).resolve().parents[1]
    index = (root / "static" / "index.html").read_text(encoding="utf-8")
    page = (root / "static" / "third-party-licenses.html").read_text(encoding="utf-8")
    notice = (root.parent / "b66-pdf-renderer" / "THIRD_PARTY_LICENSES.md").read_text(encoding="utf-8")
    assert 'href="./third-party-licenses.html"' in index
    for token in ("PyMuPDF", "AGPL-3.0", "https://github.com/pymupdf/PyMuPDF",
                  "https://github.com/skerishKang/ai-revenue-lab/tree/main/apps/b66-pdf-renderer"):
        assert token in page
    assert "/third-party-licenses.html" in notice



def test_picker_accepts_legacy_hwp_only_to_offer_hwpx_guidance():
    import subprocess
    static = Path(__file__).resolve().parents[1] / "static"
    script = "global.window=globalThis;\n" + (static / "attachment-capabilities.js").read_text(encoding="utf-8") + """
const assert = require('node:assert/strict');
assert(PadiemAttachmentCapabilities.accept.split(',').includes('.hwp'));
assert(!PadiemAttachmentCapabilities.copy('ko').documentFormats.includes('HWP'));
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
