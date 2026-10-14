"""Windows notification-area (tray) renderer for Claw Connect (#4139 S1).

Draws exactly what ``menu_model.build_menu`` describes. It owns no business
rule: the connection state comes from the injected controller and the actions
are the injected callbacks, so nothing here can claim ``CONNECTED`` without
the controller having observed it.

Windows-only: ``win32api``/``win32gui`` are imported lazily so the offline
tests and CI can import this module on any host.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping

from . import CONNECT_PRODUCT
from .connection import ConnectionState
from .menu_model import ACTION_QUIT, ITEM_STATUS, build_menu

#: Private message the tray uses for its own taskbar callback.
WM_TRAY = 0x8000 + 21  # WM_APP + 21
WM_TRAY_TOOLTIP = WM_TRAY + 1
NIM_ADD = 0x0
NIM_DELETE = 0x2
NIF_MESSAGE = 0x1
NIF_ICON = 0x2
NIF_TIP = 0x4

_STATE_SUFFIX: dict[ConnectionState, str] = {
    ConnectionState.DISCONNECTED: "disconnected",
    ConnectionState.CONNECTING: "connecting...",
    ConnectionState.CONNECTED: "connected",
    ConnectionState.PAUSED: "paused",
}


class ConnectTray:
    """The notification-area icon and its context menu."""

    def __init__(
        self,
        *,
        state_source: Callable[[], ConnectionState],
        actions: Mapping[str, Callable[[], None]],
        web_url: str,
    ) -> None:
        self._state_source = state_source
        self._actions = dict(actions)
        self._web_url = web_url
        self._hwnd: int | None = None
        self._notify_id = 1
        self._quit_requested = threading.Event()

    # -- lifecycle ----------------------------------------------------------
    def create(self) -> int:
        """Create the hidden message window and add the tray icon."""
        import win32con  # noqa: PLC0415
        import win32gui  # noqa: PLC0415

        instance = win32gui.GetModuleHandle(None)
        class_name = f"{CONNECT_PRODUCT}.Tray"
        window_class = win32gui.WNDCLASS()
        window_class.hInstance = instance
        window_class.lpszClassName = class_name
        # pywin32 dispatches every message in this map to a bound method with the
        # full Win32 WndProc tuple ``(hwnd, msg, wparam, lparam)`` — four
        # positional arguments, not three. A handler that declares fewer raises
        # ``TypeError`` *inside* ``PumpMessages()``; the exception is swallowed by
        # the C dispatcher, so the loop keeps running and the process can only be
        # stopped by a forced kill. Every handler below therefore takes exactly
        # these four parameters.
        window_class.lpfnWndProc = {
            win32con.WM_CREATE: self._on_create,
            WM_TRAY: self._on_tray,
            win32con.WM_COMMAND: self._on_command,
            win32con.WM_DESTROY: self._on_destroy,
        }
        win32gui.RegisterClass(window_class)
        # CreateWindowEx is the canonical creation call; the hidden message
        # window needs no extended style.
        self._hwnd = win32gui.CreateWindowEx(
            0, class_name, class_name, win32con.WS_OVERLAPPED,
            0, 0, 0, 0, 0, 0, instance, None,
        )
        # Add the icon here rather than waiting for WM_CREATE: pywin32 does not
        # reliably deliver WM_CREATE to the message map, and an icon that was
        # never added makes the NIM_DELETE in ``_on_destroy`` raise — which is
        # what left the external-stop message loop hung. ``_on_create`` stays
        # wired, so a delivered WM_CREATE just refreshes the same icon
        # (Shell_NotifyIcon NIM_ADD with the same id is idempotent).
        self._apply_icon(self._hwnd)
        return self._hwnd

    def _on_create(self, hwnd: int, _msg: int, _wparam: int, _lparam: int) -> int:
        self._apply_icon(hwnd)
        return 0

    def _apply_icon(self, hwnd: int) -> None:
        """Add or refresh the icon; the standard glyph needs no binary asset."""
        import win32con  # noqa: PLC0415
        import win32gui  # noqa: PLC0415

        icon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)
        win32gui.Shell_NotifyIcon(
            NIM_ADD,
            (hwnd, self._notify_id, NIF_MESSAGE | NIF_ICON | NIF_TIP, WM_TRAY, icon,
             f"{CONNECT_PRODUCT} - {_STATE_SUFFIX[self._state_source()]}"),
        )

    def refresh(self) -> None:
        """Repaint the tooltip after a state change (safe from any thread)."""
        if self._hwnd is None:
            return
        import win32api  # noqa: PLC0415

        win32api.PostMessage(self._hwnd, WM_TRAY_TOOLTIP, 0, 0)

    # -- interaction --------------------------------------------------------
    def _on_tray(self, hwnd: int, _msg: int, wparam: int, lparam: int) -> int:
        import win32con  # noqa: PLC0415

        if wparam != self._notify_id:
            return 0
        if lparam == win32con.WM_RBUTTONUP:
            self._show_menu(hwnd)
        elif lparam == win32con.WM_LBUTTONDBLCLK:
            callback = self._actions.get("open_web")
            if callback is not None:
                callback()
        elif lparam == WM_TRAY_TOOLTIP:
            self._apply_icon(hwnd)
        return 0

    def _show_menu(self, hwnd: int) -> None:
        import win32api  # noqa: PLC0415
        import win32con  # noqa: PLC0415
        import win32gui  # noqa: PLC0415

        menu = win32gui.CreatePopupMenu()
        command_ids: dict[int, str] = {}
        next_id = 100
        for item in build_menu(self._state_source()):
            if item.separator:
                win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")
                continue
            flags = win32con.MF_STRING
            if not item.enabled or item.id == ITEM_STATUS:
                flags |= win32con.MF_GRAYED
            command_ids[next_id] = item.id
            win32gui.AppendMenu(menu, flags, next_id, item.label)
            next_id += 1

        x, y = win32api.GetCursorPos()
        command = win32gui.TrackPopupMenu(
            menu, win32con.TPM_RIGHTBUTTON | win32con.TPM_RETURNCMD, x, y, 0, hwnd, None
        )
        win32gui.DestroyMenu(menu)
        win32api.PostMessage(hwnd, win32con.WM_NULL, 0, 0)
        action_id = command_ids.get(command)
        if action_id is None:
            return
        if action_id == ACTION_QUIT:
            self.quit()
            return
        callback = self._actions.get(action_id)
        if callback is not None:
            callback()

    def _on_command(
        self, _hwnd: int, _msg: int, _wparam: int, _lparam: int
    ) -> int:
        return 0

    def _on_destroy(self, hwnd: int, _msg: int, _wparam: int, _lparam: int) -> int:
        import win32gui  # noqa: PLC0415

        # Removing the icon is best-effort cleanup. Shell_NotifyIcon raises
        # E_FAIL when the icon is already gone, and a raise here would skip
        # PostQuitMessage — leaving PumpMessages() blocked forever, which is the
        # #4420 external-stop hang. The quit message must always be posted.
        try:
            win32gui.Shell_NotifyIcon(NIM_DELETE, (hwnd, self._notify_id, 0, 0, 0, ""))
        except Exception:
            pass
        win32gui.PostQuitMessage(0)
        return 0

    # -- control ------------------------------------------------------------
    def run(self) -> None:
        """Blocking Win32 message loop. Returns after ``quit()``."""
        import win32gui  # noqa: PLC0415

        if self._hwnd is None:
            self.create()
        win32gui.PumpMessages()

    def quit(self) -> None:
        """Request the message loop to end. Safe from any thread."""
        self._quit_requested.set()
        if self._hwnd is None:
            return
        import win32con  # noqa: PLC0415
        import win32gui  # noqa: PLC0415

        win32gui.PostMessage(self._hwnd, win32con.WM_DESTROY, 0, 0)

    @property
    def hwnd(self) -> int | None:
        return self._hwnd

    @property
    def quit_requested(self) -> bool:
        return self._quit_requested.is_set()


__all__ = [
    "ConnectTray",
    "NIF_ICON",
    "NIF_MESSAGE",
    "NIF_TIP",
    "NIM_ADD",
    "NIM_DELETE",
    "WM_TRAY",
]
