"""#5360: an authorized owner reads their own original business content.

Owner decision 2026-10-20: the authorized account/workspace user and the AI
must get the owner's own original business content in full. Only a real
authentication, ownership and tenant check may withhold it, and credentials
stay filtered at the diagnostic and log boundary.

No live provider, PC, D1 or network call happens here.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.claw_general_routes import _owner_claw_context
from kagent.claw_memory import (
    ClawMemoryCandidate,
    ClawMemoryError,
    ClawMemoryKind,
    ClawMemoryProposal,
    ClawMemorySourceRef,
    ClawPartyMemory,
    ClawPartyRole,
    ClawProposalState,
    ClawSourceOrigin,
    InMemoryClawMemoryStore,
    sha256_text,
)
OWNER_TITLE = "삼성상사 30A 케이블 재주문 승인: Authorization: Bearer " + "a" * 24
OWNER_BODY = "삼성상사 견적 요청: 케이블 30A 100개, 납기 9월 20일"


def test_the_owners_own_conversation_text_reaches_the_model_unchanged(monkeypatch):
    """The AI context carries the owner's original text, not a masked copy."""
    import app.claw_general_routes as routes

    class OwnedStore:
        async def get_conversation(self, user_id, conversation_id, *, product_scope):
            return {
                "id": conversation_id,
                "messages": [
                    {"role": "user", "content": OWNER_BODY},
                    {"role": "assistant", "content": "확인했습니다."},
                ],
            }

    monkeypatch.setattr(routes, "auth_ready", lambda _: True)
    monkeypatch.setattr(routes, "current_user_id", lambda _: "owner")
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(history_store=OwnedStore())))

    context = asyncio.run(_owner_claw_context(request, "chat_" + "a" * 32, "최신 요청"))

    assert OWNER_BODY in context
    assert context.endswith("최신 요청")


def _source(workspace_id: str = "ws-a") -> ClawMemorySourceRef:
    return ClawMemorySourceRef(
        source_id="src-5360",
        workspace_id=workspace_id,
        origin=ClawSourceOrigin.PASTE,
        body_sha256=sha256_text(OWNER_BODY),
        created_at=datetime(2026, 10, 21, 9, 0, tzinfo=timezone.utc),
        raw_excerpt=OWNER_BODY,
    )


def _candidate(workspace_id: str = "ws-a") -> ClawMemoryCandidate:
    return ClawMemoryCandidate(
        candidate_id="cand-5360",
        workspace_id=workspace_id,
        kind=ClawMemoryKind.PARTY,
        payload={"name": "삼성상사", "role": "customer"},
        source=_source(workspace_id),
        created_at=datetime(2026, 10, 21, 9, 0, tzinfo=timezone.utc),
    )


def test_the_owner_memory_projection_carries_the_original_fields_and_body():
    """The authorized workspace owner reads the original body; diagnostics do not."""
    store = InMemoryClawMemoryStore()
    store.submit_candidate(_candidate(), proposal_id="prop-5360")
    store.decide_proposal(
        "prop-5360",
        ClawProposalState.APPROVED,
        workspace_id="ws-a",
        decided_by="owner-1",
        decided_at=datetime(2026, 10, 21, 9, 5, tzinfo=timezone.utc),
    )
    store.apply_proposal(
        "prop-5360",
        workspace_id="ws-a",
        memory_id="mem-5360",
        applied_at=datetime(2026, 10, 21, 9, 6, tzinfo=timezone.utc),
    )

    projection = store.projection("ws-a", member_id="member-1")

    assert [record["name"] for record in projection["parties"]] == ["삼성상사"]
    assert OWNER_BODY in repr(projection)
    diagnostic = store.projection("ws-a", member_id="member-1", include_raw=False)
    assert OWNER_BODY not in repr(diagnostic)
    assert sha256_text(OWNER_BODY) in repr(diagnostic)


def test_a_different_workspace_never_reads_the_owner_memory():
    store = InMemoryClawMemoryStore()
    store.submit_candidate(_candidate(), proposal_id="prop-5360")

    assert store.projection("ws-b", member_id="member-1")["parties"] == []
    assert store.projection("ws-b", member_id="member-1")["proposals"] == []
    with pytest.raises(ClawMemoryError):
        store.decide_proposal(
            "prop-5360",
            ClawProposalState.APPROVED,
            workspace_id="ws-b",
            decided_by="owner-2",
            decided_at=datetime(2026, 10, 21, 9, 5, tzinfo=timezone.utc),
        )
