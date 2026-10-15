"""``python -m padiem_connector`` / ``claw-connect`` command line (#4139 S1, S2).

    padiem-connector                start the tray (single instance)
    padiem-connector status         machine-readable state, no tray
    padiem-connector stop           ask a running tray to quit
    padiem-connector login          open the reviewed PADIEM login / consent page
    padiem-connector enroll <challenge_id> <pairing_code>
                                redeem a reviewed pairing code into a device binding
    padiem-connector logout         forget this device binding (keeps the device id)
    padiem-connector autostart on   register only with a durable valid credential
    padiem-connector autostart off  remove it
    padiem-connector autostart show whether it is registered
    padiem-connector --version      product and version

No subcommand needs administrator rights. ``autostart`` writes only to the
current user's ``Run`` key. ``login``/``enroll`` never accept a password or a
browser cookie: the reviewed PADIEM session issues the one-time pairing code
that ``enroll`` redeems with this device's Broker device id.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys

from . import AUTOSTART_RUN_VALUE_NAME, CONNECT_PRODUCT, CONNECT_VERSION, SINGLE_INSTANCE_MUTEX
from .autostart import Autostart, AutostartRefused, start_command
from .enrollment import (
    BrokerNotConfiguredError,
    EnrollmentContractError,
)
from .runtime import CONNECT_APP_EXIT_ALREADY_RUNNING, ConnectApp

USAGE = "%(prog)s [start|status|doctor|stop|login|enroll|logout|autostart on|off|show]"


def _autostart_command() -> str:
    """The exact command line registered for logon autostart."""
    return start_command()


def _committed_enrollment():
    """Read-only credential gate; never mint an identity on a refused request."""
    from .enrollment import ConnectorEnrollment
    return ConnectorEnrollment().committed_record()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="padiem-connector",
        description=f"{CONNECT_PRODUCT} — the lightweight Windows tray connector.",
        usage=USAGE,
    )
    # Subcommands, so `enroll <challenge_id> <pairing_code>` can never be
    # confused with `autostart <on|off|show>`.
    sub = parser.add_subparsers(dest="command")
    parser.set_defaults(command="start")

    sub.add_parser("start", help="start the tray (single instance) — default")
    native = sub.add_parser("open-from-web", help="start tray from exact no-data OS link")
    native.add_argument("browser_launch_uri")
    sub.add_parser("status", help="machine-readable state, no tray")
    sub.add_parser("doctor", help="read-only Agent installation preflight, no Broker traffic")
    sub.add_parser("stop", help="ask a running tray to quit")
    login = sub.add_parser("login", help="open the reviewed PADIEM login / consent page")
    login.add_argument(
        "--operator-wss-review", action="store_true",
        help="open the operator-only PC registration screen and show this PC ID",
    )
    sub.add_parser("logout", help="forget this device binding (keeps the device id)")

    enroll = sub.add_parser(
        "enroll", help="redeem a reviewed pairing code into a device binding"
    )
    enroll.add_argument("enroll_challenge", help="pairing challenge id")
    enroll.add_argument("enroll_code", nargs="?", help="legacy one-time pairing code (never accepted on operator WSS argv)")
    enroll.add_argument(
        "--operator-wss-review", action="store_true",
        help="one-shot Windows DPAPI/WSS acceptance only; explicit operator gates required",
    )
    offer = sub.add_parser(
        "offer", help="offer this PC for owner approval, then auto-enroll on approval",
    )
    offer.add_argument(
        "--operator-wss-review", action="store_true",
        help="one-shot Windows DPAPI/WSS acceptance only; explicit operator gates required",
    )

    autostart = sub.add_parser("autostart", help="credential-gated Windows logon")
    autostart.add_argument("autostart_mode", choices=["on", "off", "show"])

    parser.add_argument(
        "--version", action="version",
        version=f"{CONNECT_PRODUCT} {CONNECT_VERSION}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # Never initialise device state or call any network for a refused review
    # command. Both flags are server/operator controlled, never user input.
    if args.command == "enroll" and getattr(args, "operator_wss_review", False):
        from .operator_wss_enrollment import operator_review_admitted
        if not operator_review_admitted():
            print(json.dumps({
                "ok": False, "blocked": True,
                "detail": "operator WSS/DPAPI acceptance is not configured",
            }, ensure_ascii=False))
            return 1
    # The doctor must never initialise ConnectorEnrollment or mint device state.
    # No tray, autostart, account, Broker or Resident process is started.
    if args.command == "doctor":
        from .agent_preflight import agent_preflight
        from .enrollment import default_state_dir
        snapshot = agent_preflight(state_dir=default_state_dir())
        print(json.dumps(snapshot, ensure_ascii=False, sort_keys=True))
        return 0 if snapshot["agent_ready"] else 1

    if args.command == "open-from-web":
        from .browser_launch import accepts_browser_launch_uri
        if not accepts_browser_launch_uri(args.browser_launch_uri):
            print(json.dumps({"ok": False, "blocked": True,
                              "detail": "untrusted browser launch URI"}))
            return 2
        # Browser link can only start a tray; it cannot supply any account or
        # device entitlement, cookie, one-time code or executable command.
        app = ConnectApp()
        status = app.run(explicit_connect=True)
        if status == CONNECT_APP_EXIT_ALREADY_RUNNING:
            # Browser clicked while tray is already present: signal its one
            # existing owner-initiated offer. No URL data is conveyed.
            return 0 if app.signal_customer_offer() else 2
        return status

    # STOP and autostart OFF/SHOW must remain usable even if the Agent source
    # pin is corrupt. Neither action needs to start or resolve the Resident.
    app = None if args.command in ("stop", "autostart") else ConnectApp()

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
        if getattr(args, "operator_wss_review", False):
            from .operator_wss_enrollment import operator_review_admitted
            if not operator_review_admitted():
                print(json.dumps({"ok": False, "blocked": True,
                                  "detail": "operator WSS/DPAPI acceptance is not configured"}))
                return 1
            import webbrowser
            # Device identity is nonsecret, and is never placed in a URL or
            # attached to a browser cookie. The user enters it on the page.
            device_id = app.enrollment.record().device_id
            from .operator_wss_enrollment import operator_review_target_host
            host = operator_review_target_host()
            url = "https://" + host + "/api/claw/connector/enrollments/setup"
            webbrowser.open(url)
            print(json.dumps({"ok": True, "device_id": device_id,
                              "login_url": url, "device_connected": False},
                             ensure_ascii=False))
            return 0
        url = app.login()
        print(json.dumps({"ok": True, "detail": "reviewed PADIEM login page opened",
                          "login_url": url}, ensure_ascii=False))
        return 0

    if args.command == "enroll":
        if not getattr(args, "enroll_challenge", None) or (
            not getattr(args, "operator_wss_review", False) and not getattr(args, "enroll_code", None)
        ):
            print(
                json.dumps(
                    {"ok": False,
                     "detail": "enroll requires <challenge_id> <pairing_code>"}
                )
            )
            return 2
        try:
            if getattr(args, "operator_wss_review", False):
                # Pairing proof is a one-time secret: Windows command-line
                # arguments are visible to process listings and shell history.
                # Never accept it as argv for a real WSS device operation.
                if args.enroll_code is not None:
                    print(json.dumps({"ok": False, "blocked": True,
                                      "detail": "Enter WSS pairing code at hidden prompt, not in command arguments."}))
                    return 2
                if not sys.stdin.isatty():
                    print(json.dumps({"ok": False, "blocked": True,
                                      "detail": "Secure interactive terminal required for WSS pairing."}))
                    return 1
                code = getpass.getpass("PADIEM 일회용 등록코드 (입력 숨김): ")
                if not code or len(code) > 256:
                    print(json.dumps({"ok": False, "blocked": True,
                                      "detail": "Pairing code invalid."}))
                    return 2
                from .operator_wss_enrollment import enroll_via_operator_wss_review
                result = asyncio.run(enroll_via_operator_wss_review(
                    enrollment=app.enrollment,
                    challenge_id=args.enroll_challenge,
                    pairing_code=code,
                ))
            else:
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
        except Exception as exc:
            # WebSocket/DPAPI may reveal file paths or credentials through
            # third-party exceptions. Do not project the raw error.
            if not getattr(args, "operator_wss_review", False):
                raise
            print(json.dumps({"ok": False, "blocked": True,
                              "detail": "operator WSS pairing security hold"}))
            return 1
        # Explicit review must never register Windows logon autostart.
        auto_outcome = (
            None if getattr(args, "operator_wss_review", False)
            else app.reconcile_autostart()
        )
        print(
            json.dumps(
                {"ok": True, "enrollment": result.safe_dict(),
                 "autostart": auto_outcome.value if auto_outcome else "unavailable",
                 "state": app.connector_status().value},
                ensure_ascii=False,
            )
        )
        return 0

    if args.command == "offer":
        from .operator_wss_enrollment import operator_review_admitted
        if not getattr(args, "operator_wss_review", False) or not operator_review_admitted():
            print(json.dumps({
                "ok": False, "blocked": True,
                "detail": "operator WSS/DPAPI acceptance is not configured",
            }, ensure_ascii=False))
            return 1
        try:
            from .operator_wss_enrollment import enroll_via_pending_pc_offer
            result = asyncio.run(enroll_via_pending_pc_offer(enrollment=app.enrollment))
        except EnrollmentContractError as exc:
            print(json.dumps({"ok": False, "detail": str(exc)}, ensure_ascii=False))
            return 2
        except Exception:
            # WebSocket/DPAPI may reveal file paths or credentials through
            # third-party exceptions. Do not project the raw error.
            print(json.dumps({"ok": False, "blocked": True,
                              "detail": "operator WSS pairing security hold"}))
            return 1
        # Explicit review must never register Windows logon autostart.
        print(
            json.dumps(
                {"ok": True, "enrollment": result.safe_dict(),
                 "autostart": "unavailable",
                 "state": app.connector_status().value},
                ensure_ascii=False,
            )
        )
        return 0

    if args.command == "logout":
        from .pause_preference import set_paused
        set_paused(app.enrollment.state_dir, True)
        app.enrollment.clear_enrollment()
        app.autostart.apply_lifecycle("unpair")
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
            try:
                autostart.enable(_autostart_command(), _committed_enrollment())
            except AutostartRefused as exc:
                print(json.dumps(
                    {"ok": False, "mode": "on", "detail": str(exc)},
                    ensure_ascii=False,
                ))
                return 1
        elif args.autostart_mode == "off":
            autostart.disable()
        print(
            json.dumps(
                {"ok": True, "mode": args.autostart_mode,
                 "enabled": autostart.is_enabled(),
                 # A corrupt or foreign Run value may carry secrets. Never
                 # reflect it to JSON even when a user asks for 'show'.
                 "command": (
                     autostart.current_command() if autostart.is_enabled() else None
                 ),
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
