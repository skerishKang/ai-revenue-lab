"""Network-free, programmable MockProvider for deterministic tests.

The provider is programmable via ``task_payloads`` (task name → fixture
payload dict). It never opens a socket or performs any I/O.

It records every request for assertion in tests. Special task names:
- ``error``: always returns PROVIDER_ERROR.
- ``invalid_payload``: always returns SCHEMA_MISMATCH by validating
  ``{"bad": "data"}`` against the schema.

Optional ``responses`` list allows ordered scripted responses for retry
scenarios (e.g. failure followed by success). Each dict has keys:
  - ``task`` (optional): task name filter.
  - ``kind``: ``payload``, ``error``, or ``schema_mismatch``.
  - ``payload``: fixture payload (for ``payload`` kind).
  - ``usage`` (optional): token usage dict.
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, ValidationError

from app.domain.enums import CostClass, ProviderErrorCategory
from app.domain.models import ProviderResult, ProviderUsage


class MockProvider:
    """Network-free, fixture-controlled provider for deterministic tests."""

    def __init__(
        self,
        model: str = "mock-living-fiction-v1",
        fixture_payload: dict[str, Any] | None = None,
        *,
        task_payloads: dict[str, dict[str, Any]] | None = None,
        responses: list[dict[str, Any]] | None = None,
    ):
        self._model = model
        self._fixture_payload = fixture_payload
        self._task_payloads = dict(task_payloads) if task_payloads else {}
        self._responses: list[dict[str, Any]] = (
            list(responses) if responses else []
        )
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
            return self._failure(
                start,
                request_id,
                ProviderErrorCategory.PROVIDER_ERROR,
                "simulated provider error",
            )

        if task_name == "invalid_payload":
            try:
                response_schema.model_validate({"bad": "data"})
            except ValidationError as exc:
                return self._failure(
                    start,
                    request_id,
                    ProviderErrorCategory.SCHEMA_MISMATCH,
                    str(exc),
                )

        scripted = self._consume_scripted(task_name)
        if scripted is not None:
            return self._apply_scripted(
                scripted, start, request_id, response_schema
            )

        if task_name in self._task_payloads:
            payload = self._task_payloads[task_name]
            return self._validate_and_return(
                payload, start, request_id, response_schema
            )

        fixture = self._fixture_payload if self._fixture_payload is not None else {}
        return self._validate_and_return(
            fixture, start, request_id, response_schema
        )

    def _consume_scripted(self, task_name: str) -> dict[str, Any] | None:
        for idx, entry in enumerate(self._responses):
            applies = entry.get("task")
            if applies is None or applies == task_name:
                return self._responses.pop(idx)
        return None

    def _apply_scripted(
        self,
        entry: dict[str, Any],
        start: float,
        request_id: str,
        response_schema: type[BaseModel],
    ) -> ProviderResult:
        kind = entry.get("kind", "payload")
        usage_dict = entry.get("usage")
        usage = ProviderUsage(**usage_dict) if usage_dict else None

        if kind == "error":
            r = self._failure(
                start,
                request_id,
                entry.get("category", ProviderErrorCategory.PROVIDER_ERROR),
                entry.get("message", "scripted provider error"),
            )
            return r.model_copy(update={"usage": usage}) if usage else r

        if kind == "schema_mismatch":
            r = self._failure(
                start,
                request_id,
                ProviderErrorCategory.SCHEMA_MISMATCH,
                entry.get("message", "scripted schema mismatch"),
            )
            return r.model_copy(update={"usage": usage}) if usage else r

        payload = entry.get("payload")
        r = self._validate_and_return(
            payload, start, request_id, response_schema
        )
        return r.model_copy(update={"usage": usage}) if usage else r

    def _validate_and_return(
        self,
        payload: Any,
        start: float,
        request_id: str,
        response_schema: type[BaseModel],
    ) -> ProviderResult:
        try:
            validated = response_schema.model_validate(payload)
            dumped = validated.model_dump()
        except ValidationError as exc:
            return self._failure(
                start,
                request_id,
                ProviderErrorCategory.SCHEMA_MISMATCH,
                str(exc),
            )

        elapsed = time.monotonic() - start
        return ProviderResult(
            provider="mock",
            advertised_model=self._model,
            cost_class=CostClass.FREE,
            latency_seconds=elapsed,
            retry_count=0,
            payload=dumped,
            request_id=request_id,
            success=True,
        )

    def _failure(
        self,
        start: float,
        request_id: str,
        category: ProviderErrorCategory,
        message: str,
    ) -> ProviderResult:
        elapsed = time.monotonic() - start
        return ProviderResult(
            provider="mock",
            advertised_model=self._model,
            cost_class=CostClass.FREE,
            latency_seconds=elapsed,
            retry_count=0,
            request_id=request_id,
            error_category=category,
            error_message=message,
            success=False,
        )
