"""#7065 stage 3 — a session program on a Windows pseudo console (ConPTY).

On anonymous pipes a program knows nobody is at a terminal: it may hold its
prompt back until it exits, it reads a password from a console it does not
have, and Ctrl+C cannot reach it. A pseudo console gives the program a real
console whose screen is sent back as a VT stream and whose keyboard is fed
from a pipe. The prompt is visible as soon as it is drawn, a password prompt
works, and Ctrl+C arrives as Ctrl+C.

Only Windows 10 1809 and later have the API. Everything here is the standard
library ``ctypes`` surface — the single-file helper ships no extra runtime —
and anything that cannot be opened raises ``OSError`` so the session manager
starts the program on pipes instead.

The backend contract is the one :class:`claw_connect.user_session_manager.
PipeBackend` implements: ``supports_key``, ``send_text``, ``send_key``,
``poll``, ``terminate``, ``close``; output and exit arrive through callbacks.
"""
from __future__ import annotations

import codecs
import ctypes
import subprocess
import sys
import threading
from typing import Any, Callable, Sequence

from .session_output_text import TerminalTextFilter
from .user_session_manager import BACKEND_CONPTY, SESSION_KEYS, _job_for

_PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE = 0x00020016
_EXTENDED_STARTUPINFO_PRESENT = 0x00080000
_CREATE_SUSPENDED = 0x00000004
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_STARTF_USESTDHANDLES = 0x00000100
_INFINITE = 0xFFFFFFFF
_WAIT_OBJECT_0 = 0
_ERROR_FILE_NOT_FOUND = 2
_ERROR_PATH_NOT_FOUND = 3
_ERROR_DIRECTORY = 267
_READ_CHUNK = 65_536
DRAIN_GRACE_SECONDS = 2.0

#: Key → the bytes a console keyboard sends for it. Enter is CR on a console.
KEY_BYTES = {
    "enter": b"\r",
    "tab": b"\t",
    "esc": b"\x1b",
    "ctrl_c": b"\x03",
    "ctrl_d": b"\x04",
    "ctrl_z": b"\x1a\r",
    "up": b"\x1b[A",
    "down": b"\x1b[B",
}

_HANDLE = ctypes.c_void_p
_DWORD = ctypes.c_uint32
_WORD = ctypes.c_uint16


class _Coord(ctypes.Structure):
    _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]


class _StartupInfoW(ctypes.Structure):
    _fields_ = [
        ("cb", _DWORD), ("lpReserved", ctypes.c_wchar_p), ("lpDesktop", ctypes.c_wchar_p),
        ("lpTitle", ctypes.c_wchar_p), ("dwX", _DWORD), ("dwY", _DWORD),
        ("dwXSize", _DWORD), ("dwYSize", _DWORD), ("dwXCountChars", _DWORD),
        ("dwYCountChars", _DWORD), ("dwFillAttribute", _DWORD), ("dwFlags", _DWORD),
        ("wShowWindow", _WORD), ("cbReserved2", _WORD), ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", _HANDLE), ("hStdOutput", _HANDLE), ("hStdError", _HANDLE),
    ]


class _StartupInfoExW(ctypes.Structure):
    _fields_ = [("StartupInfo", _StartupInfoW), ("lpAttributeList", ctypes.c_void_p)]


class _ProcessInformation(ctypes.Structure):
    _fields_ = [("hProcess", _HANDLE), ("hThread", _HANDLE),
                ("dwProcessId", _DWORD), ("dwThreadId", _DWORD)]


_API: Any = None
_API_LOCK = threading.Lock()


def _api() -> Any:
    """kernel32 with the signatures this module uses, or ``OSError``."""
    global _API
    with _API_LOCK:
        if _API is not None:
            return _API
        if sys.platform != "win32":
            raise OSError("a pseudo console exists on Windows only")
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        try:
            kernel.CreatePseudoConsole.restype = ctypes.c_long
            kernel.CreatePseudoConsole.argtypes = [
                _Coord, _HANDLE, _HANDLE, _DWORD, ctypes.POINTER(_HANDLE)]
            kernel.ClosePseudoConsole.restype = None
            kernel.ClosePseudoConsole.argtypes = [_HANDLE]
        except AttributeError as missing:
            raise OSError("this Windows has no pseudo console API") from missing
        signatures = {
            "CreatePipe": (ctypes.c_int, [ctypes.POINTER(_HANDLE), ctypes.POINTER(_HANDLE),
                                          ctypes.c_void_p, _DWORD]),
            "InitializeProcThreadAttributeList": (
                ctypes.c_int, [ctypes.c_void_p, _DWORD, _DWORD, ctypes.POINTER(ctypes.c_size_t)]),
            "UpdateProcThreadAttribute": (
                ctypes.c_int, [ctypes.c_void_p, _DWORD, ctypes.c_size_t, ctypes.c_void_p,
                               ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p]),
            "DeleteProcThreadAttributeList": (None, [ctypes.c_void_p]),
            "CreateProcessW": (ctypes.c_int, [
                ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_void_p,
                ctypes.c_int, _DWORD, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_void_p,
                ctypes.c_void_p]),
            "ResumeThread": (_DWORD, [_HANDLE]),
            "WaitForSingleObject": (_DWORD, [_HANDLE, _DWORD]),
            "GetExitCodeProcess": (ctypes.c_int, [_HANDLE, ctypes.POINTER(_DWORD)]),
            "TerminateProcess": (ctypes.c_int, [_HANDLE, ctypes.c_uint]),
            "ReadFile": (ctypes.c_int, [_HANDLE, ctypes.c_void_p, _DWORD,
                                        ctypes.POINTER(_DWORD), ctypes.c_void_p]),
            "WriteFile": (ctypes.c_int, [_HANDLE, ctypes.c_void_p, _DWORD,
                                         ctypes.POINTER(_DWORD), ctypes.c_void_p]),
            "CloseHandle": (ctypes.c_int, [_HANDLE]),
        }
        for name, (restype, argtypes) in signatures.items():
            function = getattr(kernel, name)
            function.restype = restype
            function.argtypes = argtypes
        _API = kernel
        return kernel


def conpty_available() -> bool:
    """Whether this PC can open a pseudo console at all."""
    try:
        _api()
    except OSError:
        return False
    return True


def _signed(code: int) -> int:
    return code - (1 << 32) if code >= (1 << 31) else code


OutputCallback = Callable[[str], None]
ExitCallback = Callable[["int | None"], None]


class ConptyBackend:
    """One program on its own pseudo console."""

    name = BACKEND_CONPTY
    keys = frozenset(SESSION_KEYS)

    def __init__(self, argv: Sequence[str], cwd: str | None, *,
                 on_output: OutputCallback, on_exit: ExitCallback,
                 cols: int = 200, rows: int = 50, **_unused: Any) -> None:
        api = _api()
        self._api = api
        self._on_output = on_output
        self._on_exit = on_exit
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._drained = threading.Event()
        self._console: int | None = None
        self._input: int | None = None
        self._output: int | None = None
        self._process: int | None = None
        self._job = None
        self._exit_code: int | None = None
        self._open(list(argv), cwd, int(cols), int(rows))
        threading.Thread(target=self._pump, daemon=True,
                         name="padiem-conpty-output").start()
        threading.Thread(target=self._wait, daemon=True,
                         name="padiem-conpty-exit").start()

    # ---- opening ------------------------------------------------------
    def _pipe(self) -> tuple[int, int]:
        read, write = _HANDLE(), _HANDLE()
        if not self._api.CreatePipe(ctypes.byref(read), ctypes.byref(write), None, 0):
            raise OSError(ctypes.get_last_error(), "a pseudo console pipe could not be created")
        return read.value, write.value

    def _open(self, argv: list[str], cwd: str | None, cols: int, rows: int) -> None:
        api = self._api
        console_in = console_out = None
        attributes = None
        try:
            console_in, self._input = self._pipe()
            self._output, console_out = self._pipe()
            console = _HANDLE()
            result = api.CreatePseudoConsole(_Coord(cols, rows), console_in, console_out, 0,
                                             ctypes.byref(console))
            if result != 0:
                raise OSError(result & 0xFFFFFFFF, "the pseudo console could not be created")
            self._console = console.value

            size = ctypes.c_size_t(0)
            api.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
            attributes = ctypes.create_string_buffer(size.value)
            if not api.InitializeProcThreadAttributeList(attributes, 1, 0, ctypes.byref(size)):
                attributes = None
                raise OSError(ctypes.get_last_error(), "the attribute list could not be built")
            if not api.UpdateProcThreadAttribute(
                    attributes, 0, _PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE,
                    ctypes.c_void_p(self._console), ctypes.sizeof(_HANDLE), None, None):
                raise OSError(ctypes.get_last_error(), "the pseudo console could not be attached")

            startup = _StartupInfoExW()
            startup.StartupInfo.cb = ctypes.sizeof(_StartupInfoExW)
            # Without this a parent whose own standard handles are redirected
            # (the windowed helper, a test runner) hands those to the child,
            # which then writes past the pseudo console. Empty handles make the
            # child take the pseudo console's own.
            startup.StartupInfo.dwFlags = _STARTF_USESTDHANDLES
            startup.lpAttributeList = ctypes.cast(attributes, ctypes.c_void_p)
            info = _ProcessInformation()
            command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
            created = api.CreateProcessW(
                None, command_line, None, None, False,
                _EXTENDED_STARTUPINFO_PRESENT | _CREATE_SUSPENDED | _CREATE_UNICODE_ENVIRONMENT,
                None, cwd, ctypes.byref(startup), ctypes.byref(info))
            if not created:
                error = ctypes.get_last_error()
                if error in (_ERROR_FILE_NOT_FOUND, _ERROR_PATH_NOT_FOUND):
                    raise FileNotFoundError(error, "the program is not on this PC")
                raise OSError(error, "the program could not be started on a pseudo console")
            self._process = info.hProcess
            self._job = _job_for(info.hProcess)
            api.ResumeThread(info.hThread)
            api.CloseHandle(info.hThread)
        except BaseException:
            self._close_handles(include_process=True)
            raise
        finally:
            if attributes is not None:
                api.DeleteProcThreadAttributeList(attributes)
            # The pseudo console holds its own duplicates of its ends.
            for handle in (console_in, console_out):
                if handle:
                    api.CloseHandle(handle)

    # ---- running ------------------------------------------------------
    def _pump(self) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        text_filter = TerminalTextFilter(preserve_redraws=True)
        buffer = ctypes.create_string_buffer(_READ_CHUNK)
        read = _DWORD(0)
        try:
            while True:
                handle = self._output
                if handle is None:
                    break
                if not self._api.ReadFile(handle, buffer, _READ_CHUNK, ctypes.byref(read), None):
                    break
                if read.value == 0:
                    break
                text = text_filter.feed(decoder.decode(buffer.raw[:read.value]))
                if text:
                    self._on_output(text)
            tail = text_filter.feed(decoder.decode(b"", final=True), final=True)
            if tail:
                self._on_output(tail)
        except Exception:  # noqa: BLE001 - a broken read ends the stream, nothing more
            pass
        finally:
            self._drained.set()

    def _wait(self) -> None:
        handle = self._process
        code: int | None = None
        if handle is not None:
            self._api.WaitForSingleObject(handle, _INFINITE)
            value = _DWORD(0)
            if self._api.GetExitCodeProcess(handle, ctypes.byref(value)):
                code = _signed(value.value)
        self._exit_code = code
        # The output pipe stays open while the pseudo console does; closing it
        # flushes the last screen and ends the reader.
        self._close_console()
        self._drained.wait(DRAIN_GRACE_SECONDS)
        self._on_exit(code)

    def _close_console(self) -> None:
        with self._lock:
            console, self._console = self._console, None
        if console:
            self._api.ClosePseudoConsole(console)

    def supports_key(self, key: str) -> bool:
        return key in self.keys

    def _write(self, data: bytes) -> None:
        with self._write_lock:
            handle = self._input
            if handle is None:
                raise BrokenPipeError("the program's input is closed")
            view = memoryview(data)
            while view:
                chunk = bytes(view[:_READ_CHUNK])
                written = _DWORD(0)
                if not self._api.WriteFile(handle, chunk, len(chunk), ctypes.byref(written), None):
                    raise BrokenPipeError(ctypes.get_last_error(), "the pseudo console took no input")
                if written.value == 0:
                    raise BrokenPipeError("the pseudo console took no input")
                view = view[written.value:]

    def send_text(self, text: str, enter: bool) -> None:
        data = text.replace("\n", "\r") + ("\r" if enter else "")
        self._write(data.encode("utf-8"))

    def send_key(self, key: str) -> None:
        self._write(KEY_BYTES[key])

    def poll(self) -> int | None:
        handle = self._process
        if handle is None:
            return self._exit_code
        if self._api.WaitForSingleObject(handle, 0) != _WAIT_OBJECT_0:
            return None
        value = _DWORD(0)
        if self._api.GetExitCodeProcess(handle, ctypes.byref(value)):
            return _signed(value.value)
        return None

    def terminate(self) -> None:
        if self._job is not None and self._job.terminate():
            return
        handle = self._process
        if handle is not None:
            self._api.TerminateProcess(handle, 1)

    def close(self) -> None:
        """Release everything once the program is gone."""
        self._close_console()
        self._drained.wait(DRAIN_GRACE_SECONDS)
        self._close_handles(include_process=self.poll() is not None)

    def _close_handles(self, *, include_process: bool) -> None:
        with self._lock:
            handles = [self._input, self._output]
            self._input = self._output = None
            if include_process:
                handles.append(self._process)
                self._process = None
            job, self._job = (self._job, None) if include_process else (None, self._job)
            console, self._console = self._console, None
        if console:
            self._api.ClosePseudoConsole(console)
        for handle in handles:
            if handle:
                self._api.CloseHandle(handle)
        if job is not None:
            job.close()


__all__ = ["ConptyBackend", "KEY_BYTES", "conpty_available"]
