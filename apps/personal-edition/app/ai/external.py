"""External runtime provider adapter using only Python stdlib.

This module implements an OpenAI-compatible chat completions client using
``urllib.request``.  No third-party HTTP library, SDK, or aiohttp is required.

Configuration is entirely environment-driven (via ``app.config.Settings``):
- ``AI_BASE_URL``: the chat completions endpoint (must end with
  ``/chat/completions`` or the path is appended automatically).
- ``AI_API_KEY``: the bearer token sent in the ``Authorization`` header.
- ``AI_MODEL``: the advertised model name sent in the request body.
- ``AI_TIMEOUT_SECONDS``: per-request socket timeout.

Credentials are **never** stored in any durable log, database record, or
exception message.  The adapter normalizes every failure into the existing
``ProviderErrorCategory`` taxonomy so that callers never see raw HTTP bodies
or credential material.
"""

from __future__ import annotations

import json
import socket
import ssl
import time
import urllib.error
import urllib.request
from typing import Any

from pydantic import BaseModel, ValidationError

from app.domain.enums import CostClass, ProviderErrorCategory
from app.domain.models import ProviderResult, ProviderUsage


def _normalize_endpoint(base_url: str) -> str:
    url = base_url.rstrip("/")
    if not url.endswith("/chat/completions"):
        url = url + "/chat/completions"
    return url


def _parse_usage(raw: dict[str, Any]) -> ProviderUsage | None:
    usage = raw.get("usage")
    if not isinstance(usage, dict):
        return None
    return ProviderUsage(
        input_tokens=usage.get("prompt_tokens"),
        output_tokens=usage.get("completion_tokens"),
        total_tokens=usage.get("total_tokens"),
    )


class ExternalProvider:
    """OpenAI-compatible provider using stdlib urllib.

    The provider never stores or logs the API key.  All errors are normalized
    to ``ProviderErrorCategory`` values.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: int = 120,
    ) -> None:
        if not base_url:
            raise ValueError("base_url must be a non-empty string")
        if not api_key:
            raise ValueError("api_key must be a non-empty string")
        if not model:
            raise ValueError("model must be a non-empty string")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")
        self._endpoint = _normalize_endpoint(base_url)
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_seconds
        self._ssl_ctx = ssl.create_default_context()

    @property
    def provider(self) -> str:
        return "external"

    @property
    def model(self) -> str:
        return self._model

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
        body = self._build_request_body(
            task_name=task_name,
            system_prompt=system_prompt,
            user_payload=user_payload,
        )
        raw_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self._endpoint,
            data=raw_bytes,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
        )
        try:
            resp = urllib.request.urlopen(
                req, timeout=self._timeout, context=self._ssl_ctx
            )
            resp_body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return self._handle_http_error(exc, start, request_id)
        except urllib.error.URLError as exc:
            return self._handle_url_error(exc, start, request_id)
        except socket.timeout:
            return self._failure(
                start, request_id, ProviderErrorCategory.TIMEOUT,
                "provider request timed out",
            )
        except OSError as exc:
            return self._failure(
                start, request_id, ProviderErrorCategory.CONNECTION_ERROR,
                "connection error",
            )

        return self._parse_response(
            resp_body, start, request_id, response_schema
        )

    def _build_request_body(
        self,
        *,
        task_name: str,
        system_prompt: str,
        user_payload: dict,
    ) -> dict[str, Any]:
        return {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(user_payload, ensure_ascii=False),
                },
            ],
            "response_format": {"type": "json_object"},
        }

    def _parse_response(
        self,
        body: str,
        start: float,
        request_id: str,
        response_schema: type[BaseModel],
    ) -> ProviderResult:
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return self._failure(
                start, request_id, ProviderErrorCategory.INVALID_JSON,
                "provider returned invalid JSON",
            )

        choices = data.get("choices")
        if not isinstance(choices, list) or len(choices) == 0:
            return self._failure(
                start, request_id, ProviderErrorCategory.PROVIDER_ERROR,
                "provider returned empty choices",
            )

        message = choices[0].get("message", {})
        content = message.get("content", "")
        if not isinstance(content, str) or not content.strip():
            return self._failure(
                start, request_id, ProviderErrorCategory.PROVIDER_ERROR,
                "provider returned empty content",
            )

        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            return self._failure(
                start, request_id, ProviderErrorCategory.INVALID_JSON,
                "provider returned invalid JSON in content",
            )

        try:
            validated = response_schema.model_validate(parsed)
        except ValidationError:
            return self._failure(
                start, request_id, ProviderErrorCategory.SCHEMA_MISMATCH,
                "provider response did not match the expected schema",
            )

        usage = _parse_usage(data)
        elapsed = time.monotonic() - start
        return ProviderResult(
            provider="external",
            advertised_model=self._model,
            cost_class=CostClass.FREE,
            latency_seconds=elapsed,
            retry_count=0,
            usage=usage or ProviderUsage(),
            payload=validated.model_dump(),
            request_id=request_id,
            success=True,
        )

    def _handle_http_error(
        self,
        exc: urllib.error.HTTPError,
        start: float,
        request_id: str,
    ) -> ProviderResult:
        code = exc.code
        if code == 429:
            return self._failure(
                start, request_id, ProviderErrorCategory.RATE_LIMIT,
                "rate limit exceeded",
            )
        if code in (401, 403):
            return self._failure(
                start, request_id, ProviderErrorCategory.REFUSAL,
                "provider refused the request",
            )
        if code >= 500:
            return self._failure(
                start, request_id, ProviderErrorCategory.PROVIDER_ERROR,
                "provider server error",
            )
        return self._failure(
            start, request_id, ProviderErrorCategory.PROVIDER_ERROR,
            "provider returned HTTP error",
        )

    def _handle_url_error(
        self,
        exc: urllib.error.URLError,
        start: float,
        request_id: str,
    ) -> ProviderResult:
        reason = exc.reason
        if isinstance(reason, socket.timeout):
            return self._failure(
                start, request_id, ProviderErrorCategory.TIMEOUT,
                "provider request timed out",
            )
        if isinstance(reason, OSError):
            return self._failure(
                start, request_id, ProviderErrorCategory.CONNECTION_ERROR,
                "connection error",
            )
        return self._failure(
            start, request_id, ProviderErrorCategory.CONNECTION_ERROR,
            "connection error",
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
            provider="external",
            advertised_model=self._model,
            cost_class=CostClass.FREE,
            latency_seconds=elapsed,
            retry_count=0,
            request_id=request_id,
            error_category=category,
            error_message=message,
            success=False,
        )
