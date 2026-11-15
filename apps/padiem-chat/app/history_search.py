"""대화 검색 보조 (#7790 R6 두 번째 구역).

`app/history.py`에서 위치만 옮긴 질의 정규화·발췌와 검색 상한이다. 동작·응답
형식·DB 쿼리 결과는 변하지 않으며, 기존 경로는 `app/history.py`가 이 이름들을
다시 내보낸다.
"""
from __future__ import annotations

# #4471 conversation search bounds: query text, result rows, and how many
# message rows a single search may scan. These cap cost; they never truncate
# a stored conversation.
MAX_CONVERSATION_SEARCH_QUERY_CHARS = 80
MAX_CONVERSATION_SEARCH_RESULTS = 20
MAX_CONVERSATION_SEARCH_SCAN_ROWS = 2000
MAX_CONVERSATION_SEARCH_SNIPPET_CHARS = 120


def _normalize_search_query(query: object) -> str:
    """Trim, collapse whitespace and bound the query. Returns '' when unusable."""
    if not isinstance(query, str):
        return ""
    collapsed = " ".join(query.split())
    return collapsed[:MAX_CONVERSATION_SEARCH_QUERY_CHARS]


def _search_snippet(hit: object, query: object) -> str:
    """Short excerpt around the first literal match. '' when there is no body hit."""
    if not isinstance(hit, str) or not hit:
        return ""
    literal = _normalize_search_query(query)
    index = hit.casefold().find(literal.casefold()) if literal else -1
    if index < 0:
        index = 0
    width = MAX_CONVERSATION_SEARCH_SNIPPET_CHARS
    start = max(0, index - width // 3)
    end = min(len(hit), start + width)
    excerpt = hit[start:end].replace("\n", " ")
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(hit) else ""
    return prefix + excerpt + suffix
