"""#6732 오케스트레이션 구간 시간: 한 줄, 단계 이름만, 실패·예외 경로에서도 남는다."""
from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

from app.orchestration_timing import STAGES, OrchestrationTiming, ensure_host_visible

ROUTES = Path(__file__).resolve().parents[1] / "app" / "orchestration_routes.py"
HOST = Path(__file__).resolve().parents[1] / "app" / "local_cpython.py"

FIELD_ORDER = (
    "validate_ms=", "policy_ms=", "conversation_ms=", "usage_ms=",
    "pc_context_ms=", "grounding_ms=", "engine_ms=", "save_ms=",
    "first_token_ms=", "total_ms=", "path=", "retried=",
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
    assert " path=engine " in line
    assert len(line.split()) == 1 + len(STAGES) + 4, line


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
    allowed = {
        '"validated"', '"policy"', '"conversation"', '"usage"',
        '"pc_context"', '"grounding"', '"engine"', '"save"', '"first_token"',
    }
    assert set(marks) <= allowed, marks
    for required in allowed - {'"first_token"'}:
        assert required in marks, (required, marks)


def _cleared_logging():
    """Detach every handler, as the COM2 host has them: uvicorn configures its own
    loggers only, so the root logger ends up with none and logging's fallback handler
    keeps WARNING and above."""
    root = logging.getLogger()
    timing = logging.getLogger("padiem_chat.orchestration_timing")
    saved = (root.handlers[:], timing.handlers[:], timing.propagate)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    for handler in list(timing.handlers):
        timing.removeHandler(handler)
    timing.propagate = True
    return saved


def _restore_logging(saved):
    root_handlers, handlers, propagate = saved
    logging.getLogger().handlers[:] = root_handlers
    timing = logging.getLogger("padiem_chat.orchestration_timing")
    for handler in list(timing.handlers):
        timing.removeHandler(handler)
    timing.propagate = propagate


def test_the_line_reaches_stderr_when_the_host_configured_no_logging(capsys):
    saved = _cleared_logging()
    try:
        ensure_host_visible()
        _marked().emit()
    finally:
        captured = capsys.readouterr()
        _restore_logging(saved)
    assert "orchestration_timing_com2 " in captured.err, captured.err
    assert captured.err.strip().endswith("retried=unknown"), captured.err


def test_the_hook_never_writes_the_line_twice(capsys):
    saved = _cleared_logging()
    try:
        ensure_host_visible()
        ensure_host_visible()
        timing = logging.getLogger("padiem_chat.orchestration_timing")
        assert len(timing.handlers) == 1, timing.handlers
        assert timing.propagate is False
        _marked().emit()
    finally:
        captured = capsys.readouterr()
        _restore_logging(saved)
    assert captured.err.count("orchestration_timing_com2 ") == 1, captured.err


def test_the_hook_stands_aside_when_the_host_configures_logging(capsys):
    saved = _cleared_logging()
    watcher = logging.StreamHandler(sys.stderr)
    try:
        logging.getLogger().addHandler(watcher)
        ensure_host_visible()
        timing = logging.getLogger("padiem_chat.orchestration_timing")
        assert timing.handlers == [], timing.handlers
        assert timing.propagate is True
        _marked().emit()
    finally:
        captured = capsys.readouterr()
        logging.getLogger().removeHandler(watcher)
        _restore_logging(saved)
    assert "orchestration_timing_com2 " in captured.err, captured.err


def test_the_cpython_host_installs_the_hook():
    # The line is only useful if the process that serves registers it: this host has
    # no logging configuration of its own, and nothing else calls the hook.
    source = HOST.read_text(encoding="utf-8")
    assert "ensure_host_visible" in source
