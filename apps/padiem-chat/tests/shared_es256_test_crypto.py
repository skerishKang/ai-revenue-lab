"""CPython test oracle only; production uses WebCrypto."""
import base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature, encode_dss_signature


def _int(value):
    return int.from_bytes(base64.urlsafe_b64decode(value + '=' * (-len(value) % 4)), 'big')


class TestES256:
    async def sign(self, jwk, message):
        key = ec.derive_private_key(_int(jwk['d']), ec.SECP256R1())
        pub = key.public_key().public_numbers()
        if pub.x != _int(jwk['x']) or pub.y != _int(jwk['y']):
            raise ValueError('invalid_key')
        r, s = decode_dss_signature(key.sign(message, ec.ECDSA(hashes.SHA256())))
        return r.to_bytes(32, 'big') + s.to_bytes(32, 'big')

    async def verify(self, jwk, signature, message):
        try:
            key = ec.EllipticCurvePublicNumbers(_int(jwk['x']), _int(jwk['y']), ec.SECP256R1()).public_key()
            sig = encode_dss_signature(int.from_bytes(signature[:32], 'big'), int.from_bytes(signature[32:], 'big'))
            key.verify(sig, message, ec.ECDSA(hashes.SHA256()))
            return True
        except Exception:
            return False
