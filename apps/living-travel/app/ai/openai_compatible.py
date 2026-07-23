"""OpenAI-compatible structured-generation provider for Living Travel."""

from __future__ import annotations

import json
import time
import urllib.request
from typing import Callable, Protocol, runtime_checkable

from pydantic import BaseModel

from app.domain.enums import CostClass, ProviderErrorCategory
from app.domain.models import ProviderResult


@runtime_checkable
class Transport(Protocol):
    """Injectable HTTP transport for the provider.

    Default implementation uses ``urllib.request``.  Tests inject a stub that
    returns synthetic responses without opening a real socket.
    """

    def request(
        self,
        url: str,
        data: bytes,
        headers: dict[str, str],
        timeout: float,
    ) -> tuple[int, bytes]: ...


class UrllibTransport:
    """Default transport backed by ``urllib.request`` (stdlib, no extra dep)."""

    def request(
        self,
        url: str,
        data: bytes,
        headers: dict[str, str],
        timeout: float,
    ) -> tuple[int, bytes]:
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()


TASK_NAMES = frozenset({"editorial_plan", "edition_draft"})


class OpenAICompatibleProvider:
    """Structured-generation provider for OpenAI-compatible chat-completions APIs.

    Parameters
    ----------
    base_url:
        Full chat-completions URL (e.g. ``https://api.openai.com/v1/chat/completions``).
    api_key:
        Bearer-token credential.
    model:
        Model identifier (e.g. ``gpt-4o-mini``).
    timeout_seconds:
        Per-request timeout.
    cost_class:
        Cost class assigned to every result from this provider.
    transport:
        Injectable HTTP transport (defaults to ``UrllibTransport``).
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: int = 30,
        cost_class: CostClass = CostClass.free,
        transport: Transport | None = None,
    ) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_seconds
        self._cost_class = cost_class
        self._transport = transport or UrllibTransport()

        self._provider_name = "openai_compatible"
        self._redacted_api_key = api_key[:4] + "..." if len(api_key) > 4 else "***"

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

        if task_name not in TASK_NAMES:
            return ProviderResult(
                provider=self._provider_name,
                model=self._model,
                cost_class=self._cost_class,
                latency_ms=(time.monotonic() - start) * 1000,
                success=False,
                error_category=ProviderErrorCategory.unknown,
                error_message=f"unsupported task: {task_name}",
            )

        try:
            body = self._build_request_body(system_prompt, user_payload)
            status, raw = self._do_request(body)
        except TimeoutError:
            return ProviderResult(
                provider=self._provider_name,
                model=self._model,
                cost_class=self._cost_class,
                latency_ms=(time.monotonic() - start) * 1000,
                success=False,
                error_category=ProviderErrorCategory.timeout,
                error_message="provider request timed out",
            )
        except Exception as exc:
            return ProviderResult(
                provider=self._provider_name,
                model=self._model,
                cost_class=self._cost_class,
                latency_ms=(time.monotonic() - start) * 1000,
                success=False,
                error_category=ProviderErrorCategory.provider_error,
                error_message="provider request failed",
            )

        latency_ms = (time.monotonic() - start) * 1000

        if status != 200:
            return ProviderResult(
                provider=self._provider_name,
                model=self._model,
                cost_class=self._cost_class,
                latency_ms=latency_ms,
                success=False,
                error_category=ProviderErrorCategory.provider_error,
                error_message=f"provider returned http {status}",
            )

        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return ProviderResult(
                provider=self._provider_name,
                model=self._model,
                cost_class=self._cost_class,
                latency_ms=latency_ms,
                success=False,
                error_category=ProviderErrorCategory.invalid_json,
                error_message="provider returned malformed JSON",
            )

        usage = parsed.get("usage", {}) or {}
        prompt_tokens = usage.get("prompt_tokens", 0) or 0
        completion_tokens = usage.get("completion_tokens", 0) or 0

        try:
            choices = parsed["choices"]
        except (KeyError, TypeError, ValueError):
            return ProviderResult(
                provider=self._provider_name,
                model=self._model,
                cost_class=self._cost_class,
                latency_ms=latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                success=False,
                error_category=ProviderErrorCategory.invalid_json,
                error_message="provider response missing choices",
            )

        if not isinstance(choices, list) or len(choices) == 0:
            return ProviderResult(
                provider=self._provider_name,
                model=self._model,
                cost_class=self._cost_class,
                latency_ms=latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                success=False,
                error_category=ProviderErrorCategory.invalid_json,
                error_message="provider returned empty choices",
            )

        message = choices[0].get("message", {})
        content = message.get("content", "")

        if not content or not isinstance(content, str):
            return ProviderResult(
                provider=self._provider_name,
                model=self._model,
                cost_class=self._cost_class,
                latency_ms=latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                success=False,
                error_category=ProviderErrorCategory.invalid_json,
                error_message="provider returned empty content",
            )

        # Strip markdown fence if present (rejected as failure)
        content_stripped = content.strip()
        if content_stripped.startswith("```"):
            return ProviderResult(
                provider=self._provider_name,
                model=self._model,
                cost_class=self._cost_class,
                latency_ms=latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                success=False,
                error_category=ProviderErrorCategory.invalid_json,
                error_message="provider returned fenced JSON",
            )

        try:
            payload = json.loads(content_stripped)
        except (json.JSONDecodeError, ValueError):
            return ProviderResult(
                provider=self._provider_name,
                model=self._model,
                cost_class=self._cost_class,
                latency_ms=latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                success=False,
                error_category=ProviderErrorCategory.invalid_json,
                error_message="provider content is not valid JSON",
            )

        if not isinstance(payload, dict):
            return ProviderResult(
                provider=self._provider_name,
                model=self._model,
                cost_class=self._cost_class,
                latency_ms=latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                success=False,
                error_category=ProviderErrorCategory.schema_mismatch,
                error_message="provider returned array, expected object",
            )

        try:
            validated = response_schema.model_validate(payload)
        except Exception:
            return ProviderResult(
                provider=self._provider_name,
                model=self._model,
                cost_class=self._cost_class,
                latency_ms=latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                success=False,
                error_category=ProviderErrorCategory.schema_mismatch,
                error_message="provider response failed schema validation",
            )

        return ProviderResult(
            provider=self._provider_name,
            model=self._model,
            cost_class=self._cost_class,
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            payload=validated.model_dump(),
            success=True,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_request_body(self, system_prompt: str, user_payload: dict) -> bytes:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ]
        body = {
            "model": self._model,
            "messages": messages,
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        return json.dumps(body, ensure_ascii=False).encode("utf-8")

    def _do_request(self, body: bytes) -> tuple[int, bytes]:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        return self._transport.request(
            self._base_url,
            data=body,
            headers=headers,
            timeout=self._timeout,
        )
