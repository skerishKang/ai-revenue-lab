import time
from typing import Any

from pydantic import BaseModel, ValidationError

from app.domain.enums import CostClass, ProviderErrorCategory
from app.domain.models import ProviderResult, ProviderUsage


class MockProvider:
    """Network-free, fixture-controlled provider for deterministic tests.

    Programmable in three ways (checked in order):

    1. ``task_payloads``: mapping task name -> fixture payload dict. Validated
       against the response schema and returned on success.
    2. ``responses``: ordered list of scripted response dicts, consumed in
       order. Supports retry scenarios (a failure followed by a success). Each
       entry has keys: ``task`` (optional), ``kind`` (``payload``/``error``/
       ``schema_mismatch``), ``payload``, and optional ``usage`` dict.
    3. ``fixture_payload``: default payload when nothing else matches.

    Special task names (backwards compatible):
    - ``error``: always returns a PROVIDER_ERROR result.
    - ``invalid_payload``: always returns a SCHEMA_MISMATCH result.

    The provider records every request and never performs any I/O or opens a
    socket.
    """

    def __init__(
        self,
        model: str = "mock-world-feed-v1",
        fixture_payload: dict[str, Any] | None = None,
        *,
        task_payloads: dict[str, dict[str, Any]] | None = None,
        responses: list[dict[str, Any]] | None = None,
    ):
        self._provider_name = "mock"
        self._model = model
        self._fixture_payload = fixture_payload
        self._task_payloads = dict(task_payloads) if task_payloads else {}
        self._responses: list[dict[str, Any]] = list(responses) if responses else []
        self._requests: list[dict[str, Any]] = []

    @property
    def provider(self) -> str:
        return self._provider_name

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
            return self._apply_scripted(scripted, start, request_id, response_schema)

        if task_name in self._task_payloads:
            return self._validate_and_return(
                self._task_payloads[task_name], start, request_id, response_schema
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
        usage = _usage_from_dict(entry.get("usage"))
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
        r = self._validate_and_return(
            entry.get("payload"), start, request_id, response_schema
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
            provider=self._provider_name,
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
            provider=self._provider_name,
            advertised_model=self._model,
            cost_class=CostClass.FREE,
            latency_seconds=elapsed,
            retry_count=0,
            request_id=request_id,
            error_category=category,
            error_message=message,
            success=False,
        )


def _usage_from_dict(usage_dict: Any) -> ProviderUsage | None:
    if usage_dict is None:
        return None
    return ProviderUsage(**usage_dict)
