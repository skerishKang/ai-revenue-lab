"""#3523: disclose no secret data in TinyFish failure diagnostics."""
import httpx
import pytest

from padiem_ai_core.web_runtime import (
    TinyFishWebProvider, WebRuntimeConfig, WebRuntimeError,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["transport", "upstream"])
async def test_bounded_diagnostic_does_not_print_secret_or_query(kind, capsys):
    private = "DO_NOT_LOG_THIS_SECRET"
    question = "DO_NOT_LOG_THIS_QUERY"
    def responder(request):
        if kind == "transport":
            raise httpx.ConnectError("DO_NOT_LOG_THIS_EXCEPTION", request=request)
        return httpx.Response(502, json={"error":"private"})

    provider = TinyFishWebProvider(
        WebRuntimeConfig(provider="tinyfish", tinyfish_api_key=private),
        transport=httpx.MockTransport(responder),
    )
    with pytest.raises(WebRuntimeError) as err:
        await provider.search(question)
    assert err.value.code == "web_unavailable"
    data=capsys.readouterr().out
    assert data.strip() == "TINYFISH_EGRESS_FAILURE=" + (
        "TRANSPORT" if kind == "transport" else "UPSTREAM_5XX")
    assert private not in data and question not in data
    assert "DO_NOT_LOG_THIS_EXCEPTION" not in data
