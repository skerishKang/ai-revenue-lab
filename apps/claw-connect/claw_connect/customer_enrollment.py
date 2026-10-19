"""Customer PC first-run: reuse canonical WSS offer and DPAPI binding stores.

The existing signed owner button creates the server intent; the PC presents
only an ephemeral possession proof on the pinned outbound WSS. This connector
never claims approval from login/browser data or self-asserted device identity.
No user code, device ID field, operator flag, or second account authority.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Any

from .device_wss_enrollment import (
    DeviceSessionRefused, canonical_binding_store,
)
from .credential_install import LocalStoreCredentialReceiver
from .pending_pc_offer import run_pending_pc_offer_and_enroll
from .review_wss_transport import open_review_only_wss_socket, VerifiedReviewTls


def protected_credential_directory(state_dir: Path) -> Path:
    """One pinned per-user protected store shared with the Resident."""
    root = state_dir.expanduser()
    if not root.is_absolute() or root.is_symlink():
        raise DeviceSessionRefused("canonical_protected_store_unavailable")
    target = root / "credentials"
    if target.is_symlink():
        raise DeviceSessionRefused("canonical_protected_store_unavailable")
    return target



def _validated_browser_executable(pid: int) -> str | None:
    """Resolve only a known browser EXE, without reading its profile or tabs."""
    if os.name != "nt" or not isinstance(pid, int) or pid <= 0:
        return None
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        filename = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(filename))
        if not kernel.QueryFullProcessImageNameW(
            handle, 0, filename, ctypes.byref(size)
        ):
            return None
        candidate = Path(filename.value)
        if candidate.name.casefold() not in {
            "tabbit browser.exe", "msedge.exe", "chrome.exe", "brave.exe",
        } or not candidate.is_file():
            return None
        return str(candidate)
    finally:
        kernel.CloseHandle(handle)


def _launching_browser_process() -> str | None:
    """Prefer the external-protocol launcher's browser, not the OS default.

    Toolhelp32 parent evidence is stronger than foreground evidence. A native
    console can briefly receive focus, so foreground is only a fallback.
    """
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.Process32FirstW.restype = wintypes.BOOL
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.Process32NextW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    snap = kernel.CreateToolhelp32Snapshot(0x00000002, 0)
    if snap and ctypes.c_void_p(snap).value != ctypes.c_void_p(-1).value:
        try:
            entry = ProcessEntry()
            entry.dwSize = ctypes.sizeof(entry)
            if kernel.Process32FirstW(snap, ctypes.byref(entry)):
                while True:
                    if entry.th32ProcessID == os.getpid():
                        path = _validated_browser_executable(
                            int(entry.th32ParentProcessID)
                        )
                        if path:
                            return path
                        break
                    if not kernel.Process32NextW(snap, ctypes.byref(entry)):
                        break
        finally:
            kernel.CloseHandle(snap)

    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetForegroundWindow.restype = wintypes.HWND
    user.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND, ctypes.POINTER(wintypes.DWORD),
    ]
    user.GetWindowThreadProcessId.restype = wintypes.DWORD
    hwnd = user.GetForegroundWindow()
    if not hwnd:
        return None
    pid = wintypes.DWORD()
    user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return _validated_browser_executable(int(pid.value))


def _existing_padiem_browser() -> str | None:
    """Find one already-open PADIEM Chat browser; never read its profile/cookies."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    discovered: set[str] = set()
    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def scan(hwnd: int, unused: int) -> bool:
        length = user32.GetWindowTextLengthW(hwnd)
        if not 12 < length < 300:
            return True
        title = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title, length + 1)
        if not title.value.startswith("Padiem Chat - "):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = kernel32.OpenProcess(0x1000, False, pid.value)
        if not handle:
            return True
        try:
            filename = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(filename))
            if kernel32.QueryFullProcessImageNameW(handle, 0, filename, ctypes.byref(size)):
                candidate = Path(filename.value)
                if candidate.name.casefold() in {
                    "tabbit browser.exe", "msedge.exe", "chrome.exe",
                } and candidate.is_file():
                    discovered.add(str(candidate))
        finally:
            kernel32.CloseHandle(handle)
        return True

    if not user32.EnumWindows(scan, 0):
        raise DeviceSessionRefused("pc_offer_owner_browser_discovery_failed")
    if len(discovered) > 1:
        raise DeviceSessionRefused("pc_offer_owner_browser_ambiguous")
    return next(iter(discovered), None)


def _open_owner_approval_page(url: str) -> None:
    """Open the handoff in the browser already hosting the original Claw tab."""
    import re
    import subprocess

    # This URL is public correlation only: never carry codes, credentials,
    # browser cookies, or account identities to the native launcher.
    if not re.fullmatch(
        r"https://chat[.]padiem[.]net/api/claw/connector/enrollments/setup"
        r"[?]request_ref=link[.][0-9a-f]{32}", url,
    ):
        raise DeviceSessionRefused("pc_offer_owner_url_invalid")
    # The OS default browser might be Edge while the signed original Claw tab
    # is Tabbit (or another allowlisted browser). BroadcastChannel cannot
    # cross browser profiles, so NEVER silently open an unrelated default.
    browser = _launching_browser_process() or _existing_padiem_browser()
    if not browser:
        raise DeviceSessionRefused("pc_offer_owner_browser_unavailable")
    try:
        subprocess.Popen([browser, url], shell=False, close_fds=True)
    except OSError as exc:
        raise DeviceSessionRefused("pc_offer_owner_browser_unavailable") from exc

async def enroll_customer_pending_offer(*, enrollment: Any, on_stage: Any = None) -> Any:
    """Attempt a SINGLE live PC offer and normal canonical credential commit.

    Until LOCAL1 mounts its server-side verified-intent matcher, the server will
    decline the WSS, and nothing is enrolled. This client deliberately does
    not open an additional approval page or forge an approval reply.
    """
    if os.name != "nt" or not getattr(sys, "frozen", False):
        raise DeviceSessionRefused("customer_bundle_required")
    package = Path(sys._MEIPASS)
    if not (package / "kagent" / "local_agent_resident_process.py").is_file():
        raise DeviceSessionRefused("canonical_agent_source_unavailable")
    sys.path.insert(0, str(package))
    from kagent.local_agent_secure_transport import (
        ProtectedFileDeviceCredentialStore, WindowsDpapiProtectedDataPort,
    )

    root = protected_credential_directory(Path(enrollment.state_dir))
    root.mkdir(parents=True, exist_ok=True)
    protected = WindowsDpapiProtectedDataPort()
    receiver = LocalStoreCredentialReceiver(store=ProtectedFileDeviceCredentialStore(
        base_dir=root, protected_data=protected,
    ))
    bindings = canonical_binding_store(base_dir=str(root), protected_data=protected)
    # Reuse the same TLS-verified, fixed-host, no-redirect socket and one-shot
    # enrollment/ACK. No operator environment option or caller supplied URL.
    async with open_review_only_wss_socket(
        source_test_authorized=True, acceptance=False,
    ) as socket:
        return await run_pending_pc_offer_and_enroll(
            socket=socket, trusted_tls=VerifiedReviewTls(), enrollment=enrollment,
            receiver=receiver, binding_store=bindings,
            owner_approval_open=_open_owner_approval_page,
            on_stage=on_stage,
        )
