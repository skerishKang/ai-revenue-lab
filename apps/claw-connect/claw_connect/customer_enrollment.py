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
    import webbrowser

    # This URL is public correlation only: never carry codes, credentials,
    # browser cookies, or account identities to the native launcher.
    if not re.fullmatch(
        r"https://chat[.]padiem[.]net/api/claw/connector/enrollments/setup"
        r"[?]request_ref=link[.][0-9a-f]{32}", url,
    ):
        raise DeviceSessionRefused("pc_offer_owner_url_invalid")
    browser = _existing_padiem_browser()
    if browser:
        try:
            subprocess.Popen([browser, url], shell=False, close_fds=True)
            return
        except OSError as exc:
            raise DeviceSessionRefused("pc_offer_owner_browser_unavailable") from exc
    if not webbrowser.open(url, new=2):
        raise DeviceSessionRefused("pc_offer_owner_browser_unavailable")

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
