"""Read-only B62 streaming model timeout parity check (#4194).

Consumes the existing Cloudflare settings GET result from protected deployment
preflight. Never contacts network, prints no secret data, and never modifies state.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

BINDING = "PADIEM_CHAT_TIMEOUT_SECONDS"
EXPECTED = 600


def check_timeout_bindings(payload: object) -> str:
    if not isinstance(payload, dict) or payload.get("success") is not True:
        return "UNVERIFIED"
    result = payload.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("bindings"), list):
        return "UNVERIFIED"
    rows = [
        b for b in result["bindings"]
        if isinstance(b, dict) and b.get("name") == BINDING
    ]
    if not rows:
        # settings_from_worker_bindings uses the 600s source default when absent.
        return "DEFAULT_600"
    if len(rows) != 1 or rows[0].get("type") != "plain_text":
        return "UNVERIFIED"
    text = rows[0].get("text")
    if not isinstance(text, str) or not text.isdecimal():
        return "UNVERIFIED"
    value = int(text)
    if not 1 <= value <= 3600:
        return "UNVERIFIED"
    return "ALIGNED_600" if value == EXPECTED else "DRIFT"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--strict", action="store_true",
                        help="Exit nonzero for drift (opt-in; never changes settings).")
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.settings.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        status = "UNVERIFIED"
    else:
        status = check_timeout_bindings(payload)
    # Only bounded enum values. Never show arbitrary binding text, keys, or paths.
    print("B62_STREAM_MODEL_TIMEOUT_PARITY=" + status)
    print("MODEL_TIMEOUT_SOURCE_DEFAULT_SECONDS=600")
    print("B62_TIMEOUT_PRODUCTION_MUTATION=0")
    if status in ("DRIFT", "UNVERIFIED"):
        print("::warning::B62_STREAM_MODEL_TIMEOUT_REQUIRES_OWNER_REVIEW")
    if status == "UNVERIFIED" or (args.strict and status == "DRIFT"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
