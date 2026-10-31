"""COM2 identity relay to a configured, authenticated HTTPS authority.

The upstream must be an explicitly provisioned private identity RPC ingress.
It is not created, enabled, or changed by this module. An unavailable or
unauthorized method fails closed; there is no local storage fallback.

Every relayed call names itself with a fresh id under the v2 proof the ingress
verifies (#6417). A 409 replay refusal is retried under a new id up to a cap:
the upstream consumes the id, so re-sending the same one can only be refused.
"""
import asyncio
import json
import os
from pathlib import Path
import time
import uuid
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from com2_identity_rpc_ingress import COM2_IDENTITY_RPC_METHODS
from internal_rpc_ingress import SERVICE_ID_HEADER, proof_for_v2

MAX_RESPONSE_BYTES = 512 * 1024
RPC_REPLAY_STATUS = 409
RPC_MAX_ATTEMPTS = 3


class IdentityRpcReplayRefused(RuntimeError):
    """The upstream had already consumed this request id."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class IdentityDoProxy:
    def __init__(self, origin, secret, *, sender=None):
        parsed = urlsplit(origin)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
            raise ValueError("private identity HTTPS origin required")
        if not isinstance(secret, str) or len(secret) < 32:
            raise ValueError("existing identity RPC proof secret required")
        self._origin = origin.rstrip("/")
        self._secret = secret
        self._sender = sender or self._send

    def __getattr__(self, method):
        if method not in COM2_IDENTITY_RPC_METHODS:
            raise AttributeError(method)

        async def call(payload):
            if not isinstance(payload, dict):
                raise TypeError("RPC payload must be an object")
            path = "/internal/rpc/" + method
            body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            url = self._origin + path
            for _ in range(RPC_MAX_ATTEMPTS):
                at = int(time.time())
                # A new id each attempt: the refused one is already consumed.
                service_id = str(uuid.uuid4())
                headers = {
                    "content-type": "application/json",
                    "x-padiem-service-at": str(at),
                    SERVICE_ID_HEADER: service_id,
                    "x-padiem-service-proof": proof_for_v2(
                        self._secret, method="POST", path=path, at=at,
                        service_id=service_id, body=body,
                    ),
                }
                try:
                    return await asyncio.to_thread(self._sender, url, body, headers)
                except IdentityRpcReplayRefused:
                    continue
            raise RuntimeError("identity RPC unavailable")
        return call

    @staticmethod
    def _send(url, body, headers):
        req = Request(url, data=body, headers=headers, method="POST")
        # No redirect: never forward a signed identity payload to another origin.
        opener = build_opener(_NoRedirect())
        try:
            with opener.open(req, timeout=8) as response:
                if response.status != 200:
                    raise RuntimeError("identity RPC unavailable")
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            if exc.code == RPC_REPLAY_STATUS:
                raise IdentityRpcReplayRefused("identity RPC refused the request id") from exc
            raise RuntimeError("identity RPC unavailable") from exc
        except OSError as exc:
            raise RuntimeError("identity RPC unavailable") from exc
        if len(raw) > MAX_RESPONSE_BYTES:
            raise RuntimeError("identity response too large")
        try:
            answer = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise RuntimeError("identity response invalid") from exc
        if type(answer) is not dict:
            raise RuntimeError("identity response invalid")
        return answer


def create_authority():
    origin = os.environ.get("COM2_IDENTITY_UPSTREAM_ORIGIN", "").strip()
    path = os.environ.get("COM2_IDENTITY_UPSTREAM_SECRET_FILE", "").strip()
    if not path:
        raise RuntimeError("existing upstream identity RPC proof file required")
    try:
        secret = Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError("identity RPC proof file unreadable") from exc
    return IdentityDoProxy(origin, secret)
