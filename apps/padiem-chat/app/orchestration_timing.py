"""오케스트레이션 한 요청의 구간 시간(#6732).

로그에는 단계 이름과 밀리초만 남긴다. 요청 본문·사용자 식별자·대화 내용은 넣지 않는다.
측정되지 않은 구간(실행 전 예외로 끝남, PC 스트리밍 레인)은 -1로 남긴다.
재시도 횟수는 Engine 응답에 실리지 않으므로 unknown이다.
"""
from __future__ import annotations

import logging
from time import perf_counter

from .journal_host import ensure_journal_visible

LOG = logging.getLogger("padiem_chat.orchestration_timing")
LOG.setLevel(logging.INFO)


def ensure_host_visible() -> None:
    """Make the stage line reach the journal on a host that configured no logging.

    Uvicorn configures only its own loggers, so on the COM2 host the root logger has
    no handler and Python's fallback handler carries WARNING and above: an application
    INFO record is created and then dropped, which is why #6732's stage times never
    appeared in the service journal. One shared implementation now owns the fix
    (``journal_host``), so this and every other stage logger cannot drift apart.
    """
    ensure_journal_visible(LOG)


# (필드 이름, 시작 표식, 끝 표식). 표식 사이의 실제 시간만 구간 값이 된다.
STAGES = (
    ("validate", "start", "validated"),
    ("policy", "validated", "policy"),
    ("conversation", "policy", "conversation"),
    ("usage", "conversation", "usage"),
    ("pc_context", "usage", "pc_context"),
    ("grounding", "pc_context", "grounding"),
    ("engine", "grounding", "engine"),
    ("save", "engine", "saved"),
)


class OrchestrationTiming:
    """요청 하나의 구간 시계. 인자는 받지 않는다 — 남길 수 있는 것은 시간뿐이다."""

    __slots__ = ("_marks", "_started", "_path")

    def __init__(self) -> None:
        self._started = perf_counter()
        self._marks: dict[str, float] = {"start": self._started}
        self._path = "engine"

    def mark(self, name: str) -> None:
        self._marks[name] = perf_counter()

    def set_path(self, value: str) -> None:
        """Answer path label only; the value is a closed server-owned enum."""

        if value in {"engine", "model_first_direct", "model_first_tool"}:
            self._path = value

    def elapsed_ms(self) -> float:
        """Time spent in this request before the answer call (답변 시간 예산)."""

        return max(0.0, (perf_counter() - self._started) * 1000.0)

    def line(self) -> str:
        fields = []
        for stage, begin, end in STAGES:
            first, second = self._marks.get(begin), self._marks.get(end)
            value = -1.0 if first is None or second is None else max(0.0, (second - first) * 1000.0)
            fields.append(f"{stage}_ms={value:.1f}")
        # #6742: 첫 토큰까지의 시간. 스트림이 없으면 -1.
        first = self._marks.get("first_token")
        first_ms = -1.0 if first is None else max(0.0, (first - self._started) * 1000.0)
        fields.append(f"first_token_ms={first_ms:.1f}")
        total = max(0.0, (perf_counter() - self._started) * 1000.0)
        return (
            "orchestration_timing_com2 "
            + " ".join(fields)
            + f" total_ms={total:.1f} path={self._path} retried=unknown"
        )

    def emit(self) -> None:
        LOG.info(self.line())
