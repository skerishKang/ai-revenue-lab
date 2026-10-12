"""Claw Connect — the lightweight Windows tray connector (#4139 S1).

Claw Connect is a *thin* host: connection state, a web entry point, pause,
reconnect, disconnect and quit. It is not an AI engine, not a model router,
not a Broker and not a P01 approval server. Every local execution still goes
through the one existing supervised Windows Resident/Local Runner.

    TRAY_UI_MINIMAL=YES
    SECOND_ENGINE=0
    SECOND_APPROVAL_STORE=0
    PUBLIC_INBOUND_PORT=0
    PRODUCTION_MUTATION=0
"""

from __future__ import annotations

CONNECT_PRODUCT = "Padiem Claw Connect"
CONNECT_VERSION = "0.1.0"
#: One mutex name shared by the tray and every other Connect entry point so a
#: double click, an npx run and an autostart run all collapse to one process.
SINGLE_INSTANCE_MUTEX = "PadiemClawConnect.SingleInstance.v1"
#: Opt-in autostart is registered under HKCU (never HKLM) so no administrator
#: right is ever requested. The value is absent unless the user asks for it.
AUTOSTART_RUN_VALUE_NAME = "PadiemClawConnect"
WEB_URL = "https://chat.padiem.net/"

__all__ = [
    "AUTOSTART_RUN_VALUE_NAME",
    "CONNECT_PRODUCT",
    "CONNECT_VERSION",
    "SINGLE_INSTANCE_MUTEX",
    "WEB_URL",
]
