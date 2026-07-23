from __future__ import annotations

import json
import random
import time
from urllib.parse import urlparse
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app.domain.enums import CostClass, ProviderErrorCategory
from app.domain.models import ProviderResult, ProviderUsage

_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503})
_NON_RETRYABLE_STATUSES = frozenset({400, 401, 402, 422})

_MAX_BACKOFF = 120.0
_INITIAL_BACKOFF = 1.0
_BACKOFF_MULTIPLIER = 2.0

_BLOCKED_HOST_PREFIXES = (
    "localhost",
    "127.",
    "10.",
    "169.254.",
    "172.16.",
    "172.17.",
    "172.18.",
    "172.19.",
    "172.20.",
    "172.21.",
    "172.22.",
    "172.23.",
    "172.24.",
    "172.25.",
    "172.26.",
    "172.27.",
    "172.28.",
    "172.29.",
    "172.30.",
    "172.31.",
    "192.168.",
    "0.",
    "::1",
    "::",
    "fe80:",
    "fc00:",
    "fd00:",
)


def validate_base_url(url: str) -> str:
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme != "https":
        raise ValueError(f"LF_AI_BASE_URL must use HTTPS, got '{scheme}'")
    if parsed.username or parsed.password:
        raise ValueError("LF_AI_BASE_URL must not contain embedded credentials")
    host = parsed.hostname or ""
    if host.startswith(_BLOCKED_HOST_PREFIXES):
        raise ValueError(
            f"LF_AI_BASE_URL host '{host}' is not allowed "
            "(loopback/private/link-local)"
        )
    path = parsed.path.rstrip("/")
    if path.endswith("/v1"):
        path = path
    elif path.endswith("/v1/chat/completions"):
        path = path
    elif path == "":
        path = "/v1"
    else:
        raise ValueError(
            f"LF_AI_BASE_URL path '{path}' is not recognized; "
            "expected '/v1' or '/v1/chat/completions'"
        )
    cleaned = f"{scheme}://{parsed.netloc}{path}"
    return cleaned


def _build_endpoint_url(base: str) -> str:
    base = base.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _choose_backoff_delay(attempt: int, retry_after: str | None) -> float:
    if retry_after is not None:
        try:
            seconds = int(retry_after)
            return min(float(seconds), _MAX_BACKOFF)
        except (ValueError, TypeError):
            pass
    delay = _INITIAL_BACKOFF * (_BACKOFF_MULTIPLIER ** attempt)
    jitter = random.uniform(0, 0.5 * delay)
    return min(delay + jitter, _MAX_BACKOFF)


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        provider_name: str = "openai_compat",
        base_url: str = "https://api.deepseek.com",
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
        self._validated_url = validate_base_url(base_url)
        self._cost_class = cost_class
        self._timeout = httpx.Timeout(
            connect=timeout_seconds,
            read=timeout_seconds,
            write=timeout_seconds,
            pool=timeout_seconds,
        )
        self._max_retries = max_retries
        self._endpoint_url = _build_endpoint_url(self._validated_url)

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model(self) -> str:
        return self._model

    @property
    def cost_class(self) -> CostClass:
        return self._cost_class

    @property
    def endpoint_url(self) -> str:
        return self._endpoint_url

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

        for attempt in range(self._max_retries + 1):
            try:
                response = httpx.post(
                    self._endpoint_url,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                    timeout=self._timeout,
                )
                response.raise_for_status()
                data = response.json()
                usage_data = data.get("usage", {})

                choices = data.get("choices")
                if not choices:
                    elapsed = time.monotonic() - start
                    return ProviderResult(
                        provider=self._provider_name,
                        advertised_model=self._model,
                        cost_class=self._cost_class,
                        latency_seconds=elapsed,
                        retry_count=attempt,
                        request_id=request_id,
                        error_category=ProviderErrorCategory.PROVIDER_ERROR,
                        error_message="missing choices in response",
                        success=False,
                        usage=ProviderUsage(
                            input_tokens=usage_data.get("prompt_tokens"),
                            output_tokens=usage_data.get("completion_tokens"),
                            total_tokens=usage_data.get("total_tokens"),
                        ),
                    )

                choice = choices[0]
                finish_reason = choice.get("finish_reason", "")
                content = (choice.get("message") or {}).get("content") or ""

                if finish_reason == "length":
                    elapsed = time.monotonic() - start
                    return ProviderResult(
                        provider=self._provider_name,
                        advertised_model=self._model,
                        cost_class=self._cost_class,
                        latency_seconds=elapsed,
                        retry_count=attempt,
                        request_id=request_id,
                        error_category=ProviderErrorCategory.PROVIDER_ERROR,
                        error_message="finish_reason=length (truncated)",
                        success=False,
                        usage=ProviderUsage(
                            input_tokens=usage_data.get("prompt_tokens"),
                            output_tokens=usage_data.get("completion_tokens"),
                            total_tokens=usage_data.get("total_tokens"),
                        ),
                    )

                stripped = content.strip()
                if not stripped:
                    elapsed = time.monotonic() - start
                    return ProviderResult(
                        provider=self._provider_name,
                        advertised_model=self._model,
                        cost_class=self._cost_class,
                        latency_seconds=elapsed,
                        retry_count=attempt,
                        request_id=request_id,
                        error_category=ProviderErrorCategory.INVALID_JSON,
                        error_message="response was empty or whitespace-only",
                        success=False,
                        usage=ProviderUsage(
                            input_tokens=usage_data.get("prompt_tokens"),
                            output_tokens=usage_data.get("completion_tokens"),
                            total_tokens=usage_data.get("total_tokens"),
                        ),
                    )

                try:
                    parsed = json.loads(stripped)
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
                if attempt < self._max_retries:
                    delay = _choose_backoff_delay(attempt, None)
                    time.sleep(delay)
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
                status = exc.response.status_code
                if status in _NON_RETRYABLE_STATUSES or attempt >= self._max_retries:
                    elapsed = time.monotonic() - start
                    return ProviderResult(
                        provider=self._provider_name,
                        advertised_model=self._model,
                        cost_class=self._cost_class,
                        latency_seconds=elapsed,
                        retry_count=attempt,
                        request_id=request_id,
                        error_category=ProviderErrorCategory.PROVIDER_ERROR,
                        error_message=f"API returned {status}",
                        success=False,
                    )
                if status in _RETRYABLE_STATUSES:
                    retry_after = exc.response.headers.get("Retry-After")
                    delay = _choose_backoff_delay(attempt, retry_after)
                    time.sleep(delay)
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
                    error_message=f"unexpected HTTP {status}",
                    success=False,
                )

            except Exception:
                if attempt < self._max_retries:
                    delay = _choose_backoff_delay(attempt, None)
                    time.sleep(delay)
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
