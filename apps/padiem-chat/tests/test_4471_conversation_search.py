"""#4471: owner-scoped conversation search behind the sidebar Search entry.

Contract under test:
  - search is owner-scoped with bound parameters (no interpolation);
  - the user query is a literal substring (LIKE wildcards escaped);
  - result rows and scanned rows are bounded; stored text is never truncated;
  - the sidebar entry is fail-closed and never touches web-search state.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.history import (  # noqa: E402
    PRODUCT_SCOPE_CHAT,
    MAX_CONVERSATION_SEARCH_QUERY_CHARS,
    MAX_CONVERSATION_SEARCH_RESULTS,
    MAX_CONVERSATION_SEARCH_SCAN_ROWS,
    MAX_CONVERSATION_SEARCH_SNIPPET_CHARS,
    D1HistoryStore,
    _escape_like,
    _normalize_search_query,
    _search_snippet,
)

STATIC = ROOT / "static"
SEARCH_JS = STATIC / "conversation-search.js"


# --- pure helpers -----------------------------------------------------------
def test_query_is_trimmed_collapsed_and_bounded():
    assert _normalize_search_query("  hello   world \n") == "hello world"
    assert _normalize_search_query("   ") == ""
    assert _normalize_search_query(None) == ""
    assert len(_normalize_search_query("가" * 500)) == MAX_CONVERSATION_SEARCH_QUERY_CHARS


def test_like_wildcards_and_escape_char_are_escaped_to_literals():
    # `%` and `_` must not behave as LIKE wildcards in a user query.
    assert _escape_like("50%") == "50\\%"
    assert _escape_like("a_b") == "a\\_b"
    # The escape character is escaped first so it stays literal.
    assert _escape_like("x\\y") == "x\\\\y"
    assert _escape_like("   ") == ""


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


def test_like_escape_clause_is_declared_for_every_pattern_match():
    db = _RecordingD1()
    store = D1HistoryStore(db)
    asyncio.run(store.search_conversations("usr_owner", "a_b%c", product_scope=PRODUCT_SCOPE_CHAT))
    sql, _ = _search_bound(db)
    # Each LIKE must declare the same escape character used by _escape_like.
    assert sql.count("ESCAPE '\\'") >= 3


# --- route -------------------------------------------------------------------
def test_search_route_is_registered_with_owner_auth_contract():
    factory = (ROOT / "app" / "app_factory.py").read_text(encoding="utf-8")
    assert '"/api/conversations/search"' in factory
    assert "api_conversation_search" in factory
    routes = (ROOT / "app" / "conversation_routes.py").read_text(encoding="utf-8")
    body = routes[routes.index("async def api_conversation_search"):]
    body = body[: body.index("async def api_conversation_detail")]
    # Same fail-closed auth contract as the list route.
    assert "auth_ready(request)" in body
    assert "current_user_id(request)" in body
    assert "status_code=401" in body
    # Bounded query: rejects oversized input rather than silently widening.
    assert "query_too_long" in body


# --- sidebar entry (static contract) -----------------------------------------
def test_search_module_is_fail_closed_and_independent_of_web_search():
    # Guard executable code, not the boundary-documenting comments.
    source = "\n".join(
        line for line in SEARCH_JS.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )
    # Fail-closed default and availability from the canonical capability
    # projection (never a client-side fetch or stored flag).
    assert "let available = false;" in source
    assert "window.PadiemProductCapabilities" in source
    assert "auth.loaded === true" in source
    assert "auth.authenticated === true" in source
    assert "auth.historyReady === true" in source
    # Never reads or toggles web-search / research controls or the center card.
    for forbidden in ("webSearchButton", "webSearchStarterButton", "deepResearchButton", "웹에서 찾아줘"):
        assert forbidden not in source, forbidden
    # No client-side credential or storage authority.
    for forbidden in ("localStorage", "sessionStorage", "document.cookie"):
        assert forbidden not in source, forbidden
    # Opening a hit goes through the canonical loader app.js publishes, not a
    # recent-list DOM row: a hit outside the recent page must still open.
    assert "window.PadiemChatConversationOpener" in source
    assert "opener.open(conversationId)" in source
    assert "openThroughHistory" not in source
    assert 'querySelectorAll(".history-item")' not in source
    # The search query is encoded, never concatenated raw into a URL.
    assert "encodeURIComponent(query)" in source


def test_search_module_reapplies_its_copy_on_locale_change():
    source = "\n".join(
        line for line in SEARCH_JS.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )
    # Module-owned dynamic copy follows the document language and is re-applied
    # on the app's locale-change event (the same convention other modules use).
    assert "document.documentElement.lang" in source
    assert 'addEventListener("padiem:localechange"' in source


# --- MUST FIX 1: canonical open path -----------------------------------------
def _executable(path: Path) -> str:
    """Comment-stripped source: these guards bind behavior, not prose."""
    return "\n".join(
        line for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )


def _fn(source: str, signature: str) -> str:
    start = source.index(signature)
    return source[start : source.index("\n  }", start)]


def test_app_js_publishes_the_canonical_opener_and_search_uses_it() -> None:
    app = _executable(STATIC / "app.js")
    opener = _fn(app, "window.PadiemChatConversationOpener = Object.freeze({")
    # The handle forwards to the one loader that already owns auth, the inFlight
    # lock, project restore and the server-verified Claw set.
    assert "openSavedConversation(conversationId)" in opener

    search = _executable(SEARCH_JS)
    assert "window.PadiemChatConversationOpener" in search
    assert "opener.open(conversationId)" in search
    # The hit id is validated before it can reach the loader.
    assert "/^chat_[a-f0-9]{32}$/.test(conversationId)" in search
    # No second conversation route: the module fetches the search endpoint only.
    assert "conversationId}" not in search
    assert "SEARCH_ENDPOINT" in search
    assert search.count("await fetch(") == 1


def test_opener_is_called_for_every_hit_not_only_recent_list_rows() -> None:
    search = _executable(SEARCH_JS)
    render = _fn(search, "  function renderResults(conversations, query) {")
    # Each rendered row binds the canonical opener directly, so membership in the
    # recent list can no longer decide whether a hit is clickable.
    assert 'row.addEventListener("click", () => openHit(conversation.id));' in render
    assert "match.click()" not in search
    assert "data-conversation-id" not in search
    # The recent-list row no longer carries the id attribute the delegation used.
    assert "data-conversation-id" not in _executable(STATIC / "app.js")


# --- MUST FIX 2: query / auth race and stale results -------------------------
def test_generation_is_superseded_at_the_keystroke_not_when_the_call_starts() -> None:
    search = _executable(SEARCH_JS)
    listener = search[
        search.index('input.addEventListener("input"') : search.index('input.addEventListener("keydown"')
    ]
    # The old request is superseded before the debounce is even scheduled, so a
    # response to the previous query can never land after a newer keystroke.
    assert listener.index("++generation") < listener.index("setTimeout(")
    # Any pending debounce is cancelled, and the previous rows are dropped at the
    # same instant rather than lingering under a "searching" label.
    assert "clearTimeout(debounceTimer)" in listener
    assert "results.replaceChildren()" in listener
    assert listener.index("results.replaceChildren()") < listener.index("setTimeout(")
    # The captured generation is handed to the request, not re-read later.
    assert "runSearch(rawQuery, seq)" in listener


def test_every_async_continuation_refuses_a_superseded_generation() -> None:
    search = _executable(SEARCH_JS)
    run = _fn(search, "  async function runSearch(rawQuery, seq) {")
    # Entry, after the response, and after a rejection: all three compare, so no
    # path lets a stale response write results or status.
    assert run.count("seq !== generation") >= 3
    assert run.index("seq !== generation") < run.index("await fetch(")
    for continuation in ("renderResults(data.conversations, query)", 'showStatus("검색을 사용할 수 없습니다."'):
        assert run.index("seq !== generation") < run.index(continuation)


def test_close_and_session_flip_invalidate_and_erase_the_panel() -> None:
    search = _executable(SEARCH_JS)
    close = _fn(search, "function closeSearch() {")
    assert "invalidate()" in close
    assert 'input.value = ""' in close
    assert close.index("invalidate()") < close.index("panel.hidden = true")

    availability = _fn(search, "function applyAvailability() {")
    assert "if (!available) closeSearch();" in availability

    auth = _fn(search, "function applyAuthState(auth) {")
    # Only a real transition clears: the projection re-dispatches on every window
    # focus, and clearing then would erase results the owner is reading.
    assert "signature !== authSignature" in auth
    assert "if (changed) invalidate();" in auth

    invalidate = _fn(search, "function invalidate() {")
    assert "generation += 1" in invalidate
    assert "clearTimeout(debounceTimer)" in invalidate
    assert "results.replaceChildren()" in invalidate
    assert "clearStatus()" in invalidate


# --- quality: scoped sidebar styling ----------------------------------------
def test_search_input_and_snippet_have_scoped_sidebar_styles() -> None:
    css = (STATIC / "history.css").read_text(encoding="utf-8")
    panel = css[css.index(".conversation-search-panel {") :]

    input_block = panel[panel.index(".conversation-search-input {") : panel.index(".conversation-search-results {")]
    assert "width: 100%" in input_block
    assert "box-sizing: border-box" in input_block
    assert "min-width: 0" in input_block
    assert "min-height: 44px" in input_block
    assert "color: inherit" in input_block

    hit = panel[panel.index(".conversation-search-hit {") : panel.index(".conversation-search-title {")]
    # The inherited .history-item nowrap/ellipsis would flatten a two-line hit.
    assert "white-space: normal" in hit
    assert "min-width: 0" in hit

    snippet = panel[panel.index(".conversation-search-snippet {") :]
    assert "-webkit-line-clamp: 2" in snippet
    assert "overflow: hidden" in snippet
    assert "overflow-wrap: anywhere" in snippet
