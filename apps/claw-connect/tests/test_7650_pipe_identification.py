"""Identification SQOS contracts and a real Windows default-level measurement."""
from __future__ import annotations

import ctypes
import subprocess
import sys
import uuid

import pytest

from claw_connect import user_helper_peer as peer
from claw_connect import user_helper_service as service
from claw_connect import user_session_delegation as delegation
from claw_connect import user_session_helper as helper


def test_win32_pipe_connection_requests_sqos_identification(monkeypatch):
    calls = []

    class Kernel:
        def WaitNamedPipeW(self, path, timeout):
            self.path = path
            self.timeout = timeout
            return True

        def CreateFileW(self, *args):
            calls.append(args)
            return 456

    kernel = Kernel()
    monkeypatch.setattr(ctypes, "WinDLL", lambda name, use_last_error: kernel)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(service, "WindowsPipeConnection", lambda handle: handle)
    assert delegation.open_pipe_connection("unused-test-pipe-path") == 456
    assert len(calls) == 1
    assert calls[0][5] == 0x00100000 | 0x00010000


class _LevelApi:
    def __init__(self, returned=4):
        self.returned = returned
        self.calls = []

    def GetTokenInformation(self, token, information, buffer, size, needed):
        self.calls.append((token, information, size))
        ctypes.cast(needed, ctypes.POINTER(ctypes.c_ulong))[0] = self.returned
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_int))[0] = peer.SECURITY_IDENTIFICATION
        return 1


@pytest.mark.parametrize("returned", [0, 3, 5])
def test_token_level_must_be_a_complete_value(returned):
    api = peer._WindowsPeerApi.__new__(peer._WindowsPeerApi)
    api.advapi = _LevelApi(returned)
    with pytest.raises(OSError, match="TokenImpersonationLevel"):
        api.token_impersonation_level(789)


def test_token_level_is_read_with_fixed_size():
    api = peer._WindowsPeerApi.__new__(peer._WindowsPeerApi)
    api.advapi = _LevelApi()
    assert api.token_impersonation_level(789) == peer.SECURITY_IDENTIFICATION
    assert api.advapi.calls == [(789, 9, ctypes.sizeof(ctypes.c_int))]


@pytest.mark.skipif(sys.platform != "win32", reason="real Windows named-pipe SQOS")
def test_dotnet_default_constructor_gets_impersonation_and_helper_refuses(tmp_path):
    device_id = "test-level-" + uuid.uuid4().hex
    listener = service.WindowsPipeListener(device_id)
    client_path = tmp_path / "default-client.ps1"
    connection = None
    client = None
    try:
        client_path.write_text(
            "$c=New-Object System.IO.Pipes.NamedPipeClientStream('.',"
            "'" + helper.pipe_name(device_id) + "',[System.IO.Pipes.PipeDirection]::InOut)\n"
            "try { $c.Connect(5000); $c.Write([byte[]](0,0,0,1),0,4); $c.Flush(); "
            "[void]$c.ReadByte() }\n"
            "finally { $c.Dispose() }\n",
            encoding="utf-8-sig",
        )
        client = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
             "Bypass", "-File", str(client_path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        connection = listener.accept(10)
        assert connection is not None
        # Production order: serve_pipe reads the 4-byte header before the
        # peer check. Measured on Windows, that order matters for a no-SQOS
        # client: verifying before the header read fails at
        # ImpersonateNamedPipeClient (error 1368, no level observed, reason
        # peer_impersonation_failed), while after the header read the
        # impersonation succeeds and the token level is 2
        # (SecurityImpersonation, the default when SQOS is not present).
        # The .NET 3-argument constructor passes TokenImpersonationLevel.None,
        # which likewise carries no SQOS, so the production outcome is the
        # level check below, not the pre-header impersonation failure.
        header = connection.read_exact_bounded(4)
        assert header == b"\x00\x00\x00\x01"
        levels = []

        class LevelObservedPeerApi(peer._WindowsPeerApi):
            def token_impersonation_level(self, token):
                level = super().token_impersonation_level(token)
                levels.append(level)
                return level

        reason = peer.verify_system_pipe_client(
            connection._handle, api=LevelObservedPeerApi())
        assert (levels, reason) == ([2], peer.PEER_IMPERSONATION_LEVEL_UNEXPECTED)
    finally:
        if connection is not None:
            connection.close()
        listener.close()
        if client is not None:
            if client.poll() is None:
                client.kill()
            client.wait(timeout=15)
