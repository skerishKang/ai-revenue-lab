"""#5895: the shared PC file-exchange routes answer for the owner and no one else.

The lane's own staging is covered by `test_5015_pc_read_dispatch.py` and the link
directory by `test_5573_pc_pairing_directory_dispatch.py`. What this file can catch
that neither can is the *new* decision these routes make: which of this account's own
PCs a picker call belongs to, what each verb asks the PC for, and what the durable
read answers while the PC is still working.

The pairing store is the real 072 schema, so a foreign `link_id` is refused by the
same rule that built it. The session identity and the lane's two staging calls are
replaced by recorders — nothing here dispatches to a PC or calls a provider.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))

import app.pc_file_exchange_routes as exchange                      # noqa: E402
import test_5573_pc_device_pairing as pairing                       # noqa: E402
from app.oracle_mesh_read_return_routes import (                       # noqa: E402
    PC_FILES_LIST_DEFAULT_LIMIT, _pc_files_command, _response,
)

OWNER = pairing.OWNER
OUTSIDER = "usr_" + "b" * 32
ORIGIN = "https://chat.example.test"
NODE = "node/meshdomain1/qa-pc"
OTHER_NODE = "node/meshdomain1/qa-pc-two"
QUARTERLY = "C:/Users/qa/분기보고"
PICTURES = "D:/그림"
JSON_ONE = json.dumps([{"Name": "1분기.md", "Length": 2048,
                        "LastWriteTimeUtc": "2026-10-01T00:00:00Z", "PSIsContainer": False},
                       {"Name": "사진", "Length": None,
                        "LastWriteTimeUtc": "2026-10-02T00:00:00Z", "PSIsContainer": True}],
                       ensure_ascii=False)
JSON_FOUND = json.dumps([{"FullName": "D:/그림/명함.png", "Name": "명함.png", "Length": 100,
                          "LastWriteTimeUtc": "2026-10-03T00:00:00Z", "PSIsContainer": False}],
                         ensure_ascii=False)


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

    async def stage_command(request, *, command, wire, trusted_owner, tool_call_ref, files_target):
        captured.append({"command": command, "wire": wire, "owner": trusted_owner,
                         "ref": tool_call_ref, "target": files_target})
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


# ── the owner's own PC, and nobody else's ────────────────────────────────

def test_browse_lists_the_owner_folder_on_the_owner_pc(monkeypatch):
    state, captured, link_id, _ = _state(monkeypatch)
    status, body = _answer(pairing.run(exchange.pc_file_exchange_browse(
        _Request(state, body={"path": "."})
    )))

    assert status == 200 and body["ok"] is True and body["state"] == "working", body
    assert exchange.DISPATCH_ID.fullmatch(body["dispatch_id"])
    assert body["run_id"].startswith("chat_pcq_") and body["conversation_id"]
    staged = captured[0]
    assert staged["target"] is not None
    assert "Get-ChildItem -LiteralPath '" + QUARTERLY + "'" in staged["command"]
    assert "PSIsContainer" in staged["command"]


def test_a_foreign_link_is_not_confirmed_to_exist(monkeypatch):
    state, captured, _link_id, _ = _state(monkeypatch)
    status, body = _answer(pairing.run(exchange.pc_file_exchange_browse(
        _Request(state, body={"link_id": "pclink_" + "f" * 32, "path": "."})
    )))
    assert status == 404 and body["error"]["code"] == "pc_link_not_found"
    assert captured == []


def test_a_malformed_link_id_is_not_dropped_into_a_guess(monkeypatch):
    state, captured, _link_id, _ = _state(monkeypatch)
    status, body = _answer(pairing.run(exchange.pc_file_exchange_browse(
        _Request(state, body={"link_id": "pclink-not-really", "path": "."})
    )))
    # Dropping an id that is not shaped like one would silently turn a tampered
    # choice into "whichever PC this account has", which is the guessing the rule
    # forbids; the call is refused before any dispatch exists.
    assert status == 400 and body["error"]["code"] == "pc_exchange_link_id_invalid"
    assert captured == []


def test_another_account_cannot_use_the_owners_link(monkeypatch):
    pairing_store, created = _links()
    state, captured, link_id, _ = _state(monkeypatch, links=(pairing_store, created), uid=OUTSIDER)
    status, body = _answer(pairing.run(exchange.pc_file_exchange_browse(
        _Request(state, body={"link_id": link_id, "path": "."})
    )))
    # Another account's link is simply not there: the answer is the same 404 a
    # missing link gets, so no caller can probe whose PC is whose.
    assert status == 404 and body["error"]["code"] == "pc_link_not_found"
    assert captured == []


def test_two_pcs_ask_the_owner_instead_of_being_guessed(monkeypatch):
    pairing_store, created = _links(second=True)
    state, captured, first, second = _state(monkeypatch, links=(pairing_store, created))

    status, body = _answer(pairing.run(exchange.pc_file_exchange_find(
        _Request(state, body={"name": "견적"})
    )))
    assert status == 409 and body["error"]["code"] == "pc_link_selection_required", body
    assert sorted(link["link_id"] for link in body["links"]) == sorted([first, second])
    assert captured == []

    status, body = _answer(pairing.run(exchange.pc_file_exchange_find(
        _Request(state, body={"name": "견적", "link_id": second})
    )))
    assert status == 200 and body["ok"] is True
    assert PICTURES in captured[0]["command"] and QUARTERLY not in captured[0]["command"]


def test_a_revoked_link_cannot_be_used(monkeypatch):
    pairing_store, created = _links(revoke=True)
    state, captured, link_id, _ = _state(monkeypatch, links=(pairing_store, created))
    status, body = _answer(pairing.run(exchange.pc_file_exchange_browse(
        _Request(state, body={"link_id": link_id, "path": "."})
    )))
    assert status == 404 and body["error"]["code"] == "pc_link_not_found"
    assert captured == []


def test_a_link_without_an_approved_folder_reads_nothing(monkeypatch):
    state, captured, link_id, _ = _state(monkeypatch, roots=())
    status, body = _answer(pairing.run(exchange.pc_file_exchange_browse(
        _Request(state, body={"link_id": link_id, "path": "."})
    )))
    assert status == 403 and body["error"]["code"] == "pc_folder_not_approved"
    assert captured == []


# ── what each verb asks the PC for ───────────────────────────────────────

def test_a_search_starts_at_the_granted_folders_and_caps_nothing(monkeypatch):
    pairing_store, created = _links(second=True)
    state, captured, first, second = _state(monkeypatch, links=(pairing_store, created))

    status, body = _answer(pairing.run(exchange.pc_file_exchange_find(
        _Request(state, body={"name": "견적서", "link_id": first})
    )))
    assert status == 200, body
    command = captured[0]["command"]
    # The CTO rule: an answer that silently stops at a number is a wrong answer.
    for forbidden in ("-First", "Select-Object -First"):
        assert forbidden not in command, forbidden
    assert QUARTERLY in command and PICTURES not in command
    # The first look does not descend: its folder rows are the plan for the rest.
    assert " -Recurse " not in command and "$_.PSIsContainer -or" in command
    assert body["folder"] is None and body["remaining"] == []
    assert body["run_id"].startswith("chat_pcq_")

    status, body = _answer(pairing.run(exchange.pc_file_exchange_find(
        _Request(state, body={"name": "견적서", "link_id": second})
    )))
    assert status == 200 and PICTURES in captured[1]["command"]
    assert QUARTERLY not in captured[1]["command"]


def test_a_search_sweeps_one_folder_at_a_time_inside_one_run(monkeypatch):
    state, captured, link_id, _ = _state(monkeypatch)
    _status, first = _answer(pairing.run(exchange.pc_file_exchange_find(
        _Request(state, body={"name": "견적서", "link_id": link_id})
    )))
    run_id = first["run_id"]

    status, body = _answer(pairing.run(exchange.pc_file_exchange_find(
        _Request(state, body={"name": "견적서", "link_id": link_id, "run_id": run_id,
                              "folder": QUARTERLY + "/2026",
                              "remaining": [QUARTERLY + "/사진"]})
    )))
    assert status == 200 and body["ok"] is True, body
    command = captured[1]["command"]
    assert " -Recurse " in command and QUARTERLY + "/2026" in command
    assert "-First" not in command
    assert body["run_id"] == run_id and body["folder"] == QUARTERLY + "/2026"
    assert body["remaining"] == [QUARTERLY + "/사진"]
    # One operation, one record: the whole sweep stays in the run the first call made,
    # and each folder is its own call the lane can hand out on its own.
    assert len(state.history_store.staged) == 1
    assert captured[0]["ref"] != captured[1]["ref"]
    assert len(state.history_store.dispatches) == 2


def test_a_queue_entry_outside_the_granted_folders_is_not_searched(monkeypatch):
    state, captured, link_id, _ = _state(monkeypatch, roots=("C:/Users/qa",))
    _status, first = _answer(pairing.run(exchange.pc_file_exchange_find(
        _Request(state, body={"name": "견적서", "link_id": link_id})
    )))
    run_id = first["run_id"]
    for body in (
        {"name": "견적서", "link_id": link_id, "run_id": run_id,
         "folder": "C:/Windows", "remaining": []},
        {"name": "견적서", "link_id": link_id, "run_id": run_id,
         "folder": "C:/Users/qa/2026", "remaining": ["C:/Windows"]},
        {"name": "견적서", "link_id": link_id, "run_id": run_id, "folder": "C:/Users/qa/2026"},
        {"name": "견적서", "link_id": link_id, "run_id": run_id, "remaining": []},
    ):
        status, answer = _answer(pairing.run(exchange.pc_file_exchange_find(
            _Request(state, body=body)
        )))
        assert status == 422, (body, answer)
    # Only the first look was staged. The folder now, or one of the folders still
    # waiting, is not allowed to reach past what this account granted.
    assert len(captured) == 1


def test_another_account_cannot_sweep_inside_someone_elses_search(monkeypatch):
    state, _captured, link_id, _ = _state(monkeypatch)
    owner_run = _answer(pairing.run(exchange.pc_file_exchange_find(
        _Request(state, body={"name": "견적서", "link_id": link_id})
    )))[1]["run_id"]

    # The outsider has a PC of their own — the same machine, linked by another
    # account — so this is not a "no PC" answer: it is the run that is not theirs.
    outsider_store = pairing.store()

    async def build():
        issued = await outsider_store.issue_code(user_id=OUTSIDER, issued_at=pairing._now())
        row = await outsider_store.redeem_code(
            code=issued["code"], mesh_node_id=OTHER_NODE, label="다른 계정 PC",
            now=pairing._now(), verified=True,
        )
        await outsider_store.approve_root(user_id=OUTSIDER, link_id=row["link_id"],
                                          path=PICTURES, now=pairing._now())
        return row

    outsider_state, outsider_captured, outsider_link, _ = _state(
        monkeypatch, links=(outsider_store, (pairing.run(build()), None)), uid=OUTSIDER,
    )
    status, body = _answer(pairing.run(exchange.pc_file_exchange_find(
        _Request(outsider_state, body={"name": "견적서", "link_id": outsider_link,
                                       "run_id": owner_run})
    )))
    # The run id is only a handle: the row, its owner and its workspace are read back,
    # so another account's search is not found rather than explained.
    assert status == 404 and body["error"]["code"] == "pc_run_not_found", body
    assert outsider_captured == []


def test_a_name_with_wildcards_stays_the_name_the_owner_typed(monkeypatch):
    state, captured, link_id, _ = _state(monkeypatch)
    status, _body = _answer(pairing.run(exchange.pc_file_exchange_find(
        _Request(state, body={"name": "2026*보고서", "link_id": link_id})
    )))
    assert status == 200
    assert "-like '*2026`*보고서*'" in captured[0]["command"]


def test_fetch_reads_a_file_and_never_a_folder(monkeypatch):
    state, captured, link_id, _ = _state(monkeypatch)
    status, body = _answer(pairing.run(exchange.pc_file_exchange_fetch(
        _Request(state, body={"path": ".", "link_id": link_id})
    )))
    assert status == 422 and body["error"]["code"] == "oracle_mesh_file_path_invalid"
    assert captured == []

    status, body = _answer(pairing.run(exchange.pc_file_exchange_fetch(
        _Request(state, body={"path": "1분기.md", "link_id": link_id})
    )))
    assert status == 200 and body["ok"] is True
    assert body["name"] == "1분기.md"
    assert exchange.DISPATCH_ID.fullmatch(body["dispatch_id"])
    assert captured[0]["read"] is True and captured[0]["relative"] == "1분기.md"


def test_a_path_outside_the_granted_folder_is_refused(monkeypatch):
    state, captured, link_id, _ = _state(monkeypatch)
    status, body = _answer(pairing.run(exchange.pc_file_exchange_fetch(
        _Request(state, body={"path": "../../Windows/win.ini", "link_id": link_id})
    )))
    assert status == 422 and captured == []


def test_two_granted_folders_are_offered_and_never_opened_by_guess(monkeypatch):
    pairing_store, created = _links(second=True)
    state, captured, first, _second = _state(monkeypatch, links=(pairing_store, created))
    pairing.run(pairing_store.approve_root(
        user_id=OWNER, link_id=first, path=PICTURES, now=pairing._now(),
    ))

    status, body = _answer(pairing.run(exchange.pc_file_exchange_browse(
        _Request(state, body={"link_id": first, "path": "."})
    )))
    # The top of a PC with two grants is a choice, exactly as a second PC is: the
    # answer names the folders in the owner's own labels and no command runs.
    assert status == 409 and body["error"]["code"] == "pc_folder_selection_required", body
    assert [folder["path"] for folder in body["folders"]] == ["분기보고/", "그림/"]
    assert all("C:/" not in str(folder) and QUARTERLY not in str(folder) for folder in body["folders"])
    assert captured == []

    status, body = _answer(pairing.run(exchange.pc_file_exchange_browse(
        _Request(state, body={"link_id": first, "path": "그림/"})
    )))
    assert status == 200 and body["ok"] is True
    assert "Get-ChildItem -LiteralPath '" + PICTURES + "'" in captured[0]["command"]
    assert QUARTERLY not in captured[0]["command"]


def test_a_found_file_is_read_by_the_path_the_search_reported(monkeypatch):
    state, captured, link_id, _ = _state(monkeypatch, roots=("C:/Users/qa",))
    status, body = _answer(pairing.run(exchange.pc_file_exchange_fetch(
        _Request(state, body={"path": "C:/Users/qa/2026/견적서.xlsx", "link_id": link_id})
    )))
    # A search answers with the PC's own full path, and the owner picks from that
    # list: the path is read through the grant it sits inside, not re-typed.
    assert status == 200 and body["ok"] is True, body
    assert captured[0]["root"] == "C:/Users/qa" and captured[0]["relative"] == "2026/견적서.xlsx"


def test_a_path_below_no_granted_folder_still_reads_nothing(monkeypatch):
    state, captured, link_id, _ = _state(monkeypatch, roots=("C:/Users/qa",))
    status, _body = _answer(pairing.run(exchange.pc_file_exchange_fetch(
        _Request(state, body={"path": "C:/Windows/win.ini", "link_id": link_id})
    )))
    assert status == 422 and captured == []


def test_a_picker_operation_is_a_real_run_with_a_durable_record(monkeypatch):
    state, captured, link_id, _ = _state(monkeypatch)
    status, body = _answer(pairing.run(exchange.pc_file_exchange_browse(
        _Request(state, body={"link_id": link_id, "path": "."})
    )))
    assert status == 200
    staged = state.history_store.staged[0]
    assert staged["run_id"] == body["run_id"]
    assert staged["action"] == "pc_files_query" and staged["conversation_id"] is None
    assert captured[0]["ref"].startswith(body["run_id"] + ":pc_file_exchange:")


def test_cancel_stops_the_owners_own_queued_command(monkeypatch):
    state, _captured, link_id, _ = _state(monkeypatch)
    run_id = _answer(pairing.run(exchange.pc_file_exchange_find(
        _Request(state, body={"name": "견적서", "link_id": link_id})
    )))[1]["run_id"]
    _answer(pairing.run(exchange.pc_file_exchange_find(
        _Request(state, body={"name": "견적서", "link_id": link_id, "run_id": run_id,
                              "folder": QUARTERLY + "/2026", "remaining": []})
    )))
    rows = [row for row in state.history_store.dispatches.values()
            if row["run_id"] == run_id]
    assert len(rows) == 2 and all(row["state"] == "pending" for row in rows)

    status, body = _answer(pairing.run(exchange.pc_file_exchange_cancel(
        _Request(state, body={"run_id": run_id})
    )))
    assert status == 200 and body["ok"] is True and body["state"] == "cancelled", body
    assert body["stopped"] == 2 and body["run_id"] == run_id
    assert all(row["state"] == "failed" and row["termination"] == "cancelled"
               for row in rows)


def test_a_command_the_pc_already_holds_is_left_to_finish(monkeypatch):
    state, _captured, link_id, _ = _state(monkeypatch)
    run_id = _answer(pairing.run(exchange.pc_file_exchange_find(
        _Request(state, body={"name": "견적서", "link_id": link_id})
    )))[1]["run_id"]
    held = next(iter(state.history_store.dispatches.values()))
    held["nonce_sha256"] = "e" * 64

    status, body = _answer(pairing.run(exchange.pc_file_exchange_cancel(
        _Request(state, body={"run_id": run_id})
    )))
    # The executor holds this one: refusing it would make the connector resend a
    # result nobody is waiting for, which holds the queue longer than letting it end.
    assert status == 200 and body["ok"] is True and body["stopped"] == 0
    assert held["state"] == "pending" and held["nonce_sha256"] == "e" * 64


def test_a_run_that_is_not_a_picker_run_is_not_cancelled(monkeypatch):
    state, _captured, _link_id, _ = _state(monkeypatch)
    for run_id in ("chat_" + "c" * 32, "run-5895", 42):
        status, body = _answer(pairing.run(exchange.pc_file_exchange_cancel(
            _Request(state, body={"run_id": run_id})
        )))
        assert status == 400, (run_id, body)
        assert body["error"]["code"] == "pc_exchange_run_id_invalid", run_id
    assert [row for row in state.history_store.dispatches.values()
            if row.get("termination") == "cancelled"] == []


def test_a_cancelled_command_is_told_as_stopped_not_as_a_failed_pc(monkeypatch):
    dispatch = "dsp_" + "3" * 32
    state, _captured, _link, _ = _state(monkeypatch)
    _finished(state, dispatch_id=dispatch, kind="command", text="{}",
              state_name="failed", termination="cancelled")
    status, body = _answer(pairing.run(exchange.pc_file_exchange_result(
        _Request(state, query={"dispatch_id": dispatch}, method="GET")
    )))
    assert status == 200 and body["ok"] is True and body["state"] == "cancelled", body
    assert "found" not in body and "items" not in body


def test_a_pc_that_really_did_not_answer_is_still_a_failure(monkeypatch):
    dispatch = "dsp_" + "2" * 32
    state, _captured, _link, _ = _state(monkeypatch)
    _finished(state, dispatch_id=dispatch, kind="command", text="{}",
              state_name="failed", termination="no_reply")
    status, body = _answer(pairing.run(exchange.pc_file_exchange_result(
        _Request(state, query={"dispatch_id": dispatch}, method="GET")
    )))
    assert status == 502 and body["error"]["code"] == "pc_dispatch_failed"


def test_the_first_look_answers_what_matched_and_which_folders_are_left(monkeypatch):
    dispatch = "dsp_" + "1" * 32
    state, _captured, _link, _ = _state(monkeypatch)
    _finished(state, dispatch_id=dispatch, kind="command", command=_seed((QUARTERLY,)),
              text=('[{"FullName":"' + QUARTERLY + '/2026","Name":"2026","Length":null,'
                    '"PSIsContainer":true},'
                    '{"FullName":"' + QUARTERLY + '/견적서.xlsx","Name":"견적서.xlsx",'
                    '"Length":9000,"PSIsContainer":false}]'))
    status, body = _answer(pairing.run(exchange.pc_file_exchange_result(
        _Request(state, query={"dispatch_id": dispatch}, method="GET")
    )))
    assert status == 200 and body["state"] == "ready", body
    assert [row["name"] for row in body["found"]] == ["견적서.xlsx"]
    assert body["folders"] == [QUARTERLY + "/2026"]


def test_a_folder_sweep_answers_only_its_own_matches(monkeypatch):
    dispatch = "dsp_" + "0" * 32
    state, _captured, _link, _ = _state(monkeypatch)
    _finished(state, dispatch_id=dispatch, kind="command",
              command=_sweep(QUARTERLY + "/2026"),
              text=('[{"FullName":"' + QUARTERLY + '/2026/견적서.xlsx",'
                    '"Name":"견적서.xlsx","Length":9000,"PSIsContainer":false}]'))
    status, body = _answer(pairing.run(exchange.pc_file_exchange_result(
        _Request(state, query={"dispatch_id": dispatch}, method="GET")
    )))
    assert status == 200 and len(body["found"]) == 1
    assert "folders" not in body
    assert body["found"][0]["folder"] == QUARTERLY + "/2026"


def test_a_reference_read_hands_back_the_words_of_the_owners_file(monkeypatch):
    dispatch = "dsp_" + "4" * 32
    state, _captured, _link, _ = _state(monkeypatch)
    _finished(state, dispatch_id=dispatch, kind="read", text="작년 신년사 본문입니다")
    state.history_store.dispatches[dispatch]["file_path"] = "C:/Users/qa/작년 신년사.txt"
    status, body = _answer(pairing.run(exchange.pc_file_exchange_reference(
        _Request(state, body={"file_id": dispatch})
    )))
    assert status == 200 and body["ok"] is True, body
    assert body["text"] == "작년 신년사 본문입니다"
    assert body["name"] == "작년 신년사.txt"
    assert body["chars"] == len("작년 신년사 본문입니다")


def test_a_reference_read_refuses_a_file_it_cannot_read(monkeypatch):
    dispatch = "dsp_" + "5" * 32
    state, _captured, _link, _ = _state(monkeypatch)
    _finished(state, dispatch_id=dispatch, kind="read",
                  text=bytes([0x50, 0x4B, 0x03, 0x04, 0xFF, 0xFE]) + b"binary")
    state.history_store.dispatches[dispatch]["file_path"] = "C:/Users/qa/낡은 파일.bin"
    status, body = _answer(pairing.run(exchange.pc_file_exchange_reference(
        _Request(state, body={"file_id": dispatch})
    )))
    assert status == 422 and body["error"]["code"] == "pc_reference_unreadable"


def test_a_reference_read_is_owner_scoped_and_needs_a_finished_fetch(monkeypatch):
    done = "dsp_" + "6" * 32
    waiting = "dsp_" + "7" * 32
    state, _captured, _link, _ = _state(monkeypatch)
    _finished(state, dispatch_id=done, kind="read", text="본문")
    state.history_store.dispatches[waiting] = {
        "dispatch_id": waiting, "user_id": OWNER, "kind": "read", "state": "pending",
        "expires_at": "2099-01-01T00:00:00.000Z",
    }

    status, body = _answer(pairing.run(exchange.pc_file_exchange_reference(
        _Request(state, body={"file_id": waiting})
    )))
    assert status == 409 and body["error"]["code"] == "oracle_mesh_result_not_ready"

    outsider = _state(monkeypatch, uid=OUTSIDER)[0]
    status, body = _answer(pairing.run(exchange.pc_file_exchange_reference(
        _Request(outsider, body={"file_id": done})
    )))
    # Another account's fetch is not found, exactly like a missing one.
    assert status == 404 and body["error"]["code"] == "pc_dispatch_not_found"


# ── the durable read the progress display watches ────────────────────────

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
            op="list", root=QUARTERLY, relative="", limit=PC_FILES_LIST_DEFAULT_LIMIT,
        )
    if termination is not None:
        row["termination"] = termination
    state.history_store.dispatches[dispatch_id] = row
    state.history_store.originals[dispatch_id] = data
    state.history_store.runs["run-5895"] = {
        "user_id": OWNER, "conversation_id": "chat_" + "c" * 32,
    }


def _seed(roots: tuple[str, ...] = (QUARTERLY,), name: str = "명함") -> str:
    return exchange._seed_search_command([{"path": path} for path in roots], name)


def _sweep(folder: str, name: str = "명함") -> str:
    return exchange._sweep_command(folder, name)


def _sha(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def test_a_still_running_operation_is_working_and_not_a_failure(monkeypatch):
    dispatch = "dsp_" + "c" * 32
    state, _captured, _link, _ = _state(
        monkeypatch,
        dispatches={dispatch: {
            "dispatch_id": dispatch, "user_id": OWNER, "kind": "command", "state": "pending",
            "expires_at": "2099-01-01T00:00:00.000Z",
        }},
    )
    status, body = _answer(pairing.run(exchange.pc_file_exchange_result(
        _Request(state, query={"dispatch_id": dispatch}, method="GET")
    )))
    assert status == 200 and body["state"] == "working" and body["poll_seconds"] == exchange.RESULT_POLL_SECONDS


def test_an_operation_that_outlived_its_own_dispatch_is_named(monkeypatch):
    dispatch = "dsp_" + "d" * 32
    state, _captured, _link, _ = _state(
        monkeypatch,
        dispatches={dispatch: {
            "dispatch_id": dispatch, "user_id": OWNER, "kind": "command", "state": "pending",
            "expires_at": "2000-01-01T00:00:00.000Z",
        }},
    )
    status, body = _answer(pairing.run(exchange.pc_file_exchange_result(
        _Request(state, query={"dispatch_id": dispatch}, method="GET")
    )))
    assert status == 410 and body["error"]["code"] == "pc_dispatch_expired"


# ── putting a file back: #5573's write, and the backup it takes first ──────

ACCOUNT_OK = json.dumps({"ok": True, "op": "write", "reason": None,
                         "target": QUARTERLY + "/축사.txt",
                         "backup": "C:/.padiem-backup/2026-10-28/축사.txt", "bytes": 18},
                        ensure_ascii=False)
ACCOUNT_REFUSED = json.dumps({"ok": False, "op": "write", "reason": "backup_failed",
                              "target": QUARTERLY + "/축사.txt", "backup": None, "bytes": 0},
                             ensure_ascii=False)


def _account_line(account: str) -> str:
    import base64

    return "PADIEM_PC_ACCOUNT=" + base64.b64encode(account.encode("utf-8")).decode("ascii")


def test_save_writes_with_the_backup_that_the_write_lane_takes_first(monkeypatch):
    state, captured, link_id, _ = _state(monkeypatch)
    status, body = _answer(pairing.run(exchange.pc_file_exchange_save(
        _Request(state, body={"path": "축사.txt", "content": "본문입니다", "link_id": link_id})
    )))
    assert status == 200 and body["ok"] is True, body
    assert body["name"] == "축사.txt"
    command = captured[0]["command"]
    assert QUARTERLY + "/축사.txt" in command
    assert ".padiem-backup" in command
    # The copy that makes the change undoable comes before the bytes are written.
    assert 0 < command.index("Copy-Item") < command.index("[IO.File]::WriteAllBytes")
    # One line, and the account printed as an expression: on the PC's own shell a
    # bare `Write-Output 'A=' + $b` reaches three arguments and prints three lines.
    assert "\n" not in command
    assert "Write-Output ('PADIEM_PC_ACCOUNT=' + $encoded)" in command
    # No prompt of any kind is generated: the account says the change happened.
    for forbidden in ("Read-Host", "$Confirm", "ShouldProcess", "Confirm-"):
        assert forbidden not in command, forbidden


def test_saving_onto_the_granted_folder_itself_is_refused(monkeypatch):
    state, captured, link_id, _ = _state(monkeypatch)
    status, _body = _answer(pairing.run(exchange.pc_file_exchange_save(
        _Request(state, body={"path": ".", "content": "본문입니다", "link_id": link_id})
    )))
    assert status == 422 and captured == []


def test_the_save_call_takes_one_source_and_never_both(monkeypatch):
    state, captured, link_id, _ = _state(monkeypatch)
    for body in ({"path": "축사.txt", "link_id": link_id},
                 {"path": "축사.txt", "content": "본문", "file_id": "dsp_" + "9" * 32,
                  "link_id": link_id}):
        status, answer = _answer(pairing.run(exchange.pc_file_exchange_save(
            _Request(state, body=body)
        )))
        assert status == 422 and answer["error"]["code"] == "pc_exchange_content_required"
    assert captured == []


def test_a_file_brought_over_is_saved_from_the_bytes_the_server_verified(monkeypatch):
    import base64

    dispatch = "dsp_" + "9" * 32
    state, captured, link_id, _ = _state(monkeypatch)
    _finished(state, dispatch_id=dispatch, kind="read", text="본문입니다")
    status, body = _answer(pairing.run(exchange.pc_file_exchange_save(
        _Request(state, body={"path": "새로 저장.txt", "file_id": dispatch, "link_id": link_id})
    )))
    assert status == 200 and body["ok"] is True, body
    payload = base64.b64encode("본문입니다".encode("utf-8")).decode("ascii")
    assert payload in captured[0]["command"]


def test_a_file_id_that_is_not_the_owners_is_not_saved(monkeypatch):
    dispatch = "dsp_" + "8" * 32
    pairing_store, created = _links()
    state, captured, link_id, _ = _state(
        monkeypatch, links=(pairing_store, created), uid=OUTSIDER,
        dispatches={dispatch: {
            "dispatch_id": dispatch, "user_id": OWNER, "kind": "read", "state": "done",
            "expires_at": "2099-01-01T00:00:00.000Z", "result_sha256": _sha(b"someone elses file"),
        }},
    )
    status, answer = _answer(pairing.run(exchange.pc_file_exchange_save(
        _Request(state, body={"path": "축사.txt", "file_id": dispatch, "link_id": link_id})
    )))
    assert status == 404 and answer["error"]["code"] == "pc_link_not_found"
    assert captured == []


def test_another_account_cannot_save_on_the_owners_pc(monkeypatch):
    pairing_store, created = _links()
    state, captured, link_id, _ = _state(monkeypatch, links=(pairing_store, created),
                                         uid=OUTSIDER)
    status, answer = _answer(pairing.run(exchange.pc_file_exchange_save(
        _Request(state, body={"path": "축사.txt", "content": "본문", "link_id": link_id})
    )))
    assert status == 404 and answer["error"]["code"] == "pc_link_not_found"
    assert captured == []


def test_the_saved_answer_is_the_pcs_own_account_of_what_it_wrote(monkeypatch):
    dispatch = "dsp_" + "7" * 32
    state, _captured, _link, _ = _state(monkeypatch)
    _finished(state, dispatch_id=dispatch, kind="command",
              text="step output\n" + _account_line(ACCOUNT_OK))
    status, body = _answer(pairing.run(exchange.pc_file_exchange_result(
        _Request(state, query={"dispatch_id": dispatch}, method="GET")
    )))
    assert status == 200 and body["ok"] is True and body["state"] == "ready"
    assert body["saved"]["target"] == QUARTERLY + "/축사.txt"
    assert body["saved"]["backup"] == "C:/.padiem-backup/2026-10-28/축사.txt"
    assert body["saved"]["bytes"] == 18


def test_a_write_the_pc_refused_is_reported_as_refused(monkeypatch):
    dispatch = "dsp_" + "6" * 32
    state, _captured, _link, _ = _state(monkeypatch)
    _finished(state, dispatch_id=dispatch, kind="command", text=_account_line(ACCOUNT_REFUSED))
    status, body = _answer(pairing.run(exchange.pc_file_exchange_result(
        _Request(state, query={"dispatch_id": dispatch}, method="GET")
    )))
    # The PC said no — a backup that failed — so the screen is not handed a success.
    assert status == 200 and body["ok"] is False and body["state"] == "ready"
    assert body["saved"]["reason"] == "backup_failed"


def test_an_unparsable_account_line_is_not_invented_into_a_saved_answer(monkeypatch):
    dispatch = "dsp_" + "5" * 32
    state, _captured, _link, _ = _state(monkeypatch)
    _finished(state, dispatch_id=dispatch, kind="command",
              text="PADIEM_PC_ACCOUNT=not-base64-at-all")
    _status, body = _answer(pairing.run(exchange.pc_file_exchange_result(
        _Request(state, query={"dispatch_id": dispatch}, method="GET")
    )))
    # No account the server can read means no claim about what the PC wrote.
    assert "saved" not in body and body["items"] == []


def test_the_listing_answer_is_the_folders_own_entries(monkeypatch):
    dispatch = "dsp_" + "e" * 32
    state, _captured, _link, _ = _state(monkeypatch)
    _finished(state, dispatch_id=dispatch, kind="command", text=JSON_ONE)
    status, body = _answer(pairing.run(exchange.pc_file_exchange_result(
        _Request(state, query={"dispatch_id": dispatch}, method="GET")
    )))
    assert status == 200 and body["state"] == "ready"
    assert [item["name"] for item in body["items"]] == ["1분기.md", "사진"]
    assert body["items"][0]["kind"] == "file" and body["items"][0]["size_bytes"] == 2048
    assert body["items"][1]["kind"] == "folder"


def test_the_search_answer_keeps_the_folder_each_name_was_found_in(monkeypatch):
    dispatch = "dsp_" + "f" * 32
    state, _captured, _link, _ = _state(monkeypatch)
    _finished(state, dispatch_id=dispatch, kind="command", text=JSON_FOUND,
              command=_sweep("D:/그림"))
    status, body = _answer(pairing.run(exchange.pc_file_exchange_result(
        _Request(state, query={"dispatch_id": dispatch}, method="GET")
    )))
    assert status == 200 and body["state"] == "ready"
    assert body["found"][0]["name"] == "명함.png"
    assert body["found"][0]["path"] == "D:/그림/명함.png"
    assert body["found"][0]["folder"] == "D:/그림"


def test_two_files_of_one_name_each_keep_their_own_folder(monkeypatch):
    dispatch = "dsp_" + "e" * 32
    state, _captured, _link, _ = _state(monkeypatch)
    _finished(state, dispatch_id=dispatch, kind="command", command=_sweep("C:/바탕화면"), text=(
        '[{"FullName":"C:/명함.png","Name":"명함.png","Length":10,'
        '"PSIsContainer":false},'
        '{"FullName":"D:/그림/명함.png","Name":"명함.png","Length":20,'
        '"PSIsContainer":false}]'
    ))
    status, body = _answer(pairing.run(exchange.pc_file_exchange_result(
        _Request(state, query={"dispatch_id": dispatch}, method="GET")
    )))
    # Both rows carry the same name, so the folder has to come from the row itself:
    # matching by name would show one folder twice and hide where the other file is.
    assert status == 200 and len(body["found"]) == 2
    assert [item["folder"] for item in body["found"]] == ["C:", "D:/그림"]
    assert [item["size_bytes"] for item in body["found"]] == [10, 20]


def test_text_arrives_as_text_and_everything_else_arrives_as_a_file(monkeypatch):
    text_dispatch = "dsp_" + "1" * 32
    binary_dispatch = "dsp_" + "2" * 32
    state, _captured, _link, _ = _state(monkeypatch)
    _finished(state, dispatch_id=text_dispatch, kind="read", text="본문입니다")
    # A zip header, not text: the sheet a menu wants to keep as a file.
    _finished(state, dispatch_id=binary_dispatch, kind="read",
              text=bytes([0x50, 0x4B, 0x03, 0x04, 0xFF, 0xFE]) + b"binary")

    _status, body = _answer(pairing.run(exchange.pc_file_exchange_result(
        _Request(state, query={"dispatch_id": text_dispatch}, method="GET")
    )))
    assert body["content_kind"] == "text" and body["content"] == "본문입니다"
    assert body["file_id"] == text_dispatch

    _status, binary = _answer(pairing.run(exchange.pc_file_exchange_result(
        _Request(state, query={"dispatch_id": binary_dispatch}, method="GET")
    )))
    assert binary["content_kind"] == "file" and binary["content"] is None
    assert binary["file_id"] == binary_dispatch

    answer = pairing.run(exchange.pc_file_exchange_file(
        _Request(state, query={"dispatch_id": binary_dispatch}, method="GET")
    ))
    assert answer.status_code == 200
    assert answer.body == b"PK\x03\x04\xff\xfebinary"
    assert answer.headers["x-padiem-pc-content-sha256"] == binary["sha256"]


def test_another_accounts_operation_is_not_addressable_at_all(monkeypatch):
    dispatch = "dsp_" + "3" * 32
    state, _captured, _link, _ = _state(
        monkeypatch, uid=OUTSIDER,
        dispatches={dispatch: {"dispatch_id": dispatch, "user_id": OWNER, "kind": "read",
                               "state": "done", "expires_at": "2099-01-01T00:00:00.000Z"}},
    )
    status, body = _answer(pairing.run(exchange.pc_file_exchange_result(
        _Request(state, query={"dispatch_id": dispatch}, method="GET")
    )))
    assert status == 404 and body["error"]["code"] == "pc_dispatch_not_found"


def test_a_dispatch_id_from_another_grammar_is_never_looked_up(monkeypatch):
    state, _captured, _link, _ = _state(monkeypatch)
    for value in ("", "dsp_1", "../dispatches", "dsp_" + "z" * 32):
        status, body = _answer(pairing.run(exchange.pc_file_exchange_result(
            _Request(state, query={"dispatch_id": value}, method="GET")
        )))
        assert status == 404 and body["error"]["code"] == "pc_dispatch_not_found", value


def test_a_pinned_output_that_no_longer_matches_its_digest_is_not_served(monkeypatch):
    dispatch = "dsp_" + "4" * 32
    state, _captured, _link, _ = _state(monkeypatch)
    _finished(state, dispatch_id=dispatch, kind="read", text="본문")
    state.history_store.dispatches[dispatch]["result_sha256"] = _sha(b"something else")
    status, body = _answer(pairing.run(exchange.pc_file_exchange_result(
        _Request(state, query={"dispatch_id": dispatch}, method="GET")
    )))
    assert status == 503 and body["error"]["code"] == "oracle_mesh_original_unavailable"
