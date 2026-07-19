import time
from typing import Any

from pydantic import BaseModel

from app.domain.enums import CostClass, ProviderErrorCategory
from app.domain.models import ProviderResult


class MockProvider:
    def __init__(
        self,
        model: str = "mock-personal-edition-v1",
        fixture_payload: dict[str, Any] | None = None,
    ):
        self._model = model
        self._fixture_payload = fixture_payload
        self._requests: list[dict[str, Any]] = []

    @property
    def model(self) -> str:
        return self._model

    @property
    def requests(self) -> list[dict[str, Any]]:
        return list(self._requests)

    def generate_structured(
        self,
        *,
        task_name: str,
        system_prompt: str,
        user_payload: dict,
        response_schema: type[BaseModel],
        request_id: str,
    ) -> ProviderResult:
        start = time.monotonic()
        self._requests.append(
            {
                "task_name": task_name,
                "request_id": request_id,
            }
        )

        if task_name == "error":
            elapsed = time.monotonic() - start
            return ProviderResult(
                provider="mock",
                advertised_model=self._model,
                cost_class=CostClass.FREE,
                latency_seconds=elapsed,
                retry_count=0,
                request_id=request_id,
                error_category=ProviderErrorCategory.PROVIDER_ERROR,
                error_message="simulated provider error",
                success=False,
            )

        if task_name == "invalid_payload":
            elapsed = time.monotonic() - start
            try:
                response_schema.model_validate({"bad": "data"})
                error_msg = "payload did not match expected schema"
            except Exception as exc:
                error_msg = str(exc)
            return ProviderResult(
                provider="mock",
                advertised_model=self._model,
                cost_class=CostClass.FREE,
                latency_seconds=elapsed,
                retry_count=0,
                request_id=request_id,
                error_category=ProviderErrorCategory.SCHEMA_MISMATCH,
                error_message=error_msg,
                success=False,
            )

        fixture = self._fixture_payload if self._fixture_payload is not None else {}
        try:
            validated = response_schema.model_validate(fixture)
            payload = validated.model_dump()
        except Exception as exc:
            elapsed = time.monotonic() - start
            return ProviderResult(
                provider="mock",
                advertised_model=self._model,
                cost_class=CostClass.FREE,
                latency_seconds=elapsed,
                retry_count=0,
                request_id=request_id,
                error_category=ProviderErrorCategory.SCHEMA_MISMATCH,
                error_message=str(exc),
                success=False,
            )

        elapsed = time.monotonic() - start
        return ProviderResult(
            provider="mock",
            advertised_model=self._model,
            cost_class=CostClass.FREE,
            latency_seconds=elapsed,
            retry_count=0,
            payload=payload,
            request_id=request_id,
            success=True,
        )
