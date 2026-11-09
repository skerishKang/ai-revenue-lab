"""The monitor splits the response-assembly window into its two legs.

``result_ingest_ms`` = executor submit_ok → Chat ``pc_result stage=received``.
``poll_discovery_ms`` = that receipt → the /api/mcp response end (the status
poll's discovery overshoot). ``chat_assemble_ms`` keeps its old meaning (whole
window, submit → response end), so historic rows stay comparable.
"""

from __future__ import annotations

import importlib.util
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[3]


def _load_measure():
    spec = importlib.util.spec_from_file_location(
        "pc_read_measure", REPO / "scripts" / "ops" / "pc_read_measure.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _window():
    t_submit = 3_000_000.00
    t_submit_ok = 3_000_000.12   # +120 ms: loopback submit acknowledged
    t_received = 3_000_000.30    # +180 ms after submit_ok: Chat receipt
    t_event = 3_000_001.90       # +1.6 s later: response end (poll overshoot)

    from datetime import datetime, timezone

    def _ts(value: float) -> str:
        # The marker's ts= field must agree with the journal stamp the way the
        # real lines do (both are wall clock on one host).
        return datetime.fromtimestamp(value, timezone.utc).isoformat(
            timespec="milliseconds").replace("+00:00", "Z")

    lines = [
        {"t": t_submit, "unit": "padiem-oracle-mesh-executor.service",
         "m": ("oracle-mesh-command phase=submit ts=" + _ts(t_submit) +
               " elapsed_ms=0 "
               "dispatch_id=dsp_1 request_id=req command_id=cmd run_hash=none")},
        {"t": t_submit_ok, "unit": "padiem-oracle-mesh-executor.service",
         "m": ("oracle-mesh-command phase=submit_ok ts=" + _ts(t_submit_ok) +
               " elapsed_ms=120 "
               "dispatch_id=dsp_1 request_id=req command_id=cmd run_hash=none status=200")},
        {"t": t_received, "unit": "padiem-chat-com2.service",
         "m": "pc_result stage=received run_hash=abc dispatch_id=dsp_1"},
        {"t": t_event, "unit": "padiem-chat-com2.service",
         "m": ('{"event":"http_request","request_id":"rid","route":"/api/mcp",'
               '"duration_ms":2000.0,"timings_ms":{},"ts":"' + _ts(t_event) + '"}')},
    ]
    return t_submit, t_received, t_event, lines


def test_the_two_legs_sum_to_the_whole_assembly_window():
    measure = _load_measure()
    t_submit, t_received, t_event, lines = _window()
    probe = {
        "started_epoch": t_submit - 2.0, "ended_epoch": t_event, "request_id": "rid",
    }
    out = measure.correlate(lines, probe)
    # Whole window keeps its meaning (submit -> response end).
    assert abs(out["chat_assemble_ms"] - 1900.0) < 2.0
    assert abs(out["result_ingest_ms"] - 180.0) < 2.0
    assert abs(out["poll_discovery_ms"] - 1600.0) < 2.0
    # The legs partition everything after the submit acknowledgement: the
    # 120 ms the executor's own submit round trip took sits outside them.
    assert abs((out["result_ingest_ms"] + out["poll_discovery_ms"] + 120.0)
               - out["chat_assemble_ms"]) < 2.0


def test_without_the_receipt_markers_both_legs_stay_none():
    """Historic journals (before the pc_result hook ships) degrade to the old
    single span instead of inventing values."""
    measure = _load_measure()
    t_submit, t_received, t_event, lines = _window()
    probe = {"started_epoch": t_submit - 2.0, "ended_epoch": t_event, "request_id": "rid"}
    trimmed = [row for row in lines if "pc_result" not in row["m"]]
    out = measure.correlate(trimmed, probe)
    assert out["chat_assemble_ms"] is not None
    assert out["result_ingest_ms"] is None
    assert out["poll_discovery_ms"] is None


def test_the_legacy_submit_only_marker_still_fills_the_receipt_leg():
    """An executor without submit_ok falls back to the submit marker."""
    measure = _load_measure()
    t_submit, t_received, t_event, lines = _window()
    probe = {"started_epoch": t_submit - 2.0, "ended_epoch": t_event, "request_id": "rid"}
    without_ack = [row for row in lines if "submit_ok" not in row["m"]]
    out = measure.correlate(without_ack, probe)
    assert abs(out["result_ingest_ms"] - 300.0) < 2.0
    assert abs(out["poll_discovery_ms"] - 1600.0) < 2.0
