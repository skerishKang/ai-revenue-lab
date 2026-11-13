"""#7107 PR-B — provision the user-session helper after Connector enrollment.

The Connector is already installed per user and has enrolled. At that point it
owns the exact ``device_id`` the PC dispatch names, so it can do the three
things the one-click installer cannot do before the PC identity exists:

1. create ``C:/ProgramData/Padiem/helper.secret`` (32 random bytes), never
   printing the value;
2. point the helper at the installed ``claw_connect`` package, with the install
   root as the task working directory;
3. register the per-user ONLOGON/Limited task and start it immediately.

A failure never fails enrollment or PC connection. The status is written to
``<install root>/helper-status.json`` and reported to the user request as
``user_session_unavailable`` by the existing delegation lane.

#7564 — who may touch the secret's folder. ``%ProgramData%`` lets every local
account create files inside a child folder, so nothing is left to inheritance:

* the folder is created already carrying its descriptor, or - when it is
  already there - is used only if this user owns it. A folder SYSTEM or the
  Administrators group owns belongs to the elevated one-click install and is
  left exactly as it is; a folder any other account made first is refused;
* the secret is new on every provisioning. A file that is already there is
  never read back or kept, because whoever wrote it knows what is in it. The
  new file is created already carrying its descriptor under a name nothing
  reads yet, and gets its name only once it is complete;
* what the disk holds afterwards is read back before the task is registered.

This lane runs as the signed-in user, without elevation, so it cannot make a
folder that only administrators may write - that is the elevated installer's
job. What it guarantees is the part an unelevated process can: SYSTEM, the
Administrators group and this user are the only accounts named, so another
ordinary account on the same PC can neither read the secret nor put a file
beside it.
"""
from __future__ import annotations

import ctypes
import getpass
import json
import os
import re
import secrets
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Sequence

from . import user_helper_registration as registration
from .user_session_helper import windows_powershell_executable

SECRET_DIR = Path(r"C:\ProgramData\Padiem")
SECRET_NAME = "helper.secret"
STATUS_NAME = "helper-status.json"
STATUS_INSTALLED = "installed"
STATUS_NOT_INSTALLED = "not_installed"
STATUS_SKIPPED = "skipped"
STATUS_PENDING_ENROLLMENT = "pending_enrollment"

SYSTEM_SID = "S-1-5-18"
ADMINISTRATORS_SID = "S-1-5-32-544"
_SID = re.compile(r"^S-1-[0-9]+(-[0-9]+)+$")
_FULL = 0x1F01FF
_READ = 0x120089
_SDDL_ACCOUNTS = {"SY": SYSTEM_SID, "BA": ADMINISTRATORS_SID}
_SDDL_RIGHTS = {"FA": _FULL, "FR": _READ}

Runner = Callable[..., Any]


def _default_run(argv: Sequence[str], **kwargs: Any) -> Any:
    return subprocess.run(
        list(argv), capture_output=True, text=True, timeout=30, **kwargs,
    )


def _write_status(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        root.mkdir(parents=True, exist_ok=True)
        (root / STATUS_NAME).write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except OSError:
        # The helper is optional; a status write failure must not fail the PC.
        pass
    return payload


def read_status(state_dir: str | os.PathLike[str]) -> dict[str, Any]:
    """Read the last provisioning outcome without creating or changing anything."""
    try:
        data = json.loads((Path(state_dir) / STATUS_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": STATUS_PENDING_ENROLLMENT}
    return data if isinstance(data, dict) else {"status": STATUS_PENDING_ENROLLMENT}


# ---------------------------------------------------------------------------
# #7564 — the descriptors, and the Windows calls that write and read them.
# ---------------------------------------------------------------------------
def folder_sddl(user_sid: str) -> str:
    """The folder: this user owns it, inheritance is cut, three accounts are named.

    The entries carry ``OICI`` so a file created inside starts from the same
    three accounts. This user has full control because this lane has no
    elevation to write with.
    """
    _require_sid(user_sid)
    return (
        f"O:{user_sid}D:PAI(A;OICI;FA;;;{SYSTEM_SID})"
        f"(A;OICI;FA;;;{ADMINISTRATORS_SID})(A;OICI;FA;;;{user_sid})"
    )


def secret_sddl(user_sid: str) -> str:
    """The secret: SYSTEM and Administrators in full, this user reading, nobody else."""
    _require_sid(user_sid)
    return (
        f"O:{user_sid}D:PAI(A;;FA;;;{SYSTEM_SID})"
        f"(A;;FA;;;{ADMINISTRATORS_SID})(A;;0x120089;;;{user_sid})"
    )


def _require_sid(value: str) -> None:
    if not isinstance(value, str) or not _SID.match(value):
        raise ValueError("not a security identifier")


def descriptor_facts(sddl: str) -> tuple[str | None, bool, frozenset]:
    """Owner, whether inheritance is cut, and every entry of one descriptor string.

    It is what it takes to say two descriptors grant the same things to the
    same accounts, however Windows chose to spell them. Anything this lane
    never writes - a deny entry, a right it has no name for - is a
    ``ValueError``, which every caller treats as "not the descriptor I set".
    """
    match = re.fullmatch(
        r"(?:O:(?P<owner>.+?))?(?:G:(?P<group>.+?))?D:(?P<flags>[A-Z]*)"
        r"(?P<entries>(?:\([^)]*\))*)",
        sddl.strip(),
    )
    if not match:
        raise ValueError("unreadable descriptor")
    entries = set()
    for body in re.findall(r"\(([^)]*)\)", match["entries"]):
        parts = body.split(";")
        if len(parts) != 6 or parts[0] != "A" or parts[3] or parts[4]:
            raise ValueError("unexpected entry")
        _kind, flags, rights, _object, _inherited, account = parts
        if rights.lower().startswith("0x"):
            mask = int(rights, 16)
        elif rights in _SDDL_RIGHTS:
            mask = _SDDL_RIGHTS[rights]
        else:
            raise ValueError("unexpected right")
        entries.add((
            _SDDL_ACCOUNTS.get(account, account), mask,
            frozenset(flags[index:index + 2] for index in range(0, len(flags), 2)),
        ))
    owner = match["owner"]
    return (
        _SDDL_ACCOUNTS.get(owner, owner) if owner else None,
        "P" in match["flags"],
        frozenset(entries),
    )


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_ulong),
        ("descriptor", ctypes.c_void_p),
        ("inherit", ctypes.c_int),
    ]


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [("sid", ctypes.c_void_p), ("attributes", ctypes.c_ulong)]


class WindowsSecurity:
    """The Windows calls this lane locks its folder and secret with.

    Kept behind one small object so the provisioning walk can be exercised on
    a machine that is not Windows; on Windows the tests use this object itself
    against a sandbox folder.
    """

    _OWNER = 0x1
    _DACL = 0x4
    _PROTECTED_DACL = 0x80000000
    _SE_FILE_OBJECT = 1
    _SDDL_REVISION = 1
    _REPARSE_POINT = 0x400
    _INVALID_ATTRIBUTES = 0xFFFFFFFF
    _GENERIC_WRITE = 0x40000000
    _CREATE_NEW = 1
    _FILE_ATTRIBUTE_NORMAL = 0x80
    _TOKEN_QUERY = 0x8
    _TOKEN_USER = 1

    def __init__(self) -> None:
        self.advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        pointer = ctypes.POINTER
        self.advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
            ctypes.c_wchar_p, ctypes.c_ulong, pointer(ctypes.c_void_p), ctypes.c_void_p,
        ]
        self.advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = ctypes.c_int
        self.advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong,
            pointer(ctypes.c_void_p), ctypes.c_void_p,
        ]
        self.advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = ctypes.c_int
        self.advapi.GetNamedSecurityInfoW.argtypes = [
            ctypes.c_wchar_p, ctypes.c_int, ctypes.c_ulong, ctypes.c_void_p,
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, pointer(ctypes.c_void_p),
        ]
        self.advapi.GetNamedSecurityInfoW.restype = ctypes.c_ulong
        self.advapi.SetNamedSecurityInfoW.argtypes = [
            ctypes.c_wchar_p, ctypes.c_int, ctypes.c_ulong, ctypes.c_void_p,
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        ]
        self.advapi.SetNamedSecurityInfoW.restype = ctypes.c_ulong
        self.advapi.GetSecurityDescriptorDacl.argtypes = [
            ctypes.c_void_p, pointer(ctypes.c_int), pointer(ctypes.c_void_p),
            pointer(ctypes.c_int),
        ]
        self.advapi.GetSecurityDescriptorDacl.restype = ctypes.c_int
        self.advapi.OpenProcessToken.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, pointer(ctypes.c_void_p),
        ]
        self.advapi.OpenProcessToken.restype = ctypes.c_int
        self.advapi.GetTokenInformation.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong,
            pointer(ctypes.c_ulong),
        ]
        self.advapi.GetTokenInformation.restype = ctypes.c_int
        self.advapi.ConvertSidToStringSidW.argtypes = [
            ctypes.c_void_p, pointer(ctypes.c_void_p),
        ]
        self.advapi.ConvertSidToStringSidW.restype = ctypes.c_int
        self.kernel.GetCurrentProcess.restype = ctypes.c_void_p
        self.kernel.CreateDirectoryW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p]
        self.kernel.CreateDirectoryW.restype = ctypes.c_int
        self.kernel.CreateFileW.argtypes = [
            ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p,
            ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p,
        ]
        self.kernel.CreateFileW.restype = ctypes.c_void_p
        self.kernel.WriteFile.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_ulong,
            pointer(ctypes.c_ulong), ctypes.c_void_p,
        ]
        self.kernel.WriteFile.restype = ctypes.c_int
        self.kernel.GetFileAttributesW.argtypes = [ctypes.c_wchar_p]
        self.kernel.GetFileAttributesW.restype = ctypes.c_ulong
        self.kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        self.kernel.CloseHandle.restype = ctypes.c_int
        self.kernel.LocalFree.argtypes = [ctypes.c_void_p]
        self.kernel.LocalFree.restype = ctypes.c_void_p

    def _failure(self) -> OSError:
        return ctypes.WinError(ctypes.get_last_error())

    def _sid_text(self, sid: Any) -> str:
        text = ctypes.c_void_p()
        if not self.advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)):
            raise self._failure()
        try:
            return ctypes.wstring_at(text)
        finally:
            self.kernel.LocalFree(text)

    def _descriptor(self, sddl: str) -> ctypes.c_void_p:
        descriptor = ctypes.c_void_p()
        if not self.advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl, self._SDDL_REVISION, ctypes.byref(descriptor), None):
            raise self._failure()
        return descriptor

    def current_user_sid(self) -> str:
        """The SID of the account this process runs as."""
        token = ctypes.c_void_p()
        if not self.advapi.OpenProcessToken(
                self.kernel.GetCurrentProcess(), self._TOKEN_QUERY, ctypes.byref(token)):
            raise self._failure()
        try:
            needed = ctypes.c_ulong()
            self.advapi.GetTokenInformation(
                token, self._TOKEN_USER, None, 0, ctypes.byref(needed))
            if needed.value < ctypes.sizeof(_SidAndAttributes):
                raise self._failure()
            buffer = ctypes.create_string_buffer(needed.value)
            if not self.advapi.GetTokenInformation(
                    token, self._TOKEN_USER, buffer, needed.value, ctypes.byref(needed)):
                raise self._failure()
            user = ctypes.cast(buffer, ctypes.POINTER(_SidAndAttributes)).contents
            return self._sid_text(user.sid)
        finally:
            self.kernel.CloseHandle(token)

    def is_link(self, path: str) -> bool:
        """Whether the name is a link that leads somewhere else."""
        attributes = self.kernel.GetFileAttributesW(path)
        if attributes == self._INVALID_ATTRIBUTES:
            raise self._failure()
        return bool(attributes & self._REPARSE_POINT)

    def describe(self, path: str) -> str:
        """The owner and access list the disk holds for ``path``, as one string."""
        descriptor = ctypes.c_void_p()
        failed = self.advapi.GetNamedSecurityInfoW(
            path, self._SE_FILE_OBJECT, self._OWNER | self._DACL,
            None, None, None, None, ctypes.byref(descriptor))
        if failed:
            raise ctypes.WinError(failed)
        try:
            text = ctypes.c_void_p()
            if not self.advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW(
                    descriptor, self._SDDL_REVISION, self._OWNER | self._DACL,
                    ctypes.byref(text), None):
                raise self._failure()
            try:
                return ctypes.wstring_at(text)
            finally:
                self.kernel.LocalFree(text)
        finally:
            self.kernel.LocalFree(descriptor)

    def create_folder(self, path: str, sddl: str) -> None:
        """Create the folder already carrying its descriptor; refuse one that exists."""
        descriptor = self._descriptor(sddl)
        try:
            attributes = _SecurityAttributes(
                ctypes.sizeof(_SecurityAttributes), descriptor, 0)
            if not self.kernel.CreateDirectoryW(path, ctypes.byref(attributes)):
                raise self._failure()
        finally:
            self.kernel.LocalFree(descriptor)

    def set_access(self, path: str, sddl: str) -> None:
        """Replace the whole access list of an existing object and cut inheritance."""
        descriptor = self._descriptor(sddl)
        try:
            present = ctypes.c_int()
            defaulted = ctypes.c_int()
            access = ctypes.c_void_p()
            if not self.advapi.GetSecurityDescriptorDacl(
                    descriptor, ctypes.byref(present), ctypes.byref(access),
                    ctypes.byref(defaulted)) or not present.value:
                raise self._failure()
            failed = self.advapi.SetNamedSecurityInfoW(
                path, self._SE_FILE_OBJECT, self._DACL | self._PROTECTED_DACL,
                None, None, access, None)
            if failed:
                raise ctypes.WinError(failed)
        finally:
            self.kernel.LocalFree(descriptor)

    def create_file(self, path: str, sddl: str, payload: bytes) -> None:
        """Write ``payload`` into a new file that is created already carrying its descriptor.

        ``CREATE_NEW`` refuses a name that exists, so a file somebody left
        there is never written through.
        """
        descriptor = self._descriptor(sddl)
        try:
            attributes = _SecurityAttributes(
                ctypes.sizeof(_SecurityAttributes), descriptor, 0)
            handle = self.kernel.CreateFileW(
                path, self._GENERIC_WRITE, 0, ctypes.byref(attributes),
                self._CREATE_NEW, self._FILE_ATTRIBUTE_NORMAL, None)
            if handle is None or handle == ctypes.c_void_p(-1).value:
                raise self._failure()
            try:
                written = ctypes.c_ulong()
                if not self.kernel.WriteFile(
                        handle, payload, len(payload), ctypes.byref(written), None):
                    raise self._failure()
                if written.value != len(payload):
                    raise OSError("short write")
            finally:
                self.kernel.CloseHandle(handle)
        finally:
            self.kernel.LocalFree(descriptor)


def _matches(security: Any, path: Path, sddl: str) -> bool:
    """Whether the disk holds exactly the descriptor that was meant for ``path``.

    That the call which set it did not fail is not the fact; what is there
    now is. A link is never the object this lane made.
    """
    try:
        if security.is_link(str(path)):
            return False
        return descriptor_facts(security.describe(str(path))) == descriptor_facts(sddl)
    except (OSError, ValueError):
        return False


def _lock_folder(folder: Path, user_sid: str, security: Any) -> str | None:
    """``None`` when the folder is this user's own and locked, else why it is not used."""
    wanted = folder_sddl(user_sid)
    if os.path.lexists(folder):
        if security.is_link(str(folder)):
            return "state_dir_is_a_link"
        if not folder.is_dir():
            return "state_dir_not_a_folder"
        try:
            owner = descriptor_facts(security.describe(str(folder)))[0]
        except (OSError, ValueError):
            owner = None
        if owner in (SYSTEM_SID, ADMINISTRATORS_SID):
            # The elevated one-click install made this folder and locked it.
            # An unelevated lane does not reopen it for itself.
            return "state_dir_managed_by_administrator"
        if owner != user_sid:
            return "state_dir_owner_untrusted"
        try:
            security.set_access(str(folder), wanted)
        except OSError:
            return "state_dir_acl_failed"
    else:
        try:
            security.create_folder(str(folder), wanted)
        except OSError:
            return "state_dir_create_failed"
    return None if _matches(security, folder, wanted) else "state_dir_acl_unverified"


def _create_secret(path: Path, user_sid: str, security: Any) -> None:
    """Write a new 32-byte secret, as hex, into a file that is locked from its first moment.

    The value is never returned, logged or printed. An existing file is
    replaced by the rename and never read: the new file keeps the descriptor
    it was created with, not the old file's.
    """
    pending = path.with_name(f"{path.name}.{secrets.token_hex(8)}.new")
    try:
        security.create_file(
            str(pending), secret_sddl(user_sid),
            (secrets.token_hex(32) + "\n").encode("ascii"),
        )
        try:
            os.chmod(path, stat.S_IWRITE)  # a read-only leftover cannot be renamed over
        except OSError:
            pass
        os.replace(pending, path)
    finally:
        try:
            pending.unlink()
        except OSError:
            pass


def _run_powershell(script: str, run: Runner, powershell: str) -> bool:
    try:
        completed = run([
            powershell, "-NoProfile", "-NonInteractive",
            "-ExecutionPolicy", "Bypass", "-Command", script,
        ])
    except Exception:
        return False
    return getattr(completed, "returncode", 1) == 0


def _register_task(*, launch: registration.HelperLaunch, user: str, run: Runner,
                   powershell: str) -> bool:
    definition = registration.task_definition(launch=launch, user=user)
    return _run_powershell(registration.register_script(definition), run, powershell)


def _current_user() -> str:
    domain = os.environ.get("USERDOMAIN", "").strip()
    name = getpass.getuser()
    return f"{domain}{os.sep}{name}" if domain else name


def provision_user_helper(
    *,
    device_id: str,
    state_dir: str | os.PathLike[str],
    python_executable: str | None = None,
    secret_dir: str | os.PathLike[str] | None = None,
    user: str | None = None,
    run: Runner | None = None,
    platform: str | None = None,
    security: Any = None,
    powershell: str | None = None,
) -> dict[str, Any]:
    """Best-effort helper provisioning; always returns a status, never raises."""
    root = Path(state_dir)
    runner = run or _default_run
    secret_path = (Path(secret_dir) if secret_dir is not None else SECRET_DIR) / SECRET_NAME
    executable = python_executable or registration.default_python_executable()
    base: dict[str, Any] = {"device_id": device_id, "task": registration.TASK_NAME}

    def done(status: str, reason: str | None = None, **extra: Any) -> dict[str, Any]:
        payload = {**base, "status": status}
        if reason is not None:
            payload["reason"] = reason
        payload.update(extra)
        return _write_status(root, payload)

    try:
        # One shared validator: an unusable id must never reach a command line.
        registration.build_launch(
            python_executable=executable,
            device_id=device_id,
            secret_file=str(secret_path),
        )
    except Exception as exc:
        return done(STATUS_NOT_INSTALLED, "device_id_invalid", error=type(exc).__name__)

    if (platform or sys.platform) != "win32":
        return done(STATUS_SKIPPED, "unsupported_platform")
    if getattr(sys, "frozen", False):
        # The standalone EXE carries no host Python; it cannot run the helper.
        return done(STATUS_SKIPPED, "frozen_connector")
    if not (root / "claw_connect").is_dir():
        return done(STATUS_SKIPPED, "claw_connect_missing")
    if not executable:
        return done(STATUS_SKIPPED, "python_missing")
    # Windows PowerShell by the path the OS reports, never by a bare name the
    # working folder could answer for.
    shell = powershell or windows_powershell_executable()
    if not shell:
        return done(STATUS_NOT_INSTALLED, "powershell_missing")

    secret_created = False
    try:
        acl = security if security is not None else WindowsSecurity()
        user_sid = acl.current_user_sid()
        # Nothing is stopped or written until the folder is this user's own.
        refusal = _lock_folder(secret_path.parent, user_sid, acl)
        if refusal is not None:
            return done(STATUS_NOT_INSTALLED, refusal)
        # A helper that is still running keeps the old secret in memory.
        if not _run_powershell(registration.stop_script(), runner, shell):
            return done(STATUS_NOT_INSTALLED, "helper_still_running")
        _create_secret(secret_path, user_sid, acl)
        secret_created = True
        if not _matches(acl, secret_path, secret_sddl(user_sid)):
            # Without a secret the helper refuses to start, so a file whose
            # descriptor could not be confirmed is never served from.
            try:
                secret_path.unlink()
            except OSError:
                pass
            return done(STATUS_NOT_INSTALLED, "secret_acl_failed", secret_created=False)
        launch = registration.build_launch(
            python_executable=executable,
            device_id=device_id,
            secret_file=str(secret_path),
            working_directory=str(root),
        )
        if not _register_task(
                launch=launch, user=user or _current_user(), run=runner, powershell=shell):
            return done(
                STATUS_NOT_INSTALLED, "task_registration_failed",
                secret_created=secret_created,
            )
        return done(STATUS_INSTALLED, secret_created=secret_created)
    except Exception as exc:
        return done(
            STATUS_NOT_INSTALLED, "provision_failed",
            error=type(exc).__name__, secret_created=secret_created,
        )
