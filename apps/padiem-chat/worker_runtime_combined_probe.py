"""Real Workerd/Pyodide multiplex for the four original runtime probes.

Each case delegates the original WorkerEntrypoint.fetch() with the *real*
incoming Workers Request. Only the /probe?case=... routing is new. Keep P01
last in the single-process runner: its existing synthetic route test patches
module globals and must not influence the HTTP/R2 contract probes.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from workers import Response, WorkerEntrypoint
from worker_runtime_timeout_probe import Default as TimeoutProbe
from worker_runtime_web_transport_probe import Default as WebTransportProbe
from worker_runtime_r2_read_probe import Default as R2ReadProbe
from worker_runtime_p01_binding_probe import Default as P01BindingProbe


PROBES = {
    "timeout": TimeoutProbe.fetch,
    "web_transport": WebTransportProbe.fetch,
    "r2_read": R2ReadProbe.fetch,
    "p01_binding": P01BindingProbe.fetch,
}


# #4139: temporary Workerd ONLY; never import this synthetic gateway from the
# production padiem-chat/worker.py. A 101 here proves the real Cloudflare
# Python ASGI/WS upgrade transport, NOT canonical Identity/Broker or TLS.
RUNTIME_WSS_PROBE_PATH = "/api/claw/connector/gateway/session"
_RUNTIME_CLIENT_PROOF = "synthetic-frame-no-credential"
_RUNTIME_SERVER_OPEN = "PADIEM_CONNECTOR_ASGI_WS_OPEN"
_RUNTIME_SERVER_ACK = "PADIEM_CONNECTOR_ASGI_WS_REPLY"


async def connector_asgi_websocket_runtime_probe(scope, receive, send):
    """Pure ASGI fixture: no session, no credential, no Broker or privileged IO."""
    if scope.get("type") != "websocket" or scope.get("path") != RUNTIME_WSS_PROBE_PATH:
        await send({"type": "websocket.close", "code": 1008})
        return
    opened = await receive()
    if opened.get("type") != "websocket.connect":
        await send({"type": "websocket.close", "code": 1008})
        return
    await send({"type": "websocket.accept"})
    await send({"type": "websocket.send", "text": _RUNTIME_SERVER_OPEN})
    incoming = await receive()
    if (incoming.get("type") == "websocket.receive"
            and incoming.get("text") == _RUNTIME_CLIENT_PROOF):
        await send({"type": "websocket.send", "text": _RUNTIME_SERVER_ACK})
    # No credential or ACK data is ever sent. The test client closes.


def _password_kdf_state() -> str:
    """``ok`` when this runtime can run the Worker's password hashing.

    The Worker's stored credential format is PBKDF2-HMAC-SHA512. A Python
    runtime without ``hashlib.pbkdf2_hmac`` cannot verify a stored hash at
    all, so every password login would answer HTTP 500. The probe runs the
    real application hashing function, so a runtime without the KDF is
    reported instead of silently passing.
    """
    try:
        from app.password_auth import hash_password, verify_password

        stored = hash_password("runtime-probe-password")
        if not verify_password("runtime-probe-password", stored):
            return "verify-failed"
        if verify_password("runtime-probe-wrong", stored):
            return "verify-wrong-accepted"
        return "ok"
    except Exception:
        return "missing"


async def _password_kdf_async_state() -> str:
    """``ok`` when the async auth dispatch and the WebCrypto bridge hold.

    #5479/#5664: the auth routes now call the runtime-dispatching async twins
    (``hash_password_async``/``verify_password_async``), which use the C
    ``hashlib`` path on 3.13 and the Workers WebCrypto bridge on a 3.14
    snapshot without ``_hashlib``. This state proves both inside the real
    runtime: a production-cost round trip, and — with the non-C dispatch
    forced so the bridge runs against this runtime's real ``js.crypto.subtle``
    — byte-identity with the pure-Python RFC 2898 reference at a bounded
    iteration count.
    """
    try:
        from app import password_kdf
        from app.password_auth import (
            hash_password_async,
            verify_password_async,
        )

        stored = await hash_password_async("runtime-probe-password")
        if not await verify_password_async("runtime-probe-password", stored):
            return "async-verify-failed"
        salt = bytes.fromhex("c8ade6e8d0d15e5a2e14aabf5e5d8f4a")
        previous = password_kdf.FORCE_NON_C_PATH
        try:
            password_kdf.FORCE_NON_C_PATH = True
            bridged = await password_kdf.pbkdf2_sha512_webcrypto(
                b"runtime-probe-bridged", salt, 2_000, 32
            )
        finally:
            password_kdf.FORCE_NON_C_PATH = previous
        reference = password_kdf.pbkdf2_sha512_python(
            b"runtime-probe-bridged", salt, 2_000, 32
        )
        if bridged != reference:
            return "webcrypto-mismatch"
        return "ok"
    except Exception:
        return "missing"


#: A credential written by the Pyodide 3.13 runtime (CPython 3.13, C
#: ``hashlib`` PBKDF2 path) through the real application hashing function,
#: corroborated byte-for-byte by OpenSSL. Members keep these exact bytes: a
#: compatibility-date move must not re-hash or migrate anything, so the runtime
#: Production moves TO has to accept a hash written before the move.
#:
#: The iteration count carried here is the stored 220,000, which is the point
#: of this vector. #5736 recorded a deployed 3.14 Worker rejecting exactly that
#: cost — ``js.crypto.subtle.deriveBits`` answers PBKDF2 above 100,000 iterations
#: with ``NotSupportedError`` and there is no ``_hashlib`` C path on that
#: snapshot — so every register, login and password reset returned HTTP 500 and
#: Production had to be rolled back. The low-iteration bridge check in
#: :func:`_password_kdf_async_state` cannot see that ceiling; this one can.
LEGACY_PYODIDE_313_STORED_HASH = (
    "pbkdf2_sha512$220000$FRiPFPCmf2W2mVjqpy85qw==$"
    "JUn+Fo0Rod5ZOJPBy80PJOfmfOBSS4hHGaUw7FM4ymg="
)
LEGACY_PYODIDE_313_PASSWORD = "runtime-probe-legacy-credential"
LEGACY_PYODIDE_313_WRONG_PASSWORD = "runtime-probe-legacy-credential-wrong"


async def _legacy_stored_credential_state() -> str:
    """``ok`` when this runtime serves a credential written by the previous one.

    This is the production-shaped check: the auth routes serve an existing
    member through ``verify_password_async`` only, so the stored prefix,
    iteration count and derived key from the earlier runtime must pass here and
    a wrong password must not. A runtime that cannot reach the stored iteration
    count reports the raising exception class instead of a bare ``missing``,
    so the CI log names the ceiling rather than hiding it.
    """
    try:
        from app.password_auth import verify_password_async

        if not await verify_password_async(
            LEGACY_PYODIDE_313_PASSWORD, LEGACY_PYODIDE_313_STORED_HASH
        ):
            return "rejected"
        if await verify_password_async(
            LEGACY_PYODIDE_313_WRONG_PASSWORD, LEGACY_PYODIDE_313_STORED_HASH
        ):
            return "wrong-accepted"
        return "ok"
    except Exception as error:
        return f"blocked:{type(error).__name__}"


#: Published OpenSSL/CPython vectors for the digest surface the auth layer uses
#: outside the password KDF (token hashing in ``app/auth.py``, abuse keys in
#: ``app/auth_abuse.py``). Compared against an external oracle, not against
#: ``hashlib`` checking itself.
_SHA256_ABC = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
_SHA512_ABC = (
    "ddaf35a193617abacc417349ae20413112e6fa4e89a97ea20a9eeee64b55d39a"
    "2192992a274fc1a836ba3c23a3feebbd454d4423643ce80e2a9ac94fa54ca49f"
)
_HMAC_KEY = b"runtime-probe-key"
_HMAC_MESSAGE = b"runtime-probe-message"
_HMAC_SHA256_FIXED = "6d6357bb3cd312e22258e5b3a69d7783c68da539b57ff8add5002f5d9f508993"
_HMAC_SHA512_FIXED = (
    "c32b7a9ab5ecb2c9326f006ad9e88d5866d4fb9b0f02243ff6bc27ed1194ae45"
    "1cf380fd26f9f598c5ee01cdcdfb08378536f6137ea6a3bf89db874e450e8fba"
)


def _digest_surface_state() -> str:
    """``ok`` when this runtime's SHA-2 and HMAC match the published vectors.

    ``_hashlib`` (OpenSSL) is absent from the Pyodide 3.14 snapshot, and the
    auth layer hashes issued tokens, abuse keys and certified payloads with
    ``hashlib``/``hmac`` directly. A runtime answering those calls with
    different bytes would invalidate credentials that were issued before the
    move, so the move is provable only if the digests are checked here.
    """
    try:
        import hashlib
        import hmac

        if hashlib.sha256(b"abc").hexdigest() != _SHA256_ABC:
            return "sha256-mismatch"
        if hashlib.sha512(b"abc").hexdigest() != _SHA512_ABC:
            return "sha512-mismatch"
        if hmac.new(_HMAC_KEY, _HMAC_MESSAGE, hashlib.sha256).hexdigest() != _HMAC_SHA256_FIXED:
            return "hmac-sha256-mismatch"
        if hmac.new(_HMAC_KEY, _HMAC_MESSAGE, hashlib.sha512).hexdigest() != _HMAC_SHA512_FIXED:
            return "hmac-sha512-mismatch"
        return "ok"
    except Exception as error:
        return f"missing:{type(error).__name__}"


def _timezone_database_state() -> str:
    """``ok`` when this runtime can resolve a real IANA zone.

    #5023: the Calendar contracts validate the explicit timezone against the
    real IANA database. A Pyodide runtime without the tz database raises
    ZoneInfoNotFoundError for every real zone, and the Calendar routes surface
    that as HTTP 400 ``invalid_timezone`` on every read. The probe runs the
    real application contract, so a runtime without the database is reported
    instead of silently passing.
    """
    try:
        from app.calendar_contracts import validate_timezone

        validate_timezone("Asia/Seoul")
        return "ok"
    except Exception:
        return "missing"




class Default(WorkerEntrypoint):
    async def fetch(self, request):
        url = urlparse(str(request.url))
        if url.path == RUNTIME_WSS_PROBE_PATH and not url.query:
            if request.headers.get("upgrade") != "websocket":
                return Response("Upgrade Required", status=426)
            from workers import asgi
            # Worker Python SDK: asgi.websocket(app, request) accepts two args.
            # The synthetic transport probe must exercise the same signature
            # as CENTRAL's review-only production candidate.
            return await asgi.websocket(connector_asgi_websocket_runtime_probe, request)
        if url.path == "/ready" and not url.query:
            # #5479: report the running CPython version AND whether this
            # runtime can still run the Worker's password hashing. The CI lane
            # must prove the runtime Production actually deploys, and the
            # Pyodide 3.14 snapshot has no `hashlib.pbkdf2_hmac`, which would
            # answer every password login with HTTP 500.
            # #5023: the same holds for the IANA timezone database the
            # Calendar contracts validate against.
            # #5664: the ready line also carries the runtime-dispatching auth
            # KDF state (async routes + WebCrypto bridge), the cross-runtime
            # stored-credential check and the digest surface, so a compatibility
            # date move is provable in this lane before Production takes it.
            import sys

            kdf_async = await _password_kdf_async_state()
            stored = await _legacy_stored_credential_state()
            return Response(
                f"ok {sys.version_info.major}.{sys.version_info.minor} "
                f"kdf={_password_kdf_state()} kdfasync={kdf_async} "
                f"tz={_timezone_database_state()} stored={stored} "
                f"digest={_digest_surface_state()}",
                status=200,
            )
        if url.path != "/probe":
            return Response("not found", status=404)
        try:
            params = parse_qs(url.query, strict_parsing=True)
        except ValueError:
            return Response("invalid probe case", status=400)
        if set(params) != {"case"} or len(params["case"]) != 1:
            return Response("invalid probe case", status=400)
        handler = PROBES.get(params["case"][0])
        if handler is None:
            return Response("invalid probe case", status=400)
        # The old handlers inspect only request.url (the path remains /probe).
        # Passing the original real Workerd Request preserves the exact
        # JS-object/Request transport assertions in each legacy probe.
        return await handler(None, request)
