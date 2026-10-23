"""Google AI Studio provider onboarding for Business 14 (#3554, 2026-10-08).

Owner selection 2026-10-08 named four Google models in the Padiem Plus set:
``gemini-3.1-flash-lite``, ``gemini-3.5-flash-lite``, ``gemma-4-26b-a4b-it``
and ``gemma-4-31b-it``. All four were confirmed present in the live
``generativelanguage.googleapis.com/v1beta/models`` catalog on 2026-10-08
(62 models total) before any registration.

Google's documented OpenAI-compatible origin is
https://generativelanguage.googleapis.com/v1beta/openai. The existing
Business 14 OpenAI-compatible client uses Authorization: Bearer with the
Google AI Studio key. Text-only calls retain this wire; slice 3-A uses native
streamGenerateContent with x-goog-api-key only for explicit tools. The existing binding is
``PADIEM_B14_CREDENTIAL_05`` (name only; the value is never read, printed, or
committed here).

Measured on 2026-10-08 against the repo-owned synthetic Korean quotation
fixture at each provider's documented defaults:

* gemini-3.5-flash-lite  text 7/7 facts 1.12s, image 5/5 facts 1.28s
* gemini-3.1-flash-lite  text 7/7 facts 0.92s, image 5/5 facts 1.37s
* gemma-4-26b-a4b-it     text 7/7 facts 13.0s, image 5/5 facts 28.1s
* gemma-4-31b-it         text 7/7 facts 49.0s; image blocked by provider capacity

Gemma 4 31B is registered as text-only because its image capability was not
measurable, and its 49.0s latency exceeds the B14 20.0s default dispatch
budget. Registration states exactly that rather than a capability nobody proved.

Registration is explicit/manual-pin only: each model lives in the exact-ID
``CATALOG_BY_ID`` table and is NOT appended to ``CATALOG_MODELS``, so
``b14/auto`` and the legacy public summary surface are untouched. Missing
credential fails closed with zero upstream calls (generic platform adapter
contract). Prices are the provider's published per-million-token rates; the
API returns no dollar field, so no measured-cost claim is made here.
"""

from __future__ import annotations

from app.pilot.catalog import CATALOG_BY_ID, CatalogModel
from app.pilot.platform_secrets import (
    CredentialSource,
    PlatformProviderSpec,
    get_platform_provider,
    register_platform_provider,
)

GOOGLE_PROVIDER_ID = "google"
GOOGLE_BASE_ORIGIN = "https://generativelanguage.googleapis.com/v1beta/openai"
GOOGLE_ALLOWED_HOST = "generativelanguage.googleapis.com"
GOOGLE_CREDENTIAL_BINDING = "PADIEM_B14_CREDENTIAL_05"

# Authority date of the catalog read and the measurements this registration cites.
GOOGLE_SOURCE_CHECKED_AT = "2026-10-08"

# model_id, upstream model, display name, context window, USD per 1M in/out,
# capabilities, sort order.
_GOOGLE_MODELS: tuple[tuple[str, str, str, int, float, float, frozenset[str], int], ...] = (
    (
        "google/gemini-3.5-flash-lite",
        "gemini-3.5-flash-lite",
        "Google: Gemini 3.5 Flash Lite",
        1_048_576,
        0.30,
        2.50,
        frozenset({"chat", "image", "coding"}),
        70,
    ),
    (
        "google/gemini-3.1-flash-lite",
        "gemini-3.1-flash-lite",
        "Google: Gemini 3.1 Flash Lite",
        1_048_576,
        0.25,
        1.50,
        frozenset({"chat", "image", "coding"}),
        71,
    ),
    (
        "google/gemma-4-26b-a4b-it",
        "gemma-4-26b-a4b-it",
        "Google: Gemma 4 26B",
        262_144,
        0.09,
        0.30,
        frozenset({"chat", "image"}),
        72,
    ),
    (
        "google/gemma-4-31b-it",
        "gemma-4-31b-it",
        "Google: Gemma 4 31B",
        262_144,
        0.09,
        0.34,
        # text-only: the image measurement was blocked by provider capacity.
        frozenset({"chat"}),
        73,
    ),
)


def register_google_provider() -> None:
    """Historic API kept only to fail closed; models are installed from b14_models.json."""
    raise RuntimeError("legacy provider registration disabled: edit b14_models.json")


def require_stream_tool_support(model_id: str, provider_id: str | None = None) -> None:
    """Capability and wire support are separate gates, including on fallback."""
    from .catalog import get_catalog_by_id
    from .errors import StreamNotSupported
    from .tool_channel import require_tool_capability

    model = get_catalog_by_id(model_id)
    if model is None or model.platform_provider_id != GOOGLE_PROVIDER_ID:
        raise StreamNotSupported()
    if provider_id is not None and provider_id != GOOGLE_PROVIDER_ID:
        raise StreamNotSupported()
    require_tool_capability(model_id)


def _google_tool_body(*, messages, tools, tool_choice, temperature, max_tokens, model_parameters):
    """Translate the already validated B14 declaration, without adding defaults."""
    from .errors import StreamNotSupported
    from .tool_channel import validate_tools, validate_tool_choice

    declared = validate_tools(tools)
    choice = validate_tool_choice(tool_choice, declared)
    contents, system_parts = [], []
    for message in messages:
        role, text = message.get("role"), message.get("content")
        # Slice 3-A exposes first-turn calls only; do not lose tool history or
        # Gemini thought signatures by pretending a text projection is a replay.
        if role not in {"system", "user", "assistant"} or not isinstance(text, str) or "tool_calls" in message:
            raise StreamNotSupported()
        if role == "system":
            system_parts.append({"text": text})
        else:
            contents.append({"role": "model" if role == "assistant" else "user", "parts": [{"text": text}]})
    functions = []
    for tool in declared:
        function = tool["function"]
        functions.append({
            "name": function["name"],
            "description": function.get("description", ""),
            "parametersJsonSchema": function["parameters"],
        })
    body = {"contents": contents, "tools": [{"functionDeclarations": functions}]}
    if system_parts:
        body["systemInstruction"] = {"parts": system_parts}
    if choice is not None:
        config = (
            {"mode": "ANY", "allowedFunctionNames": [choice["function"]["name"]]}
            if isinstance(choice, dict)
            else {"mode": {"auto": "AUTO", "none": "NONE", "required": "ANY"}[choice]}
        )
        body["toolConfig"] = {"functionCallingConfig": config}
    generation = {}
    if temperature is not None:
        generation["temperature"] = float(temperature)
    if max_tokens is not None:
        generation["maxOutputTokens"] = int(max_tokens)
    if model_parameters:
        generation["thinkingConfig"] = {"thinkingLevel": model_parameters["reasoning_effort"].upper()}
    if generation:
        body["generationConfig"] = generation
    return body


class _GoogleToolStream:
    """Decode complete native SSE frames; no tool execution or classification."""

    def __init__(self, names):
        import uuid
        self.names = names
        self.call_prefix = "call_" + uuid.uuid4().hex
        self.ids: set[str] = set()
        self.finish_reason = None
        self.saw_output = False

    def decode(self, frame):
        import json
        from .errors import MalformedUpstreamResponse
        from .stream_types import StreamEvent, StreamToolCall, _usage_from_payload
        from .tool_channel import InvalidToolDeclaration, MAX_TOOL_CALLS, validate_tool_calls

        try:
            data = "\n".join(
                line[5:].lstrip(" ") for line in frame.decode("utf-8").splitlines()
                if line.startswith("data:")
            )
            if not data:
                return []
            payload = json.loads(data)
            if not isinstance(payload, dict) or "error" in payload:
                raise ValueError("invalid native response")
            candidates = payload.get("candidates", [])
            if not isinstance(candidates, list) or len(candidates) > 1:
                raise ValueError("invalid candidate count")
            events = []
            metadata = {"response_id": payload.get("responseId"), "model": payload.get("modelVersion")}
            if candidates:
                candidate = candidates[0]
                if not isinstance(candidate, dict) or candidate.get("index", 0) != 0:
                    raise ValueError("invalid candidate")
                parts = candidate.get("content", {}).get("parts", [])
                if not isinstance(parts, list):
                    raise ValueError("invalid parts")
                for part in parts:
                    if not isinstance(part, dict):
                        raise ValueError("invalid part")
                    if part.get("thought") is True:
                        continue
                    if "functionCall" in part:
                        if self.finish_reason is not None:
                            raise ValueError("call after finish")
                        call = part["functionCall"]
                        if not isinstance(call, dict) or set(call) - {"id", "name", "args"}:
                            raise ValueError("invalid or partial call")
                        name, args = call.get("name"), call.get("args", {})
                        if name not in self.names or not isinstance(args, dict):
                            raise ValueError("invalid function call")
                        index = len(self.ids)
                        call_id = call.get("id", f"{self.call_prefix}_{index}")
                        arguments = json.dumps(args, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
                        validate_tool_calls([{"id": call_id, "type": "function", "function": {
                            "name": name, "arguments": arguments,
                        }}], 0)
                        if call_id in self.ids or index >= MAX_TOOL_CALLS:
                            raise ValueError("duplicate or excess call")
                        self.ids.add(call_id)
                        events.append(StreamEvent(**metadata, tool_call=StreamToolCall(call_id, name, arguments, index)))
                        self.saw_output = True
                    elif "text" in part:
                        text = part["text"]
                        if not isinstance(text, str) or self.finish_reason is not None:
                            raise ValueError("invalid text")
                        events.append(StreamEvent(**metadata, delta_content=text))
                        self.saw_output |= bool(text.strip())
                finish = candidate.get("finishReason")
                if finish is not None:
                    if not isinstance(finish, str) or not finish or self.finish_reason is not None:
                        raise ValueError("invalid finish")
                    if self.ids and finish != "STOP":
                        raise ValueError("incomplete tool response")
                    self.finish_reason = {"STOP": "tool_calls" if self.ids else "stop", "MAX_TOKENS": "length"}.get(finish, finish)
            usage = payload.get("usageMetadata")
            if usage is not None:
                if not isinstance(usage, dict):
                    raise ValueError("invalid usage")
                events.append(StreamEvent(**metadata, usage=_usage_from_payload({
                    "prompt_tokens": usage.get("promptTokenCount"),
                    "completion_tokens": usage.get("candidatesTokenCount"),
                    "total_tokens": usage.get("totalTokenCount"),
                })))
            return events
        except (ValueError, TypeError, AttributeError, KeyError, InvalidToolDeclaration) as exc:
            raise MalformedUpstreamResponse() from exc


async def stream_google_tool_calls(*, model_id, upstream_model, spec, messages, tools,
                                   tool_choice=None, temperature=None, max_tokens=None,
                                   model_parameters=None, transport=None):
    """Google-only native wire, entered only when tools are explicitly present.

    References: https://ai.google.dev/api/generate-content#method:-models.streamgeneratecontent
    and https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite.
    Uses the existing Google binding; no credential in the URL or diagnostics.
    """
    import httpx
    from . import platform as plat
    from .catalog import get_catalog_by_id
    from .errors import InvalidRequest, MalformedUpstreamResponse, UpstreamResponseTooLarge, UpstreamServerError, UpstreamTimeout
    from .model_native_parameters import UnsupportedModelParameter, validate_native_parameters
    from .stream_types import StreamEvent, _pop_sse_frames
    from .upstream_answer_contract import UpstreamEmptyAnswer
    from .worker_env import load_request_secret

    require_stream_tool_support(model_id, spec.provider_id)
    registered = get_catalog_by_id(model_id)
    if registered.upstream_model != upstream_model or spec.base_origin != GOOGLE_BASE_ORIGIN:
        raise InvalidRequest("Google tool wire requires the exact registered route.")
    try:
        parameters = validate_native_parameters(model_id, model_parameters or {})
    except UnsupportedModelParameter as exc:
        raise InvalidRequest(str(exc)) from exc
    body = _google_tool_body(messages=messages, tools=tools, tool_choice=tool_choice,
        temperature=temperature, max_tokens=max_tokens, model_parameters=parameters)
    await load_request_secret(spec.credential_binding_name)
    legacy_headers = plat._request_headers(spec, model_id=model_id)
    headers = {"Content-Type": "application/json", "x-goog-api-key": legacy_headers["Authorization"][7:]}
    url = f"https://{GOOGLE_ALLOWED_HOST}/v1beta/models/{upstream_model}:streamGenerateContent?alt=sse"
    permitted_names = {tool["function"]["name"] for tool in tools}
    if tool_choice == "none":
        permitted_names = set()
    elif isinstance(tool_choice, dict):
        permitted_names = {tool_choice["function"]["name"]}
    decoder = _GoogleToolStream(permitted_names)
    kwargs = {"timeout": plat.build_provider_http_timeout(model_id)}
    if transport is not None:
        kwargs["transport"] = transport
    buffer = b""
    try:
        async with httpx.AsyncClient(**kwargs) as client:
            async with client.stream("POST", url, headers=headers, json=body, follow_redirects=False) as response:
                if not 200 <= response.status_code < 300:
                    error = await plat._read_bounded_body(response)
                    plat._raise_upstream_error(response.status_code, GOOGLE_PROVIDER_ID, error.decode("utf-8", "replace"))
                async for chunk in plat._iter_sse_bounded_slices(response):
                    frames, buffer = _pop_sse_frames(buffer + chunk)
                    if len(buffer) > plat.MAX_RESPONSE_BYTES:
                        raise UpstreamResponseTooLarge(plat.MAX_RESPONSE_BYTES)
                    for frame in frames:
                        if len(frame) > plat.MAX_RESPONSE_BYTES:
                            raise UpstreamResponseTooLarge(plat.MAX_RESPONSE_BYTES)
                        for event in decoder.decode(frame):
                            yield event
                if buffer.strip():
                    for event in decoder.decode(buffer):
                        yield event
    except httpx.TimeoutException as exc:
        plat.log_provider_timeout(plat.logger, GOOGLE_PROVIDER_ID, exc, "stream")
        raise UpstreamTimeout() from exc
    except httpx.RequestError as exc:
        raise UpstreamServerError() from exc
    if decoder.finish_reason is None:
        raise MalformedUpstreamResponse()
    if not decoder.saw_output:
        raise UpstreamEmptyAnswer(decoder.finish_reason, streamed=True)
    yield StreamEvent(done=True, finish_reason=decoder.finish_reason)
