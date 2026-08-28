from __future__ import annotations

import asyncio

from app.b14_client import B14Client
from app.config import Settings
from app.model_policy import UNASSIGNED_B14_MODEL_ID


MESSAGES = [{"role": "user", "content": "안녕하세요"}]


def test_mock_completed_answer_does_not_claim_an_approved_model_route():
    async def scenario():
        result = await B14Client(Settings(runtime_mode="mock")).complete(MESSAGES)
        answer = result["answer"]
        assert result["runtime"] == "mock"
        assert result["route"]["model"] == UNASSIGNED_B14_MODEL_ID
        assert result["route"]["provider"] is None
        assert "승인된 기본 모델" not in answer
        assert "자동 추천" not in answer
        assert "provider" not in answer.lower()
        assert "모델 선택" not in answer
        assert "현재는 모의 실행 상태" in answer

    asyncio.run(scenario())
