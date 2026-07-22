import time
from typing import Any

from pydantic import BaseModel, ValidationError

from app.domain.enums import CostClass, ProviderErrorCategory
from app.domain.models import ProviderResult


class MockProvider:
    """Network-free, fixture-controlled provider for deterministic tests.

    The provider is programmable in three ways (checked in order):

    1. ``task_payloads``: a mapping from task name to fixture payload dict.
       When the requested task has a payload here, it is validated against the
       response schema and returned on success.

    2. ``responses``: an ordered list of scripted response dicts. Each entry is
       consumed in order, enabling retry scenarios (for example a provider
       failure followed by a success). Each dict has the keys:
         - ``task``: the task name it applies to (optional; if absent it
           applies to any task);
         - ``kind``: one of ``payload``, ``error``, ``schema_mismatch``;
         - ``payload``: the fixture payload (for ``payload`` kind).

    3. ``fixture_payload``: a single default payload used when no scripted
       response or task-specific payload matches. This preserves backward
       compatibility with the original MockProvider API.

    Special task names (preserved for backward compatibility):
    - ``error``: always returns a PROVIDER_ERROR result.
    - ``invalid_payload``: always returns a SCHEMA_MISMATCH result by
      validating ``{"bad": "data"}`` against the schema.

    The provider records every request for assertion in tests. It never opens
    a socket or performs any I/O.
    """

    def __init__(
        self,
        model: str = "mock-personal-edition-v1",
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
                "system_prompt": system_prompt,
                "user_payload": user_payload,
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
        usage = None
        if usage_dict is not None:
            from app.domain.models import ProviderUsage
            usage = ProviderUsage(**usage_dict)
        if kind == "error":
            r = self._failure(
                start,
                request_id,
                entry.get(
                    "category", ProviderErrorCategory.PROVIDER_ERROR
                ),
                entry.get("message", "scripted provider error"),
            )
            if usage is not None:
                return r.model_copy(update={"usage": usage})
            return r
        if kind == "schema_mismatch":
            r = self._failure(
                start,
                request_id,
                ProviderErrorCategory.SCHEMA_MISMATCH,
                entry.get("message", "scripted schema mismatch"),
            )
            if usage is not None:
                return r.model_copy(update={"usage": usage})
            return r
        payload = entry.get("payload")
        r = self._validate_and_return(
            payload, start, request_id, response_schema
        )
        if usage is not None:
            return r.model_copy(update={"usage": usage})
        return r

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
