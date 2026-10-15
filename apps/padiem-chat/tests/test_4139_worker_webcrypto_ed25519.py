"""Worker-native Ed25519 boundary, no CFFI / cryptography / live Cloudflare."""
from __future__ import annotations

import asyncio
import base64
import json
import shutil
import subprocess
import sys
from types import ModuleType, SimpleNamespace

import pytest

from app.connector_worker_webcrypto_verify import (
    CloudflareWorkerEd25519Verifier, _bytes_as_uint8,
    WORKER_ED25519_OWNER_GATEWAY_MOUNTED,
    WORKER_ED25519_PRODUCTION_ENABLED,
)

SEED="9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
PUBLIC=bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
NODE=r"""
const crypto=require('node:crypto');
const seed=Buffer.from(process.argv[1],'hex');
const key=crypto.createPrivateKey({
 key:Buffer.concat([Buffer.from('302e020100300506032b657004220420','hex'),seed]),
 format:'der',type:'pkcs8'
});
process.stdout.write(crypto.sign(null,Buffer.from(process.argv[2],'hex'),key).toString('base64'));
"""


class TypedBytes:
    @staticmethod
    def new(length):
        return [0]*length


class Crypto:
    def __init__(self, *, verdict=True):
        self.calls=[]
        self.verdict=verdict

    async def importKey(self, fmt, key, algorithm, extractable, usages):
        self.calls.append(("import",fmt,bytes(key),algorithm,extractable,usages))
        return object()

    async def verify(self, algorithm, key, signature, transcript):
        self.calls.append(("verify",algorithm,bytes(signature),bytes(transcript)))
        if isinstance(self.verdict, Exception):
            raise self.verdict
        return self.verdict


def make(*, verdict=True):
    subtle=Crypto(verdict=verdict)
    verifier=CloudflareWorkerEd25519Verifier(
        runtime_loader=lambda: (subtle,TypedBytes,lambda v: v),
    )
    return verifier,subtle


def test_worker_native_api_receives_real_binary_not_pseudo_json():
    if not shutil.which("node"):
        pytest.skip("Node crypto unavailable")
    message=b"padiem.connector-pending-pc.v1\nwindows.device\n"+bytes(range(32))
    signature=base64.b64decode(subprocess.check_output(
        ["node","-e",NODE,SEED,message.hex()],timeout=8,
    ),validate=True)
    v,api=make()
    assert asyncio.run(v.verify_ed25519(
        public_key=PUBLIC,signature=signature,transcript=message,
    )) is True
    assert api.calls[0]==("import","raw",PUBLIC,"Ed25519",False,["verify"])
    assert api.calls[1]==("verify","Ed25519",signature,message)
    assert signature!=PUBLIC


@pytest.mark.parametrize("verdict",[False,"true",1,None,[],RuntimeError("key material")])
def test_truthy_or_broken_worker_crypto_cannot_authenticate(verdict):
    v,api=make(verdict=verdict)
    assert asyncio.run(v.verify_ed25519(
        public_key=PUBLIC,signature=b"\x01"*64,transcript=b"pc transcript"
    )) is (verdict is True and type(verdict) is bool)


@pytest.mark.parametrize("input",[
    {"public_key":b"bad","signature":b"0"*64,"transcript":b"test"},
    {"public_key":PUBLIC,"signature":b"short","transcript":b"test"},
    {"public_key":PUBLIC,"signature":b"0"*64,"transcript":b""},
    {"public_key":PUBLIC,"signature":b"0"*64,"transcript":b"t"*2049},
    {"public_key":PUBLIC,"signature":"bad","transcript":b"test"},
    {"public_key":None,"signature":b"0"*64,"transcript":b"test"},
])
def test_invalid_input_never_calls_webcrypto(input):
    v,api=make()
    assert asyncio.run(v.verify_ed25519(**input)) is False
    assert api.calls==[]


def test_missing_worker_js_runtime_is_fail_closed():
    v=CloudflareWorkerEd25519Verifier(runtime_loader=lambda: (_ for _ in ()).throw(ImportError("js")))
    assert asyncio.run(v.verify_ed25519(
        public_key=PUBLIC,signature=b"0"*64,transcript=b"test",
    )) is False


def test_default_worker_import_is_lazy_and_uses_real_js_pyodide_interfaces(monkeypatch):
    api=Crypto()
    js=ModuleType("js")
    js.crypto=SimpleNamespace(subtle=api)
    js.Uint8Array=TypedBytes
    ffi=ModuleType("pyodide.ffi")
    ffi.to_js=lambda x:x
    pyodide=ModuleType("pyodide")
    pyodide.__path__=[]
    monkeypatch.setitem(sys.modules,"js",js)
    monkeypatch.setitem(sys.modules,"pyodide",pyodide)
    monkeypatch.setitem(sys.modules,"pyodide.ffi",ffi)
    v=CloudflareWorkerEd25519Verifier()
    assert asyncio.run(v.verify_ed25519(
        public_key=PUBLIC,signature=b"0"*64,transcript=b"test",
    )) is True
    assert api.calls[0][1:]==("raw",PUBLIC,"Ed25519",False,["verify"])


def test_unmounted_runtime_never_assumes_worker_crypto_authenticated():
    assert WORKER_ED25519_OWNER_GATEWAY_MOUNTED is False
    assert WORKER_ED25519_PRODUCTION_ENABLED is False
