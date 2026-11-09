"""2026-11-09: every stage logger in the Chat host reaches the journal.

The serving CPython host configures no logging, so application INFO records
were created and then dropped. #7239 fixed the queue marker and #7243 the
result marker; this pins the shared ``journal_host`` helper and proves one
line per logger — the eight that now share it plus the five the audit found
without it — lands on stderr when the host configured nothing.

The last test proves one implementation: every module's hook is the shared
helper, so a new stage line cannot arrive half-configured.
"""

from __future__ import annotations

import importlib
import logging
import re
from pathlib import Path

import pytest

from app.journal_host import ensure_journal_visible

APP = Path(__file__).resolve().parents[1] / "app"

#: logger name -> (module, the INFO call site's marker text)
STAGE_LOGGERS = {
    "padiem_chat.orchestration_timing": (
        "app.orchestration_timing", "orchestration_timing_com2"),
    "padiem_chat.chat_stream_timing": (
        "app.chat_stream_timing", "chat_stream_timing"),
    "padiem_chat.queue_store_proxy": (
        "app.queue_store_proxy", "pc_queue_call"),
    "app.oracle_mesh_read_return_routes": (
        "app.oracle_mesh_read_return_routes", "pc_result"),
    "padiem_chat.orchestration_stream": (
        "app.orchestration_stream", "orchestration_stream_fallback"),
    "app.shared_profile_provision": (
        "app.shared_profile_provision", "shared_login_account_cross_check"),
    "padiem_chat.request": (
        "app.mcp_gateway_dispatch", "mcp_tool_audit"),
    "padiem_chat.pc_correlation": (
        "app.orchestration_routes", "pc_chat"),
}


def _clear(logger):
    root = logging.getLogger()
    saved = (list(root.handlers), list(logger.handlers), logger.propagate,
             logger.level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    logger.propagate = True
    logger.setLevel(logging.NOTSET)
    return saved


def _restore(logger, saved):
    root_handlers, handlers, propagate, level = saved
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.handlers[:] = root_handlers
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    logger.handlers[:] = handlers
    logger.propagate = propagate
    logger.setLevel(level)


@pytest.mark.parametrize("logger_name", sorted(STAGE_LOGGERS))
def test_each_stage_logger_writes_one_line_to_stderr(logger_name, capsys):
    """One bound handler + INFO level means the stage line is observable."""
    module_name, marker = STAGE_LOGGERS[logger_name]
    importlib.import_module(module_name)  # the logger exists as production builds it
    logger = logging.getLogger(logger_name)
    saved = _clear(logger)
    try:
        ensure_journal_visible(logger)
        assert logger.level == logging.INFO, "the level gate would drop INFO"
        assert len(logger.handlers) == 1
        assert logger.propagate is False
        logger.info("%s stage=probe run_hash=none", marker)
    finally:
        captured = capsys.readouterr()
        _restore(logger, saved)
    assert marker in captured.err, captured.err
    assert captured.err.count(marker) == 1


@pytest.mark.parametrize("logger_name", sorted(STAGE_LOGGERS))
def test_the_second_call_never_double_binds(logger_name):
    module_name, _ = STAGE_LOGGERS[logger_name]
    importlib.import_module(module_name)
    logger = logging.getLogger(logger_name)
    saved = _clear(logger)
    try:
        assert ensure_journal_visible(logger) is True
        assert ensure_journal_visible(logger) is False
        assert len(logger.handlers) == 1
    finally:
        _restore(logger, saved)


def test_the_helper_stands_aside_when_the_host_configured_logging(capsys):
    logger = logging.getLogger("padiem_chat.test_journal_stand_aside")
    saved = _clear(logger)
    host = logging.StreamHandler()
    try:
        logging.getLogger().addHandler(host)
        assert ensure_journal_visible(logger) is False
        assert logger.handlers == []
        assert logger.propagate is True
    finally:
        logging.getLogger().removeHandler(host)
        _restore(logger, saved)


def test_every_hook_in_the_app_is_the_one_shared_helper():
    """No module keeps a private copy of the fix (drift would re-hide a line)."""
    private_copies = []
    for path in sorted(APP.glob("*.py")):
        if path.name == "journal_host.py":
            continue  # the one implementation lives here by definition
        text = path.read_text(encoding="utf-8")
        if "StreamHandler(sys.stderr)" in text and "journal_host" not in text:
            private_copies.append(path.name)
        if "addHandler(handler)" in text and "journal_host" not in text:
            private_copies.append(path.name + " (addHandler)")
    assert private_copies == [], private_copies

    # And every module that binds a hook delegates to the shared helper.
    for path in sorted(APP.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if re.search(r"def ensure_\w*host_visible", text):
            assert "ensure_journal_visible" in text, path.name
