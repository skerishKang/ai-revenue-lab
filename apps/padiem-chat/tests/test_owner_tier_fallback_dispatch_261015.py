"""Owner-pinned per-tier failover must reach B14 on both Chat transports.

Without product_tier B14 defaults to Free, so even an authenticated Plus /
Pro / Max turn silently chooses Free's backup. No provider calls required.
"""
from __future__ import annotations
import asyncio
from types import SimpleNamespace
import pytest
from app import b14_client
from padiem_control_plane.product_tier_routes import FREE_PRIMARY_B14_MODEL_ID

TIERS = [("free","free"),("low","plus"),("medium","pro"),("high","max")]

@pytest.mark.parametrize("profile,expected_tier",TIERS)
def test_completed_chat_propagates_owner_tier(monkeypatch, profile, expected_tier):
    client = b14_client.B14Client(SimpleNamespace(runtime_mode="b14"))
    # The declared Free-grade primary, never a hand-written model id: a stale
    # identity here would quietly select a different execution path.
    monkeypatch.setattr(
        b14_client, "_resolve_b62_policy",
        lambda messages, **kwargs: SimpleNamespace(
            profile=profile, model_id=FREE_PRIMARY_B14_MODEL_ID, messages=messages
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
    assert seen[0]["model"]==FREE_PRIMARY_B14_MODEL_ID

@pytest.mark.parametrize("profile,expected_tier",TIERS)
def test_streamed_chat_propagates_identical_owner_tier(monkeypatch,profile,expected_tier):
    client = b14_client.B14Client(SimpleNamespace(runtime_mode="b14"))
    # The declared Free-grade primary, so this covers the streaming path the
    # Free grade actually takes.
    monkeypatch.setattr(
        b14_client, "_resolve_b62_policy",
        lambda messages, **kwargs: SimpleNamespace(
            profile=profile, model_id=FREE_PRIMARY_B14_MODEL_ID, messages=messages
        ),
    )
    seen=[]
    async def stream(request):
        seen.append(request.agent.model_policy)
        yield b14_client.ChatStreamEvent(delta_content="ok")
        yield b14_client.ChatStreamEvent(done=True)
    monkeypatch.setattr(client,"_stream_core",stream)
    async def run():
        return [e async for e in client.stream_text_auto([{"role":"user","content":"hello"}])]
    events=asyncio.run(run())
    assert [e.delta_content for e in events if e.delta_content]==["ok"]
    assert events[-1].done is True
    assert len(seen)==1
    assert seen[0]["product_tier"]==expected_tier
    # No local attempt pin: the upstream owns the owner-pinned tier fallback.
    assert "max_attempts" not in seen[0]


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
    assert "max_attempts" not in completed.model_policy
