"""실행 결과 요약 합병 (#7790 R6 세 번째 구역).

`app/history.py`에서 위치만 옮긴 요약 합병과 상한이다. 동작·응답 형식·DB 쿼리
결과는 변하지 않으며, 기존 경로는 `app/history.py`가 이 이름들을 다시 내보낸다.
"""
from __future__ import annotations

MAX_RUN_RESULT_SUMMARY_CHARS = 200


def _merge_run_result_summaries(stored: object, addition: str) -> str:
    """#5015 — the run's aggregate summary over its commands' own summaries.

    The aggregate keeps the order the commands finished in, never repeats one
    summary, and stays inside the run summary bound. A failure is never
    dropped: the caller stores the failing command's own summary, and this
    merge keeps it in the aggregate.
    """

    parts: list[str] = []
    if isinstance(stored, str) and stored:
        parts = [part for part in stored.split("; ") if part]
    if addition and addition not in parts:
        parts.append(addition)
    return "; ".join(parts)[:MAX_RUN_RESULT_SUMMARY_CHARS]
