"""#4469: one shared Core provider priority for Chat, Engine and B66."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from padiem_ai_core.web_priority import TinyFishDaumPriorityWebProvider
from padiem_ai_core.web_runtime import WebRuntimeError


def run(coro):
    return asyncio.run(coro)


def provider(handler):
    return TinyFishDaumPriorityWebProvider(
        tinyfish_key="synthetic-tinyfish",
        daum_key="synthetic-daum",
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.parametrize("status", [402, 429])
def test_only_quota_rate_limit_retries_exactly_one_daum_search(status):
    calls = []

    def send(req):
        calls.append((req.method, str(req.url)))
        if len(calls) == 1:
            return httpx.Response(status, json={"error": "quota"})
        return httpx.Response(200, json={"documents": [
            {"title": "Public", "url": "https://example.org/article", "contents": "public data"}
        ]})

    found = run(provider(send).search("public market news"))
    assert len(calls) == 2
    assert "api.search.tinyfish.ai" in calls[0][1]
    assert "dapi.kakao.com/v2/search/web" in calls[1][1]
    assert found and found[0].provider == "daum"


@pytest.mark.parametrize("status", [400, 401, 403, 404, 500, 503])
def test_non_quota_failure_never_dispatches_second_search(status):
    calls = []

    def send(req):
        calls.append(req)
        return httpx.Response(status, json={"error": "failure"})

    with pytest.raises(WebRuntimeError):
        run(provider(send).search("public market news"))
    assert len(calls) == 1


def test_empty_results_remain_empty_and_no_daum_call():
    calls = []

    def send(req):
        calls.append(req)
        return httpx.Response(200, json={"results": []})

    assert run(provider(send).search("public market news")) == []
    assert len(calls) == 1


def test_fetch_tinyfish_only_no_daum_on_402():
    calls = []

    def send(req):
        calls.append((req.method, str(req.url)))
        return httpx.Response(402, json={"error": "quota"})

    with pytest.raises(WebRuntimeError) as exc:
        run(provider(send).fetch("https://example.org/public-page"))
    assert exc.value.code == "web_quota_exhausted"
    assert calls == [("POST", "https://api.fetch.tinyfish.ai")]


@pytest.mark.parametrize("keys", [
    {"tinyfish_key": "", "daum_key": "synthetic"},
    {"tinyfish_key": "synthetic", "daum_key": ""},
    {"tinyfish_key": None, "daum_key": "synthetic"},
    {"tinyfish_key": "synthetic", "daum_key": None},
])
def test_missing_keys_fail_closed_at_construction(keys):
    with pytest.raises(ValueError):
        TinyFishDaumPriorityWebProvider(**keys)


def test_the_missing_daum_key_is_refused_before_any_egress() -> None:
    # Whichever layer answers, the refusal must name the missing credential rather
    # than a provider list, and it must happen at construction with no request sent.
    calls = []

    def send(req):
        calls.append(req)
        return httpx.Response(200, json={"documents": []})

    with pytest.raises(ValueError, match="daum"):
        TinyFishDaumPriorityWebProvider(
            tinyfish_key="synthetic-tinyfish",
            daum_key="",
            transport=httpx.MockTransport(send),
        )
    assert calls == []


def test_the_fallback_egress_carries_only_the_daum_credential() -> None:
    seen: list[tuple[str, dict[str, str]]] = []

    def send(req):
        seen.append((str(req.url), dict(req.headers)))
        if len(seen) == 1:
            return httpx.Response(429, json={"error": "quota"})
        return httpx.Response(200, json={"documents": [
            {"title": "Public", "url": "https://example.org/article", "contents": "public data"}
        ]})

    run(provider(send).search("public market news"))
    assert len(seen) == 2
    primary_url, primary_headers = seen[0]
    fallback_url, fallback_headers = seen[1]
    assert "api.search.tinyfish.ai" in primary_url
    assert "dapi.kakao.com/v2/search/web" in fallback_url
    assert fallback_headers.get("authorization") == "KakaoAK synthetic-daum"
    egress = json.dumps({"url": fallback_url, "headers": fallback_headers})
    assert "synthetic-tinyfish" not in egress, "the primary credential must not reach the fallback origin"
