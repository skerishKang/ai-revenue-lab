"""Identify the connected pipe client before consuming its request body.

Only TokenUser is authoritative here; group membership is not an identity.
The caller has consumed the fixed four-byte frame header before impersonating.
No request processing or token/connection cleanup runs while impersonating.
"""
from __future__ import annotations

import ctypes
import os
import sys

SYSTEM_SID = "S-1-5-18"
PEER_NOT_SYSTEM = "peer_not_system"
PEER_IMPERSONATION_FAILED = "peer_impersonation_failed"
PEER_TOKEN_UNAVAILABLE = "peer_token_unavailable"
PEER_IDENTITY_UNAVAILABLE = "peer_identity_unavailable"
PEER_REASON_CODES = frozenset({
    PEER_NOT_SYSTEM, PEER_IMPERSONATION_FAILED,
    PEER_TOKEN_UNAVAILABLE, PEER_IDENTITY_UNAVAILABLE,
})
REVERT_FAILURE_EXIT_CODE = 70

_TOKEN_QUERY = 0x0008
_TOKEN_USER = 1
_ERROR_INSUFFICIENT_BUFFER = 122


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [("sid", ctypes.c_void_p), ("attributes", ctypes.c_ulong)]


class _WindowsPeerApi:
    """Load and bind APIs before entering the client's security context."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise OSError("Windows token APIs unavailable")
        self.advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.advapi.ImpersonateNamedPipeClient.argtypes = [ctypes.c_void_p]
        self.advapi.ImpersonateNamedPipeClient.restype = ctypes.c_int
        self.advapi.OpenThreadToken.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self.advapi.OpenThreadToken.restype = ctypes.c_int
        self.advapi.GetTokenInformation.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        self.advapi.GetTokenInformation.restype = ctypes.c_int
        self.advapi.ConvertSidToStringSidW.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
        ]
        self.advapi.ConvertSidToStringSidW.restype = ctypes.c_int
        self.advapi.RevertToSelf.argtypes = []
        self.advapi.RevertToSelf.restype = ctypes.c_int
        self.kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        self.kernel.CloseHandle.restype = ctypes.c_int
        self.kernel.LocalFree.argtypes = [ctypes.c_void_p]
        self.kernel.LocalFree.restype = ctypes.c_void_p

    def impersonate(self, handle) -> bool:
        return bool(self.advapi.ImpersonateNamedPipeClient(handle))

    def open_thread_token(self):
        token = ctypes.c_void_p()
        # -2 is the current-thread pseudo handle. OpenAsSelf=TRUE permits
        # querying an Identification-level token using the helper's rights.
        if not self.advapi.OpenThreadToken(
                ctypes.c_void_p(-2), _TOKEN_QUERY, True, ctypes.byref(token)):
            return None
        return token

    def token_user_sid(self, token) -> str:
        needed = ctypes.c_ulong()
        ok = self.advapi.GetTokenInformation(
            token, _TOKEN_USER, None, 0, ctypes.byref(needed))
        if ok or ctypes.get_last_error() != _ERROR_INSUFFICIENT_BUFFER:
            raise OSError("TokenUser size unavailable")
        if needed.value < ctypes.sizeof(_SidAndAttributes):
            raise OSError("TokenUser unavailable")
        buffer = ctypes.create_string_buffer(needed.value)
        if not self.advapi.GetTokenInformation(
                token, _TOKEN_USER, buffer, needed.value, ctypes.byref(needed)):
            raise OSError("TokenUser unavailable")
        user = ctypes.cast(buffer, ctypes.POINTER(_SidAndAttributes)).contents
        text = ctypes.c_void_p()
        if not self.advapi.ConvertSidToStringSidW(user.sid, ctypes.byref(text)):
            raise OSError("TokenUser SID unavailable")
        try:
            return ctypes.wstring_at(text)
        finally:
            self.kernel.LocalFree(text)

    def revert(self) -> bool:
        return bool(self.advapi.RevertToSelf())

    def close_token(self, token) -> None:
        self.kernel.CloseHandle(token)


def verify_system_pipe_client(handle, *, api=None) -> str | None:
    """Return a reason code on refusal, or None after identifying SYSTEM.

    ``api`` is an in-process test seam. A failed revert terminates the entire
    helper, including when this function runs on a daemon connection worker.
    Even an unsuccessful impersonation attempt is followed by RevertToSelf.
    """
    try:
        active = api if api is not None else _WindowsPeerApi()
    except Exception:
        return PEER_IDENTITY_UNAVAILABLE
    token = None
    restored = False
    try:
        try:
            if not active.impersonate(handle):
                return PEER_IMPERSONATION_FAILED
            token = active.open_thread_token()
            if not token:
                return PEER_TOKEN_UNAVAILABLE
            sid = active.token_user_sid(token)
            if not sid:
                return PEER_IDENTITY_UNAVAILABLE
            return None if sid == SYSTEM_SID else PEER_NOT_SYSTEM
        except Exception:
            return PEER_IDENTITY_UNAVAILABLE
        finally:
            try:
                restored = bool(active.revert())
            except BaseException:
                os._exit(REVERT_FAILURE_EXIT_CODE)
            if not restored:
                os._exit(REVERT_FAILURE_EXIT_CODE)
    finally:
        # This is deliberately after a successful revert, including errors
        # reading the SID. No cleanup or logging is allowed on revert failure.
        if restored and token:
            active.close_token(token)
