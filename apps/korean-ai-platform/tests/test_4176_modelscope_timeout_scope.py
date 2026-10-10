"""#4176 ModelScope first Production 504: bounded, phase-aware offline follow-up.

One Owner-approved actual ModelScope trial returned 504 after 10.515s but no
phase log because ModelScope was omitted from the fixed diagnostic allowlist.
A 30s *connect* allowance is a hypothesis-based mitigation, NOT a proven
low-level connect root cause or confirmation of ModelScope live success.
All tests use httpx.MockTransport: API calls, Secrets and Production changes 0.
"""
import httpx
import pytest

from app.pilot import platform as plat
from app.pilot.errors import UpstreamTimeout


def test_only_modelscope_and_previously_approved_kira_have_30s_connect():
    assert plat._CONNECT_TIMEOUT == 10.0
    assert plat._KIRA_CONNECT_TIMEOUT == 30.0
    assert plat._MODELSCOPE_CONNECT_TIMEOUT == 30.0
    assert plat._READ_TIMEOUT == 30.0
    assert plat._WRITE_TIMEOUT == 10.0
    assert plat._POOL_TIMEOUT == 10.0
    assert plat._provider_connect_timeout("modelscope") == 30.0
    assert plat._provider_connect_timeout("kira") == 30.0
    for provider in ("google", "sensenova", "inception", "poolside",
                     "atria", "experiential", "agnes-ai", "unknown"):
        assert plat._provider_connect_timeout(provider) == 10.0


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("provider,model,upstream,expected", [
    ("modelscope", "modelscope/deepseek-ai/DeepSeek-V4.1-Flash",
     "deepseek-ai/DeepSeek-V4.1-Flash", 30.0),
    ("kira", "kira/qwen3.8-flash-free", "qwen3.8-flash-free", 30.0),
    ("sensenova", "sensenova/sensenova-6.8-flash-lite",
     "sensenova-6.8-flash-lite", 10.0),
])
async def test_completed_stream_timeout_phase_safe_and_one_mock_call(
        monkeypatch, caplog, stream, provider, model, upstream, expected):
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
        model_id=model, upstream_model=upstream, provider=provider,
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
    assert timeouts == [(expected, 30.0, 10.0, 10.0)]
    assert len(requests) == 1
    assert (f"b14_safe_timeout provider={provider} phase=connect "
            f"mode={'stream' if stream else 'completed'}") in caplog.text
    assert "PRIVATE_MODEL_KEY_OR_PROMPT_SHOULD_NOT_LOG" not in caplog.text
