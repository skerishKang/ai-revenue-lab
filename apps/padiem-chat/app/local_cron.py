"""CPython entrypoint for the Worker's `scheduled()` lane (#5573 stage 2).

On Cloudflare the scheduled handler calls `run_scheduled_automation_source`,
which needs the Control Plane identity RPC, the P01 engine adapter and the push
lane — none of which a native process has yet. This command is the timer-facing
entry for that lane on COM2: it evaluates the same ON/OFF gate
(`PADIEM_CHAT_AUTOMATION_SCHEDULER_ENABLED`) and reports, with a stable marker,
exactly how far it could get. It never claims a tick ran when it did not, and
it exits non-zero only on a real configuration error.
"""
from __future__ import annotations

import os
import sys

from .config import ConfigError, Settings

STATUS_PREFIX = "CHAT_LOCAL_CRON="


def _enabled(raw: str | None) -> bool:
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


def _entry_mode(env) -> str:
    """Which reviewed CPython entry is asking for this tick.

    The Worker's scheduled lane has two CPython hosts: the loopback dev run
    (``PADIEM_LOCAL_DEV=1``) and the COM2 parallel host
    (``PADIEM_CHAT_CPYTHON_HOST=1``). Requiring the dev flag alone made the COM2
    timer entry structurally unreachable, because the host run must not carry
    that flag. The two are mutually exclusive for the same reason
    ``app.local_cpython.build_app`` refuses the pair: the host run has a real
    https origin and must never get the loopback allowance.
    """

    local_flag = str(env.get("PADIEM_LOCAL_DEV", "")).strip().lower() in {"1", "true"}
    host_flag = str(env.get("PADIEM_CHAT_CPYTHON_HOST", "")).strip().lower() in {"1", "true"}
    if local_flag and host_flag:
        raise ConfigError(
            "PADIEM_LOCAL_DEV and PADIEM_CHAT_CPYTHON_HOST are mutually exclusive"
        )
    if host_flag:
        return "host"
    if local_flag:
        return "local"
    raise ConfigError(
        "app.local_cron runs only behind PADIEM_LOCAL_DEV=1 or "
        "PADIEM_CHAT_CPYTHON_HOST=1"
    )


def run_once(environ: dict[str, str] | None = None) -> str:
    """Evaluate one tick and return the stable status line.

    Order mirrors worker.py's own gates: the explicit scheduler flag first, then
    the CPython entry this process is running as, then the bindings the tick
    actually needs. A missing binding is a truthful ``NOT_CONFIGURED`` state,
    not a crash and not a pretend success.
    """

    env = os.environ if environ is None else environ
    if not _enabled(env.get("PADIEM_CHAT_AUTOMATION_SCHEDULER_ENABLED")):
        return STATUS_PREFIX + "SKIPPED reason=automation_scheduler_disabled"
    _entry_mode(env)
    # Configuration validation stays where it already lives. ``from_env`` reads
    # the process environment, while ``environ`` is this module's test seam, so
    # cross-checking the two would compare two different sources of truth.
    Settings.from_env()
    if not env.get("PADIEM_CHAT_LOCAL_IDENTITY_RPC_ORIGIN") or not env.get(
        "PADIEM_CHAT_LOCAL_IDENTITY_RPC_SECRET"
    ):
        return STATUS_PREFIX + "NOT_CONFIGURED reason=identity_rpc_unbound"
    # The tick's executor is the P01 engine adapter. Its HTTPS stand-in lands
    # with the engine bridge; until then the lane is reported, not simulated.
    return STATUS_PREFIX + "NOT_CONFIGURED reason=p01_engine_transport_unbound"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args not in ([], ["--once"]):
        print(STATUS_PREFIX + "INVALID_ARGUMENT", flush=True)
        return 2
    try:
        print(run_once(), flush=True)
    except ConfigError:
        print(STATUS_PREFIX + "CONFIG_ERROR", flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
