import asyncio
import base64
from cryptography.hazmat.primitives.asymmetric import ec
from app.shared_auth_compare_webcrypto import WorkerES256
from tests.shared_es256_test_crypto import TestES256


def _b64int(value):
    return base64.urlsafe_b64encode(value.to_bytes(32, 'big')).rstrip(b'=').decode()


class Bytes(bytearray):
    @classmethod
    def new(cls, value):
        return cls(value)
    def to_py(self):
        return bytes(self)


class Obj:
    fromEntries = object()


class Subtle:
    def __init__(self):
        self.port = TestES256()
    async def importKey(self, kind, jwk, alg, extractable, usages):
        assert kind == 'jwk' and alg == {'name':'ECDSA','namedCurve':'P-256'}
        assert extractable is False and len(usages) == 1
        return jwk
    async def sign(self, alg, key, data):
        assert alg == {'name':'ECDSA','hash':'SHA-256'}
        return await self.port.sign(key, bytes(data))
    async def verify(self, alg, key, signature, data):
        return await self.port.verify(key, bytes(signature), bytes(data))


def test_webcrypto_ffi_passes_exact_bytes_and_rejects_tampering():
    private = ec.generate_private_key(ec.SECP256R1()).private_numbers()
    jwk = {'kty':'EC','crv':'P-256','x':_b64int(private.public_numbers.x),
           'y':_b64int(private.public_numbers.y),'d':_b64int(private.private_value)}
    public = {k:v for k,v in jwk.items() if k != 'd'}
    def convert(value, *, dict_converter, create_pyproxies):
        assert dict_converter is Obj.fromEntries and create_pyproxies is False
        return value
    port = WorkerES256(runtime_loader=lambda:(Subtle(), Bytes, Obj, convert))
    async def exercise():
        signed = await port.sign(jwk, b'exact message')
        assert len(signed) == 64
        assert await port.verify(public, signed, b'exact message')
        assert not await port.verify(public, signed, b'tampered')
    asyncio.run(exercise())
