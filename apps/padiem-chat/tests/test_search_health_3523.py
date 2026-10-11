"""#3523 live Search config truth in /health, not proof of provider reachability."""
import httpx
import pytest

from app.app_factory import create_app
from app.config import Settings


@pytest.mark.asyncio
async def test_public_search_configured_is_ready_and_deep_research_remains_unavailable():
    settings = Settings.from_values(
        runtime_mode="b14", b14_base_url="https://b14.example",
        web_provider="tinyfish_daum", tinyfish_api_key="mock-tf",
        daum_rest_api_key="mock-daum",
    )
    app=create_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        result=await client.get("/health")
    assert result.status_code == 200
    body=result.json()
    assert body["web_tools_ready"] is True
    assert body["deep_research_ready"] is False
