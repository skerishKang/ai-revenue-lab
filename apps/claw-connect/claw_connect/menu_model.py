"""Tray menu contract for Claw Connect (#4139 S1 item 5).

The menu model is pure data so the exact items, their enabled state and their
order can be verified offline without a Windows desktop session. The Win32
renderer in ``tray.py`` only draws what this model says.

Required items, in order:

1. connection state (informational, never selectable)
2. open Claw Web
3. pause / resume
4. reconnect
5. disconnect
6. quit
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from . import CONNECT_PRODUCT, CONNECT_VERSION
from .connection import ConnectionState

#: Stable action ids. The renderer maps these to callbacks; nothing else may
#: invent a menu action.
ACTION_OPEN_WEB = "open_web"
ACTION_TOGGLE_PAUSE = "toggle_pause"
ACTION_RECONNECT = "reconnect"
ACTION_DISCONNECT = "disconnect"
ACTION_QUIT = "quit"
#: Starts the reviewed PADIEM login / PC-registration consent flow. Offered only
#: when the device has no usable enrollment, so a registered PC never sees it.
ACTION_LOGIN = "login"

#: Informational, non-selectable header id.
ITEM_STATUS = "status"

STATE_LABELS: dict[ConnectionState, str] = {
    ConnectionState.DISCONNECTED: "연결 안 됨",
    ConnectionState.CONNECTING: "연결 중…",
    ConnectionState.CONNECTED: "연결됨",
    ConnectionState.PAUSED: "일시중지됨",
    # Device-authority states projected from the canonical Broker lifecycle.
    ConnectionState.UNREGISTERED: "등록 안 됨",
    ConnectionState.OFFLINE: "오프라인",
    ConnectionState.REVOKED: "권한 철회됨",
}


@dataclass(frozen=True, slots=True)
class MenuItem:
    id: str
    label: str
    enabled: bool = True
    separator: bool = False


def build_menu(state: ConnectionState) -> tuple[MenuItem, ...]:
    """The tray menu for a connection state (deterministic order)."""
    connected = state is ConnectionState.CONNECTED
    paused = state is ConnectionState.PAUSED
    connecting = state is ConnectionState.CONNECTING
    busy = connected or paused or connecting

    return (
        MenuItem(ITEM_STATUS, f"{CONNECT_PRODUCT} v{CONNECT_VERSION}", enabled=False),
        MenuItem(ITEM_STATUS, STATE_LABELS[state], enabled=False),
        MenuItem("sep1", "", separator=True),
        MenuItem(ACTION_OPEN_WEB, "Claw Web 열기"),
        MenuItem("sep2", "", separator=True),
        # The reviewed login is only offered when it is actually required.
        MenuItem(
            ACTION_LOGIN,
            "PADIEM 로그인" if state is ConnectionState.UNREGISTERED else "다시 로그인",
            enabled=state
            in (ConnectionState.UNREGISTERED, ConnectionState.REVOKED),
        ),
        MenuItem("sep4", "", separator=True),
        MenuItem(
            ACTION_TOGGLE_PAUSE,
            "일시중지" if connected else "다시 시작",
            enabled=connected or paused,
        ),
        MenuItem(ACTION_RECONNECT, "다시 연결", enabled=not connecting),
        MenuItem(ACTION_DISCONNECT, "연결 해제", enabled=busy),
        MenuItem("sep3", "", separator=True),
        MenuItem(ACTION_QUIT, "종료"),
    )


def menu_labels(state: ConnectionState) -> Sequence[str]:
    return tuple(item.label for item in build_menu(state))


def selectable_ids(state: ConnectionState) -> Sequence[str]:
    """Only the enabled, selectable action ids for a state."""
    return tuple(
        item.id for item in build_menu(state) if item.enabled and not item.separator
    )
