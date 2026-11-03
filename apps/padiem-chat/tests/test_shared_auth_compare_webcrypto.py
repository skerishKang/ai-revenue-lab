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
        self.imports = []
    async def importKey(self, kind, jwk, alg, extractable, usages):
        assert kind == 'jwk' and alg == {'name':'ECDSA','namedCurve':'P-256'}
        assert extractable is False and len(usages) == 1
        self.imports.append((usages[0], dict(jwk)))
        return dict(jwk)
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
    subtle = Subtle()
    port = WorkerES256(runtime_loader=lambda:(subtle, Bytes, Obj, convert))
    async def exercise():
        signed = await port.sign(jwk, b'exact message')
        assert await port.sign(jwk, b'second message')
        assert len(signed) == 64
        assert await port.verify(public, signed, b'exact message')
        assert not await port.verify(public, signed, b'tampered')
        assert [usage for usage, _ in subtle.imports] == ['sign', 'verify']
    asyncio.run(exercise())


def test_webcrypto_signing_key_cache_refreshes_when_jwk_rotates():
    private = ec.generate_private_key(ec.SECP256R1()).private_numbers()
    jwk = {'kty':'EC','crv':'P-256','x':_b64int(private.public_numbers.x),
           'y':_b64int(private.public_numbers.y),'d':_b64int(private.private_value)}
    def convert(value, *, dict_converter, create_pyproxies):
        return value
    subtle = Subtle()
    port = WorkerES256(runtime_loader=lambda:(subtle, Bytes, Obj, convert))

    rotated_private = ec.generate_private_key(ec.SECP256R1()).private_numbers()
    rotated = {'kty':'EC','crv':'P-256','x':_b64int(rotated_private.public_numbers.x),
               'y':_b64int(rotated_private.public_numbers.y),
               'd':_b64int(rotated_private.private_value)}

    async def exercise():
        await port.sign(jwk, b'before rotation')
        await port.sign(jwk, b'same key')
        signature = await port.sign(rotated, b'after rotation')
        assert [usage for usage, _ in subtle.imports] == ['sign', 'sign']
        assert subtle.imports[0][1] == jwk
        assert subtle.imports[1][1] == rotated
        assert await port.verify({k: v for k, v in rotated.items() if k != 'd'},
                                 signature, b'after rotation')
    asyncio.run(exercise())
