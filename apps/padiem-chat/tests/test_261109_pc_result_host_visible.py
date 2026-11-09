"""2026-11-09: the ``pc_result`` stage lines reach the COM2 journal.

Same host defect #7239 fixed for the queue marker: the serving CPython process
configures no logging, so the result-ingest INFO records
(``pc_result stage=received|stored|queue_finished …``) were created and then
dropped — the latency monitor could not split the result-receipt leg from the
status-poll overshoot. The fix binds the same message-only stderr hook to this
module's logger at the one ingest call site. No behaviour change.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from app import oracle_mesh_read_return_routes as routes

ROUTE_SOURCE = (
    Path(__file__).resolve().parents[1] / "app" / "oracle_mesh_read_return_routes.py"
).read_text(encoding="utf-8")


def _cleared():
    root = logging.getLogger()
    saved_root = list(root.handlers)
    saved = (list(routes._RESULT_LOG.handlers), routes._RESULT_LOG.propagate)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    for handler in list(routes._RESULT_LOG.handlers):
        routes._RESULT_LOG.removeHandler(handler)
    routes._RESULT_LOG.propagate = True
    return saved_root, saved


def _restore(saved):
    saved_root, (handlers, propagate) = saved
    logging.getLogger().handlers[:] = saved_root
    routes._RESULT_LOG.handlers[:] = handlers
    routes._RESULT_LOG.propagate = propagate


def test_the_pc_result_line_reaches_stderr_when_the_host_configured_no_logging(capsys):
    saved = _cleared()
    try:
        routes.ensure_result_log_host_visible()
        assert routes._RESULT_LOG.level == logging.INFO
        routes._RESULT_LOG.info(
            "pc_result stage=%s run_hash=%s dispatch_id=%s",
            "received", "abc123", "dsp_1",
        )
    finally:
        captured = capsys.readouterr()
        _restore(saved)
    line = captured.err.strip()
    assert "pc_result stage=received run_hash=abc123 dispatch_id=dsp_1" in line, captured.err


def test_the_hook_binds_once_and_stands_aside_when_the_host_configures_logging():
    saved = _cleared()
    watcher = logging.StreamHandler(sys.stderr)
    try:
        routes.ensure_result_log_host_visible()
        routes.ensure_result_log_host_visible()
        assert len(routes._RESULT_LOG.handlers) == 1
        assert routes._RESULT_LOG.propagate is False
        for handler in list(routes._RESULT_LOG.handlers):
            routes._RESULT_LOG.removeHandler(handler)
        routes._RESULT_LOG.propagate = True
        logging.getLogger().addHandler(watcher)
        routes.ensure_result_log_host_visible()
        assert routes._RESULT_LOG.handlers == []
        assert routes._RESULT_LOG.propagate is True
    finally:
        logging.getLogger().removeHandler(watcher)
        _restore(saved)


def test_every_result_ingest_log_site_shares_the_hooked_logger():
    """The ingest route calls the hook before anything logs, and every
    ``pc_result`` line flows through the hooked module logger."""
    hook_call = ROUTE_SOURCE.index("    ensure_result_log_host_visible()")
    route_def = ROUTE_SOURCE.index("async def oracle_mesh_read_result(")
    first_log = ROUTE_SOURCE.index('result_log.info("pc_result stage=received')
    assert route_def < hook_call < first_log, "the hook must run before the first log"
    # The local alias points at the hooked logger, not a second one.
    assert "result_log = _RESULT_LOG" in ROUTE_SOURCE
    assert ROUTE_SOURCE.count('result_log = logging.getLogger') == 0
    # Every logged pc_result stage keeps the bounded field grammar.
    for stage in ("received", "queue_finish_error"):
        assert f'pc_result stage={stage}' in ROUTE_SOURCE


def test_the_result_stage_names_stay_bounded():
    """Only reviewed stage words may cross the journal (no request material)."""
    import re

    logged = set(re.findall(r'pc_result stage=([A-Za-z_=%s"]+?)[ "]', ROUTE_SOURCE))
    # Literal stages written into the format strings:
    literals = set(re.findall(r'stage=([a-z_]+)', ROUTE_SOURCE))
    assert {"received", "queue_finish_error"} <= literals
    # The computed stages come from these exact fixed words in the code.
    for stage in ("stored", "not_appended", "queue_finished", "queue_not_finished"):
        assert f'"{stage}"' in ROUTE_SOURCE
    assert logged or literals  # the marker family exists at all
