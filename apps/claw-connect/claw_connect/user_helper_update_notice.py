"""One Windows notification per observed available release, in the user's session."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

_VERSION = re.compile(r"[0-9]{1,5}\.[0-9]{1,5}\.[0-9]{1,5}(?:-rc[0-9]{1,5})?")


def available_version(path: Path) -> str | None:
    try:
        if path.stat().st_size > 4096:
            return None
        row = json.loads(path.read_text(encoding="utf-8-sig"))
        version = row.get("update_available_version")
        if (row.get("status") == "installed" and row.get("update_result") == "available"
                and row.get("auto_update") is False and isinstance(version, str)
                and _VERSION.fullmatch(version)):
            return version
    except (OSError, ValueError, AttributeError):
        pass
    return None


class UpdateNotice:
    def __init__(self, path, *, clock=time.monotonic, notified, mark, show):
        self.path, self.clock = path, clock
        self.notified, self.mark, self.show = notified, mark, show
        self.next_poll = 0

    def __call__(self):
        now = self.clock()
        if now < self.next_poll:
            return
        self.next_poll = now + 30
        version = available_version(self.path)
        if version and version != self.notified():
            self.show(version)
            self.mark(version)


def windows_notice():
    """No elevation, no new executable and no update shell action."""
    import ctypes
    import winreg

    key_path = r"Software\PADIEM\PCConnect"

    def notified():
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                return winreg.QueryValueEx(key, "NotifiedVersion")[0]
        except OSError:
            return None

    def mark(version):
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                winreg.SetValueEx(key, "NotifiedVersion", 0, winreg.REG_SZ, version)
        except OSError:
            pass

    def show(version):
        def display():
            ctypes.windll.user32.MessageBoxW(
                None, "PC 연결 새 버전이 있어요. Chat에서 지금 업데이트를 선택해 주세요.",
                "PADIEM PC 연결 " + version, 0x40,
            )
        threading.Thread(target=display, daemon=True, name="padiem-update-notice").start()

    return UpdateNotice(Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Padiem" / "helper-status.json",
                        notified=notified, mark=mark, show=show)
