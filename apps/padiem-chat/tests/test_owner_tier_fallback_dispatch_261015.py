"""Owner-pinned per-tier failover must reach B14 on both Chat transports.

Without product_tier B14 defaults to Free, so even an authenticated Plus /
Pro / Max turn silently chooses Free's backup. No provider calls required.
"""
from __future__ import annotations
import asyncio
from types import SimpleNamespace
import pytest
from app import b14_client

TIERS = [("free","free"),("low","plus"),("medium","pro"),("high","max")]

@pytest.mark.parametrize("profile,expected_tier",TIERS)
def test_completed_chat_propagates_owner_tier(monkeypatch, profile, expected_tier):
    client = b14_client.B14Client(SimpleNamespace(runtime_mode="b14"))
    monkeypatch.setattr(
        b14_client, "_resolve_b62_policy",
        lambda messages, **kwargs: SimpleNamespace(
            profile=profile, model_id="opencode-go/beam-free", messages=messages
        ),
    )
    seen=[]
    async def completion(messages, **kwargs):
        seen.append(kwargs)
        return {"answer":"ok","runtime":"b14","skill":{},"route":{}}
    monkeypatch.setattr(client,"_complete_text",completion)
    out=asyncio.run(client.complete([{"role":"user","content":"hello"}]))
    assert out["answer"]=="ok"
    assert len(seen)==1
    assert seen[0]["product_tier"]==expected_tier
    assert seen[0]["model"]=="opencode-go/beam-free"

@pytest.mark.parametrize("profile,expected_tier",TIERS)
def test_streamed_chat_propagates_identical_owner_tier(monkeypatch,profile,expected_tier):
    client = b14_client.B14Client(SimpleNamespace(runtime_mode="b14"))
    monkeypatch.setattr(
        b14_client, "_resolve_b62_policy",
        lambda messages, **kwargs: SimpleNamespace(
            profile=profile, model_id="opencode-go/beam-free", messages=messages
        ),
    )
    seen=[]
    async def completion(messages,**kwargs):
        seen.append(kwargs)
        return {"answer":"ok"}
    monkeypatch.setattr(client,"_complete_text",completion)
    async def run():
        return [e async for e in client.stream_text_auto([{"role":"user","content":"hello"}])]
    events=asyncio.run(run())
    assert [e.delta_content for e in events if e.delta_content]==["ok"]
    assert events[-1].done is True
    assert len(seen)==1
    assert seen[0]["product_tier"]==expected_tier


def test_chat_does_not_pin_owner_tier_dispatch_to_one_attempt():
    profile = b14_client._agent_profile(
        skill=b14_client.get_task_mode(),
        model="google/gemini-3.1-flash-lite",
        required_capabilities=("free",),
        product_tier="free",
        tier_stream_fallback=True,
    )
    assert profile.model_policy["allow_external_fallback"] is False
    assert "max_attempts" not in profile.model_policy
    assert profile.model_policy["product_tier"] == "free"
    completed = b14_client._agent_profile(
        skill=b14_client.get_task_mode(),
        model="google/gemini-3.1-flash-lite",
        required_capabilities=("free",),
        product_tier="free",
    )
    assert completed.model_policy["max_attempts"] == 1
