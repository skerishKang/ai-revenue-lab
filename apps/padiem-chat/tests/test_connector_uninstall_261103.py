"""#6701 — Padiem PC 연결 is removable from Windows Settings and the tray.

The app-list registration and the removal path are pinned to the source that
implements them. Nothing here installs or uninstalls on a real PC.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
CS = (REPO / "scripts/pc_pairing/connect-exe/PadiemPcConnect.cs").read_text(
    encoding="utf-8"
)
INSTALL = (ROOT / "static" / "install.html").read_text(encoding="utf-8")
DOC = (REPO / "docs/operations/PC_CONNECT_EXE_20261028.md").read_text(
    encoding="utf-8"
)
MENU = (REPO / "apps/claw-connect/claw_connect/menu_model.py").read_text(
    encoding="utf-8"
)
RUNTIME = (REPO / "apps/claw-connect/claw_connect/runtime.py").read_text(
    encoding="utf-8"
)

REBUILT_SHA256 = "c302ff6dd46531dd3a874caff4a5cddac7a312cdc3ea32ce7a46ee4823f76abc"


def test_the_installer_registers_the_windows_app_list_entry():
    assert (
        r"Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\PADIEM-PC-Connect"
        in CS
    )
    assert 'UninstallDisplayName = "Padiem PC 연결"' in CS
    assert 'UninstallPublisher = "Padiem"' in CS
    assert 'key.SetValue("DisplayVersion"' in CS
    assert 'key.SetValue("UninstallString"' in CS
    assert "-Uninstall" in CS
    assert "RegistryView.Registry64" in CS
    assert "if (!RegisterUninstaller())" in CS


def test_the_uninstall_path_removes_the_service_folder_and_registration():
    assert '"-fulluninstall"' in CS
    assert "DeleteSubKeyTree(UninstallSubKey, false)" in CS
    assert "rmdir /s /q" in CS
    assert "ScheduleFolderRemoval(folder)" in CS
    assert "PadiemPcConnect.exe" in CS
    assert "if (options.Uninstall)" in CS


def test_the_tray_menu_and_runtime_offer_the_same_removal_path():
    assert 'ACTION_UNINSTALL = "uninstall"' in MENU
    assert "Padiem PC 연결 제거 (관리자 승인)" in MENU
    assert "ACTION_UNINSTALL: self.uninstall" in RUNTIME
    assert "def uninstall(self)" in RUNTIME
    assert '"runas"' in RUNTIME
    assert "관리자 승인" in RUNTIME
    assert "PadiemPcConnect.exe" in RUNTIME


def test_the_install_page_centers_removal_on_windows_settings():
    assert "Windows 설정 &gt; 앱" in INSTALL
    assert "Padiem PC 연결" in INSTALL
    assert "Padiem PC 연결 제거 (관리자 승인)" in INSTALL
    assert "제거</strong> 항목이 없습니다" not in INSTALL
    assert "-fulluninstall" in INSTALL
    assert "-fulluninstall" in DOC
    assert r"Uninstall\PADIEM-PC-Connect" in DOC


def test_the_asset_points_at_the_rebuilt_bytes():
    asset = (ROOT / "app" / "pc_pairing_connect_exe_asset.py").read_text(
        encoding="utf-8"
    )
    assert REBUILT_SHA256 in asset
    assert REBUILT_SHA256 in DOC
