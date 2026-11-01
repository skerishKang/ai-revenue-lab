"""Signed app API -> actual P01 ASGI process -> synthetic B14 socket -> answer.

Reuses the host round-trip harness. No external provider, production service,
credential configuration or deployment is touched.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import httpx
import pytest
from starlette.applications import Starlette

from app.apps_ai import APPS_AI_PATH, DEFAULT_MODEL, install_apps_ai_routes
from test_apps_ai_com2 import NOW, encoded, env, headers, payload, TEST_SECRET
from test_host_engine_roundtrip_261031 import (
    _B14, _child_path, _free_port, _serve, _wait_tcp,
    ENGINE_DIR, CALLER_ID, CREDENTIAL,
)
from _host_b14_proof import TEST_SECRET as B14_PROOF_TEST_SECRET


class RecordingB14(_B14):
    def __init__(self):
        super().__init__()
        self.observed = []

    async def __call__(self, scope, receive, send):
        raw = bytearray()
        while True:
            message = await receive()
            raw.extend(message.get("body", b""))
            if not message.get("more_body"):
                break
        self.observed.append({
            "body": json.loads(raw),
            "headers": {key.decode().lower(): value.decode() for key, value in scope["headers"]},
        })
        async def replay():
            return {"type": "http.request", "body": bytes(raw), "more_body": False}
        await super().__call__(scope, replay, send)


@pytest.fixture
def apps_engine(tmp_path):
    b14 = RecordingB14()
    b14_port, engine_port = _free_port(), _free_port()
    server = _serve(b14, b14_port)
    settings = dict(os.environ)
    for name in list(settings):
        if name.startswith("PADIEM_ENGINE_CALLER_REGISTRY") or name == "B14_SECRET_DIR":
            settings.pop(name, None)
    settings.update({
        "PADIEM_B14_SERVICE_PROOF_SECRET": B14_PROOF_TEST_SECRET,
        "PADIEM_ENGINE_CPYTHON_HOST": "1",
        "P01_HOST": "127.0.0.1", "P01_PORT": str(engine_port),
        "PADIEM_ENGINE_LOCAL_B14_ORIGIN": f"http://127.0.0.1:{b14_port}",
        "PADIEM_ENGINE_LOCAL_DB": str(tmp_path / "engine.sqlite3"),
        "PADIEM_ENGINE_CALLER_ID": CALLER_ID,
        "PADIEM_ENGINE_CALLER_SECRET": CREDENTIAL,
        "PADIEM_ENGINE_ALLOWED_APPS": "b61",
        "PYTHONPATH": _child_path(),
    })
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "asgi:app", "--host", "127.0.0.1",
         "--port", str(engine_port), "--log-level", "warning", "--no-access-log"],
        cwd=str(ENGINE_DIR), env=settings, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    try:
        assert _wait_tcp(engine_port), "synthetic local P01 did not start"
        yield f"http://127.0.0.1:{engine_port}", b14
    finally:
        server.should_exit = True
        process.terminate()
        try:
            process.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()


@pytest.mark.asyncio
async def test_both_apps_execute_through_actual_p01_and_keep_b14_app_attribution(apps_engine):
    origin, b14 = apps_engine
    settings = env(
        PADIEM_CHAT_LOCAL_P01_ENGINE_ORIGIN=origin,
        PADIEM_CHAT_LOCAL_P01_CALLER_ID=CALLER_ID,
        PADIEM_CHAT_LOCAL_P01_ENGINE_CREDENTIAL=CREDENTIAL,
    )
    app = Starlette()
    service = install_apps_ai_routes(app, env=settings)
    service._clock = lambda: NOW
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://chat.padiem.net") as client:
        for name, secret in [("storymemory", TEST_SECRET), ("bookai", TEST_SECRET + "book")]:
            body = encoded(payload())
            response = await client.post(
                APPS_AI_PATH, content=body,
                headers=headers(body, subject="sub_app_" + name, secret=secret),
            )
            assert response.status_code == 200, response.text
            result = response.json()
            assert result["answer"]
            assert "<thought>" not in result["answer"]
            assert result["context_permission"]["boundary_disposition"] == "permitted"
            assert result["context_permission"]["context_filtered_count"] == 0
            assert result["context_permission"]["context_allowed_count"] == 1
            assert b14.observed[-1]["headers"]["x-padiem-client-app"] == name
            assert b14.observed[-1]["body"]["model"] == DEFAULT_MODEL
            assert b14.observed[-1]["body"]["business14"]["max_retries"] == 0
    assert len(b14.observed) == 2
