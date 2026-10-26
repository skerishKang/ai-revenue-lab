#!/usr/bin/env python3
"""B14 health probe for COM2 operators (#5784).

Asks the loopback service the same question the existing COM2 supervisor asks of
B14 -- ``GET /health`` must answer ``status == "ok"`` and
``app == "korean-ai-platform"`` -- and adds the one truth an operator cannot
guess from a 200: whether this instance is still in demo mode.

Stdlib only, so it runs on a host before the application's own virtualenv is
working. Prints value-free JSON on one line and never a response body.

    exit 0 healthy | 1 unhealthy | 2 probe error
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

KIND = "PADIEM_COM2_B14_HEALTH_V1"
DEFAULT_URL = "http://127.0.0.1:8789/health"
EXPECTED_APP = "korean-ai-platform"


def probe(url: str, timeout: float) -> tuple[int, list[str], dict[str, object]]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
            status = int(response.status)
            raw = response.read(65_536)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # Reason class only: a URL can carry a host an operator did not approve
        # for a log line, and the exception text can echo it.
        return 2, ["unreachable:%s" % type(exc).__name__], {}
    if status != 200:
        return 1, ["http_status:%d" % status], {}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return 1, ["health_body_malformed"], {}
    if not isinstance(payload, dict):
        return 1, ["health_shape_invalid"], {}
    issues: list[str] = []
    if payload.get("status") != "ok":
        issues.append("status_not_ok")
    if payload.get("app") != EXPECTED_APP:
        issues.append("app_identity_mismatch")
    if payload.get("demo_mode") is True:
        # A demo-mode answer is a real answer about a test bed, not a live B14.
        issues.append("demo_mode_true")
    observed = {
        key: payload.get(key) for key in ("app", "phase", "demo_mode") if key in payload
    }
    return (1 if issues else 0), issues, observed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args(argv)
    code, issues, observed = probe(args.url, args.timeout)
    print(
        json.dumps(
            {
                "kind": KIND,
                "healthy": code == 0,
                "exit_code": code,
                "issues": issues,
                "observed": observed,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return code


if __name__ == "__main__":
    sys.exit(main())
