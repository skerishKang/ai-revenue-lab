"""레인 대기 시간 보조 (#7813 H1).

`app/history.py`에서 위치만 옮긴 레인 버킷의 경과 시간 계산이다. 동작·응답
형식·DB 쿼리 결과는 변하지 않으며, 기존 경로는 `app/history.py`가 이
이름들을 다시 내보낸다.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .history_errors import HistoryError


def _lane_seconds(oldest: Any, moment: datetime) -> int | None:
    """How long the oldest row in a lane bucket has been waiting, in whole seconds.

    ``None`` means the bucket is empty, which is a different fact from "0 seconds"
    and is reported as ``None`` rather than folded into a number.
    """
    if not isinstance(oldest, str) or not oldest:
        return None
    try:
        then = datetime.fromisoformat(oldest.replace("Z", "+00:00"))
    except ValueError:
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return max(0, int((moment - then).total_seconds()))


def _lane_count_age(row: Any, moment: datetime) -> dict[str, Any]:
    """One ``COUNT(*) / MIN(created_at)`` pair, as a count and an age."""
    if not isinstance(row, dict):
        raise HistoryError("oracle mesh lane read unavailable")
    count = row.get("n")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise HistoryError("oracle mesh lane read is not a count")
    return {"count": count, "oldest_seconds": _lane_seconds(row.get("oldest"), moment)}


def _lane_node(row: Any, moment: datetime) -> dict[str, Any]:
    """One PC's unanswered total, keyed by the node reference the lane stores."""
    if not isinstance(row, dict):
        raise HistoryError("oracle mesh lane read is not a row")
    node_ref = row.get("node_ref")
    count = row.get("n")
    if not isinstance(node_ref, str) or not node_ref:
        raise HistoryError("oracle mesh lane read names no node")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise HistoryError("oracle mesh lane read is not a count")
    waiting = row.get("waiting")
    if isinstance(waiting, bool) or not isinstance(waiting, int) or waiting < 0:
        raise HistoryError("oracle mesh lane read has no waiting count")
    return {"node_ref": node_ref[:256], "open": count,
            "oldest_seconds": _lane_seconds(row.get("oldest"), moment),
            "waiting": waiting,
            "waiting_oldest_seconds": _lane_seconds(row.get("waiting_oldest"), moment)}
