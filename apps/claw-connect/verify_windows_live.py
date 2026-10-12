"""Non-production live verification for Claw Connect (#4139 S1).

Runs only on the developer PC. Every registry value and shortcut it creates is
removed again, and no production secret, broker, pairing or user file is
touched. The result is a JSON report; a failed item is reported, never
papered over.

    python verify_windows_live.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent
RESULT: list[dict] = []


def record(name: str, passed: bool, detail: str = "") -> None:
    RESULT.append({"check": name, "pass": passed, "detail": detail})
    print(f"[{'PASS' if passed else 'FAIL'}] {name} {detail}".rstrip(), flush=True)


def connect(*args: str, timeout: float = 60.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "claw_connect", *args],
        capture_output=True, text=True, timeout=timeout,
        cwd=str(APP_ROOT), env={"PYTHONPATH": str(APP_ROOT), **__import__("os").environ},
    )


def find_connect_processes() -> list[int]:
    """PIDs of every running `claw_connect` process (Windows only)."""
    if sys.platform != "win32":
        return []
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | "
         "Where-Object { $_.CommandLine -like '*claw_connect*' }).ProcessId"],
        capture_output=True, text=True, timeout=30,
    ).stdout
    return [int(p) for p in out.split() if p.strip().isdigit()]


def check_single_instance() -> None:
    first = subprocess.Popen(
        [sys.executable, "-m", "claw_connect", "start"],
        cwd=str(APP_ROOT), env={"PYTHONPATH": str(APP_ROOT), **__import__("os").environ},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(3.0)
    running = find_connect_processes()
    record("tray_starts", first.poll() is None and len(running) >= 1,
           f"pid={first.pid} running={running}")

    second = connect("start", timeout=20.0)
    record("second_instance_refused", second.returncode == 3,
           f"exit={second.returncode} stdout={second.stdout.strip()[:120]}")

    # Graceful stop through the quit event, then verify nothing is left.
    # Defect-2 hardening: a forced kill()/taskkill must NEVER be masked as a
    # normal-shutdown PASS. Track whether the graceful wait timed out and we had
    # to force-kill; if so the check FAILS even though the process is gone.
    stop = connect("stop", timeout=20.0)
    forced_kill = False
    try:
        first.wait(timeout=15.0)
    except subprocess.TimeoutExpired:
        forced_kill = True
        first.kill()
        first.wait(timeout=5.0)
    time.sleep(2.0)
    remaining = find_connect_processes()
    graceful = first.returncode is not None and not remaining and not forced_kill
    detail = (
        f"exit={first.returncode} remaining={remaining} "
        f"forced_kill={forced_kill} stop={stop.stdout.strip()[:120]}"
    )
    if forced_kill:
        detail += (
            " (FAIL: external stop did not terminate the Win32 message loop; "
            "force-kill was required)"
        )
    record("quit_stops_cleanly", graceful, detail)


def check_autostart() -> None:
    import winreg  # noqa: PLC0415

    run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    name = "PadiemClawConnect"

    on = connect("autostart", "on", timeout=30.0)
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key) as key:
        value, _ = winreg.QueryValueEx(key, name)
    record("autostart_registers_on_request", on.returncode == 0 and bool(value),
           f"exit={on.returncode} registered={bool(value)}")

    off = connect("autostart", "off", timeout=30.0)
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key) as key:
            winreg.QueryValueEx(key, name)
        still = True
    except FileNotFoundError:
        still = False
    record("autostart_removes_on_request", off.returncode == 0 and not still,
           f"exit={off.returncode} still_present={still}")


def check_installer() -> None:
    import shutil  # noqa: PLC0415

    shortcut = Path.home() / (
        "AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Padiem/"
        "Padiem Claw Connect.lnk"
    )
    install_root = Path.home() / "AppData/Local/Padiem/ClawConnect"

    install = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", str(APP_ROOT / "install.ps1")],
        capture_output=True, text=True, timeout=180,
    )
    installed = shortcut.exists() and (install_root / "claw_connect" / "__init__.py").exists()
    record("installer_creates_shortcut_and_module",
           install.returncode == 0 and installed,
           f"exit={install.returncode} shortcut={shortcut.exists()} module={installed}")

    uninstall = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", str(APP_ROOT / "install.ps1"), "-Uninstall"],
        capture_output=True, text=True, timeout=180,
    )
    record("uninstaller_removes_everything",
           uninstall.returncode == 0 and not shortcut.exists() and not install_root.exists(),
           f"exit={uninstall.returncode} shortcut_left={shortcut.exists()} "
           f"root_left={install_root.exists()}")
    if shortcut.exists():
        shortcut.unlink()
    if install_root.exists():
        shutil.rmtree(install_root, ignore_errors=True)


def main() -> int:
    if sys.platform != "win32":
        print(json.dumps({"ok": False, "detail": "Windows host required"}))
        return 2
    check_single_instance()
    check_autostart()
    check_installer()
    ok = all(item["pass"] for item in RESULT)
    print(json.dumps({"ok": ok, "checks": RESULT}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
