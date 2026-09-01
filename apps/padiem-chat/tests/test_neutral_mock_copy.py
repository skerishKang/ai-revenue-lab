from __future__ import annotations

import asyncio

from app.attachments import ImageAttachment
from app.b14_client import B14Client
from app.config import Settings
from app.model_policy import DEFAULT_B14_MODEL_ID, MEDIUM_B14_MODEL_ID


MESSAGES = [{"role": "user", "content": "안녕하세요"}]
FORBIDDEN_USER_JARGON = (
    "모의",
    "모델",
    "provider",
    "route",
    "router",
    "b14",
    "low",
    "medium",
    "high",
    "unassigned",
    "poolside",
    "laguna",
)


def _assert_plain_preview_copy(answer: str) -> None:
    lowered = answer.lower()
    assert "지금은 미리보기 환경입니다." in answer
    for term in FORBIDDEN_USER_JARGON:
        assert term not in lowered


def test_mock_completed_answer_uses_plain_truthful_preview_copy():
    async def scenario():
        result = await B14Client(Settings(runtime_mode="mock")).complete(MESSAGES)
        answer = result["answer"]

        assert DEFAULT_B14_MODEL_ID == MEDIUM_B14_MODEL_ID == "poolside/laguna-s-2.1"
        assert result["request_id"] == "mock_b62"
        assert result["runtime"] == "mock"
        assert result["route"]["model"] == MEDIUM_B14_MODEL_ID
        assert result["route"]["provider"] is None
        _assert_plain_preview_copy(answer)
        assert "입력하신 질문은 ‘안녕하세요’입니다." in answer
        assert "정식 답변 기능은 준비가 끝난 뒤 이용할 수 있습니다." in answer

    asyncio.run(scenario())


def test_mock_stream_uses_same_plain_preview_framing():
    async def scenario():
        client = B14Client(Settings(runtime_mode="mock"))
        chunks = []
        done_count = 0

        async for event in client.stream_text_auto(MESSAGES):
            if event.delta_content:
                chunks.append(event.delta_content)
            if event.done:
                done_count += 1

        answer = "".join(chunks)
        _assert_plain_preview_copy(answer)
        assert "입력하신 질문은 ‘안녕하세요’입니다." in answer
        assert done_count == 1

    asyncio.run(scenario())


def test_mock_image_copy_discloses_no_analysis_without_runtime_jargon():
    async def scenario():
        attachment = ImageAttachment(
            name="preview.png",
            media_type="image/png",
            base64_data="iVBORw0KGgo=",
            byte_size=8,
        )
        result = await B14Client(Settings(runtime_mode="mock")).complete(
            MESSAGES,
            attachments=(attachment,),
        )
        answer = result["answer"]

        assert result["request_id"] == "mock_b62"
        assert result["runtime"] == "mock"
        assert result["route"]["model"] == MEDIUM_B14_MODEL_ID
        assert result["route"]["provider"] is None
        _assert_plain_preview_copy(answer)
        assert "사진 내용은 아직 분석하지 않습니다." in answer
        assert result["attachments"] == [
            {
                "type": "image",
                "name": "preview.png",
                "media_type": "image/png",
                "byte_size": 8,
            }
        ]

    asyncio.run(scenario())
