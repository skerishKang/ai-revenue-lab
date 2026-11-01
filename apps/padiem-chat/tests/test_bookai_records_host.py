"""The shipped host composition persists BookAI records across a restart."""
import os

from starlette.testclient import TestClient

from app.local_cpython import build_app
from test_bookai_records import NOW, SECRET, RECORDS_PATH, get, post, record


def test_host_installs_signed_records_and_persists_on_restart(tmp_path, monkeypatch):
    for name in tuple(os.environ):
        if name.startswith(("PADIEM_", "PC_QUEUE_", "BOOKAI_")):
            monkeypatch.delenv(name)
    settings = {
        "PADIEM_CHAT_CPYTHON_HOST": "1",
        "PADIEM_CHAT_RUNTIME_MODE": "mock",
        "PADIEM_CHAT_AUTH_MODE": "password",
        "PADIEM_CHAT_SESSION_SECRET": "fixture-chat-session-0123456789abcdef",
        "PADIEM_CHAT_WEB_PROVIDER": "off",
        "PADIEM_CHAT_LIVE_ENABLED": "false",
        "PADIEM_CHAT_PUBLIC_BASE_URL": "https://chat.example.com",
        "PADIEM_CHAT_LOCAL_DATA_DIR": str(tmp_path),
        "BOOKAI_COM2_SYNC_SECRET": SECRET,
    }
    for name, value in settings.items():
        monkeypatch.setenv(name, value)
    first = build_app()
    first.state.bookai_records_service._clock = lambda: NOW
    with TestClient(first) as client:
        assert client.get(RECORDS_PATH).status_code == 401
        response = post(client, [record()])
        assert response.status_code == 200
        assert response.json() == {"accepted": 1, "kept_newer": []}
    second = build_app()
    second.state.bookai_records_service._clock = lambda: NOW
    with TestClient(second) as client:
        assert get(client).json() == {"records": [record()], "next_since": 100, "more": False}
        assert get(client, subject="sub_other").json()["records"] == []
