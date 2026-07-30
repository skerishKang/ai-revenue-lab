"""Deterministic network-free MockProvider for testing."""

from __future__ import annotations

from pydantic import BaseModel

from app.domain.models import ProviderResult


class MockProvider:
    """Network-free, fixture-controlled provider for deterministic testing.

    Attributes
    ----------
    attempt_limit : int
        MockProvider uses a configurable attempt_limit (default 3) to match
        the historical retry behavior of GenerationService.  Tests can
        override this by constructing a new instance.

    redacted_api_key : str
        Always returns "" since MockProvider doesn't use an external API key.

    source_allowlist_predicate : None
        MockProvider generates synthetic source_refs; validation happens in the
        pipeline after the response is returned.
    """

    DEFAULT_ATTEMPT_LIMIT = 3

    def __init__(
        self,
        task_payloads: dict[str, dict] | None = None,
        responses: list[dict] | None = None,
        fixture_payload: dict | None = None,
        attempt_limit: int | None = None,
    ) -> None:
        self.task_payloads = task_payloads or {}
        self.responses = list(responses) if responses else []
        self.fixture_payload = fixture_payload or {}
        self._call_index = 0
        self.requests: list[dict] = []
        self._attempt_limit = attempt_limit if attempt_limit is not None else self.DEFAULT_ATTEMPT_LIMIT

    @property
    def attempt_limit(self) -> int:
        return self._attempt_limit

    @property
    def redacted_api_key(self) -> str:
        return ""

    @property
    def source_allowlist_predicate(self) -> None:
        return None

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
