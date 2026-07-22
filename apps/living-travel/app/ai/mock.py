"""Deterministic network-free MockProvider for testing."""

from __future__ import annotations

from pydantic import BaseModel

from app.domain.models import ProviderResult


class MockProvider:
    """Network-free, fixture-controlled provider for deterministic testing."""

    def __init__(
        self,
        task_payloads: dict[str, dict] | None = None,
        responses: list[dict] | None = None,
        fixture_payload: dict | None = None,
    ) -> None:
        self.task_payloads = task_payloads or {}
        self.responses = list(responses) if responses else []
        self.fixture_payload = fixture_payload or {}
        self._call_index = 0
        self.requests: list[dict] = []

    def generate_structured(
        self,
        *,
        task_name: str,
        system_prompt: str,
        user_payload: dict,
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

        validated = response_schema.model_validate(payload)
        return ProviderResult(
            provider="mock",
            model="mock-fixture",
            payload=validated.model_dump(),
            success=True,
        )
