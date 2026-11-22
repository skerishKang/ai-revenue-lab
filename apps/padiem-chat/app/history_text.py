"""날짜·레인·미리보기 보조 (#7813 H1·H3).

`app/history.py`에서 위치만 옮긴 레인 버킷의 경과 시간 계산, 날짜 보조와
미리보기·제목이다. 동작·응답 형식·DB 쿼리 결과는 변하지 않으며, 기존
경로는 `app/history.py`가 이 이름들을 다시 내보낸다.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from .history_constants import MAX_HISTORY_MESSAGE_CHARS, MAX_HISTORY_TITLE_CHARS, PC_CONFIRMATION_CARD_ACTIONS
from .history_errors import HistoryError
from .history_rows import _changed_rows
from .pc_command_confirmation import (
    PENDING_PC_COMMAND_MAX_AGE_SECONDS,
    STATUS_AWAITING_CONFIRMATION,
    STATUS_EXPIRED,
)


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


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _now_iso() -> str:
    return _iso(datetime.now(timezone.utc))


def _confirmation_card_cutoff(now: datetime | None = None) -> str:
    """#7603: the oldest created_at a confirmation card may still have."""

    moment = now if now is not None else datetime.now(timezone.utc)
    return _iso(moment - timedelta(seconds=PENDING_PC_COMMAND_MAX_AGE_SECONDS))


def _expire_stale_confirmation_cards_rule(moment: datetime) -> tuple[str, list[Any]]:
    """#7631 — the one expiry rule both retirement moments share.

    A card is expired when it is still ``waiting_approval`` on a confirmation
    card action and its ``created_at`` predates the confirm window cutoff.
    The daily purge adds no scope and a batch bound; the read paths add the
    calling owner and no bound. The condition and the target value live here
    and only here.
    """
    actions = sorted(PC_CONFIRMATION_CARD_ACTIONS)
    placeholders = ",".join("?" for _ in actions)
    condition = f"status=? AND action IN ({placeholders}) AND created_at<?"
    values = [STATUS_AWAITING_CONFIRMATION, *actions, _confirmation_card_cutoff(moment)]
    return condition, values


async def expire_stale_confirmation_cards_for_all_owners(
    binding: Any, *, limit: int, now: datetime | None = None,
) -> int:
    """#7631 — the daily purge retires every owner's expired cards at once.

    Same rule as the read paths' ``expire_stale_confirmation_cards``, without
    the owner narrowing and with the run's batch bound (a bounded subquery —
    stock SQLite UPDATE has no LIMIT). Returns how many rows this pass
    retired; anything left waits for the next daily run.
    """
    moment = now if now is not None else datetime.now(timezone.utc)
    condition, rule_values = _expire_stale_confirmation_cards_rule(moment)
    bound = max(1, int(limit))
    sql = (
        "UPDATE claw_run_history SET status=?, updated_at=? "
        f"WHERE run_id IN (SELECT run_id FROM claw_run_history WHERE {condition} "
        "ORDER BY created_at, run_id LIMIT ?)"
    )
    statement = binding.prepare(sql)
    statement = statement.bind(STATUS_EXPIRED, _iso(moment), *rule_values, bound)
    return _changed_rows(await statement.run())


HISTORY_PREVIEW_SUFFIX = "\n[저장 미리보기: 전체 내용 중 일부만 저장되었습니다.]"


def _bounded_text(value: str, label: str, preserve_edges: bool = False) -> str:
    # #4139: the stored preview is edge-trimmed by default. A terminal command
    # result is the one caller that must keep the exact leading/trailing
    # whitespace the PC produced, so it opts in explicitly instead of changing
    # the shared default for every other message.
    text = value if preserve_edges else value.strip()
    if not text.strip():
        raise HistoryError(f"{label} is empty")
    # Persistence is a bounded display preview, never a model-input ceiling.
    # Mark incomplete previews explicitly so users do not mistake saved history
    # for a full transcript when a long request/answer reached the provider.
    if len(text) <= MAX_HISTORY_MESSAGE_CHARS:
        return text
    suffix = HISTORY_PREVIEW_SUFFIX
    return text[:MAX_HISTORY_MESSAGE_CHARS - len(suffix)] + suffix


def _title_from_user_text(text: str) -> str:
    """Use the first user sentence verbatim; no model call or summarization."""
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    one_line = " ".join(first_line.split())
    boundary = re.search(r"[.!?。！？](?=\s|$)", one_line)
    if boundary:
        one_line = one_line[:boundary.end()]
    return one_line[:MAX_HISTORY_TITLE_CHARS] or "새 대화"


def _is_bounded_preview(content: str) -> bool:
    """Whether a stored D1 row is the bounded preview of a longer original.

    A message longer than ``MAX_HISTORY_MESSAGE_CHARS`` is stored as a
    truncated preview plus the private original, and the preview is marked
    explicitly. Every read that has to return the *whole* stored text decides
    with this one predicate, so the preview can never be mistaken for the
    answer.
    """
    return (
        len(content) == MAX_HISTORY_MESSAGE_CHARS
        and content.endswith(HISTORY_PREVIEW_SUFFIX)
    )
