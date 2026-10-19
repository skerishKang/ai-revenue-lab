"""#3523 redacted logs distinguish upstream empty from quality filtering."""
import asyncio

import httpx
import pytest

from padiem_ai_core.contracts import Evidence
from padiem_ai_core.grounding_runtime import GroundedResearchRuntime, GroundingRuntimeError
from padiem_ai_core.web_runtime import TinyFishWebProvider, WebRuntimeConfig


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize("payload,marker,length", [
    ({"results":[]}, "UPSTREAM_EMPTY", 0),
    ({"results":[{"title":"unsafe", "url":"http://127.0.0.1/internal"}]}, "NO_USABLE_URL", 0),
    ({"results":[{"title":"서울특별시", "url":"https://www.seoul.go.kr/"}]}, "USABLE", 1),
])
def test_normalization_buckets_no_sensitive_payload(payload,marker,length,capsys):
    secret="PRIVATE_TINYFISH_KEY_NEVER_LOG"
    query="PRIVATE_USER_QUERY_NEVER_LOG"
    transport=httpx.MockTransport(lambda request:httpx.Response(200,json=payload))
    provider=TinyFishWebProvider(WebRuntimeConfig(provider="tinyfish",tinyfish_api_key=secret),transport)
    found=run(provider.search(query))
    assert len(found)==length
    logs=capsys.readouterr().out
    assert logs.strip()=="TINYFISH_SEARCH_NORMALIZATION="+marker
    assert secret not in logs and query not in logs
    assert "seoul.go.kr" not in logs


@pytest.mark.parametrize("title,expected",[
    ("서울특별시", "QUALITY_SELECTED"),
    ("부산광역시", "QUALITY_FILTER_REJECTED"),
])
def test_grounding_bucket_and_navigational_evidence_selection(title,expected,capsys):
    secret="PRIVATE_USER_QUERY_NEVER_LOG"
    record=Evidence(
        id="test1",title=title,url="https://www.seoul.go.kr/",
        snippet="주요서비스",retrieved_at="2026-10-10T00:00:00Z",
        provider="tinyfish",source_type="search",
    )
    class Provider:
        async def search(self, query, limit=5):
            return [record]
    calls=[]
    async def synthesizer(context):
        calls.append(context)
        return {"answer":"ok"}
    coro=GroundedResearchRuntime(Provider()).run_search(
        "서울특별시 공식 누리집",synthesizer=synthesizer,
        additional_system_context=None,max_total_context_chars=9000,
    )
    if expected=="QUALITY_SELECTED":
        result=run(coro)
        assert result.prepared.evidence[0].title==title and len(calls)==1
    else:
        with pytest.raises(GroundingRuntimeError) as err:run(coro)
        assert err.value.code=="no_evidence"
        assert not calls
    logs=capsys.readouterr().out
    assert logs.strip()=="GROUNDING_SEARCH_EVIDENCE="+expected
    assert secret not in logs and "서울특별시" not in logs


def test_provider_empty_bucket_keeps_no_evidence_behavior(capsys):
    class Provider:
        async def search(self, query, limit=5): return []
    async def synth(context): raise AssertionError("must not synthesize")
    with pytest.raises(GroundingRuntimeError) as err:
        run(GroundedResearchRuntime(Provider()).run_search(
            "서울특별시",synthesizer=synth,additional_system_context=None,
            max_total_context_chars=9000
        ))
    assert err.value.code=="no_evidence"
    assert capsys.readouterr().out.strip()=="GROUNDING_SEARCH_EVIDENCE=PROVIDER_EMPTY"
