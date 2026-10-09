"""#3523 fixed-origin routing logs are safe to use for served Worker egress E2E."""
import httpx
import pytest

from app.config import Settings
from app.web_tools import create_web_provider


@pytest.mark.asyncio
@pytest.mark.parametrize("tinyfish_status", [200, 402, 429])
async def test_routing_log_discloses_only_actual_provider_choice(tinyfish_status, capsys):
    sensitive="DO_NOT_LOG_TOKEN_OR_QUESTION"
    seen=[]
    def handle(request):
        seen.append(str(request.url))
        if "tinyfish" in str(request.url):
            if tinyfish_status != 200:
                return httpx.Response(tinyfish_status, json={"message":sensitive})
            return httpx.Response(200, json={"results":[
                {"url":"https://www.seoul.go.kr","title":"Seoul City","snippet":"Official city"}
            ]})
        return httpx.Response(200, json={"documents":[
            {"url":"https://www.seoul.go.kr","title":"Seoul City","contents":"Official city"}
        ]})

    settings=Settings.from_values(
        runtime_mode="b14", b14_base_url="https://example.test",
        web_provider="tinyfish_daum",
        tinyfish_api_key=sensitive, daum_rest_api_key=sensitive,
    )
    provider=create_web_provider(settings, transport=httpx.MockTransport(handle))
    evidence=await provider.search(sensitive)
    assert len(evidence)==1
    result=capsys.readouterr().out
    expected="TINYFISH" if tinyfish_status == 200 else "DAUM_ON_402_429"
    assert result.strip() == "PADIEM_WEB_SEARCH_ROUTE=" + expected
    assert sensitive not in result
    assert len(seen)==(1 if tinyfish_status==200 else 2)
    assert evidence[0].provider == ("tinyfish" if tinyfish_status==200 else "daum")
