"""Opt-in Padiem AI Core provider for Living Learning.

The product keeps ownership of structured-output validation, retry policy and
accounting.  Padiem AI Core owns the product-neutral model execution contract,
while Business 14 remains the provider/model routing authority.
"""

from __future__ import annotations

import asyncio
import json
from typing import Protocol

from pydantic import BaseModel, ValidationError

from padiem_ai_core import (
    AgentProfile,
    B14ExecutionClient,
    B14ExecutionConfig,
    ErrorClass,
    ExecutionRequest,
    ExecutionResult,
    ExecutionRuntime,
    ExecutionRuntimeError,
)

from app.domain.models import ProviderResult


MAX_SCHEMA_CONTEXT_CHARS = 12_000
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TEMPERATURE = 0.2


class ExecutionRunner(Protocol):
    async def run(self, request: ExecutionRequest) -> ExecutionResult: ...


def _failure(category: str, *, model: str) -> ProviderResult:
    """Return a privacy-safe product failure without upstream exception text."""
    return ProviderResult(
        provider="padiem-core",
        model=model,
        cost_class="free",
        success=False,
        error_category=category,
        error_message=category,
    )


def _error_category(exc: ExecutionRuntimeError) -> str:
    error_class = exc.metadata.error_class
    if error_class is ErrorClass.PROVIDER_TIMEOUT:
        return "timeout"
    if error_class is ErrorClass.PROVIDER_RATE_LIMIT:
        return "rate_limit"
    if error_class is ErrorClass.AUTH_ERROR:
        return "authentication_error"
    if error_class is ErrorClass.INPUT_ERROR:
        return "invalid_request"
    if error_class is ErrorClass.POLICY_BLOCKED:
        return "provider_refusal"
    if exc.retryable:
        return "transient_provider_error"
    if error_class is ErrorClass.PROVIDER_BAD_RESPONSE:
        return "provider_refusal"
    return "core_execution_error"


def _schema_context(response_schema: type[BaseModel]) -> str:
    schema = response_schema.model_json_schema()
    text = json.dumps(
        schema,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    context = (
        "Return exactly one JSON object matching the JSON Schema below. "
        "Do not use Markdown fences, commentary, or text outside the JSON object.\n"
        f"JSON Schema:\n{text}"
    )
    if len(context) > MAX_SCHEMA_CONTEXT_CHARS:
        raise ValueError("response schema exceeds the bounded Core context")
    return context


def _user_message(task_name: str, user_payload: dict) -> str:
    if not isinstance(task_name, str) or not task_name.strip():
        raise ValueError("task_name must be non-empty")
    if not isinstance(user_payload, dict):
        raise ValueError("user_payload must be a dict")
    return json.dumps(
        {"task_name": task_name.strip(), "input": user_payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


class PadiemCoreProvider:
    provider_type = "padiem_core"

    def __init__(
        self,
        *,
        runtime: ExecutionRunner,
        model: str = "b14/auto",
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> None:
        if not callable(getattr(runtime, "run", None)):
            raise ValueError("runtime must expose async run(request)")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be non-empty")
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1 <= max_tokens <= 4096:
            raise ValueError("max_tokens must be between 1 and 4096")
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not 0 <= float(temperature) <= 2:
            raise ValueError("temperature must be between 0 and 2")
        self._runtime = runtime
        self.model = model.strip()
        self._max_tokens = max_tokens
        self._temperature = float(temperature)

    @classmethod
    def from_b14(
        cls,
        *,
        base_url: str,
        model: str = "b14/auto",
        timeout_seconds: float = 20.0,
    ) -> "PadiemCoreProvider":
        config = B14ExecutionConfig(
            base_url=base_url,
            timeout_seconds=timeout_seconds,
        )
        runtime = ExecutionRuntime(
            app_id="living-learning",
            b14_client=B14ExecutionClient(config),
        )
        return cls(runtime=runtime, model=model)

    def _request(
        self,
        *,
        task_name: str,
        system_prompt: str,
        user_payload: dict,
        response_schema: type[BaseModel],
    ) -> ExecutionRequest:
        if not isinstance(system_prompt, str) or not system_prompt.strip():
            raise ValueError("system_prompt must be non-empty")
        if not isinstance(response_schema, type) or not issubclass(response_schema, BaseModel):
            raise ValueError("response_schema must be a Pydantic BaseModel type")

        agent = AgentProfile(
            id="living-learning-structured",
            title="Living Learning Structured Generator",
            description="Generate one validated structured result for Living Learning.",
            system_instruction=system_prompt.strip(),
            task_type="korean",
            optimize_for="korean",
            max_tokens=self._max_tokens,
            required_capabilities=("free",),
            model_policy={
                "model": self.model,
                "temperature": self._temperature,
                "allow_external_fallback": False,
                "max_attempts": 1,
            },
        )
        return ExecutionRequest(
            agent=agent,
            messages=(
                {
                    "role": "user",
                    "content": _user_message(task_name, user_payload),
                },
            ),
            additional_system_context=_schema_context(response_schema),
        )

    def generate_structured(
        self,
        *,
        task_name: str,
        system_prompt: str,
        user_payload: dict,
        response_schema: type[BaseModel],
        request_id: str,
    ) -> ProviderResult:
        # request_id remains Living Learning's attempt/accounting identity. Core
        # generates its own safe trace id so arbitrary product IDs cannot weaken
        # the shared identifier contract.
        del request_id

        try:
            execution_request = self._request(
                task_name=task_name,
                system_prompt=system_prompt,
                user_payload=user_payload,
                response_schema=response_schema,
            )
        except (TypeError, ValueError, OverflowError):
            return _failure("invalid_request", model=self.model)

        try:
            result = asyncio.run(self._runtime.run(execution_request))
        except ExecutionRuntimeError as exc:
            return _failure(_error_category(exc), model=self.model)
        except Exception:
            # Never surface local/Core/private exception text through the
            # product provider result.
            return _failure("core_execution_error", model=self.model)

        try:
            decoded = json.loads(result.answer)
            if not isinstance(decoded, dict):
                raise ValueError("structured output must be a JSON object")
            validated = response_schema.model_validate(decoded)
            payload = validated.model_dump(mode="json")
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError):
            return ProviderResult(
                provider=result.metadata.provider or "padiem-core",
                model=result.metadata.model or self.model,
                cost_class="free",
                latency_ms=float(result.metadata.duration_ms or 0),
                prompt_tokens=result.metadata.usage.input_tokens,
                completion_tokens=result.metadata.usage.output_tokens,
                success=False,
                error_category="schema_mismatch",
                error_message="schema_mismatch",
            )

        return ProviderResult(
            provider=result.metadata.provider or "padiem-core",
            model=result.metadata.model or self.model,
            cost_class="free",
            latency_ms=float(result.metadata.duration_ms or 0),
            prompt_tokens=result.metadata.usage.input_tokens,
            completion_tokens=result.metadata.usage.output_tokens,
            payload=payload,
            success=True,
        )
