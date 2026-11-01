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

#6460-5 (2026-11-01 owner decision): Gemma 4 31B also declares the ``tools``
capability. Google documents native function calling for Gemma models on the
Gemini API (https://ai.google.dev/gemma/docs/core/gemma_on_gemini_api), and the
declaration below is the only place that capability is stated. The PC tool set
is included in what a tool-capable model may call: every PC call, from any
model, is executed by the same server-side step harness (admitted scope, signed
dispatch, verified result), so the model choice never widens what may run.

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
        # tools: official Gemma-on-Gemini-API function calling (#6460-5).
        frozenset({"chat", "tools"}),
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


def function_declarations(tools) -> list[dict]:
    """The one place a declared tool list becomes Gemini functionDeclarations.

    ``tools`` is the provider-shaped list every caller already holds
    (``ToolDefinition.to_provider_schema()`` produces exactly this), so a
    product adds a tool once and both the OpenAI-compatible lane and this native
    lane declare the same thing. The declaration carries the reviewed schema
    verbatim; nothing here adds, removes or narrows a parameter.
    """
    declared = _tool_channel().validate_tools(tools)
    return [
        {
            "name": tool["function"]["name"],
            "description": tool["function"].get("description", ""),
            "parametersJsonSchema": tool["function"]["parameters"],
        }
        for tool in declared
    ]


def _tool_channel():
    from . import tool_channel
    return tool_channel


def _google_tool_body(*, messages, tools, tool_choice, temperature, max_tokens, model_parameters):
    """Translate the already validated B14 declaration, without adding defaults.

    The same translation carries a follow-up turn (#4727): an assistant call
    becomes a ``functionCall`` part and each result becomes a
    ``functionResponse`` part that answers it by id. A call's opaque signature
    travels back as ``thoughtSignature`` on the call it belongs to; Gemini 3
    refuses a replay that drops it. Nothing is executed here.
    """
    import json
    from .tool_channel import (
        TOOL_COMPLETED_STATUS,
        InvalidToolDeclaration,
        validate_messages,
        validate_tools,
        validate_tool_choice,
    )

    def response_body(message):
        """One result body. A non-completion is never shaped like a result.

        A completed run answers with ``result``. Anything else answers with its
        own status and cause, so the model cannot read a refusal, an executor
        failure or a cancellation as the output the call produced.
        """
        execution = message.get("execution")
        status = execution.get("status") if isinstance(execution, dict) else None
        if status is None or status == TOOL_COMPLETED_STATUS:
            return {"result": message["content"]}
        body = {"status": status}
        if message["content"]:
            body["detail"] = message["content"]
        for name in ("error_class", "error_code"):
            if execution.get(name) is not None:
                body[name] = execution[name]
        return body

    declared = validate_tools(tools)
    declared_names = {tool["function"]["name"] for tool in declared}
    choice = validate_tool_choice(tool_choice, declared)
    turns = validate_messages(messages)

    contents, system_parts = [], []
    #: The open assistant call turn and its answers, keyed by call id.
    pending_calls: dict[str, str] | None = None
    pending_results: dict[str, dict] = {}

    def close_call_turn() -> None:
        nonlocal pending_calls, pending_results
        if pending_calls is None:
            return
        missing = [call_id for call_id in pending_calls if call_id not in pending_results]
        if missing:
            raise InvalidToolDeclaration(
                "every assistant tool call must be answered before the next turn"
            )
        contents.append({
            "role": "user",
            "parts": [pending_results[call_id] for call_id in pending_calls],
        })
        pending_calls, pending_results = None, {}

    for message in turns:
        role = message["role"]
        if role == "tool":
            call_id = message["tool_call_id"]
            if pending_calls is None or call_id not in pending_calls:
                raise InvalidToolDeclaration(
                    "a tool result must answer a call in the immediately preceding assistant turn"
                )
            if call_id in pending_results:
                raise InvalidToolDeclaration("a tool call was answered more than once")
            call_name = pending_calls[call_id]
            result_name = message.get("name")
            if result_name is not None and result_name != call_name:
                raise InvalidToolDeclaration(
                    "a tool result name does not match the call it answers"
                )
            pending_results[call_id] = {"functionResponse": {
                "id": call_id,
                "name": call_name,
                # The result is the executor's text, preserved verbatim. A
                # provider requires an object here, so it travels as one field.
                "response": response_body(message),
            }}
            continue

        close_call_turn()
        if role == "system":
            system_parts.append({"text": message["content"]})
            continue
        if role == "assistant":
            parts = []
            if message.get("content") is not None:
                text_part = {"text": message["content"]}
                # The turn's own answer part returns with the token it arrived
                # with; an unsigned answer keeps its plain part shape.
                if message.get("signature") is not None:
                    text_part["thoughtSignature"] = message["signature"]
                parts.append(text_part)
            calls: dict[str, str] = {}
            for call in message.get("tool_calls") or ():
                function = call["function"]
                name = function["name"]
                if name not in declared_names:
                    raise InvalidToolDeclaration(
                        "a historical tool call names a tool this request did not declare"
                    )
                try:
                    arguments = json.loads(function["arguments"])
                except (json.JSONDecodeError, ValueError) as exc:
                    raise InvalidToolDeclaration(
                        "a historical tool call's arguments must encode a JSON object"
                    ) from exc
                if not isinstance(arguments, dict):
                    raise InvalidToolDeclaration(
                        "a historical tool call's arguments must encode a JSON object"
                    )
                call_id = call["id"]
                if call_id in calls:
                    raise InvalidToolDeclaration("a tool call id appears twice in one turn")
                part = {"functionCall": {"id": call_id, "name": name, "args": arguments}}
                if call.get("signature") is not None:
                    part["thoughtSignature"] = call["signature"]
                parts.append(part)
                calls[call_id] = name
            if parts:
                contents.append({"role": "model", "parts": parts})
            pending_calls = calls or None
            continue

        contents.append({"role": "user", "parts": [{"text": message["content"]}]})
    close_call_turn()

    functions = function_declarations(tools)
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


class _GoogleMalformedShape(ValueError):
    def __init__(self, reason):
        self.reason = reason


class _GoogleToolStream:
    """Decode complete native SSE frames; no tool execution or classification."""

    def __init__(self, names, model_id="unknown"):
        self.model_id = model_id
        import uuid
        self.names = names
        self.call_prefix = "call_" + uuid.uuid4().hex
        self.ids: set[str] = set()
        self.finish_reason = None
        self.saw_output = False

    def decode(self, frame):
        import json
        from .malformed_diagnostics import malformed
        from .stream_types import StreamEvent, StreamToolCall, _usage_from_payload
        from .tool_channel import (
            InvalidToolDeclaration,
            MAX_TOOL_CALLS,
            MAX_TOOL_SIGNATURE_CHARS,
            validate_tool_calls,
        )

        def part_signature(part):
            """The opaque token attached to one part. Never parsed, only bounded."""

            signature = part.get("thoughtSignature")
            if signature is None:
                return None
            if (
                not isinstance(signature, str)
                or not signature.strip()
                or len(signature) > MAX_TOOL_SIGNATURE_CHARS
            ):
                raise _GoogleMalformedShape("invalid_signature")
            return signature

        payload = None
        try:
            data = "\n".join(
                line[5:].lstrip(" ") for line in frame.decode("utf-8").splitlines()
                if line.startswith("data:")
            )
            if not data:
                return []
            payload = json.loads(data)
            if not isinstance(payload, dict) or "error" in payload:
                raise _GoogleMalformedShape("payload_not_object_or_error")
            candidates = payload.get("candidates", [])
            if not isinstance(candidates, list) or len(candidates) > 1:
                raise _GoogleMalformedShape("candidate_count")
            events = []
            metadata = {"response_id": payload.get("responseId"), "model": payload.get("modelVersion")}
            if candidates:
                candidate = candidates[0]
                if not isinstance(candidate, dict) or candidate.get("index", 0) != 0:
                    raise _GoogleMalformedShape("invalid_candidate")
                parts = candidate.get("content", {}).get("parts", [])
                if not isinstance(parts, list):
                    raise _GoogleMalformedShape("invalid_parts")
                for part in parts:
                    if not isinstance(part, dict):
                        raise _GoogleMalformedShape("invalid_part")
                    if part.get("thought") is True:
                        continue
                    if "functionCall" in part:
                        if self.finish_reason is not None:
                            raise _GoogleMalformedShape("call_after_finish")
                        call = part["functionCall"]
                        if not isinstance(call, dict) or set(call) - {"id", "name", "args"}:
                            raise _GoogleMalformedShape("invalid_call")
                        name, args = call.get("name"), call.get("args", {})
                        if name not in self.names or not isinstance(args, dict):
                            raise _GoogleMalformedShape("invalid_function_call")
                        signature = part_signature(part)
                        index = len(self.ids)
                        call_id = call.get("id", f"{self.call_prefix}_{index}")
                        arguments = json.dumps(args, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
                        validate_tool_calls([{"id": call_id, "type": "function", "function": {
                            "name": name, "arguments": arguments,
                        }}], 0)
                        if call_id in self.ids or index >= MAX_TOOL_CALLS:
                            raise _GoogleMalformedShape("duplicate_or_excess_call")
                        self.ids.add(call_id)
                        events.append(StreamEvent(**metadata, tool_call=StreamToolCall(
                            call_id, name, arguments, index, signature=signature,
                        )))
                        self.saw_output = True
                    elif "text" in part:
                        text = part["text"]
                        if not isinstance(text, str) or self.finish_reason is not None:
                            raise _GoogleMalformedShape("invalid_text")
                        # A signed answer part relays its own token. A thinking
                        # part is deliberately not relayed above, so its token
                        # has no part to travel with; the turn's merge rule is
                        # the last non-null token a consumer saw.
                        events.append(StreamEvent(
                            **metadata, delta_content=text,
                            signature=part_signature(part),
                        ))
                        self.saw_output |= bool(text.strip())
                finish = candidate.get("finishReason")
                if finish is not None:
                    if not isinstance(finish, str) or not finish or self.finish_reason is not None:
                        raise _GoogleMalformedShape("invalid_finish")
                    if self.ids and finish != "STOP":
                        raise _GoogleMalformedShape("incomplete_tool_response")
                    self.finish_reason = {"STOP": "tool_calls" if self.ids else "stop", "MAX_TOKENS": "length"}.get(finish, finish)
            usage = payload.get("usageMetadata")
            if usage is not None:
                if not isinstance(usage, dict):
                    raise _GoogleMalformedShape("usage_not_object")
                # The native wire reports the three counts and, for a thinking
                # model, the thinking tokens beside them. Dropping that fourth
                # number would leave a row whose total is larger than the parts
                # it was built from, with nothing to explain the difference.
                events.append(StreamEvent(**metadata, usage=_usage_from_payload({
                    "prompt_tokens": usage.get("promptTokenCount"),
                    "completion_tokens": usage.get("candidatesTokenCount"),
                    "total_tokens": usage.get("totalTokenCount"),
                    "completion_tokens_details": {
                        "reasoning_tokens": usage.get("thoughtsTokenCount"),
                    },
                }, provider="google", model=self.model_id, path="native_stream", payload=payload)))
            return events
        except (ValueError, TypeError, AttributeError, KeyError, InvalidToolDeclaration) as exc:
            reason = (exc.reason if isinstance(exc, _GoogleMalformedShape) else
                      "utf8_decode" if isinstance(exc, UnicodeDecodeError) else
                      "json_decode" if isinstance(exc, json.JSONDecodeError) else "invalid_native_shape")
            raise malformed(reason, payload, provider="google", model=self.model_id,
                            path="native_stream") from None


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
    from .errors import InvalidRequest, UpstreamResponseTooLarge, UpstreamServerError, UpstreamTimeout
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
    decoder = _GoogleToolStream(permitted_names, model_id)
    kwargs = {"timeout": plat.build_provider_http_timeout(model_id)}
    if transport is not None:
        kwargs["transport"] = transport
    buffer = b""
    try:
        async with httpx.AsyncClient(**kwargs) as client:
            async with client.stream("POST", url, headers=headers, json=body, follow_redirects=False) as response:
                if not 200 <= response.status_code < 300:
                    error = await plat._read_bounded_body(response)
                    plat._raise_upstream_error(response.status_code, GOOGLE_PROVIDER_ID, error.decode("utf-8", "replace"), model_id=model_id)
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
        from .malformed_diagnostics import malformed
        raise malformed("missing_finish", provider="google", model=model_id, path="native_stream")
    if not decoder.saw_output:
        raise UpstreamEmptyAnswer(decoder.finish_reason, streamed=True)
    yield StreamEvent(done=True, finish_reason=decoder.finish_reason)
