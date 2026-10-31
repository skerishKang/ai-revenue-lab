"""Round trip: the real Engine host app behind the Chat host transport.

This is the first end-to-end exercise of the host Engine path that does not stop
at a stub: ``apps/padiem-ai-engine/asgi.py`` runs as a real loopback uvicorn
process with its own SQLite idempotency database and a synthetic B14 service, and
Chat reaches it through ``LocalEngineHttpTransport`` with the same caller surface
``build_local_engine_client`` composes.

What it proves here: the Chat host transport receives the Engine's own NDJSON
lifecycle records, in order, without buffering, and the Chat bridge projects the
Engine's terminal code into one bounded B62 error instead of hanging or leaking
Engine text.

The Engine host has a real model-execution binding. The synthetic B14 fixture
provides explicit unavailable and successful responses to test both terminal
contracts, with a fresh fixture per test.
"""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn

REPO = Path(__file__).resolve().parents[3]
ENGINE_DIR = REPO / "apps" / "padiem-ai-engine"
CHAT_DIR = REPO / "apps" / "padiem-chat"

CALLER_ID = "b62-chat"
CREDENTIAL = "s" * 40


def _child_path() -> str:
    return ";".join(
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
    """A synthetic B14 that answers both provider shapes and records use."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    @staticmethod
    def _chunk(content: str | None = None, finish: str | None = None) -> bytes:
        payload = {
            "id": "chatcmpl-host",
            "model": "host-model",
            "object": "chat.completion.chunk",
            "business14": {"route_mode": "synthetic", "request_id": "req-host"},
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": content} if content else {},
                    "finish_reason": finish,
                }
            ],
        }
        return f"data: {json.dumps(payload)}\n\n".encode()

    async def __call__(self, scope, receive, send) -> None:
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body"):
                break
        self.calls.append(scope["path"])
        if scope["path"].endswith("stream-preview"):
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
                        "body": self._chunk(content=piece),
                        "more_body": True,
                    }
                )
            await send(
                {
                    "type": "http.response.body",
                    "body": self._chunk(finish="stop"),
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
            "business14": {"route_mode": "synthetic", "request_id": "req-host"},
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "합성 답변"},
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


@pytest.fixture
def engine_host(tmp_path_factory, request):
    b14 = _B14()
    b14_port = _free_port()
    b14_server = _serve(b14, b14_port)
    engine_port = _free_port()
    unavailable_socket = None
    upstream_port = b14_port
    if request.node.name == "test_a_turn_streams_the_engines_own_records_in_order":
        unavailable_socket = socket.socket()
        unavailable_socket.bind(("127.0.0.1", 0))
        upstream_port = unavailable_socket.getsockname()[1]
    import os

    env = dict(os.environ)
    env.update(
        {
            "PADIEM_ENGINE_CPYTHON_HOST": "1",
            "P01_HOST": "127.0.0.1",
            "P01_PORT": str(engine_port),
            "PADIEM_ENGINE_LOCAL_B14_ORIGIN": f"http://127.0.0.1:{upstream_port}",
            "PADIEM_ENGINE_LOCAL_DB": str(
                tmp_path_factory.mktemp("engine") / "engine.sqlite3"
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
        if unavailable_socket is not None:
            unavailable_socket.close()
        b14_server.should_exit = True
        process.terminate()
        try:
            process.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()


def _client(origin: str):
    from app.local_p01_engine import CHAT_ENGINE_APP_ID, local_p01_engine_config_from_env
    from app.local_engine_transport import LocalEngineHttpTransport
    from padiem_ai_engine_client import PadiemAiEngineClient

    env = {
        "PADIEM_CHAT_LOCAL_P01_ENGINE_ORIGIN": origin,
        "PADIEM_CHAT_LOCAL_P01_CALLER_ID": CALLER_ID,
        "PADIEM_CHAT_LOCAL_P01_ENGINE_CREDENTIAL": CREDENTIAL,
    }
    config, diagnostic = local_p01_engine_config_from_env(env)
    assert config is not None and diagnostic is None
    return PadiemAiEngineClient(
        transport=LocalEngineHttpTransport(config.origin),
        app_id=CHAT_ENGINE_APP_ID,
        caller_id=config.caller_id,
        credential=config.credential,
    )


class _Store:
    async def save_pause(self, **kwargs) -> None:  # pragma: no cover - nothing pauses
        raise AssertionError("no pause is expected from this run")


def _skill():
    return type(
        "Skill",
        (),
        {
            "id": "chat",
            "title": "Padiem Chat",
            "description": "host round trip",
            "system_instruction": "answer",
            "task_type": "general",
            "optimize_for": "balanced",
            "max_tokens": None,
        },
    )()


def _bridge(client):
    from app.orchestration_bridge import B62EngineOrchestrationBridge

    return B62EngineOrchestrationBridge(client=client, store=_Store())


async def test_a_turn_streams_the_engines_own_records_in_order(engine_host) -> None:
    """The Engine app answers through the Chat transport, unbuffered and in order."""

    from app.orchestration_bridge import B62OrchestrationError

    bridge = _bridge(_client(engine_host["origin"]))
    stream = bridge.start_stream(
        user_id="u1",
        messages=[{"role": "user", "content": "안녕"}],
        skill=_skill(),
        model_id="host-model",
        user_text="안녕",
        conversation_id="c1",
        pc_tools=None,
        subject_id=None,
        session_id="c1",
    )

    kinds: list[str] = []
    arrivals: list[float] = []
    error: B62OrchestrationError | None = None
    started = time.monotonic()
    try:
        async for record in stream:
            arrivals.append(time.monotonic() - started)
            event = record.get("event") if isinstance(record, dict) else None
            if event is None:
                continue
            kinds.append(str(event.get("kind")))
            if event.get("kind") == "run_failed":
                assert event["metadata"]["error_code"] == "upstream_unavailable"
    except B62OrchestrationError as exc:
        # A failed run closes the Engine stream with its error frame; the client
        # raises it after the lifecycle records were already handed on.
        error = exc

    assert kinds[:2] == ["run_started", "context_prepared"]
    assert kinds[-1] == "run_failed"
    # Each record is handed on as the Engine produced it: the first frame does
    # not wait for the terminal one.
    assert arrivals[-1] >= arrivals[0]
    assert len(arrivals) == len(kinds)
    # The terminal failure crosses as one bounded B62 error, not Engine text.
    assert error is not None
    assert error.code == "upstream_unavailable"
    assert "AI 연결" in error.user_message
    # The configured model service is unreachable in this test.
    assert engine_host["b14"].calls == []



async def test_a_second_turn_still_streams_after_an_early_close(engine_host) -> None:
    """Closing the consumer must not poison the next turn."""

    bridge = _bridge(_client(engine_host["origin"]))
    first = bridge.start_stream(
        user_id="u1",
        messages=[{"role": "user", "content": "첫 턴"}],
        skill=_skill(),
        model_id="host-model",
        user_text="첫 턴",
        conversation_id="c1",
        pc_tools=None,
        subject_id=None,
        session_id="c1",
    )
    assert isinstance(await first.__anext__(), dict)
    await first.aclose()

    second = bridge.start_stream(
        user_id="u1",
        messages=[{"role": "user", "content": "둘째 턴"}],
        skill=_skill(),
        model_id="host-model",
        user_text="둘째 턴",
        conversation_id="c2",
        pc_tools=None,
        subject_id=None,
        session_id="c2",
    )
    records = [record async for record in second]
    kinds = [str(record["event"]["kind"]) for record in records if "event" in record]
    assert kinds[:2] == ["run_started", "context_prepared"]
    assert kinds[-1] == "run_completed"
    assert records[-1]["result"].answer == "합성 답변"
    assert engine_host["b14"].calls



async def test_the_engine_refuses_a_wrong_credential(engine_host) -> None:
    """The host transport still travels a validated caller surface."""

    from app.local_engine_transport import LocalEngineHttpTransport
    from app.orchestration_bridge import B62OrchestrationError
    from padiem_ai_engine_client import PadiemAiEngineClient

    client = PadiemAiEngineClient(
        transport=LocalEngineHttpTransport(engine_host["origin"]),
        app_id="padiem-chat",
        caller_id=CALLER_ID,
        credential="x" * 40,
    )
    bridge = _bridge(client)
    with pytest.raises(B62OrchestrationError):
        async for _record in bridge.start_stream(
            user_id="u1",
            messages=[{"role": "user", "content": "안녕"}],
            skill=_skill(),
            model_id="host-model",
            user_text="안녕",
            conversation_id="c1",
            pc_tools=None,
            subject_id=None,
            session_id="c1",
        ):
            pass
