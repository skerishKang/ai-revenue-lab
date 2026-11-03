"""#6732 오케스트레이션 구간 시간: 한 줄, 단계 이름만, 실패·예외 경로에서도 남는다."""
from __future__ import annotations

import logging
import re
from pathlib import Path

from app.orchestration_timing import STAGES, OrchestrationTiming

ROUTES = Path(__file__).resolve().parents[1] / "app" / "orchestration_routes.py"

FIELD_ORDER = (
    "validate_ms=", "policy_ms=", "conversation_ms=", "usage_ms=",
    "pc_context_ms=", "grounding_ms=", "engine_ms=", "save_ms=",
    "first_token_ms=", "total_ms=", "retried=",
)


def _marked():
    timing = OrchestrationTiming()
    for name in ("validated", "policy", "conversation", "usage", "pc_context", "grounding", "engine", "saved"):
        timing.mark(name)
    return timing


def test_one_line_carries_every_stage_in_order():
    line = _marked().line()
    assert line.startswith("orchestration_timing_com2 ")
    positions = [line.index(field) for field in FIELD_ORDER]
    assert positions == sorted(positions), line
    for stage, _begin, _end in STAGES:
        assert re.search(rf"\b{stage}_ms=\d+\.\d", line), (stage, line)
    assert line.endswith("retried=unknown"), line
    assert len(line.split()) == 1 + len(STAGES) + 3, line


def test_unmeasured_stages_are_marked_not_guessed():
    timing = OrchestrationTiming()
    timing.mark("validated")
    line = timing.line()
    assert "engine_ms=-1.0" in line
    assert "save_ms=-1.0" in line


def test_emit_writes_one_info_record_and_no_request_material():
    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    logger = logging.getLogger("padiem_chat.orchestration_timing")
    handler = Capture()
    logger.addHandler(handler)
    try:
        _marked().emit()
    finally:
        logger.removeHandler(handler)
    assert len(records) == 1
    assert records[0].levelno == logging.INFO
    message = records[0].getMessage()
    assert message.startswith("orchestration_timing_com2 ")
    for forbidden in ("@", "sub_", "cookie", "안녕", "messages", "prompt"):
        assert forbidden not in message, (forbidden, message)


def test_the_route_marks_only_stage_names_and_always_emits():
    source = ROUTES.read_text(encoding="utf-8")
    # 실패·예외 경로 포함: finally에서 한 번 남긴다.
    assert "timing = OrchestrationTiming()" in source
    assert "response = await _answer_orchestration(request, timing)" in source
    assert "return response" in source
    assert "finally:" in source
    assert "timing.emit()" in source
    marks = re.findall(r"timing\.mark\(([^)]*)\)", source)
    assert marks == [
        '"validated"', '"policy"', '"conversation"', '"usage"',
        '"pc_context"', '"grounding"', '"engine"', '"save"',
    ], marks
