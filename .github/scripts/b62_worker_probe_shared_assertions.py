"""Exact real-Pyodide result predicates from four original Worker probes.

Run after each separate real Worker fetch; no bypassed runtime requests.
Synthetic local origin services only, with exact status and fail-closed fields.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

REQUIRED = {
    "timeout": (
        "abortsignal_import", "abortsignal_timeout_call",
        "fetch_accepts_signal", "local_normal_fetch", "local_post_form",
        "local_delay_timeout", "local_body_timeout",
    ),
    "web_transport": (
        "real_httpx_transport_class", "js_fetch_import", "abortsignal_import",
        "fetch_accepts_signal", "local_normal_fetch", "local_post_body_headers",
        "local_incremental_body", "local_delay_timeout",
        "local_body_timeout", "early_close_release",
    ),
    "p01_binding": (
        "adapter_composed", "worker_request_factory_real",
        "plus_route_entered", "binding_fetch_called_once",
        "bounded_error_after_fetch",
    ),
    "r2_read": (
        "js_arraybuffer_to_bytes", "object_arraybuffer_called_once",
        "bucket_get_called_once", "stream_body_not_used", "payload_matches",
    ),
}
REQUIRED_FALSE = {"p01_binding": "unexpected_exception", "r2_read": "unexpected_exception"}
SUCCESS = {
    "timeout": "WORKER_TIMEOUT_RUNTIME_PASS",
    "web_transport": "WORKER_WEB_TRANSPORT_PASS",
    "p01_binding": "WORKER_P01_BINDING_COMPOSITION_PASS",
    "r2_read": "WORKER_R2_OBJECTBODY_READ_PASS",
}


def check(case: str, content: object) -> str:
    if case not in REQUIRED or not isinstance(content, dict):
        raise ValueError("unknown case or malformed result")
    missing = [name for name in REQUIRED[case] if content.get(name) is not True]
    extra = REQUIRED_FALSE.get(case)
    if missing or (extra is not None and content.get(extra) is not False):
        raise ValueError(f"Workerd {case} failed: {missing}; result={content}")
    return SUCCESS[case]


def main() -> None:
    case = os.environ["B62_PROBE_CASE"]
    path = Path(os.environ["B62_PROBE_RESULT_PATH"])
    print(check(case, json.loads(path.read_text(encoding="utf-8"))))


if __name__ == "__main__":
    main()
