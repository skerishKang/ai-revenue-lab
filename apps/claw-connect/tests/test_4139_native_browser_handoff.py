"""Browser-neutral original-Claw handoff, without any implicit consent."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from claw_connect import customer_enrollment as handoff
from claw_connect.device_wss_enrollment import DeviceSessionRefused


URL = (
    "https://chat.padiem.net/api/claw/connector/enrollments/setup"
    "?request_ref=link." + "a" * 32
)


def test_original_launching_browser_wins_over_windows_default(monkeypatch):
    launch = Mock(return_value=r"C:\\Program Files\\Tabbit\\Tabbit Browser.exe")
    fallback = Mock()
    popen = Mock()
    default = Mock(side_effect=AssertionError("default browser must not open"))
    monkeypatch.setattr(handoff, "_launching_browser_process", launch)
    monkeypatch.setattr(handoff, "_existing_padiem_browser", fallback)
    monkeypatch.setattr("subprocess.Popen", popen)
    monkeypatch.setattr("webbrowser.open", default)
    handoff._open_owner_approval_page(URL)
    popen.assert_called_once_with([launch.return_value, URL], shell=False, close_fds=True)
    fallback.assert_not_called()
    default.assert_not_called()


def test_verified_visible_browser_can_fallback(monkeypatch):
    monkeypatch.setattr(handoff, "_launching_browser_process", lambda: None)
    monkeypatch.setattr(handoff, "_existing_padiem_browser", lambda: "C:/Chrome/chrome.exe")
    popen = Mock()
    monkeypatch.setattr("subprocess.Popen", popen)
    handoff._open_owner_approval_page(URL)
    popen.assert_called_once_with(["C:/Chrome/chrome.exe", URL], shell=False, close_fds=True)


def test_unknown_browser_never_silently_opens_default(monkeypatch):
    monkeypatch.setattr(handoff, "_launching_browser_process", lambda: None)
    monkeypatch.setattr(handoff, "_existing_padiem_browser", lambda: None)
    default = Mock()
    monkeypatch.setattr("webbrowser.open", default)
    with pytest.raises(DeviceSessionRefused, match="pc_offer_owner_browser_unavailable"):
        handoff._open_owner_approval_page(URL)
    default.assert_not_called()


@pytest.mark.parametrize("untrusted", [
    "https://evil.invalid/?request_ref=link." + "a" * 32,
    URL + "&user=123",
    URL.replace("link." + "a" * 32, "link." + "b" * 31),
    "http://chat.padiem.net/api/claw/connector/enrollments/setup?request_ref=link." + "a" * 32,
])
def test_browser_handoff_never_sends_untrusted_url(monkeypatch, untrusted):
    launch = Mock()
    monkeypatch.setattr(handoff, "_launching_browser_process", launch)
    with pytest.raises(DeviceSessionRefused, match="pc_offer_owner_url_invalid"):
        handoff._open_owner_approval_page(untrusted)
    launch.assert_not_called()
