"""#3523: classify TinyFish transport failures without logging sensitive payloads."""

import httpx
import pytest

from padiem_ai_core.web_runtime import TinyFishWebProvider, WebRuntimeConfig, WebRuntimeError


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("connect", "CONNECT"),
        ("read", "READ"),
        ("write", "WRITE"),
        ("remote_protocol", "REMOTE_PROTOCOL"),
        ("local_protocol", "LOCAL_PROTOCOL"),
        ("decoding", "DECODING"),
        ("protocol", "PROTOCOL"),
        ("request", "REQUEST"),
        ("other", "OTHER"),
        ("upstream", None),
    ],
)
async def test_bounded_diagnostic_does_not_print_secret_or_query(kind, expected, capsys):
    private = "DO_NOT_LOG_THIS_SECRET"
    question = "DO_NOT_LOG_THIS_QUERY"
    exception_message = "DO_NOT_LOG_THIS_EXCEPTION"

    def responder(request):
        error_types = {
            "connect": httpx.ConnectError,
            "read": httpx.ReadError,
            "write": httpx.WriteError,
            "remote_protocol": httpx.RemoteProtocolError,
            "local_protocol": httpx.LocalProtocolError,
            "decoding": httpx.DecodingError,
            "protocol": httpx.ProtocolError,
            "request": httpx.RequestError,
            "other": httpx.HTTPError,
        }
        if kind in error_types:
            raise error_types[kind](exception_message, request=request) if kind != "other" else httpx.HTTPError(exception_message)
        return httpx.Response(502, json={"error": "private"})

    provider = TinyFishWebProvider(
        WebRuntimeConfig(provider="tinyfish", tinyfish_api_key=private),
        transport=httpx.MockTransport(responder),
    )
    with pytest.raises(WebRuntimeError) as err:
        await provider.search(question)

    assert err.value.code == "web_unavailable"
    assert err.value.status_code == 502
    lines = capsys.readouterr().out.splitlines()
    if kind == "upstream":
        assert lines == ["TINYFISH_EGRESS_FAILURE=UPSTREAM_5XX"]
    else:
        assert lines == [
            "TINYFISH_EGRESS_FAILURE=TRANSPORT",
            f"TINYFISH_EGRESS_KIND={expected}",
        ]
    for forbidden in (private, question, exception_message, "private"):
        assert forbidden not in "\n".join(lines)
