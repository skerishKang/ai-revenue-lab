"""ES256 using Workers WebCrypto; no native cryptography package is needed."""
from __future__ import annotations


def _runtime():
    # Resolve JS objects only inside a request; never place them in a snapshot.
    from js import Object, Uint8Array, crypto  # type: ignore
    from pyodide.ffi import to_js  # type: ignore
    return crypto.subtle, Uint8Array, Object, to_js


class WorkerES256:
    def __init__(self, runtime_loader=None):
        self._runtime_loader = runtime_loader or _runtime

    @staticmethod
    def _uint8(data, factory):
        result = factory.new(len(data))
        for index, byte in enumerate(data):
            result[index] = byte
        return result

    async def _key(self, jwk, usage, runtime):
        subtle, _, obj, to_js = runtime
        convert = lambda value: to_js(value, dict_converter=obj.fromEntries, create_pyproxies=False)
        algorithm = convert({'name':'ECDSA', 'namedCurve':'P-256'})
        return await subtle.importKey('jwk', convert(jwk), algorithm, False, convert([usage]))

    async def sign(self, jwk, message):
        runtime = self._runtime_loader()
        subtle, uint8, obj, to_js = runtime
        key = await self._key(jwk, 'sign', runtime)
        algorithm = to_js({'name':'ECDSA','hash':'SHA-256'}, dict_converter=obj.fromEntries, create_pyproxies=False)
        output = await subtle.sign(algorithm, key, self._uint8(message, uint8))
        signature = bytes(uint8.new(output).to_py())
        if len(signature) != 64:
            raise ValueError('invalid_es256_signature')
        return signature

    async def verify(self, jwk, signature, message):
        if not isinstance(signature, bytes) or len(signature) != 64:
            return False
        runtime = self._runtime_loader()
        subtle, uint8, obj, to_js = runtime
        key = await self._key(jwk, 'verify', runtime)
        algorithm = to_js({'name':'ECDSA','hash':'SHA-256'}, dict_converter=obj.fromEntries, create_pyproxies=False)
        result = await subtle.verify(algorithm, key, self._uint8(signature, uint8), self._uint8(message, uint8))
        return result is True
