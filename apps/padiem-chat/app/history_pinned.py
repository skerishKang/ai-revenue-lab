"""고정 열 판정 (#7790 R6 세 번째 구역 중 하나).

`app/history.py`에서 위치만 옮긴 메시지다. 동작은 변하지 않으며, 기존 경로는
`app/history.py`가 이 이름을 다시 내보낸다.
"""
from __future__ import annotations

# #7175: the SQLite/D1 refusal a database one migration behind returns when a
# pinned read is attempted. SQLite names the column as written (`pinned` or
# `c.pinned`), so the check is on the missing-column wording plus the name.
_PINNED_COLUMN_MISSING = "no such column: pinned"


def _pinned_column_missing(exc: BaseException) -> bool:
    message = str(exc)
    return "no such column" in message and "pinned" in message
