"""#6701 — Padiem PC 연결 is removable from Windows Settings and the tray.

The app-list registration and the removal path are pinned to the source that
implements them. Nothing here installs or uninstalls on a real PC.
"""
# #8060: shipped reads live in _support; the uninstall claims stay here.
from _support import connector_uninstall_source as sheets

CS = sheets.connect_cs()
INSTALL = sheets.install_html()
DOC = sheets.doc()
MENU = sheets.menu_model()
RUNTIME = sheets.runtime()

REBUILT_SHA256 = "fdfdb3280261c374f38c99dab674105d3388b9b1974d441520e0f22b3f14f63f"


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
    asset = sheets.asset()
    assert REBUILT_SHA256 in asset
    assert REBUILT_SHA256 in DOC
