"""#4471: owner-scoped conversation search behind the sidebar Search entry.

Contract under test:
  - search is owner-scoped with bound parameters (no interpolation);
  - the user query is a literal substring (no wildcard can take effect);
  - no bound value is ever handed to D1 as a LIKE/GLOB pattern longer than the
    platform's documented 50-byte limit;
  - result rows and scanned rows are bounded; stored text is never truncated;
  - the sidebar entry is fail-closed and never touches web-search state.
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.history import (  # noqa: E402
    PRODUCT_SCOPE_CHAT,
    MAX_CONVERSATION_SEARCH_QUERY_CHARS,
    MAX_CONVERSATION_SEARCH_RESULTS,
    MAX_CONVERSATION_SEARCH_SCAN_ROWS,
    MAX_CONVERSATION_SEARCH_SNIPPET_CHARS,
    D1HistoryStore,
    _normalize_search_query,
    _search_snippet,
)
from _support.b66_conversation_isolation import (  # noqa: E402
    D1Sqlite,
    OWNER as REAL_OWNER,
    setup_database,
)
from _support.conversation_search_4471 import (  # noqa: E402
    app_opener_facts,
    search_css_declarations,
    search_function_facts,
    search_listener_facts,
    search_module_facts,
    search_route_facts,
)

# Cloudflare documents this ceiling; a longer pattern is refused as "too
# complex". https://developers.cloudflare.com/d1/platform/limits/ (2026-10-30)
D1_LIKE_PATTERN_MAX_BYTES = 50

# The store accepts a query up to MAX_CONVERSATION_SEARCH_QUERY_CHARS *characters*.
# Korean is 3 bytes and emoji 4 bytes per character in UTF-8, so these are the
# queries that used to turn into an illegal pattern.
LONG_QUERIES = {
    "korean17": "가" * 17,
    "korean40": "가" * 40,
    "korean80": "가" * 80,
    "english80": "community budget review notes " * 4,
    "emoji": "마을 축제 🎉 안전 점검 🚧 안내",
}


def _like_pattern_operands(sql: str, values: tuple) -> list[str]:
    """The bound values SQL will use as LIKE/GLOB patterns, by ? ordinal."""
    operands = []
    for match in re.finditer(r"\b(?:LIKE|GLOB)\s+\?", sql, re.IGNORECASE):
        ordinal = sql.count("?", 0, match.start()) + 1
        if ordinal <= len(values):
            operands.append(values[ordinal - 1])
    return operands


# --- pure helpers -----------------------------------------------------------
def test_query_is_trimmed_collapsed_and_bounded():
    assert _normalize_search_query("  hello   world \n") == "hello world"
    assert _normalize_search_query("   ") == ""
    assert _normalize_search_query(None) == ""
    assert len(_normalize_search_query("가" * 500)) == MAX_CONVERSATION_SEARCH_QUERY_CHARS


def test_a_long_korean_query_is_already_over_the_d1_pattern_ceiling():
    # Documents the arithmetic the store has to survive: the old `%needle%`
    # shape for 17 Korean characters is 53 bytes, before any user thought they
    # had typed anything unusual.
    assert len(("%" + "가" * 17 + "%").encode("utf-8")) > D1_LIKE_PATTERN_MAX_BYTES


def test_snippet_is_bounded_and_centred_on_the_literal_match():
    body = "앞" * 400 + " 파디엠 견적 " + "뒤" * 400
    snippet = _search_snippet(body, "파디엠 견적")
    assert "파디엠 견적" in snippet
    assert len(snippet) <= MAX_CONVERSATION_SEARCH_SNIPPET_CHARS + 2  # ellipses
    assert snippet.startswith("…") and snippet.endswith("…")


def test_snippet_empty_without_a_body_hit():
    assert _search_snippet(None, "x") == ""
    assert _search_snippet("", "x") == ""



# --- store behaviour against a recording fake D1 ----------------------------
class _RecordingStatement:
    def __init__(self, db, sql):
        self.db = db
        self.sql = sql
        self.values = ()

    def bind(self, *values):
        self.values = values
        self.db.bound.append((self.sql, values))
        return self

    async def run(self):
        return {"results": []}

    async def first(self):
        return None


class _RecordingD1:
    def __init__(self):
        self.bound = []

    def prepare(self, sql):
        return _RecordingStatement(self, sql)


def _search_bound(db):
    matches = [(sql, values) for sql, values in db.bound if "FROM conversations c" in sql]
    assert len(matches) == 1, "exactly one search statement must run"
    return matches[0]


def test_search_is_owner_scoped_by_a_bound_parameter():
    db = _RecordingD1()
    store = D1HistoryStore(db)
    asyncio.run(store.search_conversations("usr_owner", "견적", product_scope=PRODUCT_SCOPE_CHAT))
    sql, values = _search_bound(db)
    assert "c.user_id=?" in sql
    assert "usr_owner" in values
    # The owner id is never interpolated into the SQL text.
    assert "usr_owner" not in sql


def test_user_query_is_bound_not_interpolated_into_sql():
    db = _RecordingD1()
    store = D1HistoryStore(db)
    hostile = "x'); DROP TABLE conversations; --"
    asyncio.run(store.search_conversations("usr_owner", hostile, product_scope=PRODUCT_SCOPE_CHAT))
    sql, values = _search_bound(db)
    assert "DROP TABLE" not in sql
    assert any(isinstance(v, str) and "DROP TABLE" in v for v in values)


def test_search_scan_and_result_limits_are_bound_parameters():
    db = _RecordingD1()
    store = D1HistoryStore(db)
    asyncio.run(store.search_conversations("usr_owner", "q", limit=10_000, product_scope=PRODUCT_SCOPE_CHAT))
    sql, values = _search_bound(db)
    assert MAX_CONVERSATION_SEARCH_SCAN_ROWS in values
    assert min(MAX_CONVERSATION_SEARCH_RESULTS, 10_000) in values
    assert "LIMIT ?" in sql


def test_empty_or_whitespace_query_runs_no_search_statement():
    db = _RecordingD1()
    store = D1HistoryStore(db)
    assert asyncio.run(store.search_conversations("usr_owner", "   ", product_scope=PRODUCT_SCOPE_CHAT)) == []
    assert not any("FROM conversations c" in sql for sql, _ in db.bound)


@pytest.mark.parametrize("label", sorted(LONG_QUERIES))
def test_a_long_query_never_reaches_d1_as_an_oversized_like_pattern(label: str) -> None:
    """The load-bearing guard: whatever shape the predicate takes, no bound value
    may arrive as a LIKE/GLOB pattern over D1's documented 50-byte ceiling — and
    the query still has to reach the statement, so this cannot be satisfied by
    dropping the search."""
    db = _RecordingD1()
    store = D1HistoryStore(db)
    asyncio.run(store.search_conversations(
        "usr_owner", LONG_QUERIES[label], product_scope=PRODUCT_SCOPE_CHAT))
    sql, values = _search_bound(db)
    patterns = _like_pattern_operands(sql, values)
    oversized = [len(str(p).encode("utf-8")) for p in patterns
                 if len(str(p).encode("utf-8")) > D1_LIKE_PATTERN_MAX_BYTES]
    assert not oversized, f"{label}: LIKE pattern byte lengths {oversized}"
    needle = _normalize_search_query(LONG_QUERIES[label])
    assert needle in values, "the query must still be searched"


# --- real SQLite: the search itself must keep working ------------------------
class TestSearchOnRealSqlite:
    """The fake D1 above records statements; this runs them.

    Local SQLite has no 50-byte pattern ceiling, so these tests cannot prove the
    platform limit — they prove the fix did not change what a user gets back.
    """

    def setup_method(self):
        self.db = setup_database()
        self.store = D1HistoryStore(D1Sqlite(self.db))

    def teardown_method(self):
        self.db.close()

    def seed(self, text):
        return asyncio.run(self.store.append_exchange(
            REAL_OWNER, None, text, "합성 응답", product_scope=PRODUCT_SCOPE_CHAT))

    def search(self, query):
        return asyncio.run(self.store.search_conversations(
            REAL_OWNER, query, product_scope=PRODUCT_SCOPE_CHAT))

    def test_a_long_korean_query_finds_the_conversation(self):
        needle = "마을" + "가" * 20 + "축제"
        cid = self.seed(f"합성 기록 {needle} 끝")
        assert [hit["id"] for hit in self.search(needle)] == [cid]

    def test_an_80_character_query_still_returns_results(self):
        needle = "예산" + "나" * 76 + "심사"
        cid = self.seed(f"합성 기록 {needle}")
        assert [hit["id"] for hit in self.search(needle)] == [cid]

    def test_wildcard_characters_in_a_query_stay_literal(self):
        self.seed("합성 기록 axb 본문")
        assert self.search("a_b") == [], "_ must not act as a single-character wildcard"
        wildcard_free = self.seed("합성 기록 두 번째 본문")
        percent = self.seed("합성 기록 50% 할인 본문")
        # A literal % matches only the row that carries the character, so it is
        # not behaving as "anything" — and it still finds the row that has one.
        hits = [hit["id"] for hit in self.search("%")]
        assert hits == [percent]
        assert wildcard_free not in hits
        assert [hit["id"] for hit in self.search("50%")] == [percent]

    def test_ascii_search_stays_case_insensitive(self):
        cid = self.seed("합성 기록 Padiem Community Budget")
        assert [hit["id"] for hit in self.search("community budget")] == [cid]

    def test_emoji_query_matches_the_record_that_carries_it(self):
        cid = self.seed("합성 기록 축제 🎉 안전 점검")
        assert [hit["id"] for hit in self.search("축제 🎉 안전")] == [cid]


# --- route -------------------------------------------------------------------
def test_search_route_is_registered_with_owner_auth_contract():
    facts = search_route_facts()
    assert facts["factory_search_routes"] == [
        ("/api/conversations/search", "api_conversation_search", ("GET",))
    ]
    # Same fail-closed auth contract as the list route (AST calls).
    assert ("auth_ready", ("request",)) in facts["called"]
    assert ("current_user_id", ("request",)) in facts["called"]
    assert "auth_ready" in facts["guard_calls"]
    assert 401 in facts["status_codes"]
    # Bounded query: rejects oversized input rather than silently widening.
    assert "query_too_long" in facts["string_constants"]


# --- sidebar entry (static contract) -----------------------------------------
def test_search_module_is_fail_closed_and_independent_of_web_search():
    # Parsed from executable code (comments stripped in the helper).
    facts = search_module_facts()
    # Fail-closed default and availability from the canonical capability
    # projection (never a client-side fetch or stored flag).
    assert facts["available_initial"] is False
    assert "window.PadiemProductCapabilities" in facts["member_chains"]
    assert facts["auth_flags"] == {
        "loaded": True,
        "authenticated": True,
        "historyReady": True,
    }
    # Never reads or toggles web-search / research controls or the center card.
    for forbidden in ("webSearchButton", "webSearchStarterButton", "deepResearchButton", "웹에서 찾아줘"):
        assert forbidden not in facts["identifiers"], forbidden
        assert forbidden not in facts["string_literals"], forbidden
        assert forbidden not in facts["member_chains"], forbidden
    # No client-side credential or storage authority.
    for forbidden in ("localStorage", "sessionStorage", "document.cookie"):
        assert forbidden not in facts["identifiers"], forbidden
        assert forbidden not in facts["string_literals"], forbidden
        assert forbidden not in facts["member_chains"], forbidden
    # Opening a hit goes through the canonical loader app.js publishes, not a
    # recent-list DOM row: a hit outside the recent page must still open.
    assert "window.PadiemChatConversationOpener" in facts["member_chains"]
    assert ("opener.open", "conversationId") in facts["call_args"]
    assert "openThroughHistory" not in facts["identifiers"]
    assert not any(callee.startswith("querySelectorAll") for callee in facts["calls"])
    assert ".history-item" not in facts["string_literals"]
    # The search query is encoded, never concatenated raw into a URL.
    assert ("encodeURIComponent", "query") in facts["call_args"]


def test_search_module_reapplies_its_copy_on_locale_change():
    facts = search_module_facts()
    # Module-owned dynamic copy follows the document language and is re-applied
    # on the app's locale-change event (the same convention other modules use).
    assert "document.documentElement.lang" in facts["member_chains"]
    assert ("window", "padiem:localechange") in facts["event_listeners"]


# --- MUST FIX 1: canonical open path -----------------------------------------
def test_app_js_publishes_the_canonical_opener_and_search_uses_it() -> None:
    opener = app_opener_facts()
    # The handle forwards to the one loader that already owns auth, the inFlight
    # lock, project restore and the server-verified Claw set.
    assert opener["frozen"] is True
    assert (opener["open_param"], opener["open_callee"], opener["open_arg"]) == (
        "conversationId",
        "openSavedConversation",
        "conversationId",
    )

    facts = search_module_facts()
    assert "window.PadiemChatConversationOpener" in facts["member_chains"]
    assert ("opener.open", "conversationId") in facts["call_args"]
    # The hit id is validated before it can reach the loader.
    assert ("^chat_[a-f0-9]{32}$", "conversationId") in facts["regex_tests"]
    # No second conversation route: the module fetches the search endpoint only.
    assert not any("conversationId}" in literal for literal in facts["string_literals"])
    assert facts["endpoint"] == "/api/conversations/search"
    assert "SEARCH_ENDPOINT" in facts["identifiers"]
    assert len(facts["fetch_calls"]) == 1
    assert facts["fetch_calls"][0]["awaited"] is True
    assert "SEARCH_ENDPOINT" in facts["fetch_calls"][0]["target"]
    assert "conversationId" not in facts["fetch_calls"][0]["target"]


def test_opener_is_called_for_every_hit_not_only_recent_list_rows() -> None:
    render = search_function_facts("renderResults")
    # Each rendered row binds the canonical opener directly, so membership in the
    # recent list can no longer decide whether a hit is clickable.
    assert ("row", "click") in render["event_listeners"]
    assert ("openHit", "conversation.id") in render["call_args"]
    facts = search_module_facts()
    assert "match.click" not in facts["calls"]
    assert "data-conversation-id" not in facts["string_literals"]
    # The recent-list row no longer carries the id attribute the delegation used.
    assert app_opener_facts()["data_conversation_id_literals"] == set()


# --- MUST FIX 2: query / auth race and stale results -------------------------
def test_generation_is_superseded_at_the_keystroke_not_when_the_call_starts() -> None:
    listener = search_listener_facts("input", "input")
    events = listener["events"]
    # The old request is superseded before the debounce is even scheduled, so a
    # response to the previous query can never land after a newer keystroke.
    assert events.index("++generation") < events.index("setTimeout")
    # Any pending debounce is cancelled, and the previous rows are dropped at the
    # same instant rather than lingering under a "searching" label.
    assert ("clearTimeout", "debounceTimer") in listener["call_args"]
    assert "results.replaceChildren" in listener["calls"]
    assert events.index("results.replaceChildren") < events.index("setTimeout")
    # The captured generation is handed to the request, not re-read later.
    assert ("runSearch", "rawQuery, seq") in listener["call_args"]


def test_every_async_continuation_refuses_a_superseded_generation() -> None:
    run = search_function_facts("runSearch")
    events = run["events"]
    # Entry, after the response, and after a rejection: all three compare, so no
    # path lets a stale response write results or status.
    assert run["comparisons"].count("seq!==generation") >= 3
    assert events.index("seq!==generation") < events.index("fetch")
    assert ("renderResults", "data.conversations, query") in run["call_args"]
    assert events.index("seq!==generation") < events.index("renderResults")
    show_status_args = [args for callee, args in run["call_args"] if callee == "showStatus"]
    assert len(show_status_args) == 2
    assert all("검색을 사용할 수 없습니다." in args for args in show_status_args)
    assert events.index("seq!==generation") < events.index("showStatus")


def test_close_and_session_flip_invalidate_and_erase_the_panel() -> None:
    close = search_function_facts("closeSearch")
    assert "invalidate" in close["calls"]
    assert close["assignments"].get("input.value") == '""'
    assert close["events"].index("invalidate") < close["events"].index("assign:panel.hidden=true")

    availability = search_function_facts("applyAvailability")
    assert "if:!available" in availability["if_conditions"]
    assert "closeSearch" in availability["calls"]
    assert availability["events"].index("if:!available") < availability["events"].index("closeSearch")

    auth = search_function_facts("applyAuthState")
    # Only a real transition clears: the projection re-dispatches on every window
    # focus, and clearing then would erase results the owner is reading.
    assert "signature!==authSignature" in auth["comparisons"]
    assert "if:changed" in auth["if_conditions"]
    assert "invalidate" in auth["calls"]
    assert auth["events"].index("if:changed") < auth["events"].index("invalidate")

    invalidate = search_function_facts("invalidate")
    assert "generation+=1" in invalidate["events"]
    assert ("clearTimeout", "debounceTimer") in invalidate["call_args"]
    assert "results.replaceChildren" in invalidate["calls"]
    assert "clearStatus" in invalidate["calls"]


# --- quality: scoped sidebar styling ----------------------------------------
def test_search_input_and_snippet_have_scoped_sidebar_styles() -> None:
    input_decls = search_css_declarations(".conversation-search-input")
    assert input_decls.get("width") == "100%"
    assert input_decls.get("box-sizing") == "border-box"
    assert input_decls.get("min-width") == "0"
    assert input_decls.get("min-height") == "44px"
    assert input_decls.get("color") == "inherit"

    hit_decls = search_css_declarations(".conversation-search-hit")
    # The inherited .history-item nowrap/ellipsis would flatten a two-line hit.
    assert hit_decls.get("white-space") == "normal"
    assert hit_decls.get("min-width") == "0"

    snippet_decls = search_css_declarations(".conversation-search-snippet")
    assert snippet_decls.get("-webkit-line-clamp") == "2"
    assert snippet_decls.get("overflow") == "hidden"
    assert snippet_decls.get("overflow-wrap") == "anywhere"
