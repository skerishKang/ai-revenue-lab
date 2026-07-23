from __future__ import annotations

import json
import time
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app.domain.enums import CostClass, ProviderErrorCategory
from app.domain.models import ProviderResult, ProviderUsage

_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503})


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        provider_name: str = "openai_compat",
        base_url: str = "https://api.deepseek.com/v1",
        cost_class: CostClass = CostClass.PAID,
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
    ):
        if not api_key:
            raise ValueError(
                "LF_AI_API_KEY is required for openai_compat provider"
            )
        self._api_key = api_key
        self._model = model
        self._provider_name = provider_name
        self._base_url = base_url.rstrip("/")
        self._cost_class = cost_class
        self._timeout = timeout_seconds
        self._max_retries = max_retries

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model(self) -> str:
        return self._model

    @property
    def cost_class(self) -> CostClass:
        return self._cost_class

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

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ]

        body = {
            "model": self._model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": 0.7,
            "max_tokens": 4096,
        }

        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = httpx.post(
                    f"{self._base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                    timeout=self._timeout,
                )
                response.raise_for_status()
                data = response.json()
                choice = data["choices"][0]
                content = choice["message"]["content"]
                usage_data = data.get("usage", {})

                try:
                    parsed = json.loads(content)
                except json.JSONDecodeError:
                    elapsed = time.monotonic() - start
                    return ProviderResult(
                        provider=self._provider_name,
                        advertised_model=self._model,
                        cost_class=self._cost_class,
                        latency_seconds=elapsed,
                        retry_count=attempt,
                        request_id=request_id,
                        error_category=ProviderErrorCategory.INVALID_JSON,
                        error_message="response was not valid JSON",
                        success=False,
                        usage=ProviderUsage(
                            input_tokens=usage_data.get("prompt_tokens"),
                            output_tokens=usage_data.get("completion_tokens"),
                            total_tokens=usage_data.get("total_tokens"),
                        ),
                    )

                try:
                    validated = response_schema.model_validate(parsed)
                except ValidationError:
                    elapsed = time.monotonic() - start
                    return ProviderResult(
                        provider=self._provider_name,
                        advertised_model=self._model,
                        cost_class=self._cost_class,
                        latency_seconds=elapsed,
                        retry_count=attempt,
                        request_id=request_id,
                        error_category=ProviderErrorCategory.SCHEMA_MISMATCH,
                        error_message="response did not match expected schema",
                        success=False,
                        usage=ProviderUsage(
                            input_tokens=usage_data.get("prompt_tokens"),
                            output_tokens=usage_data.get("completion_tokens"),
                            total_tokens=usage_data.get("total_tokens"),
                        ),
                    )

                elapsed = time.monotonic() - start
                return ProviderResult(
                    provider=self._provider_name,
                    advertised_model=self._model,
                    cost_class=self._cost_class,
                    latency_seconds=elapsed,
                    retry_count=attempt,
                    usage=ProviderUsage(
                        input_tokens=usage_data.get("prompt_tokens"),
                        output_tokens=usage_data.get("completion_tokens"),
                        total_tokens=usage_data.get("total_tokens"),
                    ),
                    payload=validated.model_dump(),
                    request_id=request_id,
                    success=True,
                )

            except httpx.TimeoutException:
                last_error = None
                if attempt < self._max_retries:
                    continue
                elapsed = time.monotonic() - start
                return ProviderResult(
                    provider=self._provider_name,
                    advertised_model=self._model,
                    cost_class=self._cost_class,
                    latency_seconds=elapsed,
                    retry_count=attempt,
                    request_id=request_id,
                    error_category=ProviderErrorCategory.TIMEOUT,
                    error_message="request timed out",
                    success=False,
                )

            except httpx.HTTPStatusError as exc:
                last_error = None
                if (
                    attempt < self._max_retries
                    and exc.response.status_code in _RETRYABLE_STATUSES
                ):
                    continue
                elapsed = time.monotonic() - start
                return ProviderResult(
                    provider=self._provider_name,
                    advertised_model=self._model,
                    cost_class=self._cost_class,
                    latency_seconds=elapsed,
                    retry_count=attempt,
                    request_id=request_id,
                    error_category=ProviderErrorCategory.PROVIDER_ERROR,
                    error_message=f"API returned {exc.response.status_code}",
                    success=False,
                )

            except Exception as exc:
                last_error = exc
                if attempt < self._max_retries:
                    continue
                elapsed = time.monotonic() - start
                return ProviderResult(
                    provider=self._provider_name,
                    advertised_model=self._model,
                    cost_class=self._cost_class,
                    latency_seconds=elapsed,
                    retry_count=attempt,
                    request_id=request_id,
                    error_category=ProviderErrorCategory.UNKNOWN,
                    error_message="unexpected provider error",
                    success=False,
                )

        elapsed = time.monotonic() - start
        return ProviderResult(
            provider=self._provider_name,
            advertised_model=self._model,
            cost_class=self._cost_class,
            latency_seconds=elapsed,
            retry_count=self._max_retries,
            request_id=request_id,
            error_category=ProviderErrorCategory.UNKNOWN,
            error_message="max retries exceeded",
            success=False,
        )
