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
    asyncio.run(store.search_conversations("usr_owner", "견적"))
    sql, values = _search_bound(db)
    assert "c.user_id=?" in sql
    assert "usr_owner" in values
    # The owner id is never interpolated into the SQL text.
    assert "usr_owner" not in sql


def test_user_query_is_bound_not_interpolated_into_sql():
    db = _RecordingD1()
    store = D1HistoryStore(db)
    hostile = "x'); DROP TABLE conversations; --"
    asyncio.run(store.search_conversations("usr_owner", hostile))
    sql, values = _search_bound(db)
    assert "DROP TABLE" not in sql
    assert any(isinstance(v, str) and "DROP TABLE" in v for v in values)


def test_search_scan_and_result_limits_are_bound_parameters():
    db = _RecordingD1()
    store = D1HistoryStore(db)
    asyncio.run(store.search_conversations("usr_owner", "q", limit=10_000))
    sql, values = _search_bound(db)
    assert MAX_CONVERSATION_SEARCH_SCAN_ROWS in values
    assert min(MAX_CONVERSATION_SEARCH_RESULTS, 10_000) in values
    assert "LIMIT ?" in sql


def test_empty_or_whitespace_query_runs_no_search_statement():
    db = _RecordingD1()
    store = D1HistoryStore(db)
    assert asyncio.run(store.search_conversations("usr_owner", "   ")) == []
    assert not any("FROM conversations c" in sql for sql, _ in db.bound)


def test_like_escape_clause_is_declared_for_every_pattern_match():
    db = _RecordingD1()
    store = D1HistoryStore(db)
    asyncio.run(store.search_conversations("usr_owner", "a_b%c"))
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
    # Opening a hit goes through the existing history row, not a new loader.
    assert "openThroughHistory" in source
    assert 'querySelectorAll(".history-item")' in source
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
