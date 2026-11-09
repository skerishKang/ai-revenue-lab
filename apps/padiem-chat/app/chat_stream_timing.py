"""Chat 스트리밍 한 요청의 첫 바이트 구간 시간(#4379 후속 TTFB).

로그에는 단계 이름과 밀리초만 남긴다. 요청 본문·사용자 식별자·대화 내용은
넣지 않는다(orchestration_timing과 같은 규칙). 한 요청은 한 줄만 남기고,
응답이 끝나기 전에 이미 한 줄을 남겼으면 다시 남기지 않는다.
"""
from __future__ import annotations

import logging
from time import perf_counter

from .journal_host import ensure_journal_visible

LOG = logging.getLogger("padiem_chat.chat_stream_timing")
LOG.setLevel(logging.INFO)


def ensure_host_visible() -> None:
    """Make the stage line reach the journal on a host that configured no logging.

    Uvicorn configures only its own loggers, so on the COM2 host the root logger
    has no handler and the fallback handler drops INFO records. The fix is the
    shared ``journal_host`` one, so every stage logger binds identically.
    """
    ensure_journal_visible(LOG)


# (필드 이름, 시작 표식, 끝 표식). 표식 사이의 실제 시간만 구간 값이 된다.
STAGES = (
    ("validate", "entry", "validated"),
    ("history", "validated", "history"),
    ("project", "history", "project"),
    ("preflight", "project", "preflight"),
    ("usage", "preflight", "usage"),
    ("calendar", "usage", "calendar"),
    ("grounding", "calendar", "grounding"),
    ("lane", "grounding", "lane"),
    ("dispatch", "lane", "dispatch"),
)


class ChatStreamTiming:
    """요청 하나의 첫 바이트 구간 시계. 남길 수 있는 것은 시간뿐이다."""

    __slots__ = ("_marks", "_started", "_emitted", "_outcome")

    def __init__(self) -> None:
        self._started = perf_counter()
        self._marks: dict[str, float] = {"entry": self._started}
        self._emitted = False
        self._outcome = "completed"

    def mark(self, name: str) -> None:
        self._marks[name] = perf_counter()

    def set_outcome(self, value: str) -> None:
        """Closed server-owned label: how the first byte came out."""
        if value in {"completed", "error", "tool_lane", "cancelled"}:
            self._outcome = value

    def line(self) -> str:
        fields = []
        for stage, begin, end in STAGES:
            first, second = self._marks.get(begin), self._marks.get(end)
            value = -1.0 if first is None or second is None else max(0.0, (second - first) * 1000.0)
            fields.append(f"{stage}_ms={value:.1f}")
        # 모델 첫 토큰까지(dispatch 시작 → 첫 delta). 스트림이 없으면 -1.
        begin, first = self._marks.get("dispatch"), self._marks.get("first_token")
        first_ms = -1.0 if begin is None or first is None else max(0.0, (first - begin) * 1000.0)
        fields.append(f"first_token_ms={first_ms:.1f}")
        # 헤더+첫 프레임이 나간 시점(dispatch 시작 기준). -1이면 아직 못 나간 것이다.
        flush_ms = -1.0 if begin is None else max(0.0, (self._marks.get("flushed", begin) - begin) * 1000.0)
        fields.append(f"first_frame_flush_ms={flush_ms:.1f}")
        total = max(0.0, (perf_counter() - self._started) * 1000.0)
        return (
            "chat_stream_ttfb "
            + " ".join(fields)
            + f" total_ms={total:.1f} outcome={self._outcome}"
        )

    def emit(self) -> None:
        if self._emitted:
            return
        self._emitted = True
        LOG.info(self.line())
