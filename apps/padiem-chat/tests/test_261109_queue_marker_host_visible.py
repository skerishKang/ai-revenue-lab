"""2026-11-09: the ``pc_queue_call`` marker reaches the COM2 journal.

The dispatch stage times (queue wait) are read from the ``pc_queue_call``
journal marker, but the serving CPython host configures no logging: the root
logger has no handler and Python's fallback carries WARNING and above, so the
proxy's INFO records were created and then dropped. The measurement lane saw
no marker at all (2026-11-09 measurements, both lanes). The fix binds the same
message-only stderr hook the other stage lines already use — no behaviour
change, one observable line.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from app import queue_store_proxy as proxy

PROXY_SOURCE = (Path(__file__).resolve().parents[1] / "app" / "queue_store_proxy.py").read_text(
    encoding="utf-8",
)


def _cleared():
    root = logging.getLogger()
    saved_root = list(root.handlers)
    saved = (list(proxy.logger.handlers), proxy.logger.propagate)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    for handler in list(proxy.logger.handlers):
        proxy.logger.removeHandler(handler)
    proxy.logger.propagate = True
    return saved_root, saved


def _restore(saved):
    saved_root, (handlers, propagate) = saved
    logging.getLogger().handlers[:] = saved_root
    proxy.logger.handlers[:] = handlers
    proxy.logger.propagate = propagate


def test_the_marker_line_reaches_stderr_when_the_host_configured_no_logging(capsys):
    saved = _cleared()
    try:
        proxy.ensure_host_visible()
        proxy.logger.info(
            "pc_queue_call method=%s stage=%s status=%s outcome=%s reason=%s elapsed_ms=%s "
            "exception=%s transport_phase=%s run_hash=%s dispatch_id=%s",
            "create_oracle_mesh_dispatch", "complete", 200, "ok", "ok", 12,
            "none", "none", "none", "dsp-1",
        )
    finally:
        captured = capsys.readouterr()
        _restore(saved)
    line = captured.err.strip()
    assert "pc_queue_call method=create_oracle_mesh_dispatch" in line, captured.err
    assert "outcome=ok" in line and "elapsed_ms=12" in line
    assert "dispatch_id=dsp-1" in line


def test_the_hook_binds_once_and_never_duplicates():
    saved = _cleared()
    try:
        proxy.ensure_host_visible()
        proxy.ensure_host_visible()
        assert len(proxy.logger.handlers) == 1
        assert proxy.logger.propagate is False
    finally:
        _restore(saved)


def test_the_hook_stands_aside_when_the_host_configures_logging():
    saved = _cleared()
    watcher = logging.StreamHandler(sys.stderr)
    try:
        logging.getLogger().addHandler(watcher)
        proxy.ensure_host_visible()
        assert proxy.logger.handlers == []
        assert proxy.logger.propagate is True
    finally:
        logging.getLogger().removeHandler(watcher)
        _restore(saved)


def test_every_queue_call_path_invokes_the_hook():
    """The hook runs at the single logging call site, before anything logs."""
    body = PROXY_SOURCE
    hook_call = body.index("        ensure_host_visible()")
    call_def = body.index("    async def call(self, method: str")
    record_def = body.index("        def record(outcome, reason")
    assert call_def < hook_call < record_def, "the hook must run before record()"
    assert body.count("logger.info") == 1 and body.count("logger.warning") == 1
