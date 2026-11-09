"""Native tool calling on the Business 14 OpenCode Go Responses wire (#4727).

The tool channel (#5536) already carried a declaration to the generic
OpenAI-compatible lane and to Google's native lane. The paid Muse route refused
one: the adapter dropped the declaration, the completed envelope could not read
a call back, and the streaming lane answered without the tool the caller had
asked for.

Every outbound request here uses a synthetic MockTransport, so the suite proves
the wire shape without spending a credential or reaching a provider.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.pilot import opencode_go_wire as go
from app.pilot.errors import (
    InvalidRequest,
    MalformedUpstreamResponse,
    StreamNotSupported,
    ToolsNotSupported,
)
from app.pilot.tool_channel import GO_PROVIDER_ID, TOOL_CAPABILITY, require_stream_tool_wire
from app.pilot.model_registry_file import read_registry


def _registered_rows(provider_id: str | None = None) -> list[dict]:
    rows = list(read_registry()["models"])
    if provider_id is not None:
        rows = [row for row in rows if row["provider_id"] == provider_id]
    return rows


def _go_tool_row() -> dict:
    """The Go route the adapter carries tools for: the registry's tool row.

    The Go provider serves several routes on its own wire; only the row that
    declares the tool capability may carry a call, so that declaration is the
    selector rather than a written model id.
    """
    candidates = [
        row for row in _registered_rows(GO_PROVIDER_ID)
        if TOOL_CAPABILITY in row["capabilities"]
    ]
    assert len(candidates) == 1
    return candidates[0]


def _go_sibling_without_tools(row: dict) -> dict:
    """The Go row on the same wire family that declares no tool capability."""
    # The wire family is the adapter's own table, so a sibling on the same wire
    # is one whose upstream name the adapter routes; capability, not wire
    # family, is the gate this row proves.
    from app.pilot.opencode_go_wire import _WIRE

    candidates = [
        other for other in _registered_rows(GO_PROVIDER_ID)
        if other["id"] != row["id"]
        and TOOL_CAPABILITY not in other["capabilities"]
        and _WIRE.get(other["upstream_model"]) == _WIRE.get(row["upstream_model"])
    ]
    assert candidates
    return candidates[0]


def _go_sibling_on_another_wire(row: dict) -> dict:
    """A Go route the adapter serves on a wire other than the tool-carrying one."""
    from app.pilot.opencode_go_wire import _WIRE

    tool_wire = _WIRE.get(row["upstream_model"])
    candidates = [
        other for other in _registered_rows(GO_PROVIDER_ID)
        if other["id"] != row["id"]
        and _WIRE.get(other["upstream_model"]) != tool_wire
    ]
    assert candidates
    return candidates[0]


#: The provider whose native lane carries tools on a capability of its own and
#: is not the Go adapter (the Go adapter is gated by its own wire table).
NATIVE_PROVIDER = next(
    pid for pid in read_registry()["providers"]
    if pid != GO_PROVIDER_ID
    and any(
        row["provider_id"] == pid and TOOL_CAPABILITY in row["capabilities"]
        for row in _registered_rows()
    )
)


GO_ROW = _go_tool_row()
MUSE = GO_ROW["id"]
MUSE_UPSTREAM = GO_ROW["upstream_model"]
#: The sibling Muse model on the same wire. The registry declares no tool
#: capability for it, so it is the in-repo proof that capability, not wire
#: family, opens the route.
MUSE_UNTAGGED = _go_sibling_without_tools(GO_ROW)["id"]
MUSE_UNTAGGED_UPSTREAM = _go_sibling_without_tools(GO_ROW)["upstream_model"]
LONGCAT = _go_sibling_on_another_wire(GO_ROW)["id"]
LONGCAT_UPSTREAM = _go_sibling_on_another_wire(GO_ROW)["upstream_model"]

SESSION = "chat_0123456789abcdef0123456789abcdef"
TURNS = [{"role": "user", "content": "날씨를 알려줘"}]

TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Look up one city.",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
}


TOOL_TWO = {
    "type": "function",
    "function": {
        "name": "get_time",
        "description": "Read one clock.",
        "parameters": {"type": "object", "properties": {"zone": {"type": "string"}}},
    },
}


def _frame(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _call_item(
    item_id: str = "fc_1",
    arguments: str | dict = '{"city":"Seoul"}',
    *,
    name: str = "get_weather",
    call_id: str = "call_1",
) -> dict:
    return {
        "id": item_id,
        "type": "function_call",
        "call_id": call_id,
        "name": name,
        "arguments": arguments,
    }


def _completed(*items: dict) -> dict:
    return {
        "type": "response.completed",
        "response": {
            "status": "completed", "model": MUSE_UPSTREAM, "output": list(items),
        },
    }


@pytest.fixture(autouse=True)
def _synthetic_credentials(monkeypatch):
    """No test may read a secret or run the owner authorization gate."""
    monkeypatch.setattr(go, "_authorization_gate", lambda *_: None)

    async def _auth(headers, wire):
        return {**headers, "Authorization": "Bearer synthetic-test-credential"}

    monkeypatch.setattr(go, "_authenticated_headers", _auth)


# ---------------------------------------------------------------------------
# The declaration reaches the provider in the shape that transport documents
# ---------------------------------------------------------------------------


def test_a_declared_tool_travels_flat_on_the_responses_wire() -> None:
    _wire, body, _headers = go.prepare_go_request(
        model_id=MUSE, upstream_model=MUSE_UPSTREAM, messages=TURNS,
        session_id=SESSION, tools=[TOOL],
    )

    # The Responses transport declares a function tool flat; the nested
    # chat-completions shape would be a different contract.
    assert body["tools"] == [{
        "type": "function",
        "name": "get_weather",
        "parameters": TOOL["function"]["parameters"],
        "description": "Look up one city.",
    }]
    assert "tool_choice" not in body


# ---------------------------------------------------------------------------
# The choice binds what the answer may contain, not only what is sent
# ---------------------------------------------------------------------------


def test_a_call_is_refused_when_the_caller_forbade_tools() -> None:
    payload = {"model": MUSE_UPSTREAM, "status": "completed", "output": [_call_item()]}

    _wire, body, _h = go.prepare_go_request(
        model_id=MUSE, upstream_model=MUSE_UPSTREAM, messages=TURNS,
        session_id=SESSION, tools=[TOOL], tool_choice="none",
    )
    assert body["tool_choice"] == "none"
    with pytest.raises(MalformedUpstreamResponse):
        go._normalize_go_answer(
            "responses", MUSE_UPSTREAM, payload, latency_ms=5, response_bytes=40,
            declared_names=go._permitted_tool_names(body),
        )


@pytest.mark.asyncio
async def test_a_streamed_call_is_refused_when_the_caller_forbade_tools() -> None:
    item = _call_item()
    sse = (
        _frame("response.output_item.done", {"type": "response.output_item.done", "item": item})
        + _frame("response.completed", _completed())
    )

    with pytest.raises(MalformedUpstreamResponse):
        [
            event async for event in go.stream_go_model(
                model_id=MUSE, upstream_model=MUSE_UPSTREAM, messages=TURNS,
                session_id=SESSION, tools=[TOOL], tool_choice="none",
                transport=httpx.MockTransport(lambda request: httpx.Response(
                    200, content=sse.encode(),
                    headers={"Content-Type": "text/event-stream"},
                )),
            )
        ]


def test_a_named_choice_narrows_the_answer_to_that_one_tool() -> None:
    _wire, body, _h = go.prepare_go_request(
        model_id=MUSE, upstream_model=MUSE_UPSTREAM, messages=TURNS,
        session_id=SESSION, tools=[TOOL, TOOL_TWO],
        tool_choice={"type": "function", "function": {"name": "get_weather"}},
    )

    assert go._permitted_tool_names(body) == frozenset({"get_weather"})
    payload = {
        "model": MUSE_UPSTREAM, "status": "completed",
        # get_time was declared, so it is a legal name; it just was not the one
        # this caller asked for, and an unrequested call is not an answer.
        "output": [_call_item(name="get_time", arguments="{}")],
    }
    with pytest.raises(MalformedUpstreamResponse):
        go._normalize_go_answer(
            "responses", MUSE_UPSTREAM, payload, latency_ms=5, response_bytes=40,
            declared_names=go._permitted_tool_names(body),
        )


# ---------------------------------------------------------------------------
# Several calls in one turn, and the bound on them
# ---------------------------------------------------------------------------


def test_several_calls_in_one_turn_are_all_relayed() -> None:
    payload = {
        "model": MUSE_UPSTREAM, "status": "completed",
        "output": [
            _call_item("fc_1", '{"city":"Seoul"}'),
            _call_item("fc_2", '{"zone":"Asia/Seoul"}', name="get_time", call_id="call_2"),
        ],
    }

    answer = go._normalize_go_answer(
        "responses", MUSE_UPSTREAM, payload, latency_ms=5, response_bytes=80,
        declared_names=frozenset({"get_weather", "get_time"}),
    )

    calls = answer["choices"][0]["message"]["tool_calls"]
    assert [c["id"] for c in calls] == ["call_1", "call_2"]
    assert [c["function"]["name"] for c in calls] == ["get_weather", "get_time"]


@pytest.mark.asyncio
async def test_several_streamed_calls_number_in_order_and_round_trip() -> None:
    items = [
        _call_item("fc_1", '{"city":"Seoul"}'),
        _call_item("fc_2", '{"zone":"Asia/Seoul"}', name="get_time", call_id="call_2"),
    ]
    sse = "".join(
        _frame("response.output_item.done", {"type": "response.output_item.done", "item": item})
        for item in items
    ) + _frame("response.completed", _completed(*items))

    events = [
        event async for event in go.stream_go_model(
            model_id=MUSE, upstream_model=MUSE_UPSTREAM, messages=TURNS,
            session_id=SESSION, tools=[TOOL, TOOL_TWO],
            transport=httpx.MockTransport(lambda request: httpx.Response(
                200, content=sse.encode(),
                headers={"Content-Type": "text/event-stream"},
            )),
        )
    ]

    calls = [e.tool_call for e in events if e.tool_call is not None]
    assert [c.index for c in calls] == [0, 1]
    assert [c.name for c in calls] == ["get_weather", "get_time"]

    # The caller ran both tools; the follow-up turn must replay both calls and
    # both results, or the model cannot produce its final answer.
    conversation = [
        {"role": "user", "content": "날씨와 시각을 알려줘"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "get_weather", "arguments": '{"city":"Seoul"}'}},
            {"id": "call_2", "type": "function", "function": {"name": "get_time", "arguments": '{"zone":"Asia/Seoul"}'}},
        ]},
        {"role": "tool", "tool_call_id": "call_1", "content": "21C"},
        {"role": "tool", "tool_call_id": "call_2", "content": "14:00"},
    ]
    _wire, followup, _h = go.prepare_go_request(
        model_id=MUSE, upstream_model=MUSE_UPSTREAM, messages=conversation,
        session_id=SESSION, tools=[TOOL, TOOL_TWO],
    )

    assert [item.get("type") for item in followup["input"]] == [
        None, "function_call", "function_call", "function_call_output", "function_call_output",
    ]


@pytest.mark.asyncio
async def test_the_streamed_call_count_stays_inside_the_bound() -> None:
    from app.pilot.tool_channel import MAX_TOOL_CALLS

    items = [
        _call_item(f"fc_{i}", '{"city":"Seoul"}', call_id=f"call_{i}")
        for i in range(MAX_TOOL_CALLS + 1)
    ]
    sse = "".join(
        _frame("response.output_item.done", {"type": "response.output_item.done", "item": item})
        for item in items
    ) + _frame("response.completed", _completed(*items))

    with pytest.raises(MalformedUpstreamResponse):
        [
            event async for event in go.stream_go_model(
                model_id=MUSE, upstream_model=MUSE_UPSTREAM, messages=TURNS,
                session_id=SESSION, tools=[TOOL],
                transport=httpx.MockTransport(lambda request: httpx.Response(
                    200, content=sse.encode(),
                    headers={"Content-Type": "text/event-stream"},
                )),
            )
        ]


@pytest.mark.parametrize("choice,expected", [
    ("required", "required"),
    (
        {"type": "function", "function": {"name": "get_weather"}},
        {"type": "function", "name": "get_weather"},
    ),
])
def test_the_tool_choice_keeps_this_transports_own_shape(choice, expected) -> None:
    _wire, body, _headers = go.prepare_go_request(
        model_id=MUSE, upstream_model=MUSE_UPSTREAM, messages=TURNS,
        session_id=SESSION, tools=[TOOL], tool_choice=choice,
    )

    assert body["tool_choice"] == expected


def test_a_tool_free_request_keeps_its_exact_previous_body() -> None:
    _wire, with_tools, _ = go.prepare_go_request(
        model_id=MUSE, upstream_model=MUSE_UPSTREAM, messages=TURNS, session_id=SESSION,
    )

    assert "tools" not in with_tools and "tool_choice" not in with_tools


def test_a_model_without_the_declared_capability_is_refused_before_the_request() -> None:
    with pytest.raises(ToolsNotSupported):
        go.prepare_go_request(
            model_id=MUSE_UNTAGGED, upstream_model=MUSE_UNTAGGED_UPSTREAM,
            messages=TURNS, session_id=SESSION, tools=[TOOL],
        )


def test_a_wire_that_carries_no_tool_declaration_is_refused(monkeypatch) -> None:
    """The capability is one gate and the wire is another; neither implies the other.

    ``longcat`` is not tool-capable in the registry either, so the wire guard is
    proven with the capability check opened, not by picking a model that happens
    to satisfy both.
    """
    monkeypatch.setattr(go, "require_tool_capability", lambda _model_id: None)

    with pytest.raises(InvalidRequest, match="Unverified tool declaration"):
        go.prepare_go_request(
            model_id=LONGCAT, upstream_model=LONGCAT_UPSTREAM,
            messages=TURNS, session_id=SESSION, tools=[TOOL],
        )


# ---------------------------------------------------------------------------
# The conversation round trip: a call and its result become input items
# ---------------------------------------------------------------------------


def test_the_assistant_call_and_its_result_project_onto_responses_items() -> None:
    conversation = [
        {"role": "user", "content": "날씨를 알려줘"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {"name": "get_weather", "arguments": '{"city":"Seoul"}'},
            }],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "21C 맑음"},
    ]

    _wire, body, _headers = go.prepare_go_request(
        model_id=MUSE, upstream_model=MUSE_UPSTREAM, messages=conversation,
        session_id=SESSION, tools=[TOOL],
    )

    assert body["input"] == [
        {"role": "user", "content": "날씨를 알려줘"},
        {
            "type": "function_call", "call_id": "call_1", "name": "get_weather",
            "arguments": '{"city":"Seoul"}',
        },
        {"type": "function_call_output", "call_id": "call_1", "output": "21C 맑음"},
    ]


@pytest.mark.parametrize("mutation", [
    ({
        "role": "assistant", "content": None,
        "tool_calls": [{
            "id": "call_9", "type": "function",
            "function": {"name": "delete_file", "arguments": "{}"},
        }],
    }, "names an undeclared tool"),
    ({"role": "tool", "tool_call_id": "call_missing", "content": "ok"},
     "answers an unknown call"),
    (
        {
            "role": "assistant", "content": None,
            "tool_calls": [{
                "id": "call_1", "type": "function",
                "function": {"name": "get_weather", "arguments": "{}"},
            }],
        }, "duplicates a tool call id",
    ),
])
def test_a_turn_that_does_not_match_this_declaration_is_refused(mutation) -> None:
    turn, _reason = mutation
    conversation = [
        {"role": "user", "content": "날씨를 알려줘"},
        {
            "role": "assistant", "content": None,
            "tool_calls": [{
                "id": "call_1", "type": "function",
                "function": {"name": "get_weather", "arguments": "{}"},
            }],
        },
        turn,
    ]

    with pytest.raises(InvalidRequest):
        go.prepare_go_request(
            model_id=MUSE, upstream_model=MUSE_UPSTREAM, messages=conversation,
            session_id=SESSION, tools=[TOOL],
        )


# ---------------------------------------------------------------------------
# The completed answer
# ---------------------------------------------------------------------------


def test_a_completed_function_call_is_relayed_as_a_tool_call() -> None:
    payload = {
        "model": MUSE_UPSTREAM, "status": "completed",
        "output": [_call_item()],
        "usage": {"input_tokens": 9, "output_tokens": 3},
    }

    answer = go._normalize_go_answer(
        "responses", MUSE_UPSTREAM, payload, latency_ms=5, response_bytes=40,
        declared_names=frozenset({"get_weather"}),
    )

    message = answer["choices"][0]["message"]
    assert answer["choices"][0]["finish_reason"] == "tool_calls"
    # A call is the answer of this turn, so the absence of prose is not an
    # empty answer and the caller is given the structured call itself.
    assert message["content"] is None
    assert message["tool_calls"] == [{
        "id": "call_1", "type": "function",
        "function": {"name": "get_weather", "arguments": '{"city":"Seoul"}'},
    }]


def test_a_call_for_a_tool_the_request_never_declared_is_refused() -> None:
    payload = {
        "model": MUSE_UPSTREAM, "status": "completed",
        "output": [_call_item(item_id="fc_1", arguments="{}") | {"name": "drop_everything"}],
        "usage": {},
    }

    with pytest.raises(MalformedUpstreamResponse):
        go._normalize_go_answer(
            "responses", MUSE_UPSTREAM, payload, latency_ms=5, response_bytes=40,
            declared_names=frozenset({"get_weather"}),
        )


def test_a_call_with_no_declaration_at_all_is_refused() -> None:
    payload = {
        "model": MUSE_UPSTREAM, "status": "completed", "output": [_call_item()],
        "usage": {},
    }

    with pytest.raises(MalformedUpstreamResponse):
        go._normalize_go_answer(
            "responses", MUSE_UPSTREAM, payload, latency_ms=5, response_bytes=40,
        )


@pytest.mark.asyncio
async def test_the_completed_call_travels_end_to_end_over_the_synthetic_wire() -> None:
    seen = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={
            "model": MUSE_UPSTREAM, "status": "completed", "output": [_call_item()],
            "usage": {"input_tokens": 9, "output_tokens": 3},
        })

    answer = await go.call_go_model(
        model_id=MUSE, upstream_model=MUSE_UPSTREAM, messages=TURNS,
        session_id=SESSION, tools=[TOOL], transport=httpx.MockTransport(handle),
    )

    assert seen[0]["tools"][0]["name"] == "get_weather"
    assert answer["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "get_weather"


# ---------------------------------------------------------------------------
# The streamed answer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_streamed_call_is_emitted_once_its_arguments_are_complete() -> None:
    sse = (
        _frame("response.output_item.added", {
            "type": "response.output_item.added",
            "item": {"id": "fc_1", "type": "function_call", "call_id": "call_1",
                     "name": "get_weather", "arguments": ""},
        })
        + _frame("response.function_call_arguments.delta", {
            "type": "response.function_call_arguments.delta", "item_id": "fc_1",
            "delta": '{"city":',
        })
        + _frame("response.function_call_arguments.delta", {
            "type": "response.function_call_arguments.delta", "item_id": "fc_1",
            "delta": '"Seoul"}',
        })
        + _frame("response.output_item.done", {
            "type": "response.output_item.done", "item": _call_item(),
        })
        + _frame("response.completed", {
            "type": "response.completed",
            "response": {
                "status": "completed", "model": MUSE_UPSTREAM, "output": [_call_item()],
                "usage": {"input_tokens": 9, "output_tokens": 3},
            },
        })
    )

    events = [
        event async for event in go.stream_go_model(
            model_id=MUSE, upstream_model=MUSE_UPSTREAM, messages=TURNS,
            session_id=SESSION, tools=[TOOL],
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, content=sse.encode(),
                    headers={"Content-Type": "text/event-stream"},
                )
            ),
        )
    ]

    calls = [event.tool_call for event in events if event.tool_call is not None]
    assert len(calls) == 1
    # The three argument frames describe one call; the caller receives it once,
    # with the arguments reassembled, and never a partial fragment.
    assert calls[0].arguments == '{"city":"Seoul"}'
    assert calls[0].name == "get_weather" and calls[0].index == 0
    assert events[-1].done is True
    assert events[-1].finish_reason == "tool_calls"


@pytest.mark.asyncio
async def test_partial_arguments_never_reach_the_caller() -> None:
    sse = (
        _frame("response.function_call_arguments.delta", {
            "type": "response.function_call_arguments.delta", "item_id": "fc_1",
            "delta": '{"city":',
        })
        + _frame("response.completed", {
            "type": "response.completed",
            "response": {"status": "completed", "model": MUSE_UPSTREAM, "output": []},
        })
    )

    with pytest.raises(MalformedUpstreamResponse):
        [
            event async for event in go.stream_go_model(
                model_id=MUSE, upstream_model=MUSE_UPSTREAM, messages=TURNS,
                session_id=SESSION, tools=[TOOL],
                transport=httpx.MockTransport(lambda request: httpx.Response(
                    200, content=sse.encode(),
                    headers={"Content-Type": "text/event-stream"},
                )),
            )
        ]


@pytest.mark.asyncio
async def test_a_streamed_call_for_an_undeclared_tool_is_refused() -> None:
    item = _call_item() | {"name": "drop_everything"}
    sse = (
        _frame("response.output_item.done", {"type": "response.output_item.done", "item": item})
        + _frame("response.completed", {
            "type": "response.completed",
            "response": {"status": "completed", "model": MUSE_UPSTREAM, "output": [item]},
        })
    )

    with pytest.raises(MalformedUpstreamResponse):
        [
            event async for event in go.stream_go_model(
                model_id=MUSE, upstream_model=MUSE_UPSTREAM, messages=TURNS,
                session_id=SESSION, tools=[TOOL],
                transport=httpx.MockTransport(lambda request: httpx.Response(
                    200, content=sse.encode(),
                    headers={"Content-Type": "text/event-stream"},
                )),
            )
        ]


@pytest.mark.asyncio
async def test_the_completed_envelope_closes_a_call_the_item_frames_left_open() -> None:
    sse = (
        _frame("response.output_item.added", {
            "type": "response.output_item.added", "item": {"id": "fc_1",
                     "type": "function_call", "call_id": "call_1",
                     "name": "get_weather", "arguments": ""},
        })
        + _frame("response.function_call_arguments.done", {
            "type": "response.function_call_arguments.done", "item_id": "fc_1",
            "arguments": '{"city":"Seoul"}',
        })
        + _frame("response.completed", {
            "type": "response.completed",
            "response": {
                "status": "completed", "model": MUSE_UPSTREAM, "output": [_call_item()],
                "usage": {"input_tokens": 9, "output_tokens": 3},
            },
        })
    )

    events = [
        event async for event in go.stream_go_model(
            model_id=MUSE, upstream_model=MUSE_UPSTREAM, messages=TURNS,
            session_id=SESSION, tools=[TOOL],
            transport=httpx.MockTransport(lambda request: httpx.Response(
                200, content=sse.encode(),
                headers={"Content-Type": "text/event-stream"},
            )),
        )
    ]

    assert [e.tool_call for e in events if e.tool_call is not None][0].arguments == '{"city":"Seoul"}'


# ---------------------------------------------------------------------------
# The streaming gate is owned by the adapter that answers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_arguments_a_provider_hands_back_parsed_are_not_dropped() -> None:
    """A closed item may arrive with arguments as an object instead of a string.

    Reading that as "no arguments" would answer the caller with an empty call
    and let it run the tool with the wrong inputs.
    """
    item = _call_item(arguments={"city": "Seoul", "days": 3})
    sse = (
        _frame("response.output_item.done", {"type": "response.output_item.done", "item": item})
        + _frame("response.completed", {
            "type": "response.completed",
            "response": {"status": "completed", "model": MUSE_UPSTREAM, "output": [item]},
        })
    )

    events = [
        event async for event in go.stream_go_model(
            model_id=MUSE, upstream_model=MUSE_UPSTREAM, messages=TURNS,
            session_id=SESSION, tools=[TOOL],
            transport=httpx.MockTransport(lambda request: httpx.Response(
                200, content=sse.encode(),
                headers={"Content-Type": "text/event-stream"},
            )),
        )
    ]

    call = [e.tool_call for e in events if e.tool_call is not None][0]
    assert json.loads(call.arguments) == {"city": "Seoul", "days": 3}


def test_a_completed_call_with_parsed_arguments_is_relayed() -> None:
    payload = {
        "model": MUSE_UPSTREAM, "status": "completed",
        "output": [_call_item(arguments={"city": "Seoul"})], "usage": {},
    }

    answer = go._normalize_go_answer(
        "responses", MUSE_UPSTREAM, payload, latency_ms=5, response_bytes=40,
        declared_names=frozenset({"get_weather"}),
    )

    assert json.loads(
        answer["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
    ) == {"city": "Seoul"}


def test_the_streaming_lane_opens_for_the_route_that_carries_a_tool_call() -> None:
    require_stream_tool_wire(MUSE, GO_PROVIDER_ID)


def _tool_capable_route_without_a_tool_wire() -> tuple[str, str]:
    """A route declaring tools on a provider with no tool-carrying wire.

    The Go adapter carries a tool on its own wire table and the native adapter
    carries one on its own; every other provider answers only on the generic
    compatible lane, so a tool-capable row there must still be refused.
    """
    row = next(
        row for row in _registered_rows()
        if TOOL_CAPABILITY in row["capabilities"]
        and row["provider_id"] not in (GO_PROVIDER_ID, NATIVE_PROVIDER)
    )
    return row["id"], row["provider_id"]


@pytest.mark.parametrize("model_id,provider_id", [
    (MUSE_UNTAGGED, GO_PROVIDER_ID),
    (LONGCAT, GO_PROVIDER_ID),
    _tool_capable_route_without_a_tool_wire(),
])
def test_the_streaming_lane_stays_closed_for_a_route_that_cannot_carry_one(
    model_id, provider_id
) -> None:
    with pytest.raises(StreamNotSupported):
        require_stream_tool_wire(model_id, provider_id)


def _native_tool_rows() -> list[dict]:
    return [
        row for row in _registered_rows(NATIVE_PROVIDER)
        if TOOL_CAPABILITY in row["capabilities"]
    ]


def _native_untagged_row() -> dict:
    """The native-lane route that declares no tool capability."""
    candidates = [
        row for row in _registered_rows(NATIVE_PROVIDER)
        if TOOL_CAPABILITY not in row["capabilities"]
    ]
    assert candidates
    return candidates[0]


def _native_minimal_tool_row() -> dict:
    """The owner-decided route whose capability is exactly chat plus tools."""
    candidates = [
        row for row in _native_tool_rows() if row["capabilities"] == ["chat", TOOL_CAPABILITY]
    ]
    assert len(candidates) == 1
    return candidates[0]


def _native_fully_tagged_tool_row() -> dict:
    """The route whose tool capability rides the full measured feature set."""
    candidates = [
        row for row in _native_tool_rows()
        if row["capabilities"] != ["chat", TOOL_CAPABILITY]
    ]
    assert candidates
    return candidates[0]


def test_a_native_route_without_the_capability_is_refused_by_the_capability() -> None:
    from app.pilot.errors import ToolsNotSupported as _ToolsNotSupported

    # The route the owner did not decide carries no tools; only the
    # owner-decided one does.
    with pytest.raises(_ToolsNotSupported):
        require_stream_tool_wire(_native_untagged_row()["id"], NATIVE_PROVIDER)


def test_the_owner_decided_route_declares_tools() -> None:
    # #6460-5: the capability follows the official function-calling
    # documentation, so the same native wire now opens.
    require_stream_tool_wire(_native_minimal_tool_row()["id"], NATIVE_PROVIDER)


def test_the_tool_capable_native_route_still_streams_through_its_own_wire() -> None:
    # The Go route must not displace the lane that already served tools.
    require_stream_tool_wire(
        _native_fully_tagged_tool_row()["id"], NATIVE_PROVIDER
    )


def test_the_fully_tagged_tool_route_passes_the_native_capability_gates() -> None:
    from app.pilot.tool_channel import model_supports_tools, require_tool_capability

    row = _native_fully_tagged_tool_row()
    assert {TOOL_CAPABILITY, "coding", "image"} <= set(row["capabilities"])
    assert model_supports_tools(row["id"]) is True
    require_tool_capability(row["id"])
    require_stream_tool_wire(row["id"], NATIVE_PROVIDER)
