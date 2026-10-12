"""Shutdown regression contracts (#4420 defects 1 & 2).

Offline: no Windows desktop, no real subprocess kill, no real registry.

Defect 1 — external ``claw-connect stop`` must end the Win32 tray message loop.
          ``ConnectApp.quit()`` is invoked from the watcher thread when the quit
          event fires; if it never reaches ``tray.quit()`` the GUI thread's
          ``PumpMessages()`` blocks forever and the process only dies via a forced
          kill. These tests pin that ``quit()`` always signals the tray.

Defect 1b — every ``WNDCLASS.lpfnWndProc`` handler must accept the four
          positional arguments pywin32 actually passes
          (``hwnd, msg, wparam, lparam``). A handler with fewer parameters raises
          ``TypeError`` *inside* ``PumpMessages()``; the C dispatcher swallows it,
          the loop never sees ``WM_DESTROY``, and the process can only be stopped
          by a forced kill. This is the exact P0 that hung external ``stop``
          (``_repro.log``: ``_on_destroy() takes 2 positional arguments but 5
          were given``).

Defect 2 — the live verify harness must never mask a forced kill() as a normal
          shutdown PASS. This is pinned as a source contract because the real
          path spawns a genuine Windows process.
"""

from __future__ import annotations

import inspect
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from claw_connect.connection import ConnectionState
from claw_connect.enrollment import ConnectorEnrollment
from claw_connect.runtime import ConnectApp
from claw_connect.tray import ConnectTray, NIM_ADD, NIM_DELETE, WM_TRAY


APP_ROOT = Path(__file__).resolve().parents[1]


class _FakeTray:
    def __init__(self) -> None:
        self.quit_calls = 0

    def quit(self) -> None:
        self.quit_calls += 1


class _ExplodingTray:
    def quit(self) -> None:
        raise RuntimeError("tray already gone")


def _app(tmp_dir: str) -> ConnectApp:
    # A benign supervised command; we never actually run it in these tests.
    app = ConnectApp(
        resident_command=["python", "-c", "pass"],
        enrollment=ConnectorEnrollment(state_dir=tmp_dir),
    )
    # Swap collaborators for fakes so quit() is observed in isolation.
    app._controller = SimpleNamespace(disconnect=lambda: None)
    app._supervisor = SimpleNamespace(stop=lambda: None)
    app._tray = _FakeTray()
    return app


@pytest.fixture
def app(tmp_path) -> ConnectApp:
    return _app(str(tmp_path / "state"))
# --- defect 1: external stop reaches the tray message loop -----------------
def test_quit_signals_the_tray_so_the_message_loop_can_exit(app):
    app.quit()
    # The crux of #4420: without this call PumpMessages() hangs forever.
    assert app._tray.quit_calls == 1


def test_quit_sets_the_local_quit_event_and_tears_down_children(app):
    app.quit()
    assert app._quit.is_set()


def test_quit_is_idempotent_and_does_not_raise_on_repeat(app):
    app.quit()
    app.quit()  # a double external stop / menu+CLI race must be safe
    assert app._tray.quit_calls == 2


def test_quit_still_cleans_up_when_tray_quit_raises(app):
    app._tray = _ExplodingTray()
    # A tray that is already destroyed must not leak the supervised Resident or
    # the single-instance lock: cleanup must happen and the error swallowed.
    app.quit()
    assert app._quit.is_set()


def test_quit_source_calls_tray_quit():
    # Structural guard: the fix must remain in ConnectApp.quit.
    src = inspect.getsource(ConnectApp.quit)
    assert "self._tray.quit()" in src


# --- defect 2: forced kill is never masked as a normal shutdown PASS -------
def _load_verify_module():
    spec = importlib.util.spec_from_file_location(
        "vw_shutdown", APP_ROOT / "verify_windows_live.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_verify_harness_tracks_forced_kill_and_fails_the_check():
    module = _load_verify_module()
    src = inspect.getsource(module.check_single_instance)
    # The harness must record whether a force kill happened...
    assert "forced_kill" in src
    # ...and a forced kill must exclude the case from a PASS verdict.
    assert "not forced_kill" in src
    # ...and the recorded check must be gated on that verdict, not just liveness.
    assert "graceful" in src


def test_verify_harness_still_calls_kill_only_after_graceful_wait():
    module = _load_verify_module()
    src = inspect.getsource(module.check_single_instance)
    # The graceful wait must precede any force kill (timeout -> kill ordering).
    assert src.index("first.wait(") < src.index("first.kill()")


# --- defect 1b: pywin32 passes the full 4-tuple to every WNDPROC handler ----
# pywin32 invokes each bound handler in ``lpfnWndProc`` with exactly
# ``(hwnd, msg, wparam, lparam)``. Declaring fewer parameters is the P0 that
# hung external ``stop``: the ``TypeError`` is raised inside ``PumpMessages()``,
# swallowed by the C dispatcher, so ``WM_DESTROY`` never runs and only a forced
# kill ends the process. The bound parameter count must therefore be exactly 4.
_WNDPROC_HANDLERS = ("_on_create", "_on_tray", "_on_command", "_on_destroy")
_PYWIN32_ARGUMENTS = (0, WM_TRAY, 0, 0)  # (hwnd, msg, wparam, lparam)


def _tray() -> ConnectTray:
    """A tray that never touches Win32 (every import inside it is lazy)."""
    return ConnectTray(
        state_source=lambda: ConnectionState.DISCONNECTED,
        actions={},
        web_url="https://chat.padiem.ai/",
    )


class _StubWndClass:
    def __init__(self) -> None:
        self.hInstance = None
        self.lpszClassName = None
        self.lpfnWndProc = None


def _stub_win32(monkeypatch) -> dict:
    """Install fake win32con/win32gui so ``create()`` can run offline and we can
    capture the *real* message map and notify calls it makes, instead of
    trusting a copy."""
    captured: dict = {"notify": []}
    stub_con = SimpleNamespace(
        WM_CREATE=0x0001, WM_COMMAND=0x0111, WM_DESTROY=0x0002,
        WS_OVERLAPPED=0x0, IDI_APPLICATION=32512,
    )

    def _register_class(window_class):
        captured["lpfnWndProc"] = window_class.lpfnWndProc
        return 1

    def _notify(message, data):
        captured["notify"].append((message, data))
        return 1

    stub_gui = SimpleNamespace(
        WNDCLASS=_StubWndClass,
        GetModuleHandle=lambda _name: 1,
        RegisterClass=_register_class,
        CreateWindowEx=lambda *a, **k: 4242,
        LoadIcon=lambda *a, **k: 1,
        Shell_NotifyIcon=_notify,
    )
    monkeypatch.setitem(sys.modules, "win32con", stub_con)
    monkeypatch.setitem(sys.modules, "win32gui", stub_gui)
    return captured


def test_create_registers_the_four_handlers_with_a_four_argument_contract(monkeypatch):
    captured = _stub_win32(monkeypatch)
    _tray().create()

    message_map = captured["lpfnWndProc"]
    assert isinstance(message_map, dict)
    # Exactly the four Win32 messages the tray dispatches.
    assert set(message_map) == {0x0001, WM_TRAY, 0x0111, 0x0002}
    for handler in message_map.values():
        signature = inspect.signature(handler)
        assert len(signature.parameters) == 4, (
            f"{handler.__name__} must take (hwnd, msg, wparam, lparam); "
            f"got {list(signature.parameters)}"
        )
        # Binding the exact pywin32 call is the real contract; a wrong arity
        # raises TypeError here without invoking the handler body.
        signature.bind(*_PYWIN32_ARGUMENTS)


def test_create_adds_the_icon_without_relying_on_wm_create(monkeypatch):
    # pywin32 does not reliably deliver WM_CREATE to the message map, so the
    # icon must be added explicitly by create(); otherwise _on_destroy's
    # NIM_DELETE fails and the loop can never be told to quit.
    captured = _stub_win32(monkeypatch)
    _tray().create()
    notify = captured["notify"]
    assert notify, "create() must add the tray icon itself"
    assert notify[0][0] == NIM_ADD


def test_on_destroy_always_posts_the_quit_message(monkeypatch):
    calls: list[tuple] = []
    stub_gui = SimpleNamespace(
        Shell_NotifyIcon=lambda message, data: calls.append(("notify", message)),
        PostQuitMessage=lambda code: calls.append(("quit", code)),
    )
    monkeypatch.setitem(sys.modules, "win32gui", stub_gui)

    tray = _tray()
    tray._on_destroy(7, 0x0002, 0, 0)
    assert calls[0] == ("notify", NIM_DELETE)
    assert ("quit", 0) in calls


def test_on_destroy_posts_the_quit_message_even_when_icon_removal_raises(monkeypatch):
    # Shell_NotifyIcon raises E_FAIL when the icon is already gone. A raise here
    # must NOT skip PostQuitMessage, or PumpMessages() blocks forever — the
    # exact #4420 external-stop hang.
    posted: list[int] = []

    def _boom(*_a, **_k):
        raise OSError("Shell_NotifyIcon: unspecified error")

    stub_gui = SimpleNamespace(
        Shell_NotifyIcon=_boom,
        PostQuitMessage=lambda code: posted.append(code),
    )
    monkeypatch.setitem(sys.modules, "win32gui", stub_gui)

    tray = _tray()
    tray._on_destroy(7, 0x0002, 0, 0)
    assert posted == [0]


@pytest.mark.parametrize("name", _WNDPROC_HANDLERS)
def test_each_wndproc_handler_binds_the_pywin32_four_tuple(name):
    handler = getattr(_tray(), name)
    signature = inspect.signature(handler)
    assert len(signature.parameters) == 4
    signature.bind(*_PYWIN32_ARGUMENTS)


@pytest.mark.parametrize("name", _WNDPROC_HANDLERS)
def test_wndproc_handler_parameter_order_matches_the_win32_wndproc(name):
    # The four slots must be in Win32 WndProc order; the ``msg`` slot is the one
    # the pre-fix code omitted, so its presence and position are pinned here.
    params = list(inspect.signature(getattr(_tray(), name)).parameters)
    assert [p.lstrip("_") for p in params] == ["hwnd", "msg", "wparam", "lparam"]


def test_the_old_three_argument_shape_would_fail_the_pywin32_call():
    # Negative control: proves the arity check is meaningful and documents the
    # exact failure the P0 produced (3 declared params vs 4 passed).
    class _Legacy:
        def _on_destroy(self, hwnd, _wparam, _lparam):  # the pre-fix shape
            return 0

    legacy = _Legacy()
    with pytest.raises(TypeError):
        inspect.signature(legacy._on_destroy).bind(*_PYWIN32_ARGUMENTS)
