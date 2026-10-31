#!/usr/bin/env python3
"""P01 host configuration gate for COM2 (CTO decision 2026-10-31: loopback 8811).

Runs as systemd's ``ExecCondition`` and from ``start.sh``, so a host that is not
wired the reviewed way does not start a service that would then answer on the
wrong interface or fail opaquely.

Checks, in this order:

1. the bind is ``127.0.0.1:8811`` and nothing else — a routable host is a
   different trust decision, not a typo to tolerate;
2. the loopback dev flag is absent, because the host run must never inherit the
   dev allowance;
3. the release provides the ASGI entrypoint the unit starts.

Only names and fixed constants are printed. No credential, caller id value or
path from the environment is ever echoed.

    exit 0 ready | 2 refused (reason code) | 1 usage
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

KIND = "PADIEM_COM2_P01_CONFIG_V1"
EXPECTED_HOST = "127.0.0.1"
EXPECTED_PORT = "8811"
ASGI_ENTRY = "asgi.py"
CALLER_ID_ENV = "PADIEM_ENGINE_CALLER_ID"
CALLER_SECRET_ENV = "PADIEM_ENGINE_CALLER_SECRET"
MIN_SECRET_BYTES = 32
MAX_SECRET_BYTES = 512

REFUSED = (
    "p01_bind_not_loopback",
    "p01_port_mismatch",
    "p01_local_dev_forbidden",
    "p01_asgi_entry_missing",
    "p01_caller_id_invalid",
    "p01_caller_secret_invalid",
)


def _text(env: dict[str, str], name: str) -> str:
    value = env.get(name)
    return value.strip() if isinstance(value, str) else ""


def _flag(env: dict[str, str], name: str) -> bool:
    return _text(env, name).lower() in {"1", "true", "yes", "on"}


def check(env: dict[str, str], app_root: Path) -> str | None:
    """Return the first refusal reason, or ``None`` when the host is ready."""

    if _text(env, "P01_HOST") != EXPECTED_HOST:
        return "p01_bind_not_loopback"
    if _text(env, "P01_PORT") != EXPECTED_PORT:
        return "p01_port_mismatch"
    if _flag(env, "PADIEM_LOCAL_DEV"):
        # The COM2 host has a real origin; the dev allowance must stay off.
        return "p01_local_dev_forbidden"
    if not (app_root / "app" / ASGI_ENTRY).is_file():
        return "p01_asgi_entry_missing"
    caller_id = _text(env, CALLER_ID_ENV)
    if not caller_id or len(caller_id) > 128:
        return "p01_caller_id_invalid"
    # The engine authenticates every non-health route, so an unset credential is
    # a host that would answer 200 on /health and refuse every real call.
    secret = env.get(CALLER_SECRET_ENV)
    size = len(secret.encode("utf-8")) if isinstance(secret, str) else 0
    if not MIN_SECRET_BYTES <= size <= MAX_SECRET_BYTES:
        return "p01_caller_secret_invalid"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", default="/opt/padiem/p01")
    args = parser.parse_args(argv)
    env = dict(os.environ)
    reason = check(env, Path(args.app_root))
    if reason is not None:
        print(f"P01_CONFIG=REFUSED reason={reason}")
        return 2
    print(
        f"P01_CONFIG=READY kind={KIND} host=loopback "
        f"port={EXPECTED_PORT} asgi_entry=present"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
