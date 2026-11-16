"""예외 5종 (#7813 H1).

`app/history.py`에서 위치만 옮긴 오류 계급이다. 동작·응답 형식·DB 쿼리 결과는
변하지 않으며, 기존 경로는 `app/history.py`가 이 이름들을 다시 내보낸다.
"""
from __future__ import annotations


class HistoryError(RuntimeError):
    pass


class HistoryContextIncomplete(HistoryError):
    """A legacy or missing full-text projection cannot be used as model truth."""
    pass


class HistoryForbidden(HistoryError):
    pass


class HistoryConflict(HistoryError):
    pass


class HistoryPinUnavailable(HistoryError):
    """The pinned column (migration 104) is absent, so only the pin half refuses.

    Renames and every existing read keep working on that database; the route
    turns this into a 503 with its own code instead of failing the list.
    """
    pass
