from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys

import httpx
import pytest

from app.b14_client import B14Client, ChatRuntimeError
from app.b66_registered_model_boundary import (
    B14QuoteExactModelExecutor,
    B66ModelRouteError,
    B66RegisteredModelCompletion,
)
from app.config import Settings
from app.dispatch_quota import (
    DispatchAwareB14Client,
    DispatchAwareUsageCounterStore,
    _refund_active_reservation,
)
from app.worker_config import apply_live_deadman_switch
from test_b66_registered_model_boundary import FakeTrustedResolver, approved_route
from test_dispatch_quota_refund import RefundableMemoryStore


MODEL = "kilo/nvidia-nemotron-3-ultra-550b-a55b-free"
MESSAGES = [{"role": "user", "content": "synthetic quotation"}]


def settings(**overrides):
    values = dict(runtime_mode="b14", b14_base_url="https://b14.internal", live_enabled=True)
    values.update(overrides)
    return Settings(**values)


class Binding:
    def __init__(self, status=200, error=None):
        self.calls = []
        self.status = status
        self.error = error

    async def post_json(self, url, payload):
        self.calls.append((url, payload))
        if self.error is not None:
            raise self.error
        return self.status, json.dumps({
            "choices": [{"message": {"role": "assistant", "content": "{}"}}],
            "business14": {"route_mode": "manual", "selected_model": MODEL},
            "error": {"code": "upstream_timeout", "message": "PRIVATE PROVIDER OUTPUT"},
        }).encode()


async def reserve(store):
    decision = await DispatchAwareUsageCounterStore(store).consume(
        subject_type="user", subject_key="synthetic-user",
        minute_bucket="2026-10-08T00:00", day_bucket="2026-10-08",
        burst_limit=10, daily_limit=10, global_daily_limit=10,
        updated_at="2026-10-08T00:00:00Z",
    )
    assert decision.allowed


@pytest.mark.parametrize(("runtime", "live"), [("mock", False), ("mock", True), ("b14", False)])
def test_exact_quote_off_guard_has_zero_dispatch_before_registry_and_refunds(runtime, live):
    effective = apply_live_deadman_switch(settings(runtime_mode=runtime, live_enabled=live))
    binding = Binding()
    client = DispatchAwareB14Client(effective, service_transport=binding)
    resolver = FakeTrustedResolver(approved_route(model_id=MODEL))
    store = RefundableMemoryStore()
    facade = B66RegisteredModelCompletion(
        resolver=resolver, executor=B14QuoteExactModelExecutor(client),
        refund_pre_dispatch=_refund_active_reservation,
    )

    async def run():
        await reserve(store)
        with pytest.raises(B66ModelRouteError, match="runtime_unavailable"):
            await facade.complete(MESSAGES)
        assert await _refund_active_reservation() is False
        with pytest.raises(ChatRuntimeError) as caught:
            await client.complete_registered_quote_model(MESSAGES, model=MODEL)
        assert caught.value.code == "quote_runtime_unavailable"

    asyncio.run(run())
    assert resolver.calls == []
    assert binding.calls == []
    assert sorted(store.counts.values()) == [0, 0, 0]
    assert store.bucket_refund_calls == 3


@pytest.mark.parametrize("failure", ["binding", "model", "messages", "context", "core_validation", "serialization"])
def test_exact_quote_local_failure_refunds_before_any_service_post(failure):
    binding = Binding()
    store = RefundableMemoryStore()
    client = DispatchAwareB14Client(
        settings(), service_transport=None if failure == "binding" else binding,
        require_service_binding=True,
    )
    kwargs = dict(messages=MESSAGES, model=MODEL, additional_system_context=None)
    if failure == "model":
        kwargs["model"] = "b14/auto"
    elif failure == "messages":
        kwargs["messages"] = [{"role": "assistant", "content": "invalid"}]
    elif failure == "context":
        kwargs["additional_system_context"] = "x" * 14_001
    elif failure == "core_validation":
        kwargs["messages"] = [{"role": "user", "content": "x" * 100_001}]
    elif failure == "serialization":
        kwargs["messages"] = [{"role": "user", "content": "\ud800"}]

    async def run():
        await reserve(store)
        with pytest.raises((ChatRuntimeError, ValueError)):
            await client.complete_registered_quote_model(**kwargs)
        assert await _refund_active_reservation() is False

    asyncio.run(run())
    assert binding.calls == []
    assert sorted(store.counts.values()) == [0, 0, 0]
    assert store.bucket_refund_calls == 3


@pytest.mark.parametrize(("status", "code"), [(504, "upstream_timeout"), (503, "provider_server_error")])
def test_exact_quote_provider_failure_preserves_class_and_consumes_once(status, code):
    binding = Binding(status=status)
    store = RefundableMemoryStore()
    client = DispatchAwareB14Client(settings(), service_transport=binding, require_service_binding=True)
    facade = B66RegisteredModelCompletion(
        resolver=FakeTrustedResolver(approved_route(model_id=MODEL)),
        executor=B14QuoteExactModelExecutor(client),
        refund_pre_dispatch=_refund_active_reservation,
    )

    async def run():
        await reserve(store)
        with pytest.raises(ChatRuntimeError) as caught:
            await facade.complete(MESSAGES)
        assert caught.value.code == code
        assert "PRIVATE" not in str(caught.value)
        assert await _refund_active_reservation() is False

    asyncio.run(run())
    assert len(binding.calls) == 1
    assert sorted(store.counts.values()) == [1, 1, 1]
    assert store.bucket_refund_calls == 0


def test_exact_quote_ambiguous_transport_failure_is_not_refunded():
    binding = Binding(error=RuntimeError("PRIVATE ambiguous transport failure"))
    store = RefundableMemoryStore()
    client = DispatchAwareB14Client(settings(), service_transport=binding, require_service_binding=True)

    async def run():
        await reserve(store)
        with pytest.raises(ChatRuntimeError):
            await client.complete_registered_quote_model(MESSAGES, model=MODEL)
        assert await _refund_active_reservation() is False

    asyncio.run(run())
    assert len(binding.calls) == 1
    assert sorted(store.counts.values()) == [1, 1, 1]
    assert store.bucket_refund_calls == 0


@pytest.mark.parametrize("failure", ["core_validation", "serialization", "transport_timeout"])
def test_direct_http_quote_receipt_is_consumed_only_after_serialization(failure):
    calls = []
    store = RefundableMemoryStore()

    async def transport(request):
        calls.append(request)
        raise httpx.ReadTimeout("PRIVATE transport timeout", request=request)

    client = DispatchAwareB14Client(settings(), transport=httpx.MockTransport(transport))
    messages = MESSAGES
    if failure == "core_validation":
        messages = [{"role": "user", "content": "x" * 100_001}]
    elif failure == "serialization":
        messages = [{"role": "user", "content": "\ud800"}]

    async def run():
        await reserve(store)
        expected_error = ValueError if failure == "core_validation" else ChatRuntimeError
        with pytest.raises(expected_error):
            await client.complete_registered_quote_model(messages, model=MODEL)
        assert await _refund_active_reservation() is False

    asyncio.run(run())
    dispatched = failure == "transport_timeout"
    assert len(calls) == int(dispatched)
    assert sorted(store.counts.values()) == ([1, 1, 1] if dispatched else [0, 0, 0])
    assert store.bucket_refund_calls == (0 if dispatched else 3)


def test_actual_quote_core_budget_reaches_b14_gateway_with_one_provider_timeout():
    """Actual product/Core payload + actual B14 gateway, provider replaced in memory.

    Restoring the missing max_retries defect makes this same gateway call three
    times. The differential control proves max_attempts=1 alone is insufficient.
    """
    # Test actual product/Core/gateway retry budgets with a synthetic exact ID,
    # NOT the owner-excluded historical NVIDIA catalog route.
    synthetic_model = "test-fixture/b66-quote-budget"
    binding = Binding()
    asyncio.run(B14Client(settings(), service_transport=binding).complete_registered_quote_model(
        MESSAGES, model=synthetic_model,
    ))
    payload = binding.calls[0][1]
    assert payload["business14"]["max_retries"] == 0
    assert payload["business14"]["max_attempts"] == 1
    assert payload["business14"]["allow_external_fallback"] is False

    repo = Path(__file__).resolve().parents[3]
    script = '''
import asyncio, json, os, sys
os.environ["B14_PROVIDER_MODE"] = "live"  # Readiness metadata only.
from app.pilot import gateway
from app.pilot.errors import UpstreamTimeout
from dataclasses import replace
import app.pilot.catalog as cat
from app.pilot.b14_runtime_config import runtime_config
runtime_config.provider_mode = "live"
calls = []
async def provider_double(**kwargs):
    calls.append(kwargs["model_id"])
    raise UpstreamTimeout()
real_sleep = asyncio.sleep
async def zero_sleep(seconds):
    await real_sleep(0)
gateway.plat.call_platform_chat_completions = provider_double
gateway.asyncio.sleep = zero_sleep
payload = json.loads(sys.stdin.read())
# A synthetic route is registered ONLY inside this local subprocess.
# It cannot turn a real excluded route into a positive customer fixture.
# Copy the schema of a currently registered model, never a removed model.
# Supply a dummy in-memory credential because the provider is always mocked
# and must not trigger real upstream network calls.
os.environ["PADIEM_AGNES_API_KEY"] = "sk-test-only-b66-quote-0123456789"
approved = cat.CATALOG_BY_ID["agnes-ai/agnes-3.0-flash"]
cat.CATALOG_BY_ID[payload["model"]] = replace(
    approved, model_id=payload["model"],
    upstream_model="test-fixture/b66-quote-response",
    display_name="Synthetic quote budget transport route"
)
async def run():
    results = []
    for restore_defect in (False, True):
        calls.clear()
        options = dict(payload["business14"])
        if restore_defect:
            del options["max_retries"]
        response = await gateway._handle_alpha_chat("synthetic-b66-guard", {
            **payload, "business14": options,
        })
        results.append([response.status_code, len(calls), json.loads(response.body)["error"]["attempt_count"]])
    return results
print("OFFLINE_RESULT=" + json.dumps(asyncio.run(run())))
'''
    paths = [repo / "apps/korean-ai-platform", repo / "packages/padiem-ai-core"]
    result = subprocess.run(
        [sys.executable, "-c", script], input=json.dumps(payload), text=True,
        capture_output=True, check=True, timeout=30, cwd=repo,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(map(str, paths)), "PYTHONDONTWRITEBYTECODE": "1"},
    )
    output = next(line for line in result.stdout.splitlines() if line.startswith("OFFLINE_RESULT="))
    assert json.loads(output.removeprefix("OFFLINE_RESULT=")) == [[504, 1, 1], [504, 3, 3]]


def test_other_product_core_request_keeps_existing_b14_retry_default():
    from app.b14_client import _execution_request
    from app.task_modes import get_task_mode

    request = _execution_request(
        MESSAGES, skill=get_task_mode(), model=MODEL,
        required_capabilities=("chat",), additional_system_context=None,
    )
    assert "max_retries" not in request.agent.model_policy
