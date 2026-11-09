"""#3554 historical transport regression under the Owner's later shared policy.

The historical provider-specific connect cap is replaced by B14's shared
first-byte and stream-idle limits, with unchanged routing.

#7241 3a: the subject models and their Provider ids come from the effective
registry, and every limit comes from the app's policy module, so this suite
writes no deployment value.
"""
import httpx
import pytest

from app.pilot import platform as plat
from app.pilot.b14_timeout_policy import (
    POOL_SECONDS, WRITE_SECONDS, get_timeout_policy,
)
from app.pilot.errors import UpstreamTimeout

from _registry_values import (
    a_dispatchable_row, model_rows, provider_of, requires_owner_document,
)


#: Two distinct Providers: the dispatchable rows the adapter would serve.
#: Which rows are live is an owner decision, so the parametrised cases are
#: skipped on a host reading the placeholder fixture.
CASES = [_row for _row in (a_dispatchable_row(),) if _row is not None]
for _row in model_rows():
    if len(CASES) >= 2:
        break
    _next = a_dispatchable_row(provider_ids=frozenset({provider_of(_row["id"])}))
    if _next is not None and provider_of(_next["id"]) != provider_of(CASES[0]["id"]):
        CASES.append(_next)

pytestmark = requires_owner_document


def test_connect_timeout_provider_scope_is_exact_and_bounded():
    timeout = plat.build_provider_http_timeout()
    policy = get_timeout_policy()
    assert (timeout.connect, timeout.read, timeout.write, timeout.pool) == (
        policy.first_byte_seconds, policy.stream_idle_seconds,
        WRITE_SECONDS, POOL_SECONDS,
    )
    # No Provider-specific exception or implicit fallback is installed.


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("row", CASES, ids=[provider_of(r["id"]) for r in CASES])
async def test_exact_live_adapter_uses_provider_connect_timeout_once(
        monkeypatch, caplog, stream, row):
    provider = provider_of(row["id"])
    expected = get_timeout_policy().first_byte_seconds
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setattr(plat, "_request_headers",
                        lambda spec, model_id="": {"Content-Type": "application/json"})
    native = httpx.AsyncClient
    captured = []
    requests = []

    def local_client(*args, **kwargs):
        timeout = kwargs["timeout"]
        captured.append((timeout.connect, timeout.read, timeout.write, timeout.pool))
        assert isinstance(kwargs.get("transport"), httpx.MockTransport)
        return native(*args, **kwargs)

    async def handler(request):
        requests.append(str(request.url))
        raise httpx.ConnectTimeout("SYNTHETIC_ONLY_NO_CREDENTIAL_OR_EGRESS")

    monkeypatch.setattr(plat.httpx, "AsyncClient", local_client)
    params = {
        "model_id": row["id"],
        "upstream_model": row["upstream_model"],
        "provider": provider,
        "platform_provider_id": provider,
        "messages": [{"role": "user", "content": "synthetic"}],
        "transport": httpx.MockTransport(handler),
    }
    with caplog.at_level("WARNING"):
        with pytest.raises(UpstreamTimeout):
            if stream:
                async for _ in plat.stream_platform_chat_completions(**params):
                    pass
            else:
                await plat.call_platform_chat_completions(**params)
    policy = get_timeout_policy()
    assert captured == [(expected, policy.stream_idle_seconds, WRITE_SECONDS, POOL_SECONDS)]
    assert len(requests) == 1
    assert f"b14_provider_attempt_timeout provider={provider} reason=first_byte mode={'stream' if stream else 'completed'}" in caplog.text
    assert "SYNTHETIC_ONLY_NO_CREDENTIAL_OR_EGRESS" not in caplog.text
