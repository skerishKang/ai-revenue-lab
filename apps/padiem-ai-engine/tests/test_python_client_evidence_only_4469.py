"""#4469: client binds evidence-only Search to existing authenticated Engine origin."""
import json
from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1] / "clients" / "python"
sys.path.insert(0, str(ROOT))
from padiem_ai_engine_client import PadiemAiEngineClient, PadiemAiEngineClientError, EngineTransportResponse


class Transport:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def request(self, **request):
        self.calls.append(request)
        return self.response


def client(t):
    return PadiemAiEngineClient(
        transport=t, app_id="padiem-claw",
        caller_id="padiem-claw-service",
        credential="c" * 48,
    )


AGENT = {
    "id": "public-evidence-probe",
    "title": "Public read-only",
    "description": "Public search only",
    "task_type": "general",
    "optimize_for": "balanced",
    "max_tokens": 240,
    "model_policy": {"model": "test/route"},
}


@pytest.mark.asyncio
async def test_search_evidence_fixed_origin_and_no_model_or_secret_wire():
    transport = Transport(EngineTransportResponse(status=200, body=json.dumps({
        "ok": True,
        "operation": "search_evidence",
        "answer": None,
        "sources": [{"title": "Public", "url": "https://example.org", "retrieved_at": "2026-10-14T00:00:00Z"}],
        "grounding_context": "웹 근거 사용 규칙:\\n[1] public",
    }).encode()))
    result = await client(transport).search_evidence(query="한국은행 기준금리", agent=AGENT)
    assert result["sources"][0]["url"] == "https://example.org"
    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["url"] == "https://engine.internal/internal/v1/research"
    assert call["method"] == "POST"
    assert call["headers"]["X-Padiem-Engine-Caller"] == "padiem-claw-service"
    wire = json.loads(call["body"])
    assert wire["app_id"] == "padiem-claw"
    assert wire["operation"] == "search_evidence"
    assert wire["query"] == "한국은행 기준금리"
    assert "credential" not in wire
    assert "additional_system_context" not in wire
    assert "subject_id" not in wire


@pytest.mark.asyncio
async def test_invalid_evidence_response_fails_closed():
    transport = Transport(EngineTransportResponse(status=200, body=b'{"ok":true,"operation":"search_evidence","answer":"model answer","sources":[],"grounding_context":"injected"}'))
    with pytest.raises(PadiemAiEngineClientError):
        await client(transport).search_evidence(query="날씨", agent=AGENT)


@pytest.mark.asyncio
async def test_invalid_query_refused_before_network():
    transport = Transport(EngineTransportResponse(status=200, body=b'{}'))
    with pytest.raises(PadiemAiEngineClientError):
        await client(transport).search_evidence(query="", agent=AGENT)
    assert transport.calls == []
