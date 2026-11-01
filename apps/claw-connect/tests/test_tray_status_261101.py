from types import SimpleNamespace
import sys
from claw_connect.connection import ConnectionState
from claw_connect.menu_model import ACTION_OPEN_LOGS, ACTION_VIEW_STATUS, ACTION_RECONNECT, build_menu
from claw_connect.tray import ConnectTray, NIM_MODIFY
from claw_connect.runtime import ConnectApp

def test_tray_refresh_repaints_current_state(monkeypatch):
    observed = []
    monkeypatch.setitem(sys.modules, "win32con", SimpleNamespace(IDI_APPLICATION=1))
    monkeypatch.setitem(sys.modules, "win32gui", SimpleNamespace(
        LoadIcon=lambda *_: 11,
        Shell_NotifyIcon=lambda op, data: observed.append((op, data)),
    ))
    state = [ConnectionState.CONNECTING]
    tray = ConnectTray(state_source=lambda: state[0], actions={}, web_url="https://example.invalid")
    tray._on_refresh(1, 0, 0, 0)
    state[0] = ConnectionState.CONNECTED
    tray._on_refresh(1, 0, 0, 0)
    state[0] = ConnectionState.OFFLINE
    tray._on_refresh(1, 0, 0, 0)
    assert [x[0] for x in observed] == [NIM_MODIFY] * 3
    assert [x[1][-1].split(" - ")[-1] for x in observed] == ["다시 연결 중", "연결됨", "연결 끊김"]

def test_menu_callbacks_status_and_log_folder(monkeypatch, tmp_path):
    from claw_connect.enrollment import ConnectorEnrollment
    app = ConnectApp(resident_command=["test"], enrollment=ConnectorEnrollment(state_dir=str(tmp_path)))
    shown, opened = [], []
    monkeypatch.setattr(app, "connector_status", lambda: ConnectionState.CONNECTED)
    monkeypatch.setitem(sys.modules, "win32gui", SimpleNamespace(MessageBox=lambda *args: shown.append(args)))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr("os.startfile", lambda path: opened.append(path), raising=False)
    actions = app.actions()
    actions[ACTION_VIEW_STATUS]()
    actions[ACTION_OPEN_LOGS]()
    assert shown[0][1] == "연결됨"
    assert opened == [str(tmp_path / "Padiem" / "ClawConnect")]
    for action in (ACTION_VIEW_STATUS, ACTION_OPEN_LOGS, ACTION_RECONNECT):
        assert action in [item.id for item in build_menu(ConnectionState.OFFLINE) if item.enabled]
