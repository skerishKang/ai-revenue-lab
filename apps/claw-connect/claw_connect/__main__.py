"""``python -m claw_connect`` / ``claw-connect`` command line (#4139 S1).

    claw-connect                start the tray (single instance)
    claw-connect status         machine-readable state, no tray
    claw-connect stop           ask a running tray to quit
    claw-connect autostart on   register "run at Windows logon" (needs a durable credential)
    claw-connect autostart off  remove it, and record the durable opt-out
    claw-connect autostart show whether it is registered
    claw-connect --version      product and version

No subcommand needs administrator rights. ``autostart`` writes only to the
current user's ``Run`` key and the current user's preference key. It is
registered by default after a successful install; ``on``/``off`` only express
the owner's explicit choice, and ``on`` is refused unless this PC already holds
a durable, valid device binding.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import AUTOSTART_RUN_VALUE_NAME, CONNECT_PRODUCT, CONNECT_VERSION, SINGLE_INSTANCE_MUTEX
from .autostart import Autostart, AutostartRefused
from .runtime import CONNECT_APP_EXIT_ALREADY_RUNNING, ConnectApp

USAGE = "%(prog)s [start|status|stop|autostart on|off|show]"


def _autostart_command() -> str:
    """The exact command line registered for logon autostart."""
    return f'"{sys.executable}" -m claw_connect start'


def _committed_enrollment() -> object | None:
    """The durable local record, for the credential gate.

    ``autostart on`` must present the same evidence the programmatic install
    path does, so the owner CLI is not a way around the gate. Read-only: it
    never mints a first-launch identity, so a refused command creates nothing.
    """
    from .enrollment import ConnectorEnrollment  # noqa: PLC0415

    return ConnectorEnrollment().committed_record()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="claw-connect",
        description=f"{CONNECT_PRODUCT} — the lightweight Windows tray connector.",
        usage=USAGE,
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="start",
        choices=["start", "status", "stop", "autostart"],
        help="default: start",
    )
    parser.add_argument(
        "autostart_mode",
        nargs="?",
        choices=["on", "off", "show"],
        help="required only when command is 'autostart'",
    )
    parser.add_argument(
        "--version", action="version",
        version=f"{CONNECT_PRODUCT} {CONNECT_VERSION}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    app = ConnectApp()

    if args.command == "status":
        print(app.status_json())
        return 0

    if args.command == "stop":
        from .runtime import QuitSignal, QUIT_EVENT_NAME  # noqa: PLC0415

        delivered = QuitSignal(QUIT_EVENT_NAME).signal()
        print(
            json.dumps(
                {"ok": delivered, "detail": "quit requested" if delivered
                 else "no running instance"},
                ensure_ascii=False,
            )
        )
        return 0 if delivered else 1

    if args.command == "autostart":
        if args.autostart_mode is None:
            print(json.dumps({"ok": False, "detail": "autostart on|off|show required"}))
            return 2
        autostart = Autostart(AUTOSTART_RUN_VALUE_NAME)
        if args.autostart_mode == "on":
            # Fail closed, exactly like the programmatic install default: the
            # CLI presents the durable record and never trusts a flag.
            try:
                autostart.enable(_autostart_command(), _committed_enrollment())
            except AutostartRefused as exc:
                print(
                    json.dumps(
                        {"ok": False, "mode": "on", "detail": str(exc)},
                        ensure_ascii=False,
                    )
                )
                return 1
        elif args.autostart_mode == "off":
            autostart.disable()
        print(
            json.dumps(
                {"ok": True, "mode": args.autostart_mode,
                 "enabled": autostart.is_enabled(),
                 "command": autostart.current_command(),
                 # The durable owner choice, so "off" is distinguishable from
                 # "never installed" across processes.
                 "preference": autostart.preference()},
                ensure_ascii=False,
            )
        )
        return 0

    # `start` (default)
    code = app.run()
    if code == CONNECT_APP_EXIT_ALREADY_RUNNING:
        print(
            json.dumps(
                {"ok": False, "detail": "already running", "mutex": SINGLE_INSTANCE_MUTEX},
                ensure_ascii=False,
            )
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
