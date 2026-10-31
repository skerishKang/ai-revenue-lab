"""Exercise the staging suite against the real CPython Chat ASGI app over HTTP."""
import asyncio
import importlib.util
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from app.auth import SESSION_COOKIE, create_session_token
from app.main import create_app
from test_auth_history import MemoryHistoryStore, add_test_user, google_settings
from test_4139_claw_device_directory_route import Binding
from app.claw_device_directory_routes import BrokerDeviceDirectorySource

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "staging_com2_e2e.py"
spec = importlib.util.spec_from_file_location("staging_com2_e2e", SCRIPT)
suite = importlib.util.module_from_spec(spec)
spec.loader.exec_module(suite)


class FileStore:
    async def list_owner_files(self, user_id, *, after, limit):
        return []


@pytest.mark.parametrize("files_ready", [False, True])
@pytest.mark.parametrize("pc_ready", [False, True])
def test_suite_over_loopback(files_ready, pc_ready):
    store = MemoryHistoryStore()
    profile = asyncio.run(add_test_user(store))
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    port = sock.getsockname()[1]
    settings = google_settings(cookie_secure=False, local_dev=True,
                               public_base_url=f"http://127.0.0.1:{port}")
    app = create_app(settings, history_store=store,
                     project_file_store=FileStore() if files_ready else None,
                     claw_device_directory_source=BrokerDeviceDirectorySource(Binding()) if pc_ready else None)
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        for _ in range(200):
            if server.started:
                break
            time.sleep(0.05)
        assert server.started
        cookie = SESSION_COOKIE + "=" + create_session_token(settings, profile.id)
        assert suite.run(f"http://127.0.0.1:{port}", cookie) == (8, 0)
        assert suite.run(f"http://127.0.0.1:{port}", "") == (2, 6)
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()


@pytest.mark.parametrize("url", [
    "https://chat.padiem.net", "http://chat.padiem.net",
    "http://127.0.0.1.evil.test", "http://localhost@chat.padiem.net",
    "http://localhost/path",
])
def test_reject_non_loopback_before_connect(url):
    with pytest.raises(ValueError):
        suite.run(url, "session=x")


@pytest.mark.parametrize("origin", ["http://chat-com2-staging.padiem.net", "//evil.test"])
def test_reject_non_https_expected_origin(origin):
    with pytest.raises(ValueError):
        suite.run("http://127.0.0.1:8801", "session=x", origin)
