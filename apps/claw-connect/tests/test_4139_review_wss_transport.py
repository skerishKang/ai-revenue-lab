"""Actual WSS client interface regression using zero sockets and fake TLS."""
from __future__ import annotations

import asyncio
import ssl
import sys
from types import ModuleType, SimpleNamespace

import pytest

import claw_connect.review_wss_transport as t
from claw_connect.device_wss_enrollment import DeviceSessionRefused
from claw_connect.wss_target import REVIEW_WSS_URL, REVIEW_WSS_HOST


def test_strict_verified_tls_and_frame_logger_disabled():
    ctx = t.strict_server_tls_context()
    assert type(ctx) is ssl.SSLContext
    assert ctx.check_hostname is True and ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.minimum_version >= ssl.TLSVersion.TLSv1_2
    assert t._FRAME_LOG.disabled and not t._FRAME_LOG.propagate
    assert t.WSS_PRODUCTION_DIALER_ENABLED is False


def test_unapproved_caller_cannot_even_import_network_client():
    async def attempt():
        async with t.open_review_only_wss_socket():
            pytest.fail("network not allowed")
    with pytest.raises(DeviceSessionRefused, match="not_authorized"):
        asyncio.run(attempt())
    with pytest.raises(DeviceSessionRefused, match="not_authorized"):
        asyncio.run(t.run_review_only_wss_pairing(
            enrollment=object(), receiver=object(), challenge_id="x", pairing_code="y",
        ))


def _fake_import(monkeypatch, connect_type):
    a=ModuleType("websockets");a.__path__=[]
    b=ModuleType("websockets.asyncio");b.__path__=[]
    c=ModuleType("websockets.asyncio.client");c.connect=connect_type
    for key,value in (("websockets",a),("websockets.asyncio",b),
                      ("websockets.asyncio.client",c)):
        monkeypatch.setitem(sys.modules,key,value)


def test_real_client_factory_forces_fixed_tls_and_disallows_all_redirects(monkeypatch):
    seen={}
    class FakeConnect:
        def __init__(self,uri,**kwargs):
            seen.update(uri=uri,kwargs=kwargs,kind=type(self))
        def process_redirect(self,exc):
            return "wss://redirect-to-attacker.example"
        async def __aenter__(self):
            class Untrusted:
                transport=SimpleNamespace(get_extra_info=lambda field:None)
                async def close(self,*,code):
                    seen["close_code"]=code
            return Untrusted()
        async def __aexit__(self,*exc):
            return False
    _fake_import(monkeypatch,FakeConnect)
    async def run():
        with pytest.raises(DeviceSessionRefused,match="peer_not_verified"):
            async with t.open_review_only_wss_socket(source_test_authorized=True):
                pytest.fail("untrusted TLS should never enter pairing")
    asyncio.run(run())
    assert seen["uri"]==REVIEW_WSS_URL
    opts=seen["kwargs"]
    for name in ("proxy","origin","compression","additional_headers","subprotocols"):
        assert opts[name] is None
    assert opts["server_hostname"]==REVIEW_WSS_HOST
    assert opts["ssl"].check_hostname and opts["ssl"].verify_mode==ssl.CERT_REQUIRED
    assert opts["max_size"]==8192 and opts["max_queue"]==2
    assert opts["open_timeout"]==8 and opts["close_timeout"]==2
    assert opts["logger"] is t._FRAME_LOG
    assert seen["close_code"]==1000
    error=ValueError("HTTP redirect")
    cls=seen["kind"]
    assert cls.process_redirect(cls.__new__(cls),error) is error


def test_network_handshake_errors_are_sanitized(monkeypatch):
    class Broken:
        def __init__(self,*a,**k):
            pass
        async def __aenter__(self):
            raise ConnectionError("credential-path-secret")
        async def __aexit__(self,*args):
            return False
    _fake_import(monkeypatch,Broken)
    async def run():
        with pytest.raises(DeviceSessionRefused,match="review_wss_connection_refused") as err:
            async with t.open_review_only_wss_socket(source_test_authorized=True):
                pass
        assert "credential-path-secret" not in str(err.value)
    asyncio.run(run())


def test_plain_connection_and_wrong_tls_cannot_send_or_receive_any_frame():
    ctx=t.strict_server_tls_context()
    class Fake:
        def __init__(self):
            self.out=[]
        async def send(self,raw):
            self.out.append(raw)
        async def recv(self):
            return "credential_once"
        async def close(self,*,code):
            self.code=code
    raw=Fake()
    sock=t.VerifiedReviewSocket(raw,ctx)
    async def run():
        assert not await t.VerifiedReviewTls().verify(sock)
        with pytest.raises(DeviceSessionRefused,match="send_denied"):
            await sock.send_text("pairing_code_example_secret")
        with pytest.raises(DeviceSessionRefused,match="receive_denied"):
            await sock.receive_text()
        await sock.close()
    asyncio.run(run())
    assert raw.out==[] and raw.code==1000


def test_verified_text_frame_bounds_binary_refusal_and_tls_recheck(monkeypatch):
    ctx=t.strict_server_tls_context()
    class FakeSSL:
        def __init__(self):
            self.context=ctx;self.server_hostname=REVIEW_WSS_HOST
            self.protocol="TLSv1.3";self.cert={"subject":"mock"}
        def version(self):
            return self.protocol
        def getpeercert(self):
            return self.cert
    class Fake:
        def __init__(self):
            self.tls=FakeSSL()
            self.transport=SimpleNamespace(get_extra_info=lambda name:self.tls)
            self.out=[];self.inbound="ok"
        async def send(self,raw):
            self.out.append(raw)
        async def recv(self):
            return self.inbound
        async def close(self,*,code):
            self.code=code
    monkeypatch.setattr(t.ssl,"SSLObject",FakeSSL)
    raw=Fake();s=t.VerifiedReviewSocket(raw,ctx)
    async def run():
        assert await t.VerifiedReviewTls().verify(s)
        await s.send_text("begin")
        assert await s.receive_text()=="ok"
        with pytest.raises(DeviceSessionRefused,match="send_denied"):
            await s.send_text("X"*8193)
        raw.inbound=b"not text"
        with pytest.raises(DeviceSessionRefused,match="inbound_shape_denied"):
            await s.receive_text()
        raw.tls.server_hostname="evil.example"
        assert not s.tls_verified()
        raw.tls.server_hostname=REVIEW_WSS_HOST
        raw.tls.protocol="TLSv1.1"
        assert not s.tls_verified()
        raw.tls.protocol="TLSv1.3";raw.tls.cert={}
        assert not s.tls_verified()
        await s.close()
    asyncio.run(run())
    assert raw.out==["begin"] and raw.code==1000


def test_ordinary_cli_and_installer_do_not_enable_wss():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    assert "review_wss_transport" not in (root/"claw_connect"/"__main__.py").read_text()
    assert "review_wss_transport" not in (root/"claw_connect"/"runtime.py").read_text()
    assert "websockets" not in (root/"install.ps1").read_text()
