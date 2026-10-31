"""Answer round trip: Chat turn → Engine host → synthetic B14 → Chat.

The Engine reaches B14 through its Service Binding transport, which on this host
is ``LocalB14Binding`` forwarding to ``PADIEM_ENGINE_LOCAL_B14_ORIGIN``. The
synthetic B14 below answers in B14's own wire format — ``chat.completion.chunk``
frames carrying ``business14`` route metadata and a terminating ``[DONE]`` — so a
successful run produces a real answer instead of a provider-shape guess.

Replay is deliberately *not* expected: Chat's bridge sends no Engine idempotency
key — the Worker composition and this host share one ``build_engine_request``,
which fills only ``trace_id`` — so a second turn is a new run and B14 is called
again. The cutover keeps host behaviour identical to Production, and the second
turn below records that fact instead of inventing a key the deployed Chat does not
send.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from _host_b14_proof import TEST_SECRET, reject_invalid_proof

REPO = Path(__file__).resolve().parents[3]
ENGINE_DIR = REPO / "apps" / "padiem-ai-engine"
CALLER_ID = "b62-chat"
CREDENTIAL = "s" * 40
ANSWER = "합성 답변"


def _child_path() -> str:
    return os.pathsep.join(
        str(path)
        for path in (
            ENGINE_DIR,
            ENGINE_DIR / "clients" / "python",
            REPO / "packages" / "padiem-ai-core",
            REPO / "packages" / "padiem-control-plane",
            REPO / "apps" / "korean-ai-code-agent" / "src",
        )
    )


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _B14:
    """B14's documented wire format, with a fixed two-chunk answer."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    @staticmethod
    def _chunk(content: str | None, finish: str | None = None) -> bytes:
        payload = {
            "id": "chatcmpl-host",
            "model": "host-model",
            "object": "chat.completion.chunk",
            "business14": {
                "route_mode": "synthetic",
                "request_id": "req-host",
                "selected_model": "host-model",
            },
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": content} if content else {},
                    "finish_reason": finish,
                }
            ],
            "usage": (
                {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9}
                if finish
                else {}
            ),
        }
        return f"data: {json.dumps(payload)}\n\n".encode()

    async def __call__(self, scope, receive, send) -> None:
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body"):
                break
        if await reject_invalid_proof(scope, body, send):
            return
        self.calls.append(scope["path"])
        streaming = scope["path"].endswith("stream-preview")
        if streaming:
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"text/event-stream")],
                }
            )
            for piece in ("합성 ", "답변"):
                await send(
                    {
                        "type": "http.response.body",
                        "body": self._chunk(piece),
                        "more_body": True,
                    }
                )
            await send(
                {
                    "type": "http.response.body",
                    "body": self._chunk(None, finish="stop"),
                    "more_body": True,
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": b"data: [DONE]\n\n",
                    "more_body": True,
                }
            )
            await send({"type": "http.response.body", "body": b"", "more_body": False})
            return
        payload = {
            "id": "chatcmpl-host",
            "model": "host-model",
            "object": "chat.completion",
            "business14": {
                "route_mode": "synthetic",
                "request_id": "req-host",
                "selected_model": "host-model",
            },
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": ANSWER},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9},
        }
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send(
            {"type": "http.response.body", "body": json.dumps(payload).encode()}
        )


def _serve(app, port: int) -> uvicorn.Server:
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            access_log=False,
            lifespan="off",
        )
    )
    threading.Thread(target=server.run, daemon=True).start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("synthetic B14 did not start")
        time.sleep(0.02)
    return server


def _wait_tcp(port: int, seconds: float = 40.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.1)
    return False


@pytest.fixture(scope="module")
def engine_host(tmp_path_factory):
    b14 = _B14()
    b14_port = _free_port()
    _serve(b14, b14_port)
    engine_port = _free_port()
    env = dict(os.environ)
    env.pop("B14_SECRET_DIR", None)
    env.update(
        {
            "PADIEM_B14_SERVICE_PROOF_SECRET": TEST_SECRET,
            "PADIEM_ENGINE_CPYTHON_HOST": "1",
            "P01_HOST": "127.0.0.1",
            "P01_PORT": str(engine_port),
            "PADIEM_ENGINE_LOCAL_B14_ORIGIN": f"http://127.0.0.1:{b14_port}",
            "PADIEM_ENGINE_LOCAL_DB": str(
                tmp_path_factory.mktemp("engine-answer") / "engine.sqlite3"
            ),
            "PADIEM_ENGINE_CALLER_ID": CALLER_ID,
            "PADIEM_ENGINE_CALLER_SECRET": CREDENTIAL,
            "PADIEM_ENGINE_ALLOWED_APPS": "padiem-chat",
            "PYTHONPATH": _child_path(),
        }
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "asgi:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(engine_port),
            "--log-level",
            "warning",
        ],
        cwd=str(ENGINE_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        assert _wait_tcp(engine_port), "engine host app did not answer on its port"
        yield {"origin": f"http://127.0.0.1:{engine_port}", "b14": b14}
    finally:
        process.terminate()
        try:
            process.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()


def _bridge(origin: str):
    from app.local_engine_transport import LocalEngineHttpTransport
    from app.local_p01_engine import CHAT_ENGINE_APP_ID
    from app.orchestration_bridge import B62EngineOrchestrationBridge
    from padiem_ai_engine_client import PadiemAiEngineClient

    client = PadiemAiEngineClient(
        transport=LocalEngineHttpTransport(origin),
        app_id=CHAT_ENGINE_APP_ID,
        caller_id=CALLER_ID,
        credential=CREDENTIAL,
    )

    class _Store:
        async def save_pause(self, **kwargs) -> None:
            raise AssertionError("no pause expected")

    return B62EngineOrchestrationBridge(client=client, store=_Store())


def _turn(bridge, *, session: str = "c1", conversation: str = "c1"):
    skill = type(
        "Skill",
        (),
        {
            "id": "chat",
            "title": "Padiem Chat",
            "description": "answer round trip",
            "system_instruction": "answer",
            "task_type": "general",
            "optimize_for": "balanced",
            "max_tokens": None,
        },
    )()
    return bridge.start_stream(
        user_id="u1",
        messages=[{"role": "user", "content": "안녕"}],
        skill=skill,
        model_id="host-model",
        user_text="안녕",
        conversation_id=conversation,
        pc_tools=None,
        subject_id=None,
        session_id=session,
    )


async def _collect(stream) -> list[dict]:
    from app.orchestration_bridge import B62OrchestrationError

    records: list[dict] = []
    try:
        async for record in stream:
            records.append(record)
    except B62OrchestrationError:
        pass
    return records


def _kinds(records: list[dict]) -> list[str]:
    return [str(record["event"]["kind"]) for record in records if "event" in record]


async def test_a_turn_reaches_the_answer_and_a_second_turn_runs_again(
    engine_host,
) -> None:
    """Chat → Engine → B14 answer, then the next turn is a new run (no key sent)."""

    b14 = engine_host["b14"]
    bridge = _bridge(engine_host["origin"])

    first = await _collect(_turn(bridge))
    kinds = _kinds(first)
    assert kinds[:2] == ["run_started", "context_prepared"]
    assert kinds[-1] == "run_completed"
    answers = [
        record["result"].answer for record in first if "result" in record
    ]
    assert answers and answers[-1] == ANSWER
    calls_after_first = len(b14.calls)
    assert calls_after_first == 1

    second = await _collect(_turn(bridge))
    replay_answers = [
        record["result"].answer for record in second if "result" in record
    ]
    assert replay_answers and replay_answers[-1] == ANSWER
    # No idempotency key travels, so the Engine starts a new run and B14 answers
    # a second time — the same thing the deployed Worker path does.
    assert len(b14.calls) == calls_after_first + 1


async def test_a_turn_always_ends_in_a_bounded_state(engine_host) -> None:
    """Whatever the Engine answers, the turn terminates instead of hanging."""

    import asyncio

    bridge = _bridge(engine_host["origin"])
    records = await asyncio.wait_for(_collect(_turn(bridge, session="c9", conversation="c9")), 60)
    kinds = _kinds(records)
    assert kinds[0] == "run_started"
    assert kinds[-1] in {"run_completed", "run_failed"}
    if kinds[-1] == "run_failed":
        terminal = [record for record in records if "event" in record][-1]
        assert terminal["event"]["metadata"]["error_code"] in {
            "upstream_unavailable",
            "upstream_timeout",
            "upstream_rate_limited",
        }
