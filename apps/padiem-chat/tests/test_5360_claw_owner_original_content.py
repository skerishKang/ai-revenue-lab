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
from test_b62_claw_inbox_http_contract import (
    LIST_ALERTS,
    LIST_TASKS,
    _FOREIGN_TENANT,
    _InMemoryInboxStore,
    _OWN_TENANT,
    _client,
    SIGNED_IN_USER_ID,
)

OWNER_TITLE = "삼성상사 30A 케이블 재주문 승인: Authorization: Bearer " + "a" * 24
OWNER_ALERT_TITLE = "MeshCentralTrial 파일 회신 필요: Authorization: Bearer " + "b" * 24
OWNER_BODY = "삼성상사 견적 요청: 케이블 30A 100개, 납기 9월 20일"


def _seed_task(store, task_id, *, title, workspace_id, member_id):
    from kagent.claw_memory import ClawFollowupTask, ClawTaskStatus

    task = ClawFollowupTask(
        task_id=task_id,
        workspace_id=workspace_id,
        member_id=member_id,
        title=title,
        status=ClawTaskStatus.OPEN,
        created_at=datetime.now(timezone.utc),
    )
    store.tasks[task_id] = task
    return task


def _seed_alert(store, alert_id, *, title, workspace_id, visible_to):
    from kagent.claw_memory import (
        ClawAlert,
        ClawAlertKind,
        ClawAlertSeverity,
        ClawAlertStatus,
    )

    alert = ClawAlert(
        alert_id=alert_id,
        workspace_id=workspace_id,
        kind=ClawAlertKind.FOLLOWUP_DUE,
        severity=ClawAlertSeverity.WARN,
        title=title,
        created_at=datetime.now(timezone.utc),
        status=ClawAlertStatus.ACTIVE,
        visible_to_members=tuple(visible_to),
    )
    store.alerts[alert_id] = alert
    return alert


def test_the_owner_reads_their_own_task_and_alert_content_unchanged():
    """The owner's own record reaches the owner byte for byte."""
    store = _InMemoryInboxStore()
    client = _client(store)
    _seed_task(
        store, "task-owner", title=OWNER_TITLE,
        workspace_id=_OWN_TENANT, member_id=SIGNED_IN_USER_ID,
    )
    _seed_alert(
        store, "alert-owner", title=OWNER_ALERT_TITLE,
        workspace_id=_OWN_TENANT, visible_to=(SIGNED_IN_USER_ID,),
    )

    tasks = client.get(LIST_TASKS)
    alerts = client.get(LIST_ALERTS)

    assert tasks.status_code == 200
    assert alerts.status_code == 200
    assert [item["title"] for item in tasks.json()["items"]] == [OWNER_TITLE]
    assert [item["title"] for item in alerts.json()["items"]] == [OWNER_ALERT_TITLE]


def test_a_different_owner_cannot_read_or_touch_the_original_content():
    """A foreign workspace record stays invisible and non-disclosing."""
    store = _InMemoryInboxStore()
    _seed_task(
        store, "task-foreign", title=OWNER_TITLE,
        workspace_id=_FOREIGN_TENANT, member_id=SIGNED_IN_USER_ID,
    )
    client = _client(store)

    listed = client.get(LIST_TASKS)
    patched = client.patch(f"{LIST_TASKS}/task-foreign", json={"status": "done"})
    missing = client.patch(f"{LIST_TASKS}/never-existed", json={"status": "done"})

    assert listed.status_code == 200
    assert listed.json()["items"] == []
    assert patched.status_code == missing.status_code
    assert patched.json() == missing.json()
    assert store.status_writes == 0


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

    projection = store.projection("ws-a")

    assert [record["name"] for record in projection["parties"]] == ["삼성상사"]
    assert OWNER_BODY in repr(projection)
    diagnostic = store.projection("ws-a", include_raw=False)
    assert OWNER_BODY not in repr(diagnostic)
    assert sha256_text(OWNER_BODY) in repr(diagnostic)


def test_a_different_workspace_never_reads_the_owner_memory():
    store = InMemoryClawMemoryStore()
    store.submit_candidate(_candidate(), proposal_id="prop-5360")

    assert store.projection("ws-b")["parties"] == []
    assert store.projection("ws-b")["proposals"] == []
    with pytest.raises(ClawMemoryError):
        store.decide_proposal(
            "prop-5360",
            ClawProposalState.APPROVED,
            workspace_id="ws-b",
            decided_by="owner-2",
            decided_at=datetime(2026, 10, 21, 9, 5, tzinfo=timezone.utc),
        )
