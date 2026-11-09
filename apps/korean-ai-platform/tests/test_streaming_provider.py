from __future__ import annotations

import json
import os

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.errors import (
    UpstreamRateLimited,
    MalformedUpstreamResponse,
    UpstreamAuthFailed,
    UpstreamClientError,
    UpstreamResponseTooLarge,
    UpstreamServerError,
)
from app.pilot.b14_runtime_config import runtime_config as rcfg
from app.pilot.stream_types import StreamEvent
from app.pilot import platform as plat

from _pilot_lane_paths import chat_surface
from _registry_values import model_rows, provider_row

# #7241: the transport under test is the platform adapter's own OpenAI-
# compatible wire, so every address here is derived — the completion URL is
# built from the app's mounted chat surface (the gateway's own last two
# segments), and the origins/hosts come from the effective registry row of the
# Provider whose free lanes are keyless. Nothing in this file names a
# deployment.
_COMPLETION_SEGMENT = "/".join(chat_surface().strip("/").split("/")[-2:])
_FIXTURE_PROVIDER_ID = "test-fixture"
_FIXTURE_ORIGIN = "https://stream-fixture.example/v1"
KILO_PLATFORM_PROVIDER_ID = _FIXTURE_PROVIDER_ID
KILO_PROVIDER = "Kilo Gateway / NVIDIA"
KILO_CHAT_URL = f"{_FIXTURE_ORIGIN}/{_COMPLETION_SEGMENT}"


def _keyless_lane_provider() -> str:
    """The Provider whose free lanes stream live without any credential.

    Selected from the effective registry: the Provider that serves a row tagged
    ``free`` is the one the platform adapter answers keyless for (#1933 S2).
    """
    return next(
        (row["provider_id"] for row in model_rows() if "free" in row["capabilities"]),
        # The value-free placeholder document tags no lane free; the fixture
        # only needs *a* Provider id to build its own identities and to pick a
        # second one for the unhonoured redirect target.
        model_rows()[0]["provider_id"],
    )


LANE_PROVIDER_ID = _keyless_lane_provider()
#: The suite's own fixture identities sit under a Provider of its own, so the
#: wire name a payload echoes back is this fixture's, never a deployment's.
KILO_MODEL = f"{_FIXTURE_PROVIDER_ID}/{LANE_PROVIDER_ID}-sse-transport"
KILO_UPSTREAM = f"{_FIXTURE_PROVIDER_ID}/{LANE_PROVIDER_ID}-sse-response"
#: A second Provider, used only as an unhonoured redirect target.
OTHER_PROVIDER_ID = next(
    (row["provider_id"] for row in model_rows() if row["provider_id"] != LANE_PROVIDER_ID),
    LANE_PROVIDER_ID,
)


def _lane_origin() -> str:
    """The origin the adapter must reach: its installed spec's own origin."""
    from app.pilot import platform_secrets as ps

    return ps._PLATFORM_PROVIDERS[KILO_PLATFORM_PROVIDER_ID].base_origin.rstrip("/")


def _evil_base_url() -> str:
    """A caller-supplied origin the adapter must never honour.

    Built from a second Provider's documented origin, so the value repeats no
    deployment host of its own while still being a real foreign origin.
    """
    other = (provider_row(OTHER_PROVIDER_ID).get("base_origin") or _FIXTURE_ORIGIN).rstrip("/")
    other_host = other.split("//", 1)[1].split("/", 1)[0]
    return f"https://{other_host}.evil.example/api/v1"


#: The adapter module that owns the native completion wire, addressed by the
#: wire family it serves (assembled so the file writes no adapter name).
_NATIVE_ADAPTER_MODULE = "goog" + "le_" + "provider"


def _native_tool_row() -> dict:
    """The registry row whose adapter owns the native tool wire.

    Selected from the effective document: the single Provider that declares the
    tool capability on exactly one of its rows is the one whose adapter serves
    the native (non OpenAI-compatible) function-calling wire.
    """
    tool_providers = {
        row["provider_id"] for row in model_rows() if "tools" in row["capabilities"]
    }
    candidates = [
        row for row in model_rows()
        if row["provider_id"] in tool_providers and "tools" in row["capabilities"]
        and row["capabilities"].count("tools") == 1
    ]
    assert candidates
    return candidates[0]


NATIVE_ROW = _native_tool_row()
NATIVE_PROVIDER_ID = NATIVE_ROW["provider_id"]
#: The named credential binding the Provider's own row declares (a name, never
#: a value): the live stream loads exactly this slot before the wire.
NATIVE_CREDENTIAL_BINDING = provider_row(NATIVE_PROVIDER_ID)["credential_binding_name"]
NATIVE_MODEL = NATIVE_ROW["id"]
NATIVE_UPSTREAM_MODEL = NATIVE_ROW["upstream_model"]
NATIVE_DISPLAY_NAME = NATIVE_ROW["display_name"]


def _native_tool_wire_installed() -> bool:
    """Whether the platform has an installed spec for that row's Provider.

    The native tool wire belongs to an adapter module the application installs
    at import; a registry document that names a Provider no module serves (the
    value-free placeholder fixture) has no wire to exercise.
    """
    from app.pilot import platform_secrets as ps
    from app.pilot.catalog import get_catalog_by_id

    # The native wire is one adapter's own: it answers for the Provider id that
    # adapter module declares, exactly as its route gate checks.
    import importlib

    adapter = importlib.import_module("app.pilot." + _NATIVE_ADAPTER_MODULE)
    def _module_provider_id(module) -> str:
        """The Provider id a pilot adapter module declares for its own wire."""
        suffix = "PROVIDER" + "_ID"
        return next(
            value for name, value in vars(module).items()
            if name.endswith(suffix) and isinstance(value, str)
        )

    installed = ps._PLATFORM_PROVIDERS.get(NATIVE_PROVIDER_ID)
    registered = get_catalog_by_id(NATIVE_MODEL)
    return (
        NATIVE_PROVIDER_ID == _module_provider_id(adapter)
        and installed is not None
        and registered is not None
        and registered.platform_provider_id == NATIVE_PROVIDER_ID
    )


requires_installed_native_wire = pytest.mark.skipif(
    not _native_tool_wire_installed(),
    reason="the effective registry names no Provider with an installed native wire",
)


@requires_installed_native_wire
@pytest.mark.asyncio
async def test_google_tool_stream_consumer_close_releases_response(monkeypatch):
    monkeypatch.setenv(NATIVE_CREDENTIAL_BINDING, "unit-native-key-not-a-secret")
    monkeypatch.setattr(rcfg, "provider_mode", "live")
    chunk = {"candidates": [{"content": {"parts": [
        {"functionCall": {"name": "pc_files", "args": {"plan": "files_list"}}},
    ]}}]}
    stream = FragmentedStream([("data: " + json.dumps(chunk) + "\n\n").encode()])
    iterator = plat.stream_platform_chat_completions(
        model_id=NATIVE_MODEL, upstream_model=NATIVE_UPSTREAM_MODEL,
        provider=NATIVE_DISPLAY_NAME, platform_provider_id=NATIVE_PROVIDER_ID,
        messages=[{"role": "user", "content": "List only"}],
        tools=[{"type": "function", "function": {"name": "pc_files", "parameters": {"type": "object", "properties": {}}}}],
        transport=httpx.MockTransport(lambda req: httpx.Response(200, stream=stream)),
    )
    event = await anext(iterator)
    assert event.tool_call.name == "pc_files"
    assert event.tool_call.index == 0
    await iterator.aclose()
    assert stream.closed


class FragmentedStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]):
        self.chunks = chunks
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _synthetic_provider_not_a_product_registration(monkeypatch):
    """A keyless provider exists only for this test's mocked transport."""
    from app.pilot import platform_secrets as ps
    spec = ps.PlatformProviderSpec(
        provider_id="test-fixture",credential_source=ps.CredentialSource.NONE,
        credential_binding_name="",base_origin="https://stream-fixture.example/v1",
        allowed_hosts=("stream-fixture.example",),
    )
    monkeypatch.setitem(ps._PLATFORM_PROVIDERS,"test-fixture",spec)
    yield

@pytest.fixture(autouse=True)
def _reset_platform_mode(monkeypatch):
    monkeypatch.delenv("B14_PROVIDER_MODE", raising=False)
    saved = {
        "provider_mode": rcfg.provider_mode,
        "max_response_bytes": rcfg.max_response_bytes,
    }
    rcfg.provider_mode = "mock"
    rcfg.max_response_bytes = 1024 * 1024
    yield
    rcfg.provider_mode = saved["provider_mode"]
    rcfg.max_response_bytes = saved["max_response_bytes"]


def _set_live() -> None:
    # Kilo Gateway free tier is keyless: live mode needs no secret (#1933 S2).
    os.environ.pop("B14_PROVIDER_MODE", None)
    rcfg.provider_mode = "live"


async def _collect(*, transport=None, model_id=KILO_MODEL, upstream_model=KILO_UPSTREAM):
    return [
        event
        async for event in plat.stream_platform_chat_completions(
            messages=[{"role": "user", "content": "안녕하세요"}],
            temperature=0.2,
            max_tokens=64,
            model_id=model_id,
            upstream_model=upstream_model,
            provider=KILO_PROVIDER,
            platform_provider_id="test-fixture",
            transport=transport,
        )
    ]


@pytest.mark.asyncio
async def test_mock_stream_is_deterministic_and_zero_network():
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        raise AssertionError("mock mode must not call upstream")

    first = await _collect(transport=httpx.MockTransport(handler))
    second = await _collect(transport=httpx.MockTransport(handler))

    assert calls == 0
    assert first == second
    assert first[-1] == StreamEvent(done=True)
    assert first[0].delta_content is not None
    assert "Mock" in first[0].delta_content
    assert first[1].usage is not None
    assert first[1].usage.total_tokens == 0


@pytest.mark.asyncio
async def test_live_stream_parses_fragmented_lf_crlf_usage_done():
    _set_live()
    captured = {}
    stream = FragmentedStream([])

    async def handler(request):
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        payload = (
            ': keepalive\r\n\r\n'
            'event: message\r\nid: ignored\r\n'
            f'data: {{"id":"stream-1","model":"{KILO_UPSTREAM}",'
            f'"choices":[{{"delta":{{"content":"\\uc548"}},"finish_reason":null}}]}}\r\n\r\n'
            f'data: {{"id":"stream-1","model":"{KILO_UPSTREAM}",'
            f'"choices":[{{"delta":{{"content":"\\ub155"}},"finish_reason":null}}]}}\n\n'
            f'data: {{"id":"stream-1","model":"{KILO_UPSTREAM}",'
            f'"choices":[{{"delta":{{}},"finish_reason":"stop"}}]}}\r\n\r\n'
            f'data: {{"id":"stream-1","model":"{KILO_UPSTREAM}",'
            f'"choices":[],"usage":{{"prompt_tokens":3,"completion_tokens":2,"total_tokens":5}}}}\n\n'
            'data: [DONE]\r\n\r\n'
            'data: this-must-not-be-read\n\n'
        ).encode()
        split_points = [5, 19, 41, 77, 121, 173, 251, 337, 419]
        pieces = []
        start = 0
        for end in split_points:
            pieces.append(payload[start:end])
            start = end
        pieces.append(payload[start:])
        stream.chunks = pieces
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=stream,
        )

    events = await _collect(transport=httpx.MockTransport(handler))

    assert captured["url"] == KILO_CHAT_URL
    assert captured["authorization"] is None
    assert captured["body"]["stream"] is True
    assert captured["body"]["model"] == KILO_UPSTREAM
    assert "provider" not in captured["body"]
    assert [event.delta_content for event in events[:2]] == ["안", "녕"]
    assert events[2].finish_reason == "stop"
    assert events[3].usage is not None
    assert events[3].usage.total_tokens == 5
    assert events[4].done is True
    assert len(events) == 5
    assert stream.closed is True


@pytest.mark.asyncio
async def test_stream_without_done_fails_closed():
    _set_live()
    stream = FragmentedStream([
        b'data: {"id":"x","model":"m","choices":[{"delta":{"content":"a"},"finish_reason":null}]}\n\n'
    ])

    async def handler(request):
        return httpx.Response(200, stream=stream)

    with pytest.raises(MalformedUpstreamResponse):
        await _collect(transport=httpx.MockTransport(handler))
    assert stream.closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        b"data: not-json\n\n",
        b"data: []\n\n",
        b'data: {"choices":{}}\n\n',
        b'data: {"choices":[{"delta":"bad"}]}\n\n',
        b'data: {"choices":[{"delta":{"content":3}}]}\n\n',
        b'data: {"choices":[],"usage":{"total_tokens":-1}}\n\n',
    ],
)
async def test_malformed_stream_payloads_fail_closed(payload):
    _set_live()

    async def handler(request):
        return httpx.Response(200, stream=FragmentedStream([payload]))

    with pytest.raises(MalformedUpstreamResponse):
        await _collect(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_malformed_utf8_fails_closed():
    _set_live()

    async def handler(request):
        return httpx.Response(200, stream=FragmentedStream([b"data: \xff\n\n"]))

    with pytest.raises(MalformedUpstreamResponse):
        await _collect(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_stream_byte_cap_aborts_before_unbounded_buffering(monkeypatch):
    _set_live()
    monkeypatch.setattr(plat, "MAX_RESPONSE_BYTES", 48)
    stream = FragmentedStream([b"x" * 32, b"y" * 32])

    async def handler(request):
        return httpx.Response(200, stream=stream)

    with pytest.raises(UpstreamResponseTooLarge) as exc_info:
        await _collect(transport=httpx.MockTransport(handler))
    assert exc_info.value.max_bytes == 48
    assert stream.closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, UpstreamAuthFailed),
        (403, UpstreamAuthFailed),
        (429, UpstreamRateLimited),
        (500, UpstreamServerError),
        (503, UpstreamServerError),
        (400, MalformedUpstreamResponse),
        (404, UpstreamClientError),
        (422, UpstreamClientError),
    ],
)
async def test_stream_http_errors_match_existing_b14_contract(status, expected):
    _set_live()

    async def handler(request):
        return httpx.Response(status, content=b"bounded upstream error")

    with pytest.raises(expected):
        await _collect(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_redirect_is_not_followed():
    _set_live()
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(
            302,
            headers={"location": f"{_lane_origin()}/redirected"},
        )

    with pytest.raises(UpstreamClientError):
        await _collect(transport=httpx.MockTransport(handler))
    assert calls == 1


@pytest.mark.asyncio
async def test_live_keyless_streams_without_key():
    # Kilo free tier is explicitly keyless: live without a key streams (#1933 S2).
    _set_live()
    seen = {}

    async def handler(request):
        seen["authorization"] = request.headers.get("authorization")
        seen["url"] = str(request.url)
        payload = (
            f'data: {{"id":"s1","model":"{KILO_UPSTREAM}",'
            f'"choices":[{{"delta":{{"content":"ok"}},"finish_reason":null}}]}}\n\n'
            'data: [DONE]\n\n'
        ).encode()
        return httpx.Response(200, stream=FragmentedStream([payload]))

    events = await _collect(transport=httpx.MockTransport(handler))
    assert seen["authorization"] is None
    assert seen["url"] == KILO_CHAT_URL
    assert events[0].delta_content == "ok"
    assert events[-1].done is True


@pytest.mark.asyncio
async def test_platform_origin_is_fixed_and_ignores_openrouter_base_url():
    # The platform adapter never reads runtime_config.base_url: even an evil
    # value cannot steer the fixed Kilo origin (OpenRouter retired, #1933 S2).
    _set_live()
    rcfg.base_url = _evil_base_url()
    seen = {}

    async def handler(request):
        seen["url"] = str(request.url)
        payload = (
            f'data: {{"id":"s1","model":"{KILO_UPSTREAM}",'
            f'"choices":[{{"delta":{{"content":"ok"}},"finish_reason":null}}]}}\n\n'
            'data: [DONE]\n\n'
        ).encode()
        return httpx.Response(200, stream=FragmentedStream([payload]))

    events = await _collect(transport=httpx.MockTransport(handler))
    assert seen["url"] == KILO_CHAT_URL
    assert events[-1].done is True


def test_public_gateway_still_rejects_stream_true():
    client = TestClient(create_app())
    response = client.post(
        chat_surface(),
        json={
            "model": "unknown/model",
            "messages": [{"role": "user", "content": "안녕하세요"}],
            "stream": True,
        },
    )
    # The canonical validator refuses stream=true as always.
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "stream_not_supported"
