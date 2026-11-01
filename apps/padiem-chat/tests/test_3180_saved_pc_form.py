"""#3180 ③ — a PC form the owner already uses, saved once and reusable.

The CTO decision this file pins:

* the workbook stays on the owner's PC; the saved record carries only the form's
  structure (sheets, cells, item-row pattern) and the PC-side path reference, in
  the EXISTING saved-quote asset table — no second store and no workbook bytes;
* the repeat fill re-reads the workbook from the PC by that path, reuses the
  stored structure instead of describing it again, and remembers the row-growth
  pattern the fill needed;
* another account sees nothing and cannot fill through the saved form.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent))

import app.b66_pc_form_routes as forms                               # noqa: E402
import app.b66_pc_template_routes as quote_pc                        # noqa: E402
import app.pc_file_exchange_routes as exchange                       # noqa: E402
import test_5895_b66_pc_template as fillbase                         # noqa: E402
import test_5895_pc_file_exchange as base                            # noqa: E402
from app.b66_saved_quote_skill_store import (                        # noqa: E402
    PC_FORM_CALCULATION_AUTHORITY,
    PC_FORM_RENDERER_CONTRACT,
    SKILL_KIND_PC_FORM,
    D1SavedQuoteSkillStore,
    SavedQuoteSkillStoreError,
    build_pc_form_artifact,
    canonicalize_approved_artifact,
)

OWNER = base.OWNER
OTHER = "usr_" + "9" * 32
WORKSPACE = "ws_3180"
LANE_ID = fillbase.LANE_ID
TEMPLATE = fillbase.TEMPLATE
TEMPLATE_NAME = fillbase.TEMPLATE_NAME
FORM_PATH = base.QUARTERLY + "/" + TEMPLATE_NAME
STRUCTURE = {
    "ok": True,
    "sheets": [{
        "name": "견적서", "rows": 40, "columns": 8,
        "merged": ["A1:D1"],
        "cells": [
            {"cell": "A1", "text": "견 적 서", "formula": False},
            {"cell": "A3", "text": "거래처", "formula": False},
            {"cell": "B3", "text": "", "formula": False},
            {"cell": "A6", "text": "날짜", "formula": False},
            {"cell": "B9", "text": "=SUM(B4,B6)", "formula": True},
        ],
    }],
}


class Lane(fillbase.Lane):
    """The COM2 lane, with the structure the real lane describes."""

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == f"/files/{LANE_ID}/structure":
            self.calls.append((request.method, request.url.path))
            return httpx.Response(200, json=STRUCTURE)
        return super().handler(request)


def _db() -> sqlite3.Connection:
    migrations = Path(__file__).resolve().parents[1] / "migrations"
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("CREATE TABLE users (id TEXT PRIMARY KEY)")
    connection.executemany("INSERT INTO users(id) VALUES (?)", [(OWNER,), (OTHER,)])
    for name in ("021_b66_saved_quote_skill.sql", "079_b66_saved_quote_skill_kind.sql"):
        connection.executescript((migrations / name).read_text(encoding="utf-8"))
    return connection


def _store(db) -> D1SavedQuoteSkillStore:
    from app.d1_sqlite import SqliteD1

    return D1SavedQuoteSkillStore(SqliteD1(db))


def _state(monkeypatch, lane, *, answer=fillbase.ANSWER, owner=OWNER, db=None):
    state, history, captured = fillbase._state(monkeypatch, lane, answer=answer)
    connection = db if db is not None else _db()
    state.b66_saved_quote_skill_store = _store(connection)
    monkeypatch.setattr(forms, "auth_ready", lambda _request: True)
    monkeypatch.setattr(forms, "current_user_id", lambda _request: owner)
    monkeypatch.setattr(quote_pc, "auth_ready", lambda _request: True)
    monkeypatch.setattr(quote_pc, "current_user_id", lambda _request: owner)
    monkeypatch.setattr(forms, "_resolve_memory_workspace",
                        lambda _request, _uid: base._async(WORKSPACE))
    monkeypatch.setattr(quote_pc, "_resolve_memory_workspace",
                        lambda _request, _uid: base._async(WORKSPACE))
    return state, history, captured, connection


def _finished(history, dispatch_id, *, path=FORM_PATH):
    base._finished(SimpleNamespace(history_store=history), dispatch_id=dispatch_id,
                   kind="read", text=TEMPLATE)
    history.dispatches[dispatch_id]["file_path"] = path


def _register(state, dispatch_id, *, name="견적서 양식"):
    return base._answer(base.pairing.run(forms.pc_quote_form_register(
        base._Request(state, body={"file_id": dispatch_id, "name": name})
    )))


def _fill(state, dispatch_id, *, form_id=None, request="두암중앙교회 견적서"):
    body = {"file_id": dispatch_id, "request": request}
    if form_id:
        body["form_id"] = form_id
    return base._answer(base.pairing.run(quote_pc.pc_quote_fill(
        base._Request(state, body=body)
    )))


def test_the_form_the_owner_filled_becomes_their_saved_form(monkeypatch):
    lane = Lane()
    state, history, _captured, _db_connection = _state(monkeypatch, lane)
    dispatch = "dsp_" + "1" * 32
    _finished(history, dispatch)

    status, body = _register(state, dispatch)
    assert status == 200 and body["ok"] is True, body
    saved = body["form"]
    assert saved["skill_kind"] == SKILL_KIND_PC_FORM
    assert saved["form_path"] == FORM_PATH
    assert saved["form_filename"] == TEMPLATE_NAME
    assert saved["sheet_count"] == 1
    # The workbook itself is never stored: only its structure was described.
    assert lane.uploaded == [(TEMPLATE_NAME, TEMPLATE)]

    listed = base.pairing.run(state.b66_saved_quote_skill_store.list_skills(
        user_id=OWNER, workspace_id=WORKSPACE,
    ))
    assert len(listed) == 1
    assert listed[0]["skill_kind"] == SKILL_KIND_PC_FORM
    assert listed[0]["form_path"] == FORM_PATH
    assert listed[0]["saved_skill_id"] == saved["saved_skill_id"]


def test_another_account_sees_nothing_and_cannot_fill_through_the_form(monkeypatch):
    lane = Lane()
    state, history, _captured, connection = _state(monkeypatch, lane)
    dispatch = "dsp_" + "2" * 32
    _finished(history, dispatch)
    _status, registered = _register(state, dispatch)

    other_state, other_history, _other_captured, _same = _state(
        monkeypatch, Lane(), owner=OTHER, db=connection,
    )
    _finished(other_history, dispatch)
    assert base.pairing.run(other_state.b66_saved_quote_skill_store.list_skills(
        user_id=OTHER, workspace_id=WORKSPACE,
    )) == []
    # The owner's form id resolves to nothing for another account: the store is
    # owner-scoped, so the refusal is the same non-disclosing 404 as a missing id.
    refusal, _record = base.pairing.run(quote_pc._saved_form(
        base._Request(other_state), OTHER, registered["form"]["saved_skill_id"], FORM_PATH,
    ))
    status, body = base._answer(refusal)
    assert status == 404 and body["error"]["code"] == "form_not_found"


def test_a_repeat_fill_reuses_the_stored_structure_and_remembers_the_row_pattern(monkeypatch):
    answer = json.dumps({
        "client": "두암중앙교회",
        "mapping": {"견적서": {"B3": "두암중앙교회", "B6": "2026-10-28"}},
        "extend": [{"sheet": "견적서", "template_row": 12, "at_row": 13, "count": 2}],
    }, ensure_ascii=False)
    lane = Lane()
    state, history, _captured, connection = _state(monkeypatch, lane, answer=answer)
    template_dispatch = "dsp_" + "3" * 32
    _finished(history, template_dispatch)
    _status, registered = _register(state, template_dispatch)
    form_id = registered["form"]["saved_skill_id"]

    repeat_dispatch = "dsp_" + "4" * 32
    _finished(history, repeat_dispatch)
    lane.calls.clear()
    status, filled = _fill(state, repeat_dispatch, form_id=form_id)

    assert status == 200 and filled["ok"] is True, filled
    assert filled["filled_file_id"] == fillbase.FILLED_ID
    assert filled["form_id"] == form_id
    # The saved form's structure stood in for a fresh description.
    assert ("GET", f"/files/{LANE_ID}/structure") not in lane.calls
    seen = state.b66_quote_interpreter._client.complete.seen
    assert "거래처" in seen["system"] and "품목 행" in seen["system"]

    stored = base.pairing.run(state.b66_saved_quote_skill_store.get_skill(
        user_id=OWNER, workspace_id=WORKSPACE, saved_skill_id=form_id,
    ))
    assert stored["skill_kind"] == SKILL_KIND_PC_FORM
    assert stored["skill"]["form"]["item_rows"] == [
        {"sheet": "견적서", "template_row": 12, "at_row": 13, "count": 2},
    ]


def test_a_different_workbook_cannot_borrow_the_saved_form(monkeypatch):
    lane = Lane()
    state, history, _captured, _connection = _state(monkeypatch, lane)
    template_dispatch = "dsp_" + "5" * 32
    _finished(history, template_dispatch)
    _status, registered = _register(state, template_dispatch)

    elsewhere = "dsp_" + "6" * 32
    _finished(history, elsewhere, path=base.QUARTERLY + "/다른 양식.xlsx")
    status, refusal = _fill(state, elsewhere, form_id=registered["form"]["saved_skill_id"])
    assert status == 409 and refusal["error"]["code"] == "form_path_mismatch"


def test_a_quote_skill_id_is_not_accepted_as_a_pc_form(monkeypatch):
    lane = Lane()
    state, history, _captured, _connection = _state(monkeypatch, lane)
    dispatch = "dsp_" + "7" * 32
    _finished(history, dispatch)
    status, refusal = _fill(state, dispatch, form_id="b66skill_" + "0" * 32)
    assert status == 404 and refusal["error"]["code"] == "form_not_found"


def test_the_form_envelope_never_claims_quote_core_or_carries_bytes():
    artifact = build_pc_form_artifact(
        skill_id="pcform_" + "a" * 32, skill_name="내 견적 양식",
        form={"path": FORM_PATH, "filename": TEMPLATE_NAME,
              "structure": {"sheets": STRUCTURE["sheets"]}, "item_rows": []},
        approved_at="2026-10-29T00:00:00.000Z",
    )
    payload = json.loads(artifact.serialized_json)
    assert artifact.kind == SKILL_KIND_PC_FORM
    assert payload["rendererContract"] == PC_FORM_RENDERER_CONTRACT
    assert payload["calculationAuthority"] == PC_FORM_CALCULATION_AUTHORITY
    assert "bytes" not in artifact.serialized_json and "base64" not in artifact.serialized_json

    # Claiming QuoteCore authority under the pc_form kind is refused.
    payload["calculationAuthority"] = "quote-core"
    with pytest.raises(SavedQuoteSkillStoreError, match="calculation authority"):
        canonicalize_approved_artifact(
            skill_id=payload["id"], skill_name=payload["name"],
            fingerprint=payload["fingerprint"], version=1,
            serialized_json=json.dumps(payload), kind=SKILL_KIND_PC_FORM,
        )

    # A traversal or a bare POSIX root never becomes a stored location.
    for bad in ("../비밀/양식.xlsx", "/etc/passwd", "C:/a//b.xlsx", ""):
        with pytest.raises(SavedQuoteSkillStoreError):
            build_pc_form_artifact(
                skill_id="pcform_" + "b" * 32, skill_name="양식",
                form={"path": bad, "filename": TEMPLATE_NAME,
                      "structure": {"sheets": STRUCTURE["sheets"]}, "item_rows": []},
                approved_at="2026-10-29T00:00:00.000Z",
            )


def test_an_owner_registered_form_still_validates_as_the_skill_kind_is_unknown():
    artifact = build_pc_form_artifact(
        skill_id="pcform_" + "c" * 32, skill_name="내 견적 양식",
        form={"path": FORM_PATH, "filename": TEMPLATE_NAME,
              "structure": {"sheets": STRUCTURE["sheets"]}, "item_rows": []},
        approved_at="2026-10-29T00:00:00.000Z",
    )
    with pytest.raises(SavedQuoteSkillStoreError, match="skill kind"):
        canonicalize_approved_artifact(
            skill_id=artifact.skill_id, skill_name=artifact.skill_name,
            fingerprint=artifact.fingerprint, version=1,
            serialized_json=artifact.serialized_json, kind="essay",
        )


def test_migration_079_is_additive_and_keeps_existing_rows_as_skills():
    sql = (Path(__file__).resolve().parents[1] / "migrations"
           / "079_b66_saved_quote_skill_kind.sql").read_text(encoding="utf-8")
    assert "ALTER TABLE b66_saved_quote_skill ADD COLUMN skill_kind" in sql
    assert "DEFAULT 'skill'" in sql
    for forbidden in ("DROP TABLE", "project_files_rebuilt", "UPDATE b66_saved_quote_skill"):
        assert forbidden not in sql


def test_the_quote_screen_lists_and_reuses_the_saved_form():
    """The screen half: the same list, the PC form marked, and no re-pick."""

    script = (Path(__file__).resolve().parents[1] / "static" / "b66-quote-runtime.js").read_text(
        encoding="utf-8"
    )
    for needle in (
        '"/api/b66/pc-quote/forms"',
        '"/api/b66/pc-quote/fill"',
        'form_id: skill.saved_skill_id',
        'form_path',
        "이 양식을 내 견적서로 저장",
        "(내 PC 양식)",
    ):
        assert needle in script, needle
    # The repeat fill re-reads the workbook from the PC; it never re-registers
    # and never sends a saved form through the quote interpreter.
    assert 'saved.data.ok !== true' in script
    assert 'if (isPcForm(savedSkill))' in script


def test_confirmed_cell_mapping_is_persisted_and_used_on_repeat(monkeypatch):
    lane = Lane()
    state, history, _, _ = _state(monkeypatch, lane)
    dispatch = "dsp_" + "b" * 32
    _finished(history, dispatch)
    mapping = {"recipient": {"sheet": "견적서", "cell": "B3"}}
    response = forms.pc_quote_form_register(base._Request(state, body={
        "file_id": dispatch, "name": "가상 양식", "mapping": mapping,
    }))
    status, registered = base._answer(base.pairing.run(response))
    assert status == 200
    form_id = registered["form"]["saved_skill_id"]
    stored = base.pairing.run(state.b66_saved_quote_skill_store.get_skill(
        user_id=OWNER, workspace_id=WORKSPACE, saved_skill_id=form_id,
    ))
    assert stored["skill"]["form"]["mapping"] == mapping
    status, _ = _fill(state, dispatch, form_id=form_id, request="가상 거래처")
    assert status == 200
    assert '"recipient"' in state.b66_quote_interpreter._client.complete.seen["system"]


def test_confirmed_mapping_must_reference_valid_sheet_and_cell(monkeypatch):
    lane = Lane()
    state, history, _, _ = _state(monkeypatch, lane)
    dispatch = "dsp_" + "c" * 32
    _finished(history, dispatch)
    response = forms.pc_quote_form_register(base._Request(state, body={
        "file_id": dispatch, "name": "가상 양식",
        "mapping": {"unit_price": {"sheet": "다른 시트", "cell": "D9"}},
    }))
    status, body = base._answer(base.pairing.run(response))
    assert status == 422 and body["error"]["code"] == "form_invalid"


def test_analyzing_form_returns_candidates_without_saving(monkeypatch):
    lane = Lane()
    state, history, _, _ = _state(monkeypatch, lane)
    dispatch = "dsp_" + "d" * 32
    _finished(history, dispatch)
    response = forms.pc_quote_form_register(base._Request(state, body={
        "file_id": dispatch, "name": "가상 양식", "analyze_only": True,
    }))
    status, body = base._answer(base.pairing.run(response))
    assert status == 200
    assert body["analysis"]["recipient"]["candidates"][0]["cell"] == "B3"
    assert base.pairing.run(state.b66_saved_quote_skill_store.list_skills(
        user_id=OWNER, workspace_id=WORKSPACE,
    )) == []
