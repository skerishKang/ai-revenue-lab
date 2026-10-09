"""#3523: Korean TinyFish Search must not silently use the US/en default."""
import httpx
import pytest
from padiem_ai_core.web_runtime import TinyFishWebProvider, WebRuntimeConfig


@pytest.mark.asyncio
@pytest.mark.parametrize("query,language,location", [
    ("서울특별시 공식 홈페이지", "ko", "KR"),
    ("Seoul city official site", None, None),
])
async def test_hangul_search_country_language_context(query, language, location, capsys):
    observed = []
    key = "TEST_KEY_NEVER_LOG_THIS"
    def handler(request):
        observed.append(request)
        return httpx.Response(200, json={
            "results": [{
                "url": "https://www.seoul.go.kr/",
                "title": "Seoul City",
                "snippet": "Official government portal",
            }]
        })

    provider = TinyFishWebProvider(
        WebRuntimeConfig(provider="tinyfish", tinyfish_api_key=key),
        httpx.MockTransport(handler),
    )
    result = await provider.search(query)
    assert len(observed) == 1 and len(result) == 1
    assert observed[0].url.params.get("query") == query
    assert observed[0].url.params.get("language") == language
    assert observed[0].url.params.get("location") == location
    logs = capsys.readouterr().out.strip()
    assert logs == "TINYFISH_RESULT_COUNTS=RAW_1_SAFE_1"
    assert query not in logs and key not in logs
    assert result[0].provider == "tinyfish"


@pytest.mark.asyncio
async def test_raw_but_unsafe_url_is_dropped_with_counts_only(capsys):
    def handler(request):
        return httpx.Response(200,json={"results":[{"url":"http://localhost/internal","title":"none"}]})
    provider=TinyFishWebProvider(
        WebRuntimeConfig(provider="tinyfish",tinyfish_api_key="SECRET_TO_HIDE"),
        httpx.MockTransport(handler),
    )
    assert await provider.search("서울 공식 사이트")==[]
    output=capsys.readouterr().out.strip()
    assert output=="TINYFISH_RESULT_COUNTS=RAW_1_SAFE_0"
    assert "localhost" not in output and "SECRET_TO_HIDE" not in output
