from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from types import MappingProxyType
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit

import httpx

from .contracts import UsageMetadata

B14_CHAT_COMPLETIONS_PATH = "/api/pilot/v1/chat/completions"

# ── B14 output-limit authorities (#3553) ─────────────────────────────────────
# Three different authorities must never be merged into one number:
#
#   PRODUCT_REQUESTED_LIMIT
#       What a product/feature actually asks for as an output budget.
#       The explicit-request compatibility ceiling below is a LEGACY B14
#       PILOT VALIDATION VALUE, not model-capability truth:
#       origin commit d8714ad4 (2026-07-25, #142) validated explicit
#       max_tokens as 1..4096 in gateway.py/schemas.py; the shared Core
#       contract later copied the same range (1d6e1b7f, 2026-08-26).
#       GLOBAL_4096_ORIGIN=EARLY_B14_PILOT_VALIDATION
#       GLOBAL_4096_IS_PROVIDER_MODEL_MAX=NO
#   RUNTIME_HARD_SAFETY_CEILING
#       B14's own resource-abuse guards, independent of max_tokens:
#       response byte cap (MAX_B14_RESPONSE_BYTES / configurable up to
#       MAX_CONFIGURED_B14_RESPONSE_BYTES) and request timeout bounds
#       (B14ExecutionConfig.timeout_seconds, 1..60s). Values unchanged.
#   PROVIDER_MODEL_MAX_OUTPUT
#       What the selected provider/model can technically produce.
#       Capability metadata only (see padiem_ai_core.b14_output_limits).
#       It must never become the global request validator and must never
#       be fabricated when unknown.
#
# AUTOMATIC_MAX_OUTPUT_WIDENING=NO: raising PRODUCT_EXPLICIT_OUTPUT_TOKEN_CEILING
# is a deliberate product decision with targeted tests and byte/time safeguards,
# never an automatic copy of a provider maximum.
PRODUCT_EXPLICIT_OUTPUT_TOKEN_CEILING = 4096

MAX_B14_RESPONSE_BYTES = 1_048_576  # RUNTIME_HARD_SAFETY_CEILING (response bytes)
MAX_CONFIGURED_B14_RESPONSE_BYTES = 8 * 1_048_576  # RUNTIME_HARD_SAFETY_CEILING (configured cap)
MAX_B14_MESSAGES = 100
MAX_B14_MESSAGE_CHARS = 32_000
MAX_B14_MODEL_CHARS = 200

_TASK_TYPES = frozenset({"general", "korean", "coding", "document", "batch"})
_OPTIMIZE_FOR = frozenset({"balanced", "cost", "latency", "korean"})
_MESSAGE_ROLES = frozenset({"system", "user", "assistant"})
# B14's own enumerated rate-limit classes (apps/korean-ai-platform app/pilot/errors.py).
# The 429 body is provider-controlled text, so only these exact values may reach the
# diagnostic channel; anything else degrades to None instead of carrying a payload string.
_B14_RATE_LIMIT_DIAGNOSTIC_CODES = frozenset({
    "upstream_rate_limited",
    "upstream_rate_limited_busy",
    "kilo_free_rate_limited",
})


def _normalize_base_url(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("base_url must be a string")
    raw = value.strip()
    if not raw or any(ord(char) < 32 for char in raw):
        raise ValueError("base_url must be a non-empty URL")
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("base_url is invalid") from exc
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError("base_url must use http or https")
    if not parsed.hostname:
        raise ValueError("base_url must include a host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("base_url must not include credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("base_url must not include query or fragment")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("base_url port is invalid")
    path = parsed.path.rstrip("/")
    return urlunsplit((scheme, parsed.netloc, path, "", ""))


def _normalize_string_tuple(
    name: str,
    value: Sequence[str] | None,
    *,
    max_items: int = 32,
) -> tuple[str, ...] | None:
    if value is None:
        return None
    if isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be a sequence of strings")
    items = tuple(value)
    if len(items) > max_items:
        raise ValueError(f"{name} must contain at most {max_items} items")
    normalized: list[str] = []
    for item in items:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{name} must contain non-empty strings")
        text = item.strip()
        if len(text) > 200:
            raise ValueError(f"{name} values must not exceed 200 characters")
        normalized.append(text)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{name} must not contain duplicates")
    return tuple(normalized)


def _normalize_messages(
    messages: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    if isinstance(messages, (str, bytes)):
        raise ValueError("messages must be a sequence of message objects")
    items = tuple(messages)
    if not 1 <= len(items) <= MAX_B14_MESSAGES:
        raise ValueError(f"messages must contain 1 to {MAX_B14_MESSAGES} items")

    out: list[Mapping[str, Any]] = []
    for index, message in enumerate(items):
        if not isinstance(message, Mapping):
            raise ValueError(f"messages[{index}] must be a mapping")
        if set(message) != {"role", "content"}:
            raise ValueError(f"messages[{index}] must contain only role and content")
        role = message.get("role")
        if role not in _MESSAGE_ROLES:
            raise ValueError(f"messages[{index}].role is invalid")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError(f"messages[{index}].content must be a non-empty string")
        normalized_content = content.strip()
        if len(normalized_content) > MAX_B14_MESSAGE_CHARS:
            raise ValueError(
                f"messages[{index}].content must not exceed {MAX_B14_MESSAGE_CHARS} characters"
            )
        out.append(MappingProxyType({"role": role, "content": normalized_content}))
    return tuple(out)


def _safe_string(value: Any, *, limit: int = 300) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    return text[:limit]


def _safe_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _safe_non_negative_int(value: Any, *, maximum: int = 1_000_000_000) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0 or value > maximum:
        return None
    return value


def _safe_non_negative_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        return None
    return number


def _safe_reason_codes(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    result: list[str] = []
    for item in value[:50]:
        text = _safe_string(item, limit=120)
        if text is not None and text not in result:
            result.append(text)
    return tuple(result)


def _b14_rate_limit_diagnostic(raw: bytes) -> str | None:
    # The status alone cannot tell a provider free-tier exhaustion from a transient
    # capacity 429, and B14 already answers with one of its enumerated codes.
    try:
        data = json.loads(bytes(raw).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, Mapping):
        return None
    error = data.get("error")
    if not isinstance(error, Mapping):
        return None
    code = error.get("code")
    return code if isinstance(code, str) and code in _B14_RATE_LIMIT_DIAGNOSTIC_CODES else None


@dataclass(frozen=True, slots=True)
class B14ExecutionConfig:
    base_url: str
    # RUNTIME_HARD_SAFETY_CEILING: duration guard, independent of max_tokens (#3553).
    timeout_seconds: float = 20.0
    # RUNTIME_HARD_SAFETY_CEILING: response byte guard, independent of max_tokens.
    max_response_bytes: int = MAX_B14_RESPONSE_BYTES

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_url", _normalize_base_url(self.base_url))
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(float(self.timeout_seconds))
            or not 1 <= float(self.timeout_seconds) <= 60
        ):
            raise ValueError("timeout_seconds must be between 1 and 60")
        object.__setattr__(self, "timeout_seconds", float(self.timeout_seconds))
        if (
            isinstance(self.max_response_bytes, bool)
            or not isinstance(self.max_response_bytes, int)
            or not 1 <= self.max_response_bytes <= MAX_CONFIGURED_B14_RESPONSE_BYTES
        ):
            raise ValueError(
                f"max_response_bytes must be between 1 and {MAX_CONFIGURED_B14_RESPONSE_BYTES}"
            )

    @property
    def chat_completions_url(self) -> str:
        return self.base_url + B14_CHAT_COMPLETIONS_PATH

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "timeout_seconds": self.timeout_seconds,
            "max_response_bytes": self.max_response_bytes,
        }


@dataclass(frozen=True, slots=True)
class B14RoutingOptions:
    task_type: str | None = None
    required_capabilities: tuple[str, ...] | None = None
    optimize_for: str | None = None
    allow_external_fallback: bool | None = None
    provider_order: tuple[str, ...] | None = None
    max_attempts: int | None = None
    # B14 same-route retry ceiling for one dispatch. The gateway accepts
    # business14.max_retries in [0, 2] and defaults to 2 when the field is
    # omitted, so None keeps the historical behavior while an explicit 0
    # pins a single provider call per dispatch (#3382 one-shot contract).
    max_retries: int | None = None

    def __post_init__(self) -> None:
        if self.task_type is not None:
            if not isinstance(self.task_type, str):
                raise ValueError("task_type must be a string or None")
            task_type = self.task_type.strip().lower()
            if task_type not in _TASK_TYPES:
                raise ValueError("unsupported task_type")
            object.__setattr__(self, "task_type", task_type)

        object.__setattr__(
            self,
            "required_capabilities",
            _normalize_string_tuple("required_capabilities", self.required_capabilities),
        )

        if self.optimize_for is not None:
            if not isinstance(self.optimize_for, str):
                raise ValueError("optimize_for must be a string or None")
            optimize_for = self.optimize_for.strip().lower()
            if optimize_for not in _OPTIMIZE_FOR:
                raise ValueError("unsupported optimize_for")
            object.__setattr__(self, "optimize_for", optimize_for)

        if self.allow_external_fallback is not None and not isinstance(
            self.allow_external_fallback, bool
        ):
            raise ValueError("allow_external_fallback must be a boolean or None")

        object.__setattr__(
            self,
            "provider_order",
            _normalize_string_tuple("provider_order", self.provider_order),
        )

        if self.max_attempts is not None and (
            isinstance(self.max_attempts, bool)
            or not isinstance(self.max_attempts, int)
            or not 1 <= self.max_attempts <= 5
        ):
            raise ValueError("max_attempts must be between 1 and 5")

        if self.max_retries is not None and (
            isinstance(self.max_retries, bool)
            or not isinstance(self.max_retries, int)
            or not 0 <= self.max_retries <= 2
        ):
            raise ValueError("max_retries must be between 0 and 2")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.task_type is not None:
            out["task_type"] = self.task_type
        if self.required_capabilities is not None:
            out["required_capabilities"] = list(self.required_capabilities)
        if self.optimize_for is not None:
            out["optimize_for"] = self.optimize_for
        if self.allow_external_fallback is not None:
            out["allow_external_fallback"] = self.allow_external_fallback
        if self.provider_order is not None:
            out["provider_order"] = list(self.provider_order)
        if self.max_attempts is not None:
            out["max_attempts"] = self.max_attempts
        if self.max_retries is not None:
            out["max_retries"] = self.max_retries
        return out


# #3906: the closed vocabulary of the provider-native ``reasoning_effort``
# option the B14 gateway documents and forwards (see #3977 source
# apps/korean-ai-platform/app/pilot/model_native_parameters.py). This contract
# fixes only the wire NAME and the accepted SPELLING. WHICH served model accepts
# WHICH value stays provider capability metadata owned by B14, so a model that
# does not document a level is never offered one by a caller.
REASONING_EFFORT_VALUES = frozenset({"minimal", "low", "medium", "high"})


@dataclass(frozen=True, slots=True)
class B14ChatRequest:
    messages: tuple[Mapping[str, Any], ...]
    # #2101: `model` is required. The old `b14/auto` default let an omitted
    # route silently widen into Router auto execution. Explicit generic auto
    # requests remain valid by passing model="b14/auto".
    model: str
    temperature: float = 0.2
    max_tokens: int | None = None
    routing: B14RoutingOptions = field(default_factory=B14RoutingOptions)
    # #3906: an EXPLICIT user-selected reasoning level. Omitted stays omitted so
    # the served provider applies its own default; the payload then carries no
    # reasoning key at all. A present value is transmitted as the provider's
    # documented ``reasoning_effort`` field and is never downgraded, substituted
    # or silently dropped.
    reasoning_effort: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "messages", _normalize_messages(self.messages))
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError("model must be a non-empty string")
        model = self.model.strip()
        if len(model) > MAX_B14_MODEL_CHARS:
            raise ValueError(f"model must not exceed {MAX_B14_MODEL_CHARS} characters")
        object.__setattr__(self, "model", model)

        if (
            isinstance(self.temperature, bool)
            or not isinstance(self.temperature, (int, float))
            or not math.isfinite(float(self.temperature))
            or not 0 <= float(self.temperature) <= 2
        ):
            raise ValueError("temperature must be between 0 and 2")
        object.__setattr__(self, "temperature", float(self.temperature))

        # PRODUCT_REQUESTED_LIMIT authority: explicit output budget must stay
        # within the product's explicit-request compatibility ceiling. The
        # omitted-value contract is separate (#3551): None stays None and the
        # payload omits the field. RUNTIME byte/time guards and provider/model
        # capability metadata are separate authorities and are not consulted
        # here (capability must never be fabricated; see b14_output_limits).
        if self.max_tokens is not None and (
            isinstance(self.max_tokens, bool)
            or not isinstance(self.max_tokens, int)
            or not 1 <= self.max_tokens <= PRODUCT_EXPLICIT_OUTPUT_TOKEN_CEILING
        ):
            raise ValueError(
                "max_tokens must be between 1 and "
                f"{PRODUCT_EXPLICIT_OUTPUT_TOKEN_CEILING} or None"
            )
        if not isinstance(self.routing, B14RoutingOptions):
            raise ValueError("routing must be B14RoutingOptions")

        if (
            self.reasoning_effort is not None
            and self.reasoning_effort not in REASONING_EFFORT_VALUES
        ):
            # Fail closed on a misspelled or invented level instead of sending a
            # paid-provider request the gateway would have to reject anyway.
            raise ValueError(
                "reasoning_effort must be one of "
                + ", ".join(sorted(REASONING_EFFORT_VALUES))
                + " or None"
            )

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [dict(message) for message in self.messages],
            "temperature": self.temperature,
        }
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens
        if self.reasoning_effort is not None:
            payload["reasoning_effort"] = self.reasoning_effort
        routing = self.routing.to_dict()
        if routing:
            payload["business14"] = routing
        return payload


@dataclass(frozen=True, slots=True)
class B14RouteMetadata:
    request_id: str | None = None
    route_mode: str | None = None
    selected_provider: str | None = None
    selected_model: str | None = None
    selected_upstream_model: str | None = None
    selected_route_id: str | None = None
    actual_response_model: str | None = None
    reason_codes: tuple[str, ...] = ()
    fallback_used: bool | None = None
    attempt_count: int | None = None
    route_evidence_status: str | None = None
    estimated_krw: float | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "route_mode": self.route_mode,
            "selected_provider": self.selected_provider,
            "selected_model": self.selected_model,
            "selected_upstream_model": self.selected_upstream_model,
            "selected_route_id": self.selected_route_id,
            "actual_response_model": self.actual_response_model,
            "reason_codes": list(self.reason_codes),
            "fallback_used": self.fallback_used,
            "attempt_count": self.attempt_count,
            "route_evidence_status": self.route_evidence_status,
            "estimated_krw": self.estimated_krw,
        }


@dataclass(frozen=True, slots=True)
class B14ExecutionResult:
    answer: str
    route: B14RouteMetadata = field(default_factory=B14RouteMetadata)
    usage: UsageMetadata = field(default_factory=UsageMetadata)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "route": self.route.to_public_dict(),
            "usage": self.usage.to_public_dict(),
        }


class B14ExecutionError(RuntimeError):
    def __init__(
        self,
        code: str,
        safe_message: str,
        *,
        upstream_status_code: int | None = None,
        retryable: bool = False,
        diagnostic_class: str | None = None,
    ) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.upstream_status_code = upstream_status_code
        self.retryable = retryable
        self.diagnostic_class = diagnostic_class

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.safe_message,
            "upstream_status_code": self.upstream_status_code,
            "retryable": self.retryable,
        }


def _parse_route_metadata(data: Mapping[str, Any]) -> B14RouteMetadata:
    raw = data.get("business14")
    if not isinstance(raw, Mapping):
        return B14RouteMetadata()
    return B14RouteMetadata(
        request_id=_safe_string(raw.get("request_id"), limit=200),
        route_mode=_safe_string(raw.get("route_mode"), limit=80),
        selected_provider=_safe_string(raw.get("selected_provider"), limit=200),
        selected_model=_safe_string(raw.get("selected_model"), limit=300),
        selected_upstream_model=_safe_string(raw.get("selected_upstream_model"), limit=300),
        selected_route_id=_safe_string(raw.get("selected_route_id"), limit=300),
        actual_response_model=_safe_string(raw.get("actual_response_model"), limit=300),
        reason_codes=_safe_reason_codes(raw.get("reason_codes")),
        fallback_used=_safe_bool(raw.get("fallback_used")),
        attempt_count=_safe_non_negative_int(raw.get("attempt_count"), maximum=100),
        route_evidence_status=_safe_string(raw.get("route_evidence_status"), limit=120),
        estimated_krw=_safe_non_negative_number(raw.get("estimated_krw")),
    )


def _parse_usage(data: Mapping[str, Any]) -> UsageMetadata:
    raw = data.get("usage")
    if not isinstance(raw, Mapping):
        return UsageMetadata()
    return UsageMetadata(
        input_tokens=_safe_non_negative_int(raw.get("prompt_tokens")),
        output_tokens=_safe_non_negative_int(raw.get("completion_tokens")),
        total_tokens=_safe_non_negative_int(raw.get("total_tokens")),
    )


class B14ExecutionClient:
    def __init__(
        self,
        config: B14ExecutionConfig,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not isinstance(config, B14ExecutionConfig):
            raise ValueError("config must be B14ExecutionConfig")
        self._config = config
        self._transport = transport

    @property
    def config(self) -> B14ExecutionConfig:
        return self._config

    async def execute(self, request: B14ChatRequest) -> B14ExecutionResult:
        if not isinstance(request, B14ChatRequest):
            raise ValueError("request must be B14ChatRequest")

        timeout = httpx.Timeout(
            connect=min(self._config.timeout_seconds, 10.0),
            read=self._config.timeout_seconds,
            write=min(self._config.timeout_seconds, 10.0),
            pool=min(self._config.timeout_seconds, 10.0),
        )

        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=timeout,
                follow_redirects=False,
            ) as client:
                async with client.stream(
                    "POST",
                    self._config.chat_completions_url,
                    json=request.to_payload(),
                ) as response:
                    status_code = response.status_code
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(raw) + len(chunk) > self._config.max_response_bytes:
                            raise B14ExecutionError(
                                "upstream_response_too_large",
                                "Business 14 response exceeded the configured safety limit.",
                                upstream_status_code=status_code,
                            )
                        raw.extend(chunk)
        except B14ExecutionError:
            raise
        except httpx.TimeoutException as exc:
            raise B14ExecutionError(
                "upstream_timeout",
                "Business 14 did not respond before the configured timeout.",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise B14ExecutionError(
                "upstream_unavailable",
                "Business 14 transport is unavailable.",
                retryable=True,
            ) from exc

        if status_code in {401, 403}:
            raise B14ExecutionError(
                "upstream_auth_error",
                "Business 14 rejected the service request authorization.",
                upstream_status_code=status_code,
            )
        if status_code == 429:
            raise B14ExecutionError(
                "upstream_rate_limited",
                "Business 14 is rate limiting requests.",
                upstream_status_code=status_code,
                retryable=True,
                diagnostic_class=_b14_rate_limit_diagnostic(raw),
            )
        if 400 <= status_code < 500:
            raise B14ExecutionError(
                "upstream_request_error",
                "Business 14 rejected the request.",
                upstream_status_code=status_code,
            )
        if status_code >= 500:
            raise B14ExecutionError(
                "upstream_server_error",
                "Business 14 returned a server error.",
                upstream_status_code=status_code,
                retryable=True,
            )
        if status_code < 200 or status_code >= 300:
            raise B14ExecutionError(
                "upstream_request_error",
                "Business 14 returned an unsupported HTTP status.",
                upstream_status_code=status_code,
            )

        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise B14ExecutionError(
                "malformed_upstream",
                "Business 14 returned malformed JSON.",
                upstream_status_code=status_code,
                diagnostic_class="upstream_malformed_json",
            ) from exc
        if not isinstance(data, Mapping):
            raise B14ExecutionError(
                "malformed_upstream",
                "Business 14 returned an unexpected response shape.",
                upstream_status_code=status_code,
                diagnostic_class="upstream_unexpected_shape",
            )

        try:
            answer = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise B14ExecutionError(
                "malformed_upstream",
                "Business 14 response did not contain assistant content.",
                upstream_status_code=status_code,
                diagnostic_class="upstream_missing_content",
            ) from exc
        if not isinstance(answer, str):
            raise B14ExecutionError(
                "malformed_upstream",
                "Business 14 assistant content was not text.",
                upstream_status_code=status_code,
                diagnostic_class="upstream_non_text_content",
            )
        normalized_answer = answer.strip()
        if not normalized_answer:
            raise B14ExecutionError(
                "empty_upstream_answer",
                "Business 14 returned an empty assistant answer.",
                upstream_status_code=status_code,
                diagnostic_class="upstream_empty_answer",
            )

        return B14ExecutionResult(
            answer=normalized_answer,
            route=_parse_route_metadata(data),
            usage=_parse_usage(data),
        )
