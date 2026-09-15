from __future__ import annotations

"""#2544 — the completed (non-streaming) path gets its own bounded timeout.

The B14 gateway behind the ``B14_SERVICE`` binding runs a bounded retry/fallback
envelope of 45s (#1988/#1990). The shared ``timeout_seconds`` (20s) also drives
the streaming client, so the completed path could not simply raise it. These tests
pin the separation: ``completed_timeout_seconds`` (50s) governs ONLY the completed
text/image path, while ``timeout_seconds`` (20s) keeps governing streaming.
"""

import json

import httpx
import pytest

from app.b14_client import B14Client
from app.config import ConfigError, Settings
from app.worker_config import settings_from_worker_bindings

# B14 gateway bounded retry/fallback envelope (see #1988/#1990 and
# apps/padiem-ai-engine/tests/test_b14_transport_timeout.py). The completed
# deadline must exceed this so a single gateway attempt can resolve before the
# product gives up.
B14_GATEWAY_ENVELOPE_SECONDS = 45.0

USER_MESSAGES = [{"role": "user", "content": "hi"}]


class FakeServiceTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def post_json(self, url: str, payload: dict) -> tuple[int, bytes]:
        self.calls.append((url, payload))
        payload_body = {
            "id": "resp_1",
            "model": "agnes",
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        }
        return 200, json.dumps(payload_body).encode("utf-8")


def test_default_settings_separate_completed_from_streaming_timeout():
    settings = Settings()
    assert settings.timeout_seconds == 20.0, "streaming/shared timeout must stay at 20s"
    assert settings.completed_timeout_seconds == 50.0, "completed path gets the 50s envelope"


def test_completed_timeout_exceeds_b14_gateway_envelope():
    settings = Settings()
    assert settings.completed_timeout_seconds > B14_GATEWAY_ENVELOPE_SECONDS, (
        "completed deadline must be longer than the B14 gateway retry envelope"
    )
    assert settings.completed_timeout_seconds <= 60.0, "must stay within the Core 1..60 bound"


def test_completed_timeout_validation_bounds_and_numeric():
    with pytest.raises(ConfigError, match="PADIEM_CHAT_COMPLETED_TIMEOUT_SECONDS must be between 1 and 60"):
        Settings.from_values(completed_timeout_seconds=999)
    with pytest.raises(ConfigError, match="PADIEM_CHAT_COMPLETED_TIMEOUT_SECONDS must be between 1 and 60"):
        Settings.from_values(completed_timeout_seconds=0)
    with pytest.raises(ConfigError, match="PADIEM_CHAT_COMPLETED_TIMEOUT_SECONDS must be numeric"):
        Settings.from_values(completed_timeout_seconds="not-a-number")


def test_completed_timeout_is_independent_of_streaming_timeout():
    settings = Settings.from_values(timeout_seconds=7, completed_timeout_seconds=50)
    assert settings.timeout_seconds == 7.0
    assert settings.completed_timeout_seconds == 50.0


def test_env_default_is_fifty(monkeypatch):
    monkeypatch.setenv("PADIEM_CHAT_RUNTIME_MODE", "b14")
    monkeypatch.setenv("PADIEM_CHAT_B14_BASE_URL", "https://b14.internal")
    monkeypatch.delenv("PADIEM_CHAT_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("PADIEM_CHAT_COMPLETED_TIMEOUT_SECONDS", raising=False)
    settings = Settings.from_env()
    assert settings.timeout_seconds == 20.0
    assert settings.completed_timeout_seconds == 50.0


def test_env_override_is_respected(monkeypatch):
    monkeypatch.setenv("PADIEM_CHAT_RUNTIME_MODE", "b14")
    monkeypatch.setenv("PADIEM_CHAT_B14_BASE_URL", "https://b14.internal")
    monkeypatch.setenv("PADIEM_CHAT_TIMEOUT_SECONDS", "20")
    monkeypatch.setenv("PADIEM_CHAT_COMPLETED_TIMEOUT_SECONDS", "55")
    settings = Settings.from_env()
    assert settings.timeout_seconds == 20.0
    assert settings.completed_timeout_seconds == 55.0


def test_worker_binding_defaults_are_untouched():
    settings = settings_from_worker_bindings({})
    assert settings.timeout_seconds == 20.0, "live PADIEM_CHAT_TIMEOUT_SECONDS default must stay 20"
    assert settings.completed_timeout_seconds == 50.0


def test_worker_binding_reads_completed_override():
    settings = settings_from_worker_bindings(
        {
            "PADIEM_CHAT_RUNTIME_MODE": "b14",
            "PADIEM_CHAT_B14_BASE_URL": "https://b14.internal",
            "PADIEM_CHAT_TIMEOUT_SECONDS": "20",
            "PADIEM_CHAT_COMPLETED_TIMEOUT_SECONDS": "52",
        }
    )
    assert settings.timeout_seconds == 20.0
    assert settings.completed_timeout_seconds == 52.0


def test_completed_transport_and_config_use_completed_timeout_only():
    client = B14Client(
        Settings(runtime_mode="b14", b14_base_url="https://b14.internal"),
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
        service_transport=FakeServiceTransport(),
        require_service_binding=True,
    )

    # Streaming / shared config keeps the 20s timeout.
    assert client._config().timeout_seconds == 20.0
    # Completed config and completed transport use the 50s completed timeout.
    assert client._completion_config().timeout_seconds == 50.0
    completion_transport = client._completion_transport()
    assert completion_transport._timeout_seconds == 50.0


@pytest.mark.asyncio
async def test_completed_request_succeeds_beyond_the_old_twenty_second_cap():
    # A service transport that answers normally must run through the 50s
    # completed deadline (previously the shared 20s cap). This proves the
    # completed path is wired to completed_timeout_seconds end to end.
    service = FakeServiceTransport()
    client = B14Client(
        Settings(runtime_mode="b14", b14_base_url="https://b14.internal"),
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
        service_transport=service,
        require_service_binding=True,
    )
    result = await client.complete(USER_MESSAGES)
    assert result["runtime"] == "b14"
    assert len(service.calls) == 1
