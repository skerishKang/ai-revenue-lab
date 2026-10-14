"""B66 #4466/#4412: conversation state machine, facts contract, D1 slot.

The server — never the model or the browser — owns intent transitions, quote
fact validation and the write boundary. These tests prove that from the pure
logic up, including the real SQL migration and the private D1 slot.
"""
from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import threading
from pathlib import Path

import pytest

from app.b66_ai_conversation import (
    B66ConversationError,
    ConversationRevisionConflict,
    MODE_GENERAL,
    MODE_QUOTE,
    append_history,
    apply_message_transition,
    bump_revision,
    cancel_staged_transition,
    choose_method_transition,
    confirm_transition,
    conversation_prompt,
    delta_overwrites_known_facts,
    empty_state,
    merge_facts,
    missing_fields,
    next_question,
    normalize_conversation_state,
    normalize_facts,
    normalize_facts_delta,
    parse_model_output,
    state_summary,
)
from app.b66_ai_conversation_store import D1ConversationStore

MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "041_b66_ai_conversation.sql"

A = "usr_" + "a" * 32
B = "usr_" + "b" * 32


def _model_payload(reply, intent, facts=None):
    return json.dumps({"reply": reply, "intent": intent, "facts": facts}, ensure_ascii=False)


# ── intent transitions: the word 견적 alone never opens authoring ──

def test_general_intent_stays_general():
    state = apply_message_transition(empty_state(), "안녕하세요!", "general", {})
    assert state["mode"] == MODE_GENERAL
    assert state["_mode_changed"] is False
    assert state["facts"]["items"] == []


def test_quote_explain_stays_general_even_with_the_word_quote():
    # "견적서가 뭔지 설명해 줘": the model classified an explanation question.
    state = apply_message_transition(empty_state(), "견적서는 거래 내역을 적는 문서입니다.", "quote_explain", {})
    assert state["mode"] == MODE_GENERAL


def test_explicit_quote_create_opens_authoring_and_offers_both_methods():
    state = apply_message_transition(empty_state(), "견적서를 만들어 드릴게요.", "quote_create", {})
    assert state["mode"] == MODE_QUOTE
    assert state["awaiting_method"] is True
    assert state["approval_required"] is False
    assert state["_mode_changed"] is True


def test_exit_quote_returns_to_general_and_keeps_facts_for_resume():
    state = empty_state()
    state["facts"] = merge_facts(
        state["facts"],
        {"recipient": {"company": "가상건설"}, "items": [{"name": "배관", "qty": 100}]},
    )
    state["mode"] = MODE_QUOTE
    state["method"] = "flexible"
    state = apply_message_transition(state, "다른 이야기 하죠.", "exit_quote", {})
    assert state["mode"] == MODE_GENERAL
    assert state["_mode_changed"] is True
    # Collected facts survive the mode change; nothing was silently erased.
    assert state["facts"]["recipient"]["company"] == "가상건설"
    assert state["facts"]["items"][0]["qty"] == 100


def test_quote_modify_without_active_authoring_stays_general():
    state = apply_message_transition(
        empty_state(), "어떤 견적을 수정할까요?", "quote_modify", {"items": [{"name": "배관"}]}
    )
    assert state["mode"] == MODE_GENERAL
    assert state["staged"] is False


# ── quote fact validation: QuoteCore stays the only calculation authority ──

@pytest.mark.parametrize("key", [
    "subtotal", "supplyAmount", "vatAmount", "grandTotal", "total", "amount",
    "computedTotals", "template", "sender", "approval", "fingerprint",
    "saved_skill_id", "savedSkillId",
])
def test_model_may_never_supply_a_computed_or_forbidden_key(key):
    with pytest.raises(B66ConversationError) as excinfo:
        normalize_facts_delta({"items": [{"name": "배관", "qty": 1, key: 100}]})
    assert excinfo.value.message == "forbidden_total_key"


@pytest.mark.parametrize("bad", [
    {"items": [{"name": "배관", "qty": -5}]},
    {"items": [{"name": "배관", "qty": "많이"}]},
    {"items": [{"name": "배관", "qty": True}]},
    {"recipient": {"company": 5}},
    {"items": [{"name": "x" * 241}]},
    {"memo": "x" * 1001},
    {"taxMode": "WEIRD"},
    {"secret": "customer"},
])
def test_invalid_facts_deltas_are_rejected_bounded(bad):
    with pytest.raises(B66ConversationError):
        normalize_facts_delta(bad)


def test_oversize_item_list_is_rejected():
    with pytest.raises(B66ConversationError) as excinfo:
        normalize_facts_delta({"items": [{"name": f"품목{i}"} for i in range(21)]})
    assert excinfo.value.message == "too_many_items"


def test_nan_and_infinity_are_rejected():
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(B66ConversationError):
            normalize_facts_delta({"items": [{"name": "배관", "qty": value}]})


def test_merge_preserves_known_facts_when_a_later_turn_mentions_one_value():
    state = empty_state()
    state["facts"] = merge_facts(
        state["facts"],
        {"recipient": {"company": "가상건설"}, "items": [{"name": "배관", "qty": 100}]},
    )
    # A later turn only states the unit price; qty and recipient must survive.
    state["facts"] = merge_facts(state["facts"], {"items": [{"name": "배관", "unitPrice": 18000}]})
    assert state["facts"]["items"][0]["qty"] == 100
    assert state["facts"]["items"][0]["unitPrice"] == 18000
    assert state["facts"]["recipient"]["company"] == "가상건설"
    assert missing_fields(state["facts"]) == []


def test_merge_appends_new_items_and_merges_matching_names():
    state = empty_state()
    state["facts"] = merge_facts(state["facts"], {"items": [{"name": "배관", "qty": 100}]})
    state["facts"] = merge_facts(
        state["facts"], {"items": [{"name": "배관", "unitPrice": 18000}, {"name": "밸브", "qty": 5}]}
    )
    assert [item["name"] for item in state["facts"]["items"]] == ["배관", "밸브"]
    assert state["facts"]["items"][0]["unitPrice"] == 18000
    assert state["facts"]["items"][1]["qty"] == 5


def test_missing_fields_and_next_question_are_server_derived():
    facts = normalize_facts({"items": [{"name": "배관", "qty": 100}]})
    assert missing_fields(facts) == ["recipient", "items[0].unitPrice"]
    assert next_question(missing_fields(facts)) == "받으실 거래처(회사명) 또는 담당자명을 알려 주세요."
    assert next_question(["items[0].unitPrice"]) == "단가는 얼마인가요?"
    complete = normalize_facts({
        "recipient": {"company": "가상건설"},
        "items": [{"name": "배관", "qty": 100, "unitPrice": 18000}],
    })
    assert missing_fields(complete) == []
    assert next_question(missing_fields(complete)) is None


def test_tax_mode_is_not_required_so_a_customer_is_never_blocked_forever():
    facts = normalize_facts({
        "recipient": {"company": "가상건설"},
        "items": [{"name": "배관", "qty": 100, "unitPrice": 18000}],
    })
    assert facts["taxMode"] == ""
    assert missing_fields(facts) == []


# ── model output parsing: fail closed, never guess intent ──

def test_plain_json_payload_parses():
    reply, intent, delta = parse_model_output(_model_payload("안녕하세요!", "general"))
    assert (reply, intent, delta) == ("안녕하세요!", "general", {})


def test_fenced_json_payload_parses():
    raw = "```json\n" + _model_payload("네", "confirm") + "\n```"
    reply, intent, _ = parse_model_output(raw)
    assert (reply, intent) == ("네", "confirm")


def test_single_fenced_payload_inside_prose_parses():
    raw = "다음과 같이 답변합니다.\n```json\n" + _model_payload("네", "confirm") + "\n```"
    reply, intent, _ = parse_model_output(raw)
    assert (reply, intent) == ("네", "confirm")


@pytest.mark.parametrize("raw", [
    "",
    "   ",
    "그냥 텍스트",
    "```json\n{\"reply\": \"a\", \"intent\": \"general\", \"facts\": null}\n```\n{\"reply\": \"b\", \"intent\": \"general\"}",
    '{"reply": "a", "intent": "general", "facts": null, "extra": 1}',
    '{"reply": "a", "intent": "make_quote", "facts": null}',
    '{"reply": "", "intent": "general", "facts": null}',
    '{"intent": "general"}',
    '{"reply": "a", "intent": "general", "facts": {"total": 100}}',
    "not json at all",
])
def test_non_contract_model_output_is_rejected_fail_closed(raw):
    with pytest.raises(B66ConversationError):
        parse_model_output(raw)


def test_prompt_includes_server_state_and_forbids_totals():
    state = empty_state()
    state["mode"] = MODE_QUOTE
    state["method"] = "guided"
    state["facts"] = merge_facts(state["facts"], {"items": [{"name": "배관", "qty": 100}]})
    state["missing"] = missing_fields(state["facts"])
    prompt = conversation_prompt(state)
    assert "mode=quote_authoring" in prompt
    assert "authoring_method=guided" in prompt
    assert "배관" in prompt
    assert "recipient" in prompt
    assert "계산값은 절대 넣지" in prompt
    assert len(prompt) <= 4_000


# ── explicit method / staged modification transitions ──

def test_choose_method_requires_quote_mode():
    with pytest.raises(B66ConversationError) as excinfo:
        choose_method_transition(empty_state(), "flexible")
    assert excinfo.value.message == "not_in_quote_mode"


@pytest.mark.parametrize("method", ["flexible", "guided"])
def test_choose_method_sets_method_without_a_model_call(method):
    state = apply_message_transition(empty_state(), "만들어 드릴게요.", "quote_create", {})
    state.pop("_mode_changed")
    state = choose_method_transition(state, method)
    assert state["method"] == method
    assert state["awaiting_method"] is False


def test_staged_modification_is_not_applied_until_explicit_confirm():
    state = apply_message_transition(empty_state(), "만들어 드릴게요.", "quote_create", {
        "recipient": {"company": "가상건설"},
        "items": [{"name": "배관", "qty": 100, "unitPrice": 18000}],
    })
    state.pop("_mode_changed")
    state = choose_method_transition(state, "flexible")
    before = json.dumps(state["facts"], ensure_ascii=False, sort_keys=True)
    # A model intent alone must not change collected facts.
    state = apply_message_transition(state, "수량을 200으로 바꿀까요?", "quote_modify", {
        "items": [{"name": "배관", "qty": 200}],
    })
    state.pop("_mode_changed")
    assert state["staged"] is True
    assert json.dumps(state["facts"], ensure_ascii=False, sort_keys=True) == before
    assert state["approval_required"] is True
    # Only an explicit customer confirm applies the staged change.
    state = confirm_transition(state)
    assert state["facts"]["items"][0]["qty"] == 200
    assert state["staged"] is False


@pytest.mark.parametrize("intent", ["quote_modify", "confirm", "quote_create", "general"])
def test_a_model_reply_may_never_rewrite_an_already_known_value(intent):
    """The overwrite rule is intent-independent: the label grants no authority."""
    state = apply_message_transition(empty_state(), "만들어 드릴게요.", "quote_create", {
        "recipient": {"company": "가상건설"},
        "items": [{"name": "배관", "qty": 100, "unitPrice": 18000}],
    })
    state.pop("_mode_changed")
    before = json.dumps(state["facts"], ensure_ascii=False, sort_keys=True)
    state = apply_message_transition(state, "수량 200으로 확정해 주세요", intent, {
        "items": [{"name": "배관", "qty": 200}],
    })
    state.pop("_mode_changed")
    assert state["staged"] is True
    assert state["approval_required"] is True
    assert json.dumps(state["facts"], ensure_ascii=False, sort_keys=True) == before


def test_newly_stated_values_are_collected_without_staging():
    """Collecting a value the customer has not stated yet is not a modification."""
    state = apply_message_transition(empty_state(), "만들어 드릴게요.", "quote_create", {})
    state.pop("_mode_changed")
    state = apply_message_transition(state, "배관 100m 18000원입니다", "quote_create", {
        "recipient": {"company": "가상건설"},
        "items": [{"name": "배관", "qty": 100, "unitPrice": 18000}],
    })
    state.pop("_mode_changed")
    assert state["staged"] is False
    assert state["facts"]["items"][0]["qty"] == 100
    assert missing_fields(state["facts"]) == []


def test_restating_the_same_value_is_not_a_modification():
    state = apply_message_transition(empty_state(), "만들어 드릴게요.", "quote_create", {
        "recipient": {"company": "가상건설"},
        "items": [{"name": "배관", "qty": 100}],
    })
    state.pop("_mode_changed")
    state = apply_message_transition(state, "배관 100m 맞습니다", "quote_create", {
        "items": [{"name": "배관", "qty": 100}],
    })
    state.pop("_mode_changed")
    assert state["staged"] is False


def test_delta_overwrites_known_facts_ignores_empty_and_unknown_values():
    facts = normalize_facts({
        "recipient": {"company": "가상건설"},
        "items": [{"name": "배관", "qty": 100}],
    })
    assert delta_overwrites_known_facts(facts, {"recipient": {"company": ""}}) is False
    assert delta_overwrites_known_facts(facts, {"items": [{"name": "밸브", "qty": 5}]}) is False
    assert delta_overwrites_known_facts(facts, {"items": [{"name": "배관", "qty": 200}]}) is True
    assert delta_overwrites_known_facts(facts, {"recipient": {"company": "다른회사"}}) is True


def test_cancel_staged_keeps_the_original_facts():
    state = apply_message_transition(empty_state(), "만들어 드릴게요.", "quote_create", {
        "items": [{"name": "배관", "qty": 100, "unitPrice": 18000}],
    })
    state.pop("_mode_changed")
    state = choose_method_transition(state, "flexible")
    state = apply_message_transition(state, "수량을 바꿀까요?", "quote_modify", {
        "items": [{"name": "배관", "qty": 200}],
    })
    state.pop("_mode_changed")
    state = cancel_staged_transition(state)
    assert state["facts"]["items"][0]["qty"] == 100
    assert state["staged"] is False


def test_confirm_without_staged_change_is_refused():
    with pytest.raises(B66ConversationError) as excinfo:
        confirm_transition(empty_state())
    assert excinfo.value.message == "no_staged_change"


def test_staged_change_holds_only_the_proposed_delta():
    """Regression: a staged change is a delta, never a canonical facts object.

    Expanding it into a full facts object inserted empty placeholders
    (``taxMode: ""``), which confirm time then re-validated as a delta and
    rejected as ``invalid_tax_mode`` — the staged change could never be applied.
    """
    state = apply_message_transition(empty_state(), "만들어 드릴게요.", "quote_create", {
        "recipient": {"company": "가상건설"},
        "items": [{"name": "배관", "qty": 100, "unitPrice": 18000}],
    })
    state.pop("_mode_changed")
    state = apply_message_transition(state, "수량을 200으로 바꿀까요?", "quote_modify", {
        "items": [{"name": "배관", "qty": 200}],
    })
    state.pop("_mode_changed")
    assert state["staged"] is True
    staged = state["staged_facts"]
    assert set(staged) == {"items"}
    assert "taxMode" not in staged
    assert staged["items"] == [{"name": "배관", "qty": 200, "unitPrice": None, "unit": ""}]
    # Only the proposed quantity moves; the recipient and price are untouched.
    state = confirm_transition(state)
    assert state["facts"]["items"][0]["qty"] == 200
    assert state["facts"]["items"][0]["unitPrice"] == 18000
    assert state["facts"]["recipient"]["company"] == "가상건설"
    assert state["staged_facts"] is None


def test_staged_change_survives_a_persisted_state_roundtrip():
    """The same defect reached customers through the D1 slot, not only in memory."""
    state = apply_message_transition(empty_state(), "만들어 드릴게요.", "quote_create", {
        "recipient": {"company": "가상건설"},
        "items": [{"name": "배관", "qty": 100, "unitPrice": 18000}],
    })
    state.pop("_mode_changed")
    state = apply_message_transition(state, "수량을 200으로 바꿀까요?", "quote_modify", {
        "items": [{"name": "배관", "qty": 200}],
    })
    state.pop("_mode_changed")
    reloaded = normalize_conversation_state(json.loads(json.dumps(state, ensure_ascii=False)))
    assert reloaded["staged"] is True
    reloaded = confirm_transition(reloaded)
    assert reloaded["facts"]["items"][0]["qty"] == 200
    assert reloaded["staged"] is False


def test_a_staged_change_with_an_invalid_tax_mode_is_still_refused():
    """The fix narrows nothing: an unusable proposed tax mode is still rejected."""
    state = apply_message_transition(empty_state(), "만들어 드릴게요.", "quote_create", {})
    state.pop("_mode_changed")
    with pytest.raises(B66ConversationError) as excinfo:
        apply_message_transition(state, "면세로 해 주세요.", "quote_modify", {"taxMode": "WEIRD"})
    assert excinfo.value.message == "invalid_tax_mode"


def test_confirm_refuses_a_stored_staged_change_that_is_not_a_valid_delta():
    """A tampered persisted slot fails closed instead of mutating facts."""
    state = apply_message_transition(empty_state(), "만들어 드릴게요.", "quote_create", {})
    state.pop("_mode_changed")
    state["staged"] = True
    state["staged_facts"] = {"total": 1}
    with pytest.raises(B66ConversationError):
        normalize_conversation_state(state)


# ── persisted state bounds ──

@pytest.mark.parametrize("mutate", [
    lambda d: d.update(schema="evil"),
    lambda d: d.update(mode="chat"),
    lambda d: d.update(method="telepathy"),
    lambda d: d.update(awaiting_method="yes"),
    lambda d: d.update(revision=-1),
    lambda d: d.update(revision="3"),
    lambda d: d.update(revision=True),
    lambda d: d.update(missing="recipient"),
    lambda d: d.update(history=[{"role": "user"}]),
    lambda d: d.update(history=[{"role": "tool", "content": "x"}]),
    lambda d: d.update(answer_origin="model_said_so"),
    lambda d: d["facts"].update(total=100),
])
def test_invalid_persisted_state_is_rejected(mutate):
    state = empty_state()
    mutate(state)
    with pytest.raises(B66ConversationError):
        normalize_conversation_state(state)


def test_history_is_bounded_to_the_last_turns():
    state = empty_state()
    for index in range(12):
        state = append_history(state, f"질문{index}", f"답변{index}")
    assert len(state["history"]) == 8
    assert state["history"][-1]["content"] == "답변11"


def test_state_summary_exposes_facts_but_never_the_message_log():
    state = empty_state()
    state = append_history(state, "비밀 메시지", "비밀 답변")
    state["last_user_message"] = "비밀 메시지"
    summary = state_summary(state)
    assert "history" not in summary
    assert "last_user_message" not in summary
    assert "last_answer" not in summary
    assert "비밀" not in json.dumps(summary, ensure_ascii=False)
    assert summary["revision"] == state["revision"]


def test_bump_revision_advances_once():
    state = empty_state()
    assert bump_revision(state)["revision"] == 1
    assert bump_revision(bump_revision(state))["revision"] == 2


# ── real SQL migration contract ──

_SQL_COMMENT_RE = re.compile(r"--[^\n]*")
# A destructive *statement verb*. Matching is on the leading verb of an
# executable statement only, so a column named ``updated_at`` or a referential
# ``ON DELETE CASCADE`` action (both plain data definition) is never confused
# with a real ``UPDATE``/``DELETE`` statement.
_DESTRUCTIVE_VERBS = frozenset(
    {"DROP", "ALTER", "DELETE", "UPDATE", "TRUNCATE", "GRANT", "REVOKE", "REPLACE"}
)


def _executable_statements(sql: str) -> list[str]:
    """Statement-level view of a migration: comments removed, split on ';'."""
    without_comments = "\n".join(
        _SQL_COMMENT_RE.sub("", line) for line in sql.splitlines()
    )
    return [statement.strip() for statement in without_comments.split(";") if statement.strip()]


def _destructive_statements(sql: str) -> list[str]:
    """Executable statements whose leading verb destroys data or changes grants."""
    found = []
    for statement in _executable_statements(sql):
        leading = re.match(r"[A-Za-z]+", statement)
        if leading and leading.group(0).upper() in _DESTRUCTIVE_VERBS:
            found.append(statement)
    return found


def test_migration_is_one_additive_owner_scoped_slot():
    sql = MIGRATION.read_text(encoding="utf-8")
    statements = [
        line.strip() for line in sql.splitlines()
        if line.strip() and not line.lstrip().startswith("--")
    ]
    assert statements == [
        "PRAGMA foreign_keys = ON;",
        "CREATE TABLE IF NOT EXISTS b66_ai_conversation (",
        "user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,",
        "workspace_id TEXT NOT NULL,",
        "state_json TEXT NOT NULL,",
        "revision INTEGER NOT NULL DEFAULT 0,",
        "updated_at TEXT NOT NULL,",
        "PRIMARY KEY (user_id, workspace_id)",
        ");",
    ]
    # No executable statement may drop, alter, rewrite or re-grant anything.
    assert _destructive_statements(sql) == []
    # 027 stays reserved for #3925; 040 is the previous migration.
    existing = sorted(path.name for path in MIGRATION.parent.glob("*.sql"))
    assert "027" not in "".join(existing)
    assert "040_claw_web_xlsx_p01_decision_release.sql" in existing
    assert MIGRATION.name == "041_b66_ai_conversation.sql"


def test_benign_ddl_and_comments_are_not_flagged_as_destructive():
    """Differential proof for the previous false positive.

    A line-prefix scan flagged ``updated_at TEXT NOT NULL,`` as an ``UPDATE``
    statement and would flag any comment mentioning a destructive verb. Both
    are plain data definition / documentation, not executable destruction.
    """
    sql = (
        "-- DROP TABLE users was considered and rejected for this migration.\n"
        "-- DELETE FROM b66_ai_conversation is never issued here.\n"
        "CREATE TABLE IF NOT EXISTS b66_ai_conversation (\n"
        "    updated_at TEXT NOT NULL,\n"
        "    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE\n"
        ");\n"
    )
    assert _destructive_statements(sql) == []


@pytest.mark.parametrize("statement", [
    "DROP TABLE b66_ai_conversation",
    "ALTER TABLE b66_ai_conversation ADD COLUMN evil TEXT",
    "DELETE FROM b66_ai_conversation",
    "UPDATE b66_ai_conversation SET state_json = '{}'",
    "TRUNCATE TABLE b66_ai_conversation",
    "GRANT ALL ON b66_ai_conversation TO public",
    "REVOKE SELECT ON b66_ai_conversation FROM app_role",
    "REPLACE INTO b66_ai_conversation (user_id) VALUES ('usr_x')",
])
def test_genuinely_destructive_migration_sql_is_still_detected(statement):
    assert _destructive_statements(statement) == [statement]


def test_destructive_statement_after_a_benign_one_is_still_detected():
    sql = (
        "CREATE TABLE IF NOT EXISTS t (updated_at TEXT);\n"
        "DROP TABLE users;\n"
    )
    assert _destructive_statements(sql) == ["DROP TABLE users"]


def test_migration_creates_exactly_one_slot_table():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert sql.upper().count("CREATE TABLE") == 1


# ── private D1 slot behavior ──

class Prepared:
    def __init__(self, db, sql, barrier=None):
        self.db, self.sql, self.args, self.barrier = db, sql, (), barrier

    def bind(self, *args):
        self.args = args
        return self

    async def first(self):
        row = self.db.execute(self.sql, self.args).fetchone()
        return dict(row) if row else None

    async def run(self):
        if self.barrier is not None:
            # Real writers overlap here: both requests have already read the
            # slot and are about to commit against the same revision.
            self.barrier.wait()
        cursor = self.db.execute(self.sql, self.args)
        changes = cursor.rowcount
        self.db.commit()
        # Cloudflare D1 reports the affected-row count on meta.changes.
        return {"success": True, "meta": {"changes": changes}}


class SQLiteD1:
    """A real SQLite connection behind the D1 prepare/bind/first/run surface."""

    def __init__(self, db, *, barrier=None, autocommit=False):
        self.db = db
        self.barrier = barrier
        if autocommit:
            db.isolation_level = None

    def prepare(self, sql):
        return Prepared(self.db, sql, self.barrier)


@pytest.fixture
def source():
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE users (id TEXT PRIMARY KEY)")
    db.executemany("INSERT INTO users(id) VALUES (?)", [(A,), (B,)])
    db.executescript(MIGRATION.read_text(encoding="utf-8"))
    yield db, D1ConversationStore(SQLiteD1(db))
    db.close()


async def test_slot_roundtrip_and_foreign_account_isolation(source):
    _, store = source
    assert await store.load(user_id=A, workspace_id=f"owner:{A}") is None
    state = empty_state()
    state["mode"] = MODE_QUOTE
    state["facts"] = merge_facts(state["facts"], {"recipient": {"company": "A사"}})
    state = bump_revision(state)
    await store.save(
        user_id=A, workspace_id=f"owner:{A}", state=state, expected_revision=0
    )
    loaded = await store.load(user_id=A, workspace_id=f"owner:{A}")
    assert loaded is not None
    assert loaded["mode"] == MODE_QUOTE
    assert loaded["facts"]["recipient"]["company"] == "A사"
    # A different account never sees another account's slot.
    assert await store.load(user_id=B, workspace_id=f"owner:{B}") is None


async def test_same_user_foreign_workspace_is_isolated(source):
    _, store = source
    state = bump_revision(empty_state())
    await store.save(
        user_id=A, workspace_id="owner:independent-workspace", state=state, expected_revision=0
    )
    assert await store.load(user_id=A, workspace_id=f"owner:{A}") is None


async def test_malformed_stored_row_fails_closed(source):
    db, store = source
    db.execute(
        "INSERT INTO b66_ai_conversation (user_id,workspace_id,state_json,updated_at)"
        " VALUES (?,?,?,?)", (A, f"owner:{A}", '{"schema":"evil"}', "2026-10-14"),
    )
    db.commit()
    with pytest.raises(B66ConversationError):
        await store.load(user_id=A, workspace_id=f"owner:{A}")


async def test_oversize_stored_row_fails_closed(source):
    db, store = source
    state = empty_state()
    state["memo"] = "x" * 40_000
    raw = json.dumps(state, ensure_ascii=False)
    db.execute(
        "INSERT INTO b66_ai_conversation (user_id,workspace_id,state_json,updated_at)"
        " VALUES (?,?,?,?)", (A, f"owner:{A}", raw, "2026-10-14"),
    )
    db.commit()
    with pytest.raises(B66ConversationError):
        await store.load(user_id=A, workspace_id=f"owner:{A}")


async def test_a_row_whose_guard_revision_disagrees_with_its_state_fails_closed(source):
    db, store = source
    state = bump_revision(empty_state())
    db.execute(
        "INSERT INTO b66_ai_conversation (user_id,workspace_id,state_json,revision,updated_at)"
        " VALUES (?,?,?,?,?)",
        (A, f"owner:{A}", json.dumps(state, ensure_ascii=False), 99, "2026-10-14"),
    )
    db.commit()
    # A tampered guard cannot be trusted to reject a stale writer.
    with pytest.raises(B66ConversationError):
        await store.load(user_id=A, workspace_id=f"owner:{A}")


async def test_clear_removes_only_the_owner_slot(source):
    db, store = source
    await store.save(
        user_id=A, workspace_id=f"owner:{A}", state=bump_revision(empty_state()),
        expected_revision=0,
    )
    await store.save(
        user_id=B, workspace_id=f"owner:{B}", state=bump_revision(empty_state()),
        expected_revision=0,
    )
    await store.clear(user_id=A, workspace_id=f"owner:{A}")
    assert await store.load(user_id=A, workspace_id=f"owner:{A}") is None
    assert await store.load(user_id=B, workspace_id=f"owner:{B}") is not None


async def test_oversize_state_is_refused_on_save(source):
    _, store = source
    state = empty_state()
    state["facts"]["memo"] = "x" * 33_000
    with pytest.raises(B66ConversationError):
        await store.save(
            user_id=A, workspace_id=f"owner:{A}", state=state, expected_revision=0
        )

# ── P0-A: quote facts are mutable only inside server-owned authoring scope ──

def _authoring_with(*facts_deltas, mode=MODE_QUOTE):
    """A state already collecting the given facts inside authoring scope."""
    state = empty_state()
    state["mode"] = mode
    state["method"] = "flexible"
    state["awaiting_method"] = False
    for delta in facts_deltas:
        state["facts"] = merge_facts(state["facts"], delta)
    state["missing"] = missing_fields(state["facts"])
    return state


def test_a_general_reply_cannot_rewrite_a_quantity_left_behind_by_exit_quote():
    # The customer built a quote, said "그만", and kept the collected facts.
    state = _authoring_with({"items": [{"name": "벽시공", "qty": 100, "unitPrice": 18000}]})
    state = apply_message_transition(state, "네, 다른 궁금한 점이 있어요.", "exit_quote", {})
    assert state["mode"] == MODE_GENERAL
    assert state["facts"]["items"][0]["qty"] == 100

    # An ordinary reply that "helpfully" proposes a different quantity.
    after = apply_message_transition(
        state, "수량을 500개로 바꿔드릴게요.", "general",
        {"items": [{"name": "벽시공", "qty": 500, "unitPrice": 18000}]},
    )
    assert after["mode"] == MODE_GENERAL
    assert after["facts"]["items"][0]["qty"] == 100
    assert after["staged"] is False


@pytest.mark.parametrize("intent", ["general", "quote_explain", "quote_modify", "confirm", "clarify"])
def test_no_general_intent_label_grants_fact_authority_after_exit(intent):
    state = _authoring_with({"recipient": {"company": "한빛"}, "taxMode": "EXCLUSIVE"})
    state = apply_message_transition(state, "잠시 다른 얘기할게요.", "exit_quote", {})
    after = apply_message_transition(
        state, "말씀해드릴게요.", intent,
        {"recipient": {"company": "한빛"}, "taxMode": "INCLUSIVE", "memo": "빠른 시공"},
    )
    assert after["facts"]["taxMode"] == "EXCLUSIVE"
    assert after["facts"]["memo"] == ""
    assert after["staged"] is False


def test_a_general_reply_cannot_add_a_new_row_while_no_quote_is_being_created():
    state = empty_state()
    assert state["mode"] == MODE_GENERAL
    after = apply_message_transition(
        state, "네, 도와드릴게요.", "general",
        {"items": [{"name": "타일", "qty": 10, "unitPrice": 5000}]},
    )
    assert after["facts"]["items"] == []
    assert after["mode"] == MODE_GENERAL


def test_reentering_quote_mode_with_conflicting_facts_never_replaces_them():
    state = _authoring_with({"items": [{"name": "벽시공", "qty": 100, "unitPrice": 18000}]})
    state = apply_message_transition(state, "다른 얘긴 이만할게요.", "exit_quote", {})

    # The very message that reopens authoring carries a conflicting quantity.
    reopened = apply_message_transition(
        state, "견적 다시 만들어 주세요.", "quote_create",
        {"items": [{"name": "벽시공", "qty": 300, "unitPrice": 18000}]},
    )
    assert reopened["mode"] == MODE_QUOTE
    assert reopened["_mode_changed"] is True
    assert reopened["facts"]["items"][0]["qty"] == 100, "direct replacement on re-entry"
    assert reopened["staged"] is False

    # Repeating the change inside authoring stages it for explicit confirmation.
    staged = apply_message_transition(
        reopened, "수량을 300개로 바꿀까요?", "quote_modify",
        {"items": [{"name": "벽시공", "qty": 300, "unitPrice": 18000}]},
    )
    assert staged["staged"] is True
    assert staged["facts"]["items"][0]["qty"] == 100
    confirmed = confirm_transition(staged)
    assert confirmed["facts"]["items"][0]["qty"] == 300


def test_an_explicit_create_turn_still_collects_genuinely_new_facts():
    after = apply_message_transition(
        empty_state(), "견적 만들어 주세요.", "quote_create",
        {"recipient": {"company": "한빛"}, "items": [{"name": "타일", "qty": 10, "unitPrice": 5000}]},
    )
    assert after["mode"] == MODE_QUOTE
    assert after["_mode_changed"] is True
    assert after["facts"]["recipient"]["company"] == "한빛"
    assert after["facts"]["items"][0]["name"] == "타일"
    assert after["facts"]["items"][0]["qty"] == 10


def test_resuming_a_retained_quote_collects_new_values_but_not_replacements():
    state = _authoring_with({"recipient": {"company": "한빛"}, "taxMode": "EXCLUSIVE"})
    state = apply_message_transition(state, "여기까지 할게요.", "exit_quote", {})
    resumed = apply_message_transition(
        state, "견적 이어서 만들게요.", "quote_create",
        {"recipient": {"person": "김담당"}, "items": [{"name": "타일", "qty": 10, "unitPrice": 5000}]},
    )
    assert resumed["facts"]["recipient"]["company"] == "한빛"
    assert resumed["facts"]["recipient"]["person"] == "김담당"
    assert resumed["facts"]["items"][0]["name"] == "타일"
    assert resumed["facts"]["taxMode"] == "EXCLUSIVE"


# ── P1: an exactly empty model taxMode means "not provided" ──

def test_an_empty_model_tax_mode_is_absent_rather_than_a_proposed_change():
    assert normalize_facts_delta({"taxMode": ""}) == {}


def test_an_empty_model_tax_mode_never_clears_a_known_tax_mode():
    known = normalize_facts({"taxMode": "EXCLUSIVE"})
    assert merge_facts(known, {"taxMode": ""})["taxMode"] == "EXCLUSIVE"


def test_an_empty_model_tax_mode_stages_nothing_in_authoring_scope():
    state = _authoring_with({"recipient": {"company": "한빛"}, "taxMode": "EXCLUSIVE"})
    after = apply_message_transition(state, "세금은 그대로예요.", "quote_modify", {"taxMode": ""})
    assert after["staged"] is False
    assert after["staged_facts"] is None
    assert after["facts"]["taxMode"] == "EXCLUSIVE"


def test_an_empty_model_tax_mode_keeps_a_fresh_create_usable():
    after = apply_message_transition(
        empty_state(), "견적 만들어 주세요.", "quote_create",
        {"recipient": {"company": "한빛"}, "taxMode": ""},
    )
    assert after["mode"] == MODE_QUOTE
    assert after["facts"]["taxMode"] == ""


@pytest.mark.parametrize(
    "value",
    ["WEIRD", "exclusive", " EXCLUSIVE", "EXCLUSIVE ", " ", 0, 1, True, None, ["EXCLUSIVE"], {"a": 1}],
)
def test_every_other_unusable_tax_mode_is_still_refused(value):
    with pytest.raises(B66ConversationError) as caught:
        normalize_facts_delta({"taxMode": value})
    assert caught.value.message == "invalid_tax_mode"


def test_an_unusable_tax_mode_fails_the_turn_closed_before_any_transition():
    state = _authoring_with({"taxMode": "EXCLUSIVE"})
    with pytest.raises(B66ConversationError):
        parse_model_output(_model_payload("네", "quote_modify", {"taxMode": "WEIRD"}))
    # The caller keeps the previous state, so the known tax mode is intact.
    assert state["facts"]["taxMode"] == "EXCLUSIVE"


# ── P0-B: the D1 write is a revision compare-and-swap ──

async def test_a_second_write_on_the_same_revision_loses_and_keeps_the_first(source):
    _, store = source
    first = bump_revision(_authoring_with({"recipient": {"company": "한빛"}}))
    await store.save(
        user_id=A, workspace_id=f"owner:{A}", state=first, expected_revision=0
    )
    # A second request that read the same empty slot before the first committed.
    second = bump_revision(_authoring_with({"recipient": {"company": "두빛"}}))
    with pytest.raises(ConversationRevisionConflict):
        await store.save(
            user_id=A, workspace_id=f"owner:{A}", state=second, expected_revision=0
        )
    stored = await store.load(user_id=A, workspace_id=f"owner:{A}")
    assert stored["revision"] == 1
    assert stored["facts"]["recipient"]["company"] == "한빛"


async def test_a_write_that_does_not_advance_exactly_one_revision_is_refused(source):
    _, store = source
    with pytest.raises(B66ConversationError) as caught:
        await store.save(
            user_id=A, workspace_id=f"owner:{A}", state=empty_state(), expected_revision=0
        )
    assert caught.value.message == "revision_advance_required"
    assert await store.load(user_id=A, workspace_id=f"owner:{A}") is None


@pytest.mark.parametrize("expected", [-1, 1.0, "0", None, True])
async def test_an_unusable_expected_revision_never_reaches_the_database(source, expected):
    _, store = source
    with pytest.raises(B66ConversationError) as caught:
        await store.save(
            user_id=A, workspace_id=f"owner:{A}",
            state=bump_revision(empty_state()), expected_revision=expected,
        )
    assert caught.value.message == "invalid_revision"
    assert await store.load(user_id=A, workspace_id=f"owner:{A}") is None


class _NoMetaD1:
    """A binding whose result carries no affected-row count at all."""

    def __init__(self, db):
        self.inner = SQLiteD1(db)

    def prepare(self, sql):
        prepared = self.inner.prepare(sql)
        prepared.run = self._run
        return prepared

    @staticmethod
    async def _run():
        return {}


async def test_a_write_the_database_cannot_verify_fails_closed(source):
    db, store = source
    unverifiable = D1ConversationStore(_NoMetaD1(db))
    with pytest.raises(B66ConversationError) as caught:
        await unverifiable.save(
            user_id=A, workspace_id=f"owner:{A}",
            state=bump_revision(empty_state()), expected_revision=0,
        )
    assert caught.value.message == "conversation_state_write_unverifiable"
    assert await store.load(user_id=A, workspace_id=f"owner:{A}") is None


def _seed_file_slot(path):
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=15000")
    db.execute("CREATE TABLE users (id TEXT PRIMARY KEY)")
    db.executemany("INSERT INTO users(id) VALUES (?)", [(A,), (B,)])
    db.executescript(MIGRATION.read_text(encoding="utf-8"))
    db.commit()
    db.close()


def _racing_turn(path, barrier, outcomes, *, user, company):
    """One request that reads the slot, then commits against what it read."""

    async def turn():
        db = sqlite3.connect(path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=15000")
        store = D1ConversationStore(SQLiteD1(db, barrier=barrier, autocommit=True))
        try:
            loaded = await store.load(user_id=user, workspace_id=f"owner:{user}")
            expected = 0 if loaded is None else loaded["revision"]
            state = bump_revision(_authoring_with({"recipient": {"company": company}}))
            assert state["revision"] == expected + 1
            await store.save(
                user_id=user, workspace_id=f"owner:{user}",
state=state, expected_revision=expected,
            )
            outcomes.append(f"ok:{company}")
        except ConversationRevisionConflict:
            outcomes.append("revision_conflict")
        except BaseException as exc:  # surfaced by the caller's assertion
            outcomes.append(f"error:{exc!r}")
        finally:
            db.close()

    def run():
        asyncio.run(turn())

    return run


def test_two_concurrent_turns_on_one_slot_leave_exactly_one_durable_winner(tmp_path):
    """A real overlapping race, not a replayed sequential one.

    Two threads each open their own connection to the same on-disk slot. Both
    read revision 0 before either writes, then a barrier releases both
    compare-and-swap statements together. Exactly one may commit; the other must
    be told ``revision_conflict`` and must not have replaced the winner's state.
    """
    path = tmp_path / "slot.sqlite"
    _seed_file_slot(path)
    outcomes: list[str] = []
    barrier = threading.Barrier(2, timeout=30)
    threads = [
        threading.Thread(target=_racing_turn(path, barrier, outcomes, user=A, company="한빛")),
        threading.Thread(target=_racing_turn(path, barrier, outcomes, user=A, company="두빛")),
]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    winners = [outcome.split(":", 1)[1] for outcome in outcomes if outcome.startswith("ok:")]
    assert len(outcomes) == 2 and len(winners) == 1, outcomes
    assert [o for o in outcomes if not o.startswith(("ok:", "error:"))] == ["revision_conflict"]

    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    row = db.execute(
        "SELECT state_json,revision FROM b66_ai_conversation WHERE user_id=? AND workspace_id=?",
        (A, f"owner:{A}"),
    ).fetchone()
    db.close()
    stored = json.loads(row["state_json"])
    assert row["revision"] == 1 and stored["revision"] == 1
    # The single durable winner's own value survived, untouched by the loser.
    assert stored["facts"]["recipient"]["company"] == winners[0]
    assert stored["mode"] == MODE_QUOTE


def test_concurrent_writers_in_different_tenants_do_not_collide(tmp_path):
    """The same overlapping race across two accounts stays two successes."""
    path = tmp_path / "slot.sqlite"
    _seed_file_slot(path)
    outcomes: list[str] = []
    barrier = threading.Barrier(2, timeout=30)
    threads = [
        threading.Thread(target=_racing_turn(path, barrier, outcomes, user=A, company="한빛")),
        threading.Thread(target=_racing_turn(path, barrier, outcomes, user=B, company="두빛")),
]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert sorted(outcomes) == ["ok:두빛", "ok:한빛"], outcomes

    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    rows = db.execute(
        "SELECT user_id,state_json FROM b66_ai_conversation ORDER BY user_id"
    ).fetchall()
    db.close()
    assert {
        row["user_id"]: json.loads(row["state_json"])["facts"]["recipient"]["company"]
        for row in rows
    } == {A: "한빛", B: "두빛"}
