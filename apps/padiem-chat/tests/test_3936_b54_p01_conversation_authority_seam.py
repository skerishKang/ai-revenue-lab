"""#3936/#4416 — B54 → P01 conversation-authority seam, source-pinned (test-only).

Companion to the merged B14-side proof (PR #4524,
``apps/korean-ai-platform/tests/test_opencode_go_session_bridge_gap.py``). That
test pins the *downstream* half of the #4416 gap: B14's completed and SSE
preview bodies reject a ``session_id`` field, a forged ``x-opencode-session``
header changes nothing, and a missing/forged session never reaches the network.

This file pins the *upstream* half, which is LOCAL1's boundary: what the B54
Claw route actually asserts before it hands a run to P01, and whether any
product / owner / workspace / conversation assertion survives that hop.

Established on current main (source-pinned below, no production change):

* ``_resolve_intake_session_reference`` reads exactly ONE body field
  (``conversation_id``) and re-verifies it against the owner-scoped history
  store before quota, tenant resolution, or P01 dispatch;
* ``resolve_current_b54_canonical_session`` reads exactly one value from the
  request (the signed-cookie user id) and pins the product server-side;
* ``_trusted_p01_request_snapshot`` carries a CLOSED shape whose only identity
  field is ``session_id``, and that value is ``run.run_id`` — per-run, never
  per-conversation.

Missing edge (the reason this stays test-only): no typed
product/owner/workspace/conversation assertion crosses B54 → P01 → Engine →
B14. ``ClawRun``/``ClawTaskIntent`` have no conversation field, so the only
thing that survives the hop is *text*: prior owner turns are concatenated into
``intent.task`` by ``_owner_claw_context``. That is context, not authority.
Widening it requires CENTRAL to confirm a private, signed/internal typed
context type; nothing here changes that contract, and the OpenCode Go provider
stays OFF.

All tests are network-free and use synthetic owner-scoped stores only. No
production D1, provider, model, tier, or routing state is touched.
"""

from __future__ import annotations

import dataclasses
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token

import test_b54_claw_general_p01_routing as base
from test_3930_b54_live_sse_relay import HEADERS as LIVE_HEADERS, _streaming_adapter

GENERAL = base.GENERAL_ROUTE_PATH
CANONICAL_SUBJECT = "sub_" + "a" * 32
CANONICAL_TENANT = "tenant_b54_seam"

_FORBIDDEN_RUN_FIELDS = ("conversation", "tenant", "workspace", "subject", "session")


# ── synthetic owner-scoped conversation authority ───────────────────────────


class _OwnerThreadStore:
    """Owner-scoped conversation store with real server-side id minting.

    Mirrors the shape ``_resolve_intake_session_reference``,
    ``_owner_claw_context``, ``_save_claw_exchange`` and
    ``project_completed_general_run`` each independently require.
    """

    def __init__(self) -> None:
        self.threads: dict[str, dict] = {}
        self.runs: list[dict] = []

    def seed(self, text: str, answer: str) -> str:
        cid = "chat_" + uuid.uuid4().hex
        self.threads[cid] = {
            "id": cid,
            "project_id": None,
            "messages": [
                {"role": "user", "content": text},
                {"role": "assistant", "content": answer},
            ],
        }
        return cid

    async def get_user(self, user_id: str):
        return None

    async def append_exchange(
        self, user_id, conversation_id, user_text, answer, project_id=None
    ) -> str:
        assert user_id == base.SIGNED_IN_USER_ID
        cid = conversation_id or ("chat_" + uuid.uuid4().hex)
        if cid not in self.threads:
            self.threads[cid] = {"id": cid, "project_id": project_id, "messages": []}
        self.threads[cid]["messages"].extend(
            [
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": answer},
            ]
        )
        return cid

    async def get_conversation(self, user_id: str, conversation_id: str):
        if user_id != base.SIGNED_IN_USER_ID:
            return None
        return self.threads.get(conversation_id)

    async def record_claw_run(self, **kwargs):
        self.runs.append(kwargs)


def _bridge(*, subject: str | None = CANONICAL_SUBJECT, tenant: str | None = CANONICAL_TENANT):
    return SimpleNamespace(
        auth_session=SimpleNamespace(
            subject=SimpleNamespace(subject_id=subject),
            tenant_id=tenant,
        )
    )


_DEFAULT_BRIDGE = object()


@contextmanager
def _seam_client(store, adapter, bridge=_DEFAULT_BRIDGE):
    """Real route client; ``bridge`` is the CP session the resolver returns.

    ``bridge=_DEFAULT_BRIDGE`` (the default) uses the canonical subject+tenant
    session; pass ``None`` explicitly to model a signed-out / revoked session.
    """
    settings = base._settings()
    app = create_app(
        settings=settings, history_store=store, claw_p01_adapter=adapter
    )
    with TestClient(app, base_url="https://chat.example.test") as client:
        client.cookies.set(
            SESSION_COOKIE,
            create_session_token(settings, base.SIGNED_IN_USER_ID),
            domain="chat.example.test",
            path="/",
        )
        resolved = _bridge() if bridge is _DEFAULT_BRIDGE else bridge
        with patch(
            "app.b54_canonical_session.resolve_current_b54_canonical_session",
            new=AsyncMock(return_value=resolved),
        ):
            yield client


def _runs(adapter) -> list:
    return [call.args[0] for call in adapter.execute.await_args_list]


def _assert_no_authority_on_run(run) -> None:
    """The run handed to P01 must carry no conversation/tenant/subject field."""
    names = [f.name for f in dataclasses.fields(run)]
    names += [f.name for f in dataclasses.fields(run.intent)]
    for name in names:
        assert not any(token in name for token in _FORBIDDEN_RUN_FIELDS), name


def test_authority_absence_helper_rejects_a_conversation_bearing_run() -> None:
    """Self-check: the structural assertion above is not vacuous.

    If a future change adds a conversation/tenant/subject field to the P01 run
    or its intent, ``_assert_no_authority_on_run`` must reject it.
    """

    @dataclasses.dataclass
    class _Intent:
        task: str
        conversation_id: str

    @dataclasses.dataclass
    class _Run:
        run_id: str
        intent: _Intent

    import pytest

    with pytest.raises(AssertionError):
        _assert_no_authority_on_run(_Run("run_x", _Intent("t", "chat_" + "a" * 32)))


# ── 0. the P01 dispatch argument set is closed ─────────────────────────────


def test_p01_dispatch_arguments_are_a_closed_set() -> None:
    """No conversation/tenant/workspace value may ride along as a dispatch arg."""
    store = _OwnerThreadStore()
    thread = store.seed("closed-args-prior-context", "closed-args-prior-answer")
    adapter = base._make_adapter(subject_lane=True)

    with _seam_client(store, adapter) as client:
        response = client.post(
            GENERAL,
            json=base._payload(
                conversation_id=thread,
                workspace_id="tenant_forged",
                messages=[{"role": "user", "content": "closed-args-probe"}],
            ),
        )

    assert response.status_code == 200, response.text
    kwargs = adapter.execute.await_args.kwargs
    assert set(kwargs) <= {"product_tier", "subject_id", "selected_model_id"}
    assert kwargs["subject_id"] == CANONICAL_SUBJECT
    assert "tenant_forged" not in str(kwargs)

    run = _runs(adapter)[0]
    # The model-only Claw scope is what allows a provider-native prompt; it is
    # a product scope, not an ownership or conversation assertion.
    assert run.intent.repository_ref == "padiem-chat"
    assert run.intent.source_surface == "padiem_claw_general_model_only"
    assert thread not in str(dataclasses.asdict(run.intent))



# ── 1. two conversations cannot share owner history ─────────────────────────


def test_two_conversations_never_share_owner_history() -> None:
    store = _OwnerThreadStore()
    thread_a = store.seed("alpha-unique-prior-context", "alpha-prior-answer")
    thread_b = store.seed("bravo-unique-prior-context", "bravo-prior-answer")
    adapter = base._make_adapter(subject_lane=True)

    with _seam_client(store, adapter) as client:
        first = client.post(
            GENERAL,
            json=base._payload(
                conversation_id=thread_a,
                messages=[{"role": "user", "content": "alpha-current-question"}],
            ),
        )
        second = client.post(
            GENERAL,
            json=base._payload(
                conversation_id=thread_b,
                messages=[{"role": "user", "content": "bravo-current-question"}],
            ),
        )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    runs = _runs(adapter)
    assert len(runs) == 2

    task_a, task_b = runs[0].intent.task, runs[1].intent.task
    assert "alpha-unique-prior-context" in task_a
    assert "alpha-current-question" in task_a
    assert "bravo-unique-prior-context" not in task_a
    assert "bravo-current-question" not in task_a

    assert "bravo-unique-prior-context" in task_b
    assert "bravo-current-question" in task_b
    assert "alpha-unique-prior-context" not in task_b
    assert "alpha-current-question" not in task_b

    assert [row["conversation_id"] for row in store.runs] == [thread_a, thread_b]
    assert {row["workspace_id"] for row in store.runs} == {CANONICAL_TENANT}


# ── 2. same conversation is stable across turns, but has no P01 session ─────


def test_same_conversation_is_stable_across_turns_without_a_p01_session_binding() -> None:
    store = _OwnerThreadStore()
    thread = store.seed("turn-one-prior-context", "turn-one-prior-answer")
    adapter = base._make_adapter(subject_lane=True)

    with _seam_client(store, adapter) as client:
        turn_two = client.post(
            GENERAL,
            json=base._payload(
                conversation_id=thread,
                messages=[{"role": "user", "content": "turn-two-question"}],
            ),
        )
        turn_three = client.post(
            GENERAL,
            json=base._payload(
                conversation_id=thread,
                messages=[{"role": "user", "content": "turn-three-question"}],
            ),
        )

    assert turn_two.status_code == 200, turn_two.text
    assert turn_three.status_code == 200, turn_three.text

    # The owner-visible conversation id is the SAME on every turn.
    assert f'"conversation_id":"{thread}"' in turn_two.text
    assert f'"conversation_id":"{thread}"' in turn_three.text

    runs = _runs(adapter)
    assert len(runs) == 2
    # The P01 identity is NOT stable: it is minted per run, so no Engine-side
    # correlation to the owner conversation exists on the wire.
    assert runs[0].run_id != runs[1].run_id
    assert runs[0].intent.task_id != runs[1].intent.task_id
    for run in runs:
        _assert_no_authority_on_run(run)
        assert thread not in run.run_id
        assert thread not in run.intent.task_id
    # Turn 3 sees turn 2 through the store, not through any run-level binding.
    assert "turn-two-question" in runs[1].intent.task

    assert {row["conversation_id"] for row in store.runs} == {thread}


# ── 3. first turn: no conversation binding, context is text only ───────────


def test_first_turn_dispatches_with_no_conversation_binding_at_all() -> None:
    store = _OwnerThreadStore()
    adapter = base._make_adapter(subject_lane=True)

    with _seam_client(store, adapter) as client:
        response = client.post(
            GENERAL, json=base._payload(messages=[{"role": "user", "content": "first-turn-only"}])
        )

    assert response.status_code == 200, response.text
    runs = _runs(adapter)
    assert len(runs) == 1
    run = runs[0]
    # No prior owner context exists, so the task is the bare latest user turn:
    # the first-turn P01 dispatch carries no conversation identity whatsoever.
    assert run.intent.task == "first-turn-only"
    _assert_no_authority_on_run(run)

    # The durable conversation is minted server-side AFTER completion, never
    # supplied by the browser and never sent to P01.
    assert len(store.runs) == 1
    minted = store.runs[0]["conversation_id"]
    assert minted is not None and minted.startswith("chat_")
    assert f'"conversation_id":"{minted}"' in response.text
    assert minted not in run.intent.task


# ── 4. continuation without canonical tenant fails closed ──────────────────


def test_continuation_without_canonical_tenant_fails_closed_before_dispatch() -> None:
    store = _OwnerThreadStore()
    thread = store.seed("owned-prior-context", "owned-prior-answer")
    adapter = base._make_adapter(subject_lane=True)

    with _seam_client(store, adapter, bridge=_bridge(tenant=None)) as client:
        response = client.post(
            GENERAL,
            json=base._payload(
                conversation_id=thread,
                workspace_id="browser-supplied-tenant",
                messages=[{"role": "user", "content": "continuation-without-tenant"}],
            ),
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "workspace_scope_unavailable"
    adapter.execute.assert_not_awaited()
    assert store.runs == []
    assert "browser-supplied-tenant" not in response.text


def test_continuation_without_canonical_subject_fails_closed_before_dispatch() -> None:
    store = _OwnerThreadStore()
    thread = store.seed("owned-prior-context", "owned-prior-answer")
    adapter = base._make_adapter(subject_lane=True)

    with _seam_client(store, adapter, bridge=None) as client:
        response = client.post(
            GENERAL,
            json=base._payload(
                conversation_id=thread,
                subject_id=CANONICAL_SUBJECT,
                messages=[{"role": "user", "content": "continuation-without-session"}],
            ),
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "canonical_b54_session_unavailable"
    adapter.execute.assert_not_awaited()
    assert store.runs == []


# ── 5. SSE parity: identical conversation + subject authority ──────────────


def test_live_sse_foreign_conversation_denied_before_any_dispatch() -> None:
    store = _OwnerThreadStore()
    adapter = _streaming_adapter()

    with _seam_client(store, adapter) as client:
        client.app.state.claw_live_sse_enabled = True
        response = client.post(
            GENERAL,
            json=base._payload(
                conversation_id="chat_" + "f" * 32,
                messages=[{"role": "user", "content": "sse-foreign-conversation"}],
            ),
            headers=LIVE_HEADERS,
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "conversation_not_found"
    adapter.execute.assert_not_awaited()
    assert store.runs == []


def test_live_sse_and_completed_use_the_same_conversation_and_subject_authority() -> None:
    store = _OwnerThreadStore()
    thread = store.seed("shared-prior-context", "shared-prior-answer")

    completed_adapter = base._make_adapter(subject_lane=True)
    with _seam_client(store, completed_adapter) as client:
        completed = client.post(
            GENERAL,
            json=base._payload(
                conversation_id=thread,
                messages=[{"role": "user", "content": "completed-path-question"}],
            ),
        )

    live_adapter = _streaming_adapter()
    with _seam_client(store, live_adapter) as client:
        client.app.state.claw_live_sse_enabled = True
        live = client.post(
            GENERAL,
            json=base._payload(
                conversation_id=thread,
                messages=[{"role": "user", "content": "live-path-question"}],
            ),
            headers=LIVE_HEADERS,
        )

    assert completed.status_code == 200, completed.text
    assert live.status_code == 200, live.text
    assert "event: p01_event" in live.text

    assert completed_adapter.execute.await_args.kwargs["subject_id"] == CANONICAL_SUBJECT
    assert live_adapter.execute.await_args.kwargs["subject_id"] == CANONICAL_SUBJECT

    # Both paths persist through the same authority: same owner, same
    # conversation, same canonical tenant.
    assert len(store.runs) == 2
    for row in store.runs:
        assert row["user_id"] == base.SIGNED_IN_USER_ID
        assert row["conversation_id"] == thread
        assert row["workspace_id"] == CANONICAL_TENANT
    assert f'"conversation_id":"{thread}"' in live.text


# ── 6. forged browser authority never reaches P01 ──────────────────────────


def test_forged_browser_authority_never_reaches_the_p01_run() -> None:
    store = _OwnerThreadStore()
    thread = store.seed("owned-prior-context", "owned-prior-answer")
    adapter = base._make_adapter(subject_lane=True)
    forged = {
        "subject_id": "sub_" + "b" * 32,
        "tenant_id": "tenant_forged",
        "workspace_id": "tenant_forged",
        "user_id": "usr_forged",
        "session_id": "chat_" + "e" * 32,
        "run_id": "run_" + "d" * 24,
    }

    with _seam_client(store, adapter) as client:
        response = client.post(
            GENERAL,
            json=base._payload(
                conversation_id=thread,
                messages=[{"role": "user", "content": "forged-authority-probe"}],
                **forged,
            ),
        )

    assert response.status_code == 200, response.text
    # The canonical subject comes from the Control Plane session, never the body.
    assert adapter.execute.await_args.kwargs["subject_id"] == CANONICAL_SUBJECT

    run = _runs(adapter)[0]
    serialized = repr(run)
    for value in forged.values():
        assert value not in serialized
    _assert_no_authority_on_run(run)

    row = store.runs[0]
    assert row["user_id"] == base.SIGNED_IN_USER_ID
    assert row["workspace_id"] == CANONICAL_TENANT
    assert row["conversation_id"] == thread
    assert "tenant_forged" not in str(row)
