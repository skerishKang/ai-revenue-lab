"""#5895: the shared PC file-exchange routes answer for the owner and no one else.

The lane's own staging is covered by `test_5015_pc_read_dispatch.py` and the link
directory by `test_5573_pc_pairing_directory_dispatch.py`. What this file can catch
that neither can is the *new* decision these routes make: which of this account's own
PCs a picker call belongs to, what each verb asks the PC for, and what the durable
read answers while the PC is still working.

The pairing store is the real 072 schema, so a foreign `link_id` is refused by the
same rule that built it. The session identity and the lane's two staging calls are
replaced by recorders — nothing here dispatches to a PC or calls a provider.

The shared preparation (_Request/_Store/_links/_state/_finished and the
constants) lives in tests/_support/pc_file_exchange.py (#8061) so consumers
do not import this test file.
"""
from __future__ import annotations

import base64
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import app.pc_file_exchange_routes as exchange                      # noqa: E402
import _support.pc_device_pairing as pairing                       # noqa: E402
from _support.pc_file_exchange import (  # noqa: E402
    OTHER_NODE, OUTSIDER, OWNER, PICTURES, QUARTERLY,
    _Request, _answer, _finished, _hwp_fixture, _lane_client,
    _links, _sha, _state,
)
from app.oracle_mesh_read_return_routes import (                       # noqa: E402
    PC_FILES_LIST_PAGE_SIZE, _pc_files_command,
)


def _carried(command: str) -> list[str]:
    return [
        base64.b64decode(blob, validate=True).decode("utf-8")
        for blob in re.findall(r"FromBase64String\('([A-Za-z0-9+/=]+)'\)", command)
    ]


JSON_ONE = json.dumps([{"Name": "1분기.md", "Length": 2048,
                        "LastWriteTimeUtc": "2026-10-01T00:00:00Z", "PSIsContainer": False},
                       {"Name": "사진", "Length": None,
                        "LastWriteTimeUtc": "2026-10-02T00:00:00Z", "PSIsContainer": True}],
                       ensure_ascii=False)
JSON_FOUND = json.dumps([{"FullName": "D:/그림/명함.png", "Name": "명함.png", "Length": 100,
                          "LastWriteTimeUtc": "2026-10-03T00:00:00Z", "PSIsContainer": False}],
                         ensure_ascii=False)


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
    assert QUARTERLY in _carried(staged["command"])
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
    # #7560: the name is one quoted literal and is wildcard-escaped on the PC.
    assert "WildcardPattern]::Escape('2026*보고서')" in captured[0]["command"]
    assert "-like $padiemFindPattern" in captured[0]["command"]


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
    assert PICTURES in _carried(captured[0]["command"])
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


def _seed(roots: tuple[str, ...] = (QUARTERLY,), name: str = "명함") -> str:
    return exchange._seed_search_command([{"path": path} for path in roots], name)


def _sweep(folder: str, name: str = "명함") -> str:
    return exchange._sweep_command(folder, name)


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


def _page_envelope(rows, *, offset, total, has_more):
    return json.dumps({"offset": offset, "total": total, "has_more": has_more,
                       "items": rows}, ensure_ascii=False)


def _row(name, folder=False):
    return {"Name": name, "Length": None if folder else 10,
            "LastWriteTimeUtc": "2026-10-01T00:00:00Z", "PSIsContainer": folder}


def _listing_body(monkeypatch, text, command=None, *, state=None, dispatch=None):
    # `state` may be shared across pages by a pagination loop: the pairing
    # store and the session identity do not change between pages, only the
    # finished dispatch row does. Rebuilding them per page re-ran the whole
    # migration set hundreds of times for one test.
    if dispatch is None:
        dispatch = "dsp_" + "a" * 32
    if state is None:
        state, _captured, _link, _ = _state(monkeypatch)
    _finished(state, dispatch_id=dispatch, kind="command", text=text, command=command)
    return _answer(pairing.run(exchange.pc_file_exchange_result(
        _Request(state, query={"dispatch_id": dispatch}, method="GET")
    )))


def test_a_listing_page_carries_the_total_and_the_next_cursor(monkeypatch):
    rows = [_row("f%04d" % n) for n in range(PC_FILES_LIST_PAGE_SIZE)]
    status, body = _listing_body(monkeypatch, _page_envelope(
        rows, offset=0, total=4925, has_more=True))
    assert status == 200 and body["state"] == "ready"
    assert len(body["items"]) == PC_FILES_LIST_PAGE_SIZE
    assert body["total"] == 4925 and body["has_more"] is True
    assert body["next_cursor"] == str(PC_FILES_LIST_PAGE_SIZE)


def test_the_last_page_says_there_is_nothing_left(monkeypatch):
    rows = [_row("last%03d" % n) for n in range(25)]
    _status, body = _listing_body(monkeypatch, _page_envelope(
        rows, offset=4900, total=4925, has_more=False))
    assert body["total"] == 4925 and len(body["items"]) == 25
    assert body["has_more"] is False and body["next_cursor"] is None


def test_a_listing_stored_before_paging_is_one_final_page_without_a_total(monkeypatch):
    # A dispatch staged before this change carries a bare row array. It is reported as
    # one final page with no total — never as "the folder ended here".
    _status, body = _listing_body(monkeypatch, JSON_ONE)
    assert len(body["items"]) == 2
    assert body["total"] is None
    assert body["has_more"] is False and body["next_cursor"] is None


@pytest.mark.parametrize("count", [0, 1, 200, 201, 5000])
def test_every_page_sums_to_the_total_without_gaps_or_repeats(monkeypatch, count):
    every = [_row("item%05d" % n) for n in range(count)]
    names = [row["Name"] for row in every]
    # One pairing store and session for every page: only the dispatch row
    # changes per page. (Previously each page rebuilt the full migration
    # set, which cost ~17 s in CI for the 5000-row case.)
    state, _captured, _link, _ = _state(monkeypatch)
    seen, offset, pages = [], 0, 0
    while True:
        window = every[offset:offset + PC_FILES_LIST_PAGE_SIZE]
        has_more = offset + len(window) < count
        _status, body = _listing_body(monkeypatch, _page_envelope(
            window, offset=offset, total=count, has_more=has_more),
            state=state, dispatch="dsp_" + "%032d" % offset)
        assert body["total"] == count
        seen.extend(item["name"] for item in body["items"])
        pages += 1
        if not body["has_more"]:
            break
        offset = int(body["next_cursor"])
        assert pages <= count // PC_FILES_LIST_PAGE_SIZE + 2
    assert seen == names
    assert len(seen) == len(set(seen)) == count


def test_a_name_search_travels_as_a_name_and_never_as_a_pattern():
    # A plain word may ride the provider's own -Filter as a coarse pre-filter; the exact
    # IndexOf test still decides, and the term travels as one quoted literal.
    plain = _pc_files_command(op="list", root=QUARTERLY, relative="", filter_term="보고서")
    assert "보고서" in _carried(plain)
    assert "*보고서*" in _carried(plain)
    assert "-Filter $filter" in plain
    assert "$_.Name.IndexOf($needle," in plain
    assert plain.isascii()

    # A wildcard, a quote or a semicolon is never a pattern: the pre-filter falls back to
    # '*' and the exact term still travels as its own base64 value (#7973/#7974).
    for term in ("a*b", "it's", "q'; Remove-Item x", "x[y]", "a/b"):
        command = _pc_files_command(op="list", root=QUARTERLY, relative="", filter_term=term)
        assert "*" in _carried(command), term
        assert term in _carried(command), term
        assert "Remove-Item" not in command, term
        assert command.isascii(), term
    injected = _pc_files_command(op="list", root=QUARTERLY, relative="",
                                 filter_term="q'; Remove-Item x")
    assert "q'; Remove-Item x" in _carried(injected)

    for bad in ("", None, "line" + chr(10) + "break", "nul" + chr(0)):
        if bad is None:
            # Absent is the plain listing, not an error.
            assert "$needle=" not in _pc_files_command(op="list", root=QUARTERLY, relative="")
            continue
        with pytest.raises(ValueError, match="filter term"):
            _pc_files_command(op="list", root=QUARTERLY, relative="", filter_term=bad)


def test_a_browse_filter_is_refused_when_it_carries_control_characters(monkeypatch):
    for bad in ("", "a" + chr(10) + "b", "a" + chr(127) + "b", 7, True):
        state, captured, _link, _ = _state(monkeypatch)
        status, body = _answer(pairing.run(exchange.pc_file_exchange_browse(
            _Request(state, body={"path": ".", "filter": bad})
        )))
        assert status == 400 and body["error"]["code"] == "pc_exchange_invalid_body", bad
        assert captured == []
    state, captured, _link, _ = _state(monkeypatch)
    status, body = _answer(pairing.run(exchange.pc_file_exchange_browse(
        _Request(state, body={"path": ".", "filter": "보고서"})
    )))
    assert status == 200 and body["state"] == "working" and body["filter"] == "보고서"
    assert "보고서" in _carried(captured[0]["command"])


def test_a_filtered_page_reports_the_number_of_matches_and_pages_them(monkeypatch):
    matches = [_row("match%03d" % n) for n in range(204)]
    state, _captured, _link, _ = _state(monkeypatch)
    seen, offset = [], 0
    while True:
        window = matches[offset:offset + PC_FILES_LIST_PAGE_SIZE]
        has_more = offset + len(window) < 204
        _status, body = _listing_body(monkeypatch, _page_envelope(
            window, offset=offset, total=204, has_more=has_more),
            state=state, dispatch="dsp_" + "%032d" % offset)
        assert body["total"] == 204
        seen.extend(item["name"] for item in body["items"])
        if not body["has_more"]:
            break
        offset = int(body["next_cursor"])
    assert seen == [row["Name"] for row in matches]


def test_a_page_two_asks_the_pc_to_skip_the_page_already_shown(monkeypatch):
    state, captured, _link, _ = _state(monkeypatch)
    status, body = _answer(pairing.run(exchange.pc_file_exchange_browse(
        _Request(state, body={"path": ".", "cursor": "400"})
    )))
    assert status == 200 and body["state"] == "working"
    assert "Select-Object -Skip 400 -First " in captured[0]["command"]
    assert body["cursor"] == "400"


@pytest.mark.parametrize("bad", ["abc", "-1", "1.5", "0x10", "1" * 12, 5, True])
def test_a_malformed_cursor_is_refused_before_anything_is_staged(monkeypatch, bad):
    state, captured, _link, _ = _state(monkeypatch)
    status, body = _answer(pairing.run(exchange.pc_file_exchange_browse(
        _Request(state, body={"path": ".", "cursor": bad})
    )))
    assert status == 400 and body["error"]["code"] == "pc_exchange_invalid_body"
    assert captured == []


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


# ── the legacy .hwp reference: #6126 — never converted, one guidance code ───


def test_a_picked_legacy_hwp_is_refused_locally_with_the_guidance_code(monkeypatch):
    import httpx

    # #6126: the older binary Hangul format is never converted anywhere. The
    # OLE2 signature in the file's own first bytes is the whole decision, so
    # the bytes never travel to the COM2 lane's reader — even a lane that
    # would happily read this exact file.
    seen = []

    def lane(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True, "text": "변환 금지", "chars": 4})

    payload = _hwp_fixture()
    dispatch = "dsp_" + "a" * 32
    state, _captured, _link, _ = _state(monkeypatch)
    state.file_lane_client = _lane_client(httpx.MockTransport(lane))
    _finished(state, dispatch_id=dispatch, kind="read", text=payload)
    state.history_store.dispatches[dispatch]["file_path"] = "C:/Users/qa/작년 축사.hwp"

    status, body = _answer(pairing.run(exchange.pc_file_exchange_reference(
        _Request(state, body={"file_id": dispatch})
    )))

    assert status == 422 and body["error"]["code"] == "legacy_hwp_unsupported", body
    # The refusal is local: zero lane requests, no conversion, no guessing.
    assert seen == []


def test_a_mislabeled_hwpx_named_hwp_keeps_being_read_as_hwpx(monkeypatch):
    import zipfile
    from io import BytesIO

    # A .hwp name whose bytes are a real HWPX (ZIP) package is HWPX: the same
    # pure-Python reader a .hwpx upload takes, no lane, no conversion.
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", b"application/hwp+zip")
        archive.writestr("Contents/section1.xml", (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
            'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
            "<hp:p><hp:runs><hp:t>이름과 다른 HWPX 본문</hp:t></hp:runs></hp:p></hs:sec>"
        ).encode("utf-8"))
    payload = output.getvalue()

    dispatch = "dsp_" + "b" * 32
    state, _captured, _link, _ = _state(monkeypatch)
    _finished(state, dispatch_id=dispatch, kind="read", text=payload)
    state.history_store.dispatches[dispatch]["file_path"] = "C:/Users/qa/보고서.hwp"

    status, body = _answer(pairing.run(exchange.pc_file_exchange_reference(
        _Request(state, body={"file_id": dispatch})
    )))
    assert status == 200 and body["ok"] is True, body
    assert body["name"] == "보고서.hwp"
    assert "이름과 다른 HWPX 본문" in body["text"]


def test_a_hwp_that_is_neither_ole_nor_zip_stays_unreadable(monkeypatch):
    # Neither signature (and not decodable text): the same plain unreadable
    # answer as before #6126, never a guessed conversion.
    dispatch = "dsp_" + "c" * 32
    state, _captured, _link, _ = _state(monkeypatch)
    _finished(state, dispatch_id=dispatch, kind="read",
              text=b"\xff\x00\xfe the owner's undecodable document")
    state.history_store.dispatches[dispatch]["file_path"] = "C:/Users/qa/계약서.hwp"

    status, body = _answer(pairing.run(exchange.pc_file_exchange_reference(
        _Request(state, body={"file_id": dispatch})
    )))
    assert status == 422 and body["error"]["code"] == "pc_reference_unreadable", body
