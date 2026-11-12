"""#7602 — a run-out lease hands the readers out again, and only the readers.

#7562 decided re-delivery from ``kind``: a ``read`` (the file download lane) was
handed out again, while a ``command`` or ``desktop`` was settled as uncertain
because the PC may already have run it. That covered the file read but not the
other readers: file list, search and chunk read travel as ``kind='command'``
because they run the reviewed PowerShell lane, so a dropped response lost them
even though running one twice changes nothing.

``read_only`` is the server's read/write word for the operation it staged. A row
that predates the column (NULL) keeps the old ``kind`` rule exactly.
"""
from __future__ import annotations

import asyncio
import hashlib
from types import SimpleNamespace

import pytest

from app import oracle_mesh_read_return_routes as routes
from test_4139_mesh_original import _dispatch_kwargs, fixture

EXPIRED = "2000-01-01T00:00:00.000Z"
OWNER = "usr_owner_4139"
RUN = "run-original-1"
WORKSPACE = "ws-1"
ROOT = "C:/Users/limone/Documents/견적"

READ_COMMANDS = {
    "list": routes._pc_files_command(op="list", root=ROOT, relative="."),
    "search": routes.pc_search_command(
        roots=[{"label": "문서", "path": ROOT}],
        query="견적", mode="name", limit=routes.PC_SEARCH_MAX_LIMIT,
    ),
    "read_chunk": routes.pc_read_chunk_command(
        root=ROOT, relative="견적.txt", offset=0, length=1024,
    ),
}

WRITE_COMMANDS = {
    "write": "Set-Content -LiteralPath 'C:/a.txt' -Value hi",
    "delete": "Remove-Item -LiteralPath 'C:/a.txt'",
}


def _nonce(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _staged(store, run_id: str, **overrides) -> str:
    asyncio.run(store.record_claw_run(
        user_id=OWNER, run_id=run_id, channel="web", action="txt_read",
        title="Claw: lease", status="pending", conversation_id="chat_" + "c" * 32,
        workspace_id=WORKSPACE,
    ))
    row = asyncio.run(store.create_oracle_mesh_dispatch(
        **_dispatch_kwargs(run_id=run_id, **overrides)
    ))
    return row["dispatch_id"]


def _claimed(store, run_id: str, label: str, **overrides) -> str:
    dispatch_id = _staged(store, run_id, **overrides)
    handed = asyncio.run(store.oldest_pending_oracle_mesh_dispatch())
    assert handed["dispatch_id"] == dispatch_id
    assert asyncio.run(store.claim_oracle_mesh_dispatch(
        dispatch_id=dispatch_id, nonce_sha256=_nonce(label),
    )) is True
    return dispatch_id


def _lease(store, dispatch_id: str, instant: str) -> None:
    asyncio.run(store._run(
        "UPDATE oracle_mesh_dispatch SET claimed_until=? WHERE dispatch_id=?",
        instant, dispatch_id,
    ))


def _row(store, dispatch_id: str) -> dict:
    return asyncio.run(store._first(
        "SELECT state, termination, nonce_sha256, read_only "
        "FROM oracle_mesh_dispatch WHERE dispatch_id=?",
        dispatch_id,
    ))


def test_the_server_reads_only_the_readers_and_never_a_writer():
    """The read/write word comes from the resolved op, not from a request."""
    assert {
        op for op in routes._PC_FILES_OPS if routes._pc_files_read_only(op)
    } == {"list", "read", "read_chunk", "search"}
    # Anything unknown — including something a body might invent — is a write.
    for unknown in ("", "read_only", "READ", None, 1, "write", "edit", "move", "delete"):
        assert routes._pc_files_read_only(unknown) is False


@pytest.mark.parametrize("op", sorted(READ_COMMANDS))
def test_each_read_command_is_handed_out_again_after_the_lease_runs_out(tmp_path, op):
    store, _bucket = fixture(tmp_path)
    dispatch_id = _claimed(
        store, "run-7602-read-" + op, "first",
        kind="command", command_text=READ_COMMANDS[op],
        read_only=routes._pc_files_read_only(op),
    )
    _lease(store, dispatch_id, EXPIRED)

    again = asyncio.run(store.oldest_pending_oracle_mesh_dispatch())
    assert again is not None and again["dispatch_id"] == dispatch_id
    assert asyncio.run(store.claim_oracle_mesh_dispatch(
        dispatch_id=dispatch_id, nonce_sha256=_nonce("second"),
    )) is True
    assert _row(store, dispatch_id) == {
        "state": "pending", "termination": None,
        "nonce_sha256": _nonce("second"), "read_only": 1,
    }


@pytest.mark.parametrize("op", sorted(WRITE_COMMANDS))
def test_a_write_command_is_still_settled_and_never_handed_out_again(tmp_path, op):
    store, _bucket = fixture(tmp_path)
    dispatch_id = _claimed(
        store, "run-7602-write-" + op, "first",
        kind="command", command_text=WRITE_COMMANDS[op],
        read_only=routes._pc_files_read_only(op),
    )
    _lease(store, dispatch_id, EXPIRED)

    assert asyncio.run(store.oldest_pending_oracle_mesh_dispatch()) is None
    assert asyncio.run(store.claim_oracle_mesh_dispatch(
        dispatch_id=dispatch_id, nonce_sha256=_nonce("second"),
    )) is False
    assert _row(store, dispatch_id) == {
        "state": "failed", "termination": "no_reply",
        "nonce_sha256": _nonce("first"), "read_only": 0,
    }


def test_a_request_that_says_read_cannot_turn_a_write_into_a_read(monkeypatch):
    """A ``read_only``/``kind`` field in the wire is not a value this route reads."""
    captured: dict = {}

    class _History:
        async def get_claw_run(self, user_id, run_id):
            return {
                "run_id": run_id, "workspace_id": WORKSPACE,
                "conversation_id": "chat_" + "d" * 32,
            }

        async def get_local_task_correlation(self, user_id, run_id):
            return None

        async def create_oracle_mesh_dispatch(self, **fields):
            captured.update(fields)
            return {**fields, "dispatch_id": "dsp_" + "e" * 32, "state": "pending"}

    class _Identity:
        async def resolve_connector_owner_scope(self, *, session_id):
            return {"account_ref": "acct-1", "workspace_ref": WORKSPACE}

    async def _target(request, mesh_source, *, account_ref, owner_id, device_id):
        return {"node_ref": "node-1", "device_id": "device-1"}

    monkeypatch.setattr(
        routes, "_channel_source",
        lambda request: SimpleNamespace(execution_mode=routes.EXECUTION_MODE_MESH),
    )
    monkeypatch.setattr(routes, "_owner_command_target", _target)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        control_plane_identity_authority=_Identity(), history_store=_History(),
    )))
    response = asyncio.run(routes.dispatch_oracle_mesh_command_intent(
        request,
        command="Remove-Item -LiteralPath 'C:/a.txt'",
        # The body claims the read word; the route resolves a shell command.
        wire={"run_id": RUN, "device_id": "device-1", "confirmed": True,
              "read_only": True, "kind": "read"},
        trusted_owner=(
            SimpleNamespace(tenant_id=WORKSPACE, session_id="sess-7602"),
            OWNER, WORKSPACE,
        ),
    ))

    assert response.status_code == 200
    assert captured["read_only"] is False


def test_two_results_for_one_redelivered_read_are_applied_once(tmp_path):
    store, _bucket = fixture(tmp_path)
    dispatch_id = _claimed(
        store, "run-7602-duplicate", "first",
        kind="command", command_text=READ_COMMANDS["list"], read_only=True,
    )
    _lease(store, dispatch_id, EXPIRED)
    assert asyncio.run(store.claim_oracle_mesh_dispatch(
        dispatch_id=dispatch_id, nonce_sha256=_nonce("second"),
    )) is True

    first = asyncio.run(store.consume_oracle_mesh_dispatch(
        dispatch_id=dispatch_id, nonce="second",
    ))
    assert first is not None and first["claim"] == "first"
    # The same delivery arriving twice — and a late one under the old nonce —
    # changes nothing: the pending -> received update had one winner.
    assert asyncio.run(store.consume_oracle_mesh_dispatch(
        dispatch_id=dispatch_id, nonce="second",
    )) is None
    assert asyncio.run(store.consume_oracle_mesh_dispatch(
        dispatch_id=dispatch_id, nonce="first",
    )) is None
    assert _row(store, dispatch_id)["state"] == "received"
    # Once the result is stored, a further delivery is refused as well.
    asyncio.run(store._run(
        "UPDATE oracle_mesh_dispatch SET state='done' WHERE dispatch_id=?",
        dispatch_id,
    ))
    assert asyncio.run(store.consume_oracle_mesh_dispatch(
        dispatch_id=dispatch_id, nonce="second",
    )) is None


@pytest.mark.parametrize("kind,command_text,redelivered", [
    ("read", None, True),
    ("command", "hostname.exe", False),
])
def test_a_row_without_the_new_word_keeps_the_old_kind_rule(
    tmp_path, kind, command_text, redelivered,
):
    """Existing rows have read_only NULL and behave exactly as before."""
    store, _bucket = fixture(tmp_path)
    dispatch_id = _claimed(
        store, "run-7602-legacy-" + kind, "first",
        kind=kind, command_text=command_text,
        read_only=None,
    )
    assert _row(store, dispatch_id)["read_only"] is None
    _lease(store, dispatch_id, EXPIRED)

    handed = asyncio.run(store.oldest_pending_oracle_mesh_dispatch())
    if redelivered:
        assert handed is not None and handed["dispatch_id"] == dispatch_id
        assert _row(store, dispatch_id)["state"] == "pending"
    else:
        assert handed is None
        assert _row(store, dispatch_id) == {
            "state": "failed", "termination": "no_reply",
            "nonce_sha256": _nonce("first"), "read_only": None,
        }
