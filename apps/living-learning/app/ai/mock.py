"""Network-free MockProvider for deterministic testing."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.domain.models import ProviderResult


_DEFAULT_LESSON_PLAN = {
    "title": "테스트 레슨",
    "sections": [
        {"section_id": "s1", "title": "섹션 1", "description": "설명 코드 예제", "emphasis": "중요"},
    ],
}

_DEFAULT_LESSON_CONTENT = {
    "content_version": "1.0",
    "title": "테스트 컨텐츠",
    "sections": [
        {"section_id": "s1", "title": "섹션 1", "content": "내용 설명", "includes_code": True, "code_snippet": "x = 1"},
    ],
    "review_questions": [
        {"question": "Q1: 무엇입니까?", "correct_answer": "이것입니다", "explanation": "왜냐하면"},
        {"question": "Q2: 왜 입니까?", "correct_answer": "저것입니다", "explanation": "그러니까"}
    ],
    "code_examples": [
        {
            "example_id": "ex1",
            "language": "python",
            "code": "x = 10\nprint(x)",
            "explanation": "변수에 값 할당",
            "expected_output": "10",
        }
    ],
}


class MockProvider:
    provider_type: str = "mock"
    model: str = "mock-fixture"

    def __init__(
        self,
        task_payloads: dict[str, dict] | None = None,
        responses: list[dict] | None = None,
        fixture_payload: dict | None = None,
    ) -> None:
        self.task_payloads = task_payloads or {}
        self.responses = list(responses) if responses else []
        self.fixture_payload = fixture_payload or _DEFAULT_LESSON_PLAN
        self._call_index = 0
        self.requests: list[dict[str, Any]] = []

    def _get_default_payload(self, task_name: str) -> dict:
        if task_name == "lesson_content":
            return _DEFAULT_LESSON_CONTENT
        return _DEFAULT_LESSON_PLAN

    def generate_structured(
        self,
        *,
        task_name: str,
        system_prompt: str,
        user_payload: dict[str, Any],
        response_schema: type[BaseModel],
        request_id: str,
    ) -> ProviderResult:
        self.requests.append(
            {
                "task_name": task_name,
                "system_prompt": system_prompt,
                "user_payload": user_payload,
                "request_id": request_id,
            }
        )

        if task_name == "error":
            return ProviderResult(
                provider="mock",
                model="mock-error",
                success=False,
                error_category="provider_error",
                error_message="simulated error",
            )

        if self.responses and self._call_index < len(self.responses):
            payload = self.responses[self._call_index]
            self._call_index += 1
        elif task_name in self.task_payloads:
            payload = self.task_payloads[task_name]
        else:
            payload = self.fixture_payload

        default_payload = self._get_default_payload(task_name)
        if not payload or payload == {}:
            payload = default_payload

        validated = response_schema.model_validate(payload)
        return ProviderResult(
            provider="mock",
            model="mock-fixture",
            payload=validated.model_dump(),
            success=True,
        )