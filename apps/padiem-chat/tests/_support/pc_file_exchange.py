"""PC file-exchange shared test preparation (#8061).

Moved out of test_5895_pc_file_exchange so the test-to-test import ratchet
does not grow: the hub and its consumers all import these names from here.

The pairing store is the real 072 schema, so a foreign `link_id` is refused
by the same rule that built it. The session identity and the lane's two
staging calls are replaced by recorders — nothing here dispatches to a PC
or calls a provider.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import app.pc_file_exchange_routes as exchange
import _support.pc_device_pairing as pairing
from app.oracle_mesh_read_return_routes import _pc_files_command, _response

__all__ = [
    "LANE_SECRET", "NODE", "ORIGIN", "OTHER_NODE", "OUTSIDER", "OWNER",
    "PICTURES", "QUARTERLY", "pairing",
    "_Request", "_Store", "_answer", "_async", "_finished",
    "_hwp_fixture", "_lane_client", "_links", "_sha", "_state",
]

OWNER = pairing.OWNER
OUTSIDER = "usr_" + "b" * 32
ORIGIN = "https://chat.example.test"
NODE = "node/meshdomain1/qa-pc"
OTHER_NODE = "node/meshdomain1/qa-pc-two"
QUARTERLY = "C:/Users/qa/분기보고"
PICTURES = "D:/그림"
LANE_SECRET = "fixture-file-lane-secret-" + "0" * 16


class _Request:
    def __init__(self, state, *, body=None, query=None, method="POST"):
        self.app = SimpleNamespace(state=state)
        self._raw = json.dumps(body).encode("utf-8") if body is not None else b""
        self.query_params = dict(query or {})
        self.method = method
        self.headers = {"content-type": "application/json", "origin": ORIGIN}

    async def body(self):
        return self._raw


class _Store:
    """The calls these routes make on the owner store, kept honest.

    A staged dispatch is recorded as a row, so cancelling one goes through the same
    condition the SQL uses — pending, never handed out, this owner, this run — and a
    route that stopped the wrong row would be caught here rather than in production.
    """

    FAR = "2099-01-01T00:00:00.000Z"

    def __init__(self, *, dispatches=None, originals=None, runs=None):
        self.staged = []
        self.dispatches = dispatches if dispatches is not None else {}
        self.originals = originals if originals is not None else {}
        self.runs = runs if runs is not None else {}
        self.staged_rows = 0

    def stage(self, *, user_id, run_id, kind, command=None, tool_call_ref=None,
              file_path="command"):
        self.staged_rows += 1
        dispatch_id = "dsp_" + format(self.staged_rows, "032x")
        self.dispatches[dispatch_id] = {
            "dispatch_id": dispatch_id, "user_id": user_id, "run_id": run_id, "kind": kind,
            "state": "pending", "expires_at": self.FAR, "command_text": command,
            "command_id": "cmd-" + str(self.staged_rows),
            "revision_ref": "rev-" + str(self.staged_rows),
            "tool_call_ref": tool_call_ref, "file_path": file_path, "nonce_sha256": None,
        }
        return dispatch_id

    async def cancel_oracle_mesh_dispatches_for_run(self, *, user_id, run_id):
        stopped = 0
        for row in self.dispatches.values():
            if (row.get("user_id") != user_id or row.get("run_id") != run_id
                    or row.get("state") != "pending" or row.get("nonce_sha256") is not None):
                continue
            row["state"] = "failed"
            row["termination"] = "cancelled"
            stopped += 1
        return stopped

    async def record_chat_pc_drive_run(self, **fields):
        self.staged.append(fields)
        self.runs[fields["run_id"]] = {
            "run_id": fields["run_id"], "user_id": fields["user_id"],
            "workspace_id": fields["workspace_id"], "conversation_id": "chat_" + "c" * 32,
            "status": "pending",
        }
        return "chat_" + "c" * 32

    async def get_claw_run(self, user_id, run_id):
        row = self.runs.get(run_id)
        return dict(row) if isinstance(row, dict) and row.get("user_id") == user_id else None

    async def get_oracle_mesh_dispatch_for_owner(self, *, user_id, dispatch_id):
        row = self.dispatches.get(dispatch_id)
        return dict(row) if isinstance(row, dict) and row.get("user_id") == user_id else None

    async def read_oracle_mesh_original(self, *, user_id, dispatch_id, conversation_id, message_id):
        row = self.dispatches.get(dispatch_id)
        if row is None or row.get("user_id") != user_id:
            return None
        data = self.originals.get(dispatch_id)
        return None if data is None else (data, row["result_sha256"])


def _links(*, second: bool = False, revoke: bool = False, roots: tuple[str, ...] = (QUARTERLY,)):
    store = pairing.store()

    async def build():
        issued = await store.issue_code(user_id=OWNER, issued_at=pairing._now())
        first = await store.redeem_code(
            code=issued["code"], mesh_node_id=NODE, label="사무실 PC",
            now=pairing._now(), verified=True,
        )
        for path in roots:
            await store.approve_root(user_id=OWNER, link_id=first["link_id"], path=path,
                                     now=pairing._now())
        other = None
        if second:
            issued_two = await store.issue_code(user_id=OWNER, issued_at=pairing._now())
            other = await store.redeem_code(
                code=issued_two["code"], mesh_node_id=OTHER_NODE, label="집 PC",
                now=pairing._now(), verified=True,
            )
            await store.approve_root(user_id=OWNER, link_id=other["link_id"], path=PICTURES,
                                     now=pairing._now())
        if revoke:
            await store.revoke_link(user_id=OWNER, link_id=first["link_id"], now=pairing._now())
        return first, other

    return store, pairing.run(build())


def _state(monkeypatch, *, links=None, uid=OWNER, roots=(QUARTERLY,), store=None,
           dispatches=None, originals=None, runs=None):
    """A signed-in owner, one real pairing store, and a recording PC lane."""

    pairing_store, created = _links(roots=roots) if links is None else links
    state = SimpleNamespace(
        pc_device_pairing_store=pairing_store,
        history_store=store or _Store(dispatches=dispatches, originals=originals, runs=runs),
        oracle_mesh_return_source=SimpleNamespace(configured=True, execution_mode="mesh"),
        control_plane_identity_authority=object(),
    )
    session = SimpleNamespace(session_id="sess-5895", product_id="b62", tenant_id="tnt-5895")
    monkeypatch.setattr(exchange, "auth_ready", lambda _request: True)
    monkeypatch.setattr(exchange, "current_user_id", lambda _request: uid)
    monkeypatch.setattr(
        exchange, "_resolve_chat_owner",
        lambda request, user_id: _async((session, "subject-5895", "workspace-5895")),
    )
    monkeypatch.setattr(exchange, "_check_mesh_grant",
                        lambda request, session, *, device_id=None: _async(True))

    async def resolved_target(request, *, session, selected_device_id, user_id):
        rows = await pairing_store.links_for_owner(user_id=user_id)
        named = [row for row in rows if row.get("mesh_node_id") == selected_device_id]
        if len(named) != 1:
            return None, _response({"ok": False, "error": {"code": "oracle_mesh_device_unverified"}},
                                   status=403)
        row = named[0]
        roots = [root for root in row["roots"] if root.get("state") == "active"]
        return {
            "authorized": True,
            "target": {"node_ref": row["mesh_node_id"], "device_id": row["mesh_node_id"],
                       "link_id": row["link_id"], "label": row["label"], "roots": roots},
            "roots": roots, "account_ref": "acc-5895", "workspace_ref": "ws-5895",
        }, None

    monkeypatch.setattr(exchange, "_engine_pc_files_target", resolved_target)

    captured: list[dict] = []

    async def stage_command(request, *, command, wire, trusted_owner, tool_call_ref,
                            files_target, share_roots=None):
        captured.append({"command": command, "wire": wire, "owner": trusted_owner,
                         "ref": tool_call_ref, "target": files_target,
                         "share_roots": share_roots})
        dispatch_id = state.history_store.stage(
            user_id=trusted_owner[1], run_id=wire["run_id"], kind="command",
            command=command, tool_call_ref=tool_call_ref)
        return _response({"ok": True, "dispatch": {
            "dispatch_id": dispatch_id, "run_id": wire["run_id"], "state": "pending",
            "expires_at": _Store.FAR, "kind": "command",
        }})

    async def stage_read(request, *, wire, trusted_owner, tool_call_ref, target, root, relative):
        captured.append({"read": True, "wire": wire, "root": root, "relative": relative,
                         "ref": tool_call_ref, "target": target})
        dispatch_id = state.history_store.stage(
            user_id=trusted_owner[1], run_id=wire["run_id"], kind="read",
            tool_call_ref=tool_call_ref, file_path=root + "/" + relative)
        return _response({"ok": True, "dispatch": {
            "dispatch_id": dispatch_id, "run_id": wire["run_id"], "state": "pending",
            "expires_at": _Store.FAR, "kind": "read",
        }})

    monkeypatch.setattr(exchange, "dispatch_oracle_mesh_command_intent", stage_command)
    monkeypatch.setattr(exchange, "dispatch_oracle_mesh_file_read_intent", stage_read)
    link_id, other_link_id = (created[0]["link_id"], created[1]["link_id"] if created[1] else None)
    return state, captured, link_id, other_link_id

def _async(value):
    async def ready():
        return value
    return ready()

def _answer(response):
    return response.status_code, json.loads(response.body.decode("utf-8"))

def _finished(state, *, dispatch_id, kind, text, command=None, state_name="done",
              termination=None):
    """One dispatch row exactly as the lane's own SQL would leave it.

    The command text is built by the shipped builders, not copied by hand: which
    answer is a listing, a first look or a subtree sweep is decided by what the PC
    was really asked, so a test that invented the text could pass against a command
    the route no longer sends.
    """

    data = text if isinstance(text, bytes) else text.encode("utf-8")
    row = {
        "dispatch_id": dispatch_id, "user_id": OWNER, "run_id": "run-5895",
        "kind": kind, "state": state_name, "expires_at": "2099-01-01T00:00:00.000Z",
        "command_id": "cmd-1", "revision_ref": "rev-1", "result_sha256": _sha(data),
    }
    if kind == "command":
        row["command_text"] = command if command is not None else _pc_files_command(
            op="list", root=QUARTERLY, relative="",
        )
    if termination is not None:
        row["termination"] = termination
    state.history_store.dispatches[dispatch_id] = row
    state.history_store.originals[dispatch_id] = data
    state.history_store.runs["run-5895"] = {
        "user_id": OWNER, "conversation_id": "chat_" + "c" * 32,
    }


def _sha(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()

def _hwp_fixture() -> bytes:
    # parents[3]: _support -> tests -> padiem-chat -> apps (the fixture lives
    # under apps/padiem-file-lane, as it did from the hub test file).
    return (Path(__file__).resolve().parents[3]
            / "padiem-file-lane" / "tests"
            / "fixtures" / "example.hwp").read_bytes()

def _lane_client(transport):
    from app.file_lane import FileLaneClient

