"""오케스트레이션 한 요청의 구간 시간(#6732).

로그에는 단계 이름과 밀리초만 남긴다. 요청 본문·사용자 식별자·대화 내용은 넣지 않는다.
측정되지 않은 구간(실행 전 예외로 끝남, PC 스트리밍 레인)은 -1로 남긴다.
재시도 횟수는 Engine 응답에 실리지 않으므로 unknown이다.
"""
from __future__ import annotations

import logging
import re
from time import perf_counter
from typing import Any

from .journal_host import ensure_journal_visible
from .pc_dispatch_wait_window import PC_DISPATCH_NO_RESULT_CODE

#: One closed-lane reason: a lower-case name, nothing else can ride here.
_PC_LANE_CODE = re.compile(r"\A[a-z][a-z0-9_]{0,40}\Z")
#: An offered-tool count is a small integer; nothing larger is a measurement.
_TOOLS_OFFERED_MAX = 64
#: The only three ways this server presses for a tool call.
_FORCED_VALUES = frozenset({"none", "required", "retry"})

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

    __slots__ = ("_marks", "_started", "_path", "_pc_lane_closed",
                "_pc_tools_offered", "_tool_called", "_forced", "_reason")

    def __init__(self) -> None:
        self._started = perf_counter()
        self._marks: dict[str, float] = {"start": self._started}
        self._path = "engine"
        # #7826: why a PC-capable turn was answered by the plain path. "none"
        # means this request never asked the question; every other value is a
        # name from chat_pc_drive, never a device, account or address.
        self._pc_lane_closed = "none"
        # #7841: how many PC tools this turn actually handed the model, and
        # whether the model then requested one. Counts only: no tool name, no
        # device, no account. "none" means this path never offered any.
        self._pc_tools_offered = "none"
        self._tool_called = "none"
        # #7841: how this turn tried to make the model use a tool. "none" is the
        # unchanged path; "required" asked the provider to require a tool call;
        # "retry" asked the same model once more in words.
        self._forced = "none"
        # #7841: why a PC tool turn ended before its result. ``None`` keeps the
        # line byte-identical to before; the only value is the closed
        # PC-dispatch window word.
        self._reason: str | None = None

    def mark(self, name: str) -> None:
        self._marks[name] = perf_counter()

    def set_path(self, value: str) -> None:
        """Answer path label only; the value is a closed server-owned enum."""

        if value in {"engine", "model_first_direct", "model_first_tool"}:
            self._path = value

    def set_pc_lane_closed(self, value: str) -> None:
        """Record one closed-lane reason; the vocabulary is server-owned."""

        if isinstance(value, str) and _PC_LANE_CODE.fullmatch(value):
            self._pc_lane_closed = value

    def set_pc_tools_offered(self, value: Any) -> None:
        """Record how many PC tools this turn offered the model.

        A count, never a list: a tool name, a device and an account stay out of
        this line. ``0`` is a real measurement (the lane carried no tool) and is
        kept apart from ``none``, which means the question was never asked.
        """

        if type(value) is int and 0 <= value <= _TOOLS_OFFERED_MAX:
            self._pc_tools_offered = str(value)

    def set_tool_called(self, value: Any) -> None:
        """Record whether the model requested one of the offered tools."""

        if type(value) is int and value in (0, 1):
            self._tool_called = str(value)

    def set_forced(self, value: str) -> None:
        """Record how this turn pressed for a tool call; a closed vocabulary."""

        if value in _FORCED_VALUES:
            self._forced = value

    def set_reason(self, value: str | None) -> None:
        """Record the closed reason a PC tool turn ended without a result."""

        self._reason = value if value == PC_DISPATCH_NO_RESULT_CODE else None

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
        reason = f" reason={self._reason}" if self._reason else ""
        return (
            "orchestration_timing_com2 "
            + " ".join(fields)
            + f" total_ms={total:.1f} path={self._path}"
            + f" pc_lane_closed={self._pc_lane_closed}"
            + f" pc_tools_offered={self._pc_tools_offered} tool_called={self._tool_called}"
            + f" forced={self._forced}"
            + reason
            + " retried=unknown"
        )

    def emit(self) -> None:
        LOG.info(self.line())
