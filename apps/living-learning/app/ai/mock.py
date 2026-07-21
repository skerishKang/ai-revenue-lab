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
        {"question": "Q1: 무엇입니까?", "correct_answer": "설명", "explanation": "왜냐하면"},
        {"question": "Q2: 왜 입니까?", "correct_answer": "10", "explanation": "그러니까"}
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

    def __init__(
        self,
        task_payloads: dict[str, dict] | None = None,
        responses: list[dict] | None = None,
        fixture_payload: dict | None = None,
        model: str = "mock-fixture",
    ) -> None:
        self.model = model
        self.task_payloads = task_payloads or {}
        self.responses = list(responses) if responses else []
        self.fixture_payload = fixture_payload
        self._call_index = 0
        self.requests: list[dict[str, Any]] = []

    def _get_default_payload(self, task_name: str) -> dict:
        if task_name in ("lesson_content", "adapted_lesson_content"):
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
        elif self.fixture_payload is not None:
            payload = self.fixture_payload
        else:
            payload = self._get_default_payload(task_name)

        # Deep copy to avoid mutating default
        import copy
        payload = copy.deepcopy(payload)

        # Apply adaptation rules if direction_choices exist
        dc = user_payload.get("direction_choices", "")
        if "slower_pace" in dc and task_name == "adapted_lesson_plan":
            if payload.get("sections"):
                payload["sections"].append({"section_id": "s2", "title": "섹션 2", "description": "short"})
        if "reduce_theory" in dc and task_name == "adapted_lesson_plan":
            if payload.get("sections"):
                payload["sections"][0]["description"] = "short"
        if "simplify_jargon" in dc and task_name == "adapted_lesson_plan":
            if payload.get("sections"):
                payload["sections"][0]["description"] = "정의"
        
        if "more_examples" in dc and task_name == "adapted_lesson_content":
            payload.setdefault("code_examples", []).append({"example_id": "ex2", "code": "y = 2\nprint(y)", "explanation": "test", "expected_output": "2"})
        if "code_first" in dc and task_name == "adapted_lesson_content":
            if payload.get("sections"):
                payload["sections"][0]["includes_code"] = True
                payload["sections"][0]["code_snippet"] = "z = 3"
        if "reduce_theory" in dc and task_name == "adapted_lesson_content":
            if payload.get("sections"):
                payload["sections"][0]["content"] = "short"
        if "slower_pace" in dc and task_name == "adapted_lesson_content":
            if payload.get("sections"):
                payload["sections"][0]["content"] = "short"
                payload["sections"].append({"section_id": "s2", "title": "섹션 2", "content": "short"})
        if "more_review" in dc and task_name == "adapted_lesson_content":
            payload.setdefault("review_questions", []).append({"question": "Q3", "correct_answer": "10", "explanation": "E"})
        if "simplify_jargon" in dc and task_name == "adapted_lesson_content":
            if payload.get("sections"):
                payload["sections"][0]["content"] = "정의: 매우 쉽다"

        validated = response_schema.model_validate(payload)
        return ProviderResult(
            provider="mock",
            model=self.model,
            payload=validated.model_dump(),
            success=True,
        )