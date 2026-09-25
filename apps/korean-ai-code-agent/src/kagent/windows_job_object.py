"""Windows Job Object process-tree containment for the canonical Local Agent executor.

This module adds exactly one capability to the existing canonical Windows
direct-process executor: the ability to terminate a **whole descendant process
tree** on timeout, explicit cancel, and terminal cleanup.

Design constraints honoured here:

- No new process authority. The caller still owns the single ``Popen`` launch,
  the trusted executable allowlist, the P01 approval, the selected-root ``cwd``
  policy, and the bounded environment allowlist.
- No new approval authority and no new filesystem authority.
- No shell widening. ``shell=False`` and the blocked script/shell-host list
  stay exactly as they were.
- No admin elevation. Only ``job32``/``kernel32`` calls available to a standard
  user are used.
- No third-party dependency. ``pywin32`` is deliberately **not** added; the
  implementation uses the standard library ``ctypes`` surface only, so the
  KAgent zero-dependency posture is preserved.
- Non-Windows platforms fail closed. Nothing here becomes a hidden
  cross-platform substitute for the Windows executor.
- The child is launched suspended, assigned to the job, and only then resumed,
  so untrusted work cannot spawn and escape before containment is established.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import subprocess
from typing import Any, Self

from .contracts import ContractError

__all__ = [
    "JOB_OBJECT_ADMIN_ELEVATION_REQUIRED",
    "JOB_OBJECT_NATIVE_PRIMITIVE",
    "JOB_OBJECT_UNAVAILABLE_ERROR",
    "PYWIN32_DEPENDENCY_ADDED",
    "WINDOWS_JOB_OBJECT_IMPLEMENTED",
    "JobBoundProcess",
    "WindowsJobObject",
    "launch_job_bound_process",
    "windows_process_is_alive",
]

WINDOWS_JOB_OBJECT_IMPLEMENTED = True
JOB_OBJECT_NATIVE_PRIMITIVE = "windows_job_object"
PYWIN32_DEPENDENCY_ADDED = False
JOB_OBJECT_ADMIN_ELEVATION_REQUIRED = False
JOB_OBJECT_UNAVAILABLE_ERROR = "windows job object containment is unavailable on this platform"

_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
# The x64 SDK layout of JOBOBJECT_EXTENDED_LIMIT_INFORMATION is 144 bytes even
# though the documented field set only spans 136, because the Win32 headers pad
# the trailing members to the 8-byte structure alignment. SetInformationJobObject
# rejects any other length with ERROR_BAD_LENGTH (24), so the exact required
# length is asserted here instead of being derived from ctypes.sizeof.
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_SIZE = 144
_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_QUOTA = 0x0100
_THREAD_SUSPEND_RESUME = 0x0002
_TH32CS_SNAPTHREAD = 0x00000004
_STILL_ACTIVE_EXIT_CODE = 259
_MAX_RESUME_ITERATIONS = 8
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class _JobObjectBasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _JobObjectExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JobObjectBasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", wintypes.DWORD),
        ("PeakJobMemoryUsed", wintypes.DWORD),
    ]


class _ThreadEntry32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", wintypes.LONG),
        ("tpDeltaPri", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
    ]


_KERNEL32: Any = None
_KERNEL32_READY = False


def _kernel32() -> Any:
    global _KERNEL32, _KERNEL32_READY
    if os.name != "nt":
        raise ContractError(JOB_OBJECT_UNAVAILABLE_ERROR)
    if not _KERNEL32_READY:
        library = ctypes.WinDLL("kernel32", use_last_error=True)
        library.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        library.CreateJobObjectW.restype = wintypes.HANDLE
        library.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        library.SetInformationJobObject.restype = wintypes.BOOL
        library.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        library.AssignProcessToJobObject.restype = wintypes.BOOL
        library.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        library.TerminateJobObject.restype = wintypes.BOOL
        library.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        library.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        library.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ThreadEntry32)]
        library.Thread32First.restype = wintypes.BOOL
        library.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ThreadEntry32)]
        library.Thread32Next.restype = wintypes.BOOL
        library.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        library.OpenThread.restype = wintypes.HANDLE
        library.ResumeThread.argtypes = [wintypes.HANDLE]
        library.ResumeThread.restype = wintypes.DWORD
        library.CloseHandle.argtypes = [wintypes.HANDLE]
        library.CloseHandle.restype = wintypes.BOOL
        library.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        library.OpenProcess.restype = wintypes.HANDLE
        library.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        library.GetExitCodeProcess.restype = wintypes.BOOL
        _KERNEL32 = library
        _KERNEL32_READY = True
    return _KERNEL32


def _process_handle(process: subprocess.Popen[str]) -> int:
    handle = getattr(process, "_handle", None)
    if not handle:
        raise ContractError("Windows subprocess did not expose an OS process handle for job assignment")
    return int(handle)


def _resume_suspended_primary_thread(process: subprocess.Popen[str]) -> int:
    """Resume every thread of a freshly created suspended process.

    A process created with ``CREATE_SUSPENDED`` has executed no user code yet,
    so its only thread is the primary thread and it cannot have forked a
    descendant. Enumerating the thread list is therefore deterministic, and the
    enumeration happens strictly after the job assignment succeeded.
    """
    library = _kernel32()
    snapshot = library.CreateToolhelp32Snapshot(_TH32CS_SNAPTHREAD, 0)
    if not snapshot or snapshot == _INVALID_HANDLE_VALUE:
        raise ContractError("failed to enumerate the suspended child thread for job-bound resume")
    resumed = 0
    try:
        entry = _ThreadEntry32()
        entry.dwSize = ctypes.sizeof(_ThreadEntry32)
        more = library.Thread32First(snapshot, ctypes.byref(entry))
        while more:
            if entry.th32OwnerProcessID == process.pid:
                thread = library.OpenThread(_THREAD_SUSPEND_RESUME, False, entry.th32ThreadID)
                if thread and thread != _INVALID_HANDLE_VALUE:
                    try:
                        for _ in range(_MAX_RESUME_ITERATIONS):
                            previous = library.ResumeThread(thread)
                            if previous == 0xFFFFFFFF:
                                raise ContractError("failed to resume the job-assigned child thread")
                            if previous <= 1:
                                break
                    finally:
                        library.CloseHandle(thread)
                    resumed += 1
            entry.dwSize = ctypes.sizeof(_ThreadEntry32)
            more = library.Thread32Next(snapshot, ctypes.byref(entry))
    finally:
        library.CloseHandle(snapshot)
    if resumed == 0:
        raise ContractError("no suspended child thread was found to resume after job assignment")
    return resumed


def windows_process_is_alive(pid: int) -> bool:
    """Best-effort liveness probe used by containment evidence, never by policy."""
    if os.name != "nt":
        raise ContractError(JOB_OBJECT_UNAVAILABLE_ERROR)
    library = _kernel32()
    handle = library.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        if not library.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return code.value == _STILL_ACTIVE_EXIT_CODE
    finally:
        library.CloseHandle(handle)


class WindowsJobObject:
    """Minimal ``ctypes`` Job Object handle with kill-on-close semantics."""

    def __init__(self) -> None:
        library = _kernel32()
        handle = library.CreateJobObjectW(None, None)
        if not handle or handle == _INVALID_HANDLE_VALUE:
            raise ContractError("failed to create a Windows Job Object for process-tree containment")
        self._handle = handle
        self._closed = False
        self._terminated = False
        limits = _JobObjectExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        buffer = ctypes.create_string_buffer(_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_SIZE)
        ctypes.memmove(buffer, ctypes.byref(limits), ctypes.sizeof(limits))
        applied = library.SetInformationJobObject(
            handle,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
            buffer,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_SIZE,
        )
        if not applied:
            self.close()
            raise ContractError("failed to enable JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE on the Job Object")

    @property
    def handle(self) -> int:
        return int(self._handle)

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def terminated(self) -> bool:
        return self._terminated

    def assign(self, process: subprocess.Popen[str]) -> None:
        if self._closed:
            raise ContractError("cannot assign a process to a closed Windows Job Object")
        library = _kernel32()
        if not library.AssignProcessToJobObject(self._handle, _process_handle(process)):
            raise ContractError("failed to assign the Windows child process to its Job Object")
        self._terminated = False

    def resume(self, process: subprocess.Popen[str]) -> None:
        if self._closed:
            raise ContractError("cannot resume a child outside an open Windows Job Object")
        _resume_suspended_primary_thread(process)

    def terminate_tree(self) -> bool:
        """Terminate every live process currently assigned to this job."""
        if self._closed:
            return False
        library = _kernel32()
        terminated = bool(library.TerminateJobObject(self._handle, 1))
        if terminated:
            self._terminated = True
        return terminated

    def close(self) -> None:
        """Close the job handle. ``KILL_ON_JOB_CLOSE`` reaps any remaining tree member."""
        if self._closed:
            return
        self._closed = True
        library = _kernel32()
        library.CloseHandle(self._handle)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def safe_dict(self) -> dict[str, Any]:
        return {
            "native_primitive": JOB_OBJECT_NATIVE_PRIMITIVE,
            "kill_on_job_close": True,
            "launch_suspended_before_assignment": True,
            "admin_elevation": False,
            "pywin32_dependency": False,
        }


class JobBoundProcess:
    """A ``Popen`` that is already contained in its Job Object and running."""

    __slots__ = ("job", "process")

    def __init__(self, *, process: subprocess.Popen[str], job: WindowsJobObject) -> None:
        self.process = process
        self.job = job


def launch_job_bound_process(
    argv: list[str],
    *,
    cwd: str,
    environment: dict[str, str],
    creationflags: int = 0,
) -> JobBoundProcess:
    """Launch ``argv`` inside a Job Object with no escape window.

    The child is created suspended, assigned to a kill-on-close Job Object, and
    only then resumed. ``shell`` is never widened: the caller keeps ``False``.
    """
    if os.name != "nt":
        raise ContractError(JOB_OBJECT_UNAVAILABLE_ERROR)
    suspend_flag = getattr(subprocess, "CREATE_SUSPENDED", 0x00000004)
    job = WindowsJobObject()
    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
            env=environment,
            creationflags=creationflags | suspend_flag,
        )
        job.assign(process)
        job.resume(process)
    except BaseException:
        if process is not None:
            job.terminate_tree()
            try:
                process.kill()
            except OSError:
                pass
            try:
                process.wait(timeout=5)
            except (subprocess.TimeoutExpired, OSError):
                pass
        job.close()
        raise
    return JobBoundProcess(process=process, job=job)
