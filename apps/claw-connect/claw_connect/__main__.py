"""``python -m claw_connect`` / ``claw-connect`` command line (#4139 S1, S2).

    claw-connect                start the tray (single instance)
    claw-connect status         machine-readable state, no tray
    claw-connect stop           ask a running tray to quit
    claw-connect login          open the reviewed PADIEM login / consent page
    claw-connect enroll <challenge_id> <pairing_code>
                                redeem a reviewed pairing code into a device binding
    claw-connect logout         forget this device binding (keeps the device id)
    claw-connect autostart on   register "run at Windows logon" (opt-in)
    claw-connect autostart off  remove it
    claw-connect autostart show whether it is registered
    claw-connect --version      product and version

No subcommand needs administrator rights. ``autostart`` writes only to the
current user's ``Run`` key. ``login``/``enroll`` never accept a password or a
browser cookie: the reviewed PADIEM session issues the one-time pairing code
that ``enroll`` redeems with this device's Broker device id.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import AUTOSTART_RUN_VALUE_NAME, CONNECT_PRODUCT, CONNECT_VERSION, SINGLE_INSTANCE_MUTEX
from .autostart import Autostart
from .enrollment import (
    BrokerNotConfiguredError,
    EnrollmentContractError,
)
from .runtime import CONNECT_APP_EXIT_ALREADY_RUNNING, ConnectApp

USAGE = "%(prog)s [start|status|stop|login|enroll|logout|autostart on|off|show]"


def _autostart_command() -> str:
    """The exact command line registered for logon autostart."""
    return f'"{sys.executable}" -m claw_connect start'


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="claw-connect",
        description=f"{CONNECT_PRODUCT} — the lightweight Windows tray connector.",
        usage=USAGE,
    )
    # Subcommands, so `enroll <challenge_id> <pairing_code>` can never be
    # confused with `autostart <on|off|show>`.
    sub = parser.add_subparsers(dest="command")
    parser.set_defaults(command="start")

    sub.add_parser("start", help="start the tray (single instance) — default")
    sub.add_parser("status", help="machine-readable state, no tray")
    sub.add_parser("stop", help="ask a running tray to quit")
    sub.add_parser("login", help="open the reviewed PADIEM login / consent page")
    sub.add_parser("logout", help="forget this device binding (keeps the device id)")

    enroll = sub.add_parser(
        "enroll", help="redeem a reviewed pairing code into a device binding"
    )
    enroll.add_argument("enroll_challenge", help="pairing challenge id")
    enroll.add_argument("enroll_code", help="one-time pairing code")

    autostart = sub.add_parser("autostart", help="opt-in run at Windows logon")
    autostart.add_argument("autostart_mode", choices=["on", "off", "show"])

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

    if args.command == "login":
        url = app.login()
        print(
            json.dumps(
                {"ok": True, "detail": "reviewed PADIEM login page opened",
                 "login_url": url},
                ensure_ascii=False,
            )
        )
        return 0

    if args.command == "enroll":
        if not getattr(args, "enroll_challenge", None) or not getattr(args, "enroll_code", None):
            print(
                json.dumps(
                    {"ok": False,
                     "detail": "enroll requires <challenge_id> <pairing_code>"}
                )
            )
            return 2
        try:
            result = app.enrollment.complete_login(
                challenge_id=args.enroll_challenge, pairing_code=args.enroll_code
            )
        except BrokerNotConfiguredError:
            # The LOCAL1 pairing route is not activated. Report the honest
            # blocked state instead of claiming a successful enrollment.
            print(
                json.dumps(
                    {"ok": False, "blocked": True,
                     "detail": "broker pairing route is not configured; enrollment "
                               "cannot be completed",
                     "state": app.connector_status().value},
                    ensure_ascii=False,
                )
            )
            return 1
        except EnrollmentContractError as exc:
            print(json.dumps({"ok": False, "detail": str(exc)}, ensure_ascii=False))
            return 2
        print(
            json.dumps(
                {"ok": True, "enrollment": result.safe_dict(),
                 "state": app.connector_status().value},
                ensure_ascii=False,
            )
        )
        return 0

    if args.command == "logout":
        app.enrollment.clear_enrollment()
        print(
            json.dumps(
                {"ok": True, "detail": "device binding cleared",
                 "state": app.connector_status().value},
                ensure_ascii=False,
            )
        )
        return 0

    if args.command == "autostart":
        if getattr(args, "autostart_mode", None) is None:
            print(json.dumps({"ok": False, "detail": "autostart on|off|show required"}))
            return 2
        autostart = Autostart(AUTOSTART_RUN_VALUE_NAME)
        if args.autostart_mode == "on":
            autostart.enable(_autostart_command())
        elif args.autostart_mode == "off":
            autostart.disable()
        print(
            json.dumps(
                {"ok": True, "mode": args.autostart_mode,
                 "enabled": autostart.is_enabled(),
                 "command": autostart.current_command()},
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
