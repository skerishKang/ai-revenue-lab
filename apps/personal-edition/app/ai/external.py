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
import logging
import re
import socket
import ssl
import time
import urllib.error
import urllib.request
from typing import Any

from pydantic import BaseModel, ValidationError

from app.domain.enums import CostClass, ProviderErrorCategory
from app.domain.models import ProviderResult, ProviderUsage

_log = logging.getLogger(__name__)

_REFUSAL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"content.?policy|safety.?filter|content.?moderat|violat(?:es?|ed)?"
        r".?(?:policy|guideline|terms|rules)|flagged?.?(?:by|for|as)"
        r".?(?:safety|policy|moderation)|harmful|hate.?speech|self.?harm"
        r"|violence|sexual|graphic|blocked?.?(?:by|for)?(?:safety|policy)"
        r"|refused?.?(?:to|because)|cannot.?assist|unable.?to.?help"
        r"|not.?allowed|against.?(?:policy|guidelines|terms)",
        re.IGNORECASE,
    ),
]

_MINIMAL_REFUSAL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"content.?policy|safety.?filter|content.?moderat|"
        r"violat(?:es?|ed)?.?(?:policy|guideline|terms|rules)|"
        r"blocked?.?(?:by|for)?(?:safety|policy)|"
        r"not.?allowed|against.?(?:policy|guidelines|terms)",
        re.IGNORECASE,
    ),
]


def _normalize_endpoint(base_url: str) -> str:
    url = base_url.rstrip("/")
    if not url.endswith("/chat/completions"):
        url = url + "/chat/completions"
    return url


def _parse_usage(raw: dict[str, Any]) -> ProviderUsage | None:
    usage = raw.get("usage")
    if not isinstance(usage, dict):
        return None
    try:
        input_tokens = usage.get("prompt_tokens")
        output_tokens = usage.get("completion_tokens")
        total_tokens = usage.get("total_tokens")
        if input_tokens is not None:
            input_tokens = int(input_tokens)
            if input_tokens < 0:
                input_tokens = None
        if output_tokens is not None:
            output_tokens = int(output_tokens)
            if output_tokens < 0:
                output_tokens = None
        if total_tokens is not None:
            total_tokens = int(total_tokens)
            if total_tokens < 0:
                total_tokens = None
        return ProviderUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        )
    except (TypeError, ValueError, OverflowError):
        return None


def _is_refusal_message(message: str) -> bool:
    for pat in _REFUSAL_PATTERNS:
        if pat.search(message):
            return True
    return False


def _check_provider_declared_refusal(data: dict[str, Any]) -> str | None:
    error_obj = data.get("error")
    if isinstance(error_obj, dict):
        message = error_obj.get("message", "")
        if isinstance(message, str) and _is_refusal_message(message):
            return "refusal"
        error_type = error_obj.get("type", "")
        if isinstance(error_type, str) and _is_refusal_message(error_type):
            return "refusal"
    choices = data.get("choices")
    if isinstance(choices, list) and len(choices) > 0:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message", {})
            if isinstance(message, dict):
                content = message.get("content", "")
                if isinstance(content, str) and _is_refusal_message(content):
                    return "refusal"
                finish_reason = message.get("finish_reason", "")
                if isinstance(finish_reason, str) and _is_refusal_message(
                    finish_reason
                ):
                    return "refusal"
    return None


_VALID_COST_CLASSES = frozenset({
    CostClass.FREE.value,
    CostClass.PAID.value,
    CostClass.LOCAL.value,
    CostClass.UNKNOWN.value,
})


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
        cost_class: CostClass = CostClass.FREE,
        response_format_mode: str = "json_schema",
    ) -> None:
        if not base_url:
            raise ValueError("base_url must be a non-empty string")
        if not api_key:
            raise ValueError("api_key must be a non-empty string")
        if not model:
            raise ValueError("model must be a non-empty string")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")
        if cost_class.value not in _VALID_COST_CLASSES:
            raise ValueError(
                f"cost_class must be one of {sorted(_VALID_COST_CLASSES)}, "
                f"got '{cost_class.value}'"
            )
        if response_format_mode not in ("json_schema", "json_object"):
            raise ValueError(
                f"response_format_mode must be 'json_schema' or 'json_object', "
                f"got '{response_format_mode}'"
            )
        self._endpoint = _normalize_endpoint(base_url)
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_seconds
        self._cost_class = cost_class
        self._response_format_mode = response_format_mode
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
        try:
            return self._generate_structured_inner(
                task_name=task_name,
                system_prompt=system_prompt,
                user_payload=user_payload,
                response_schema=response_schema,
                request_id=request_id,
            )
        except Exception:
            _log.exception(
                "unexpected error in ExternalProvider (request_id=%s)",
                request_id,
            )
            return ProviderResult(
                provider="external",
                advertised_model=self._model,
                cost_class=CostClass.UNKNOWN,
                latency_seconds=0.0,
                retry_count=0,
                request_id=request_id,
                error_category=ProviderErrorCategory.UNKNOWN,
                error_message="unexpected provider error",
                success=False,
            )

    def _generate_structured_inner(
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
            response_schema=response_schema,
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
            resp_bytes = resp.read()
            try:
                resp_body = resp_bytes.decode("utf-8")
            except UnicodeDecodeError:
                return self._failure(
                    start,
                    request_id,
                    ProviderErrorCategory.INVALID_JSON,
                    "provider returned invalid UTF-8",
                )
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
        response_schema: type[BaseModel] | None = None,
    ) -> dict[str, Any]:
        if self._response_format_mode == "json_schema" and response_schema is not None:
            schema = response_schema.model_json_schema()
            schema_name = response_schema.__name__
            response_format: dict[str, Any] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                },
            }
        else:
            response_format = {"type": "json_object"}

        return {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(user_payload, ensure_ascii=False),
                },
            ],
            "response_format": response_format,
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

        if not isinstance(data, dict):
            return self._failure(
                start, request_id, ProviderErrorCategory.SCHEMA_MISMATCH,
                "provider returned non-object JSON response",
            )

        provider_refusal = _check_provider_declared_refusal(data)
        if provider_refusal is not None:
            return self._failure(
                start, request_id, ProviderErrorCategory.REFUSAL,
                "provider refused the request due to content policy",
            )

        choices = data.get("choices")
        if not isinstance(choices, list) or len(choices) == 0:
            return self._failure(
                start, request_id, ProviderErrorCategory.PROVIDER_ERROR,
                "provider returned empty choices",
            )

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            return self._failure(
                start, request_id, ProviderErrorCategory.SCHEMA_MISMATCH,
                "provider returned non-object choice entry",
            )

        message = first_choice.get("message", {})
        if not isinstance(message, dict):
            return self._failure(
                start, request_id, ProviderErrorCategory.SCHEMA_MISMATCH,
                "provider returned non-object message entry",
            )

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
            cost_class=self._cost_class,
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
                start, request_id, ProviderErrorCategory.AUTH_FAILURE,
                "authentication or authorization failed",
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
            cost_class=self._cost_class,
            latency_seconds=elapsed,
            retry_count=0,
            request_id=request_id,
            error_category=category,
            error_message=message,
            success=False,
        )
