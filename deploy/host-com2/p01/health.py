#!/usr/bin/env python3
"""P01 health probe for COM2 operators (loopback 8811).

Asks the local Engine the same question the existing COM2 supervisor asks of
P01 -- ``GET /internal/v1/health`` must answer ``status=ok``,
``service=padiem-ai-engine``, ``completed_run``, ``streaming_run`` and
``service_identity=required_for_all_non_health_routes`` -- and never prints a
response body.

The contract is the one already declared in ``scripts/ops/com2_runtime.py``
(``CONTRACTS["p01"]``); the packaging test asserts the two cannot drift apart.

Stdlib only, so it runs on a host before the release virtualenv is working.

    exit 0 healthy | 1 unhealthy | 2 probe error
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

KIND = "PADIEM_COM2_P01_HEALTH_V1"
DEFAULT_URL = "http://127.0.0.1:8811/internal/v1/health"
EXPECTED = {
    "service": "padiem-ai-engine",
    "service_identity": "required_for_all_non_health_routes",
}
EXPECTED_TRUE = ("completed_run", "streaming_run")
OBSERVED_KEYS = ("service", "contract_version", "completed_run", "streaming_run")


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
    for name, expected in EXPECTED.items():
        if payload.get(name) != expected:
            issues.append("%s_mismatch" % name)
    for name in EXPECTED_TRUE:
        if payload.get(name) is not True:
            issues.append("%s_not_true" % name)
    observed = {key: payload.get(key) for key in OBSERVED_KEYS if key in payload}
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
