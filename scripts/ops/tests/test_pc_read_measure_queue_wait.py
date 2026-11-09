"""The latency monitor computes queue wait from the ``pc_queue_call`` marker.

Two-sided contract, offline:

* Chat side — the exact line shape the proxy logs (its source is read here, so
  a field rename cannot drift away from the parser).
* Monitor side — ``correlate()`` derives ``queue_wait_ms`` from that marker
  (dispatch creation) against the executor's ``phase=claimed`` marker.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[3]


def _load_measure():
    spec = importlib.util.spec_from_file_location(
        "pc_read_measure", REPO / "scripts" / "ops" / "pc_read_measure.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _marker_line(**fields) -> str:
    values = {
        "method": "create_oracle_mesh_dispatch", "stage": "complete", "status": "200",
        "outcome": "ok", "reason": "ok", "elapsed_ms": "12", "exception": "none",
        "transport_phase": "none", "run_hash": "none", "dispatch_id": "dsp-1",
    }
    values.update(fields)
    return (
        "pc_queue_call method=%(method)s stage=%(stage)s status=%(status)s "
        "outcome=%(outcome)s reason=%(reason)s elapsed_ms=%(elapsed_ms)s "
        "exception=%(exception)s transport_phase=%(transport_phase)s "
        "run_hash=%(run_hash)s dispatch_id=%(dispatch_id)s" % values
    )


PARSE_FIELDS = (
    "method", "stage", "status", "outcome", "reason", "elapsed_ms",
    "exception", "transport_phase", "run_hash", "dispatch_id",
)


def test_the_parser_matches_the_line_the_proxy_logs():
    """The logged field order and the parser's are the same contract."""
    measure = _load_measure()
    proxy_source = (REPO / "apps" / "padiem-chat" / "app" / "queue_store_proxy.py").read_text(
        encoding="utf-8",
    )
    start = proxy_source.index('"pc_queue_call method=%s')
    end = proxy_source.index("dispatch_id=%s", start)
    format_text = proxy_source[start:end + len("dispatch_id=%s")]
    logged_order = re.findall(r"(\w+)=%s", format_text)
    assert logged_order == list(PARSE_FIELDS)

    matched = measure._QUEUE_CALL_RE.match(_marker_line())
    assert matched is not None
    assert matched.group("method") == "create_oracle_mesh_dispatch"
    assert matched.group("dispatch_id") == "dsp-1"
    assert matched.group("elapsed_ms") == "12"


def test_queue_wait_is_the_claimed_marker_minus_the_dispatch_creation():
    measure = _load_measure()
    t0 = 1_000_000.0  # dispatch creation (queue call answer)
    t1 = t0 + 0.75  # executor phase=claimed
    lines = [
        {"t": t0, "unit": "padiem-chat-com2.service", "m": _marker_line()},
        {"t": t1, "unit": "padiem-oracle-mesh-executor.service",
         "m": ("oracle-mesh-command phase=claimed ts="
               "2026-11-09T00:00:00.000000+00:00 elapsed_ms=0 "
               "dispatch_id=dsp-1 request_id=req-1 command_id=cmd-1 run_hash=none")},
    ]
    probe = {"started_epoch": t0 - 1.0, "ended_epoch": t1 + 0.5, "request_id": ""}
    out = measure.correlate(lines, probe)
    assert out["dispatch_id"] == "dsp-1"
    assert out["queue_wait_ms"] == 750.0


def test_the_dispatch_marker_without_a_yet_unknown_dispatch_id_is_not_queue_wait():
    """A marker that names no dispatch (pairing reads, presence beats) never
    masquerades as the dispatch creation the queue wait is measured from."""
    measure = _load_measure()
    t0 = 2_000_000.0
    lines = [
        {"t": t0, "unit": "padiem-chat-com2.service",
         "m": _marker_line(method="links_for_owner", dispatch_id="none")},
        {"t": t0 + 0.2, "unit": "padiem-chat-com2.service", "m": _marker_line()},
        {"t": t0 + 0.5, "unit": "padiem-oracle-mesh-executor.service",
         "m": ("oracle-mesh-command phase=claimed ts="
               "2026-11-09T00:00:00.000000+00:00 elapsed_ms=0 "
               "dispatch_id=dsp-1 request_id=req-1 command_id=cmd-1 run_hash=none")},
    ]
    probe = {"started_epoch": t0 - 1.0, "ended_epoch": t0 + 1.0, "request_id": ""}
    out = measure.correlate(lines, probe)
    assert out["queue_wait_ms"] == 300.0
