"""#4176 historical timeout probe, updated for the common model idle policy.

The historical per-Provider connect setting is replaced by B14's shared
first-byte and stream-idle bounds. Tests are MockTransport only.

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


CASES = [_row for _row in (a_dispatchable_row(),) if _row is not None]
for _row in model_rows():
    if len(CASES) >= 2:
        break
    _next = a_dispatchable_row(provider_ids=frozenset({provider_of(_row["id"])}))
    if _next is not None and provider_of(_next["id"]) != provider_of(CASES[0]["id"]):
        CASES.append(_next)

pytestmark = requires_owner_document


def test_no_provider_keeps_a_per_provider_connect_exception():
    timeout = plat.build_provider_http_timeout()
    policy = get_timeout_policy()
    assert (timeout.connect, timeout.read, timeout.write, timeout.pool) == (
        policy.first_byte_seconds, policy.stream_idle_seconds,
        WRITE_SECONDS, POOL_SECONDS,
    )
    # The prior per-Provider exceptions were superseded by one shared limit.


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("row", CASES, ids=[provider_of(r["id"]) for r in CASES])
async def test_completed_stream_timeout_phase_safe_and_one_mock_call(
        monkeypatch, caplog, stream, row):
    provider = provider_of(row["id"])
    expected = get_timeout_policy().first_byte_seconds
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setattr(
        plat, "_request_headers",
        lambda spec, model_id="": {"Content-Type": "application/json"},
    )
    base_client = httpx.AsyncClient
    timeouts = []
    requests = []
    def tracked_client(*args, **kwargs):
        t=kwargs["timeout"]
        timeouts.append((t.connect, t.read, t.write, t.pool))
        assert isinstance(kwargs.get("transport"), httpx.MockTransport)
        return base_client(*args, **kwargs)
    monkeypatch.setattr(plat.httpx, "AsyncClient", tracked_client)

    async def handler(request):
        requests.append(str(request.url))
        raise httpx.ConnectTimeout("PRIVATE_MODEL_KEY_OR_PROMPT_SHOULD_NOT_LOG")
    args=dict(
        model_id=row["id"], upstream_model=row["upstream_model"], provider=provider,
        platform_provider_id=provider,
        messages=[{"role":"user","content":"synthetic"}],
        transport=httpx.MockTransport(handler),
    )
    with caplog.at_level("WARNING"):
        with pytest.raises(UpstreamTimeout):
            if stream:
                async for _ in plat.stream_platform_chat_completions(**args):
                    pass
            else:
                await plat.call_platform_chat_completions(**args)
    policy = get_timeout_policy()
    assert timeouts == [(expected, policy.stream_idle_seconds, WRITE_SECONDS, POOL_SECONDS)]
    assert len(requests) == 1
    assert (f"b14_provider_attempt_timeout provider={provider} reason=first_byte "
            f"mode={'stream' if stream else 'completed'}") in caplog.text
    assert "PRIVATE_MODEL_KEY_OR_PROMPT_SHOULD_NOT_LOG" not in caplog.text
