"""COM2-only private PC-offer socket; canonical Broker actor and storage."""
import asyncio
import hmac
import re
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from starlette.websockets import WebSocketDisconnect, WebSocketState

from internal_rpc_ingress import proof_for
from padiem_control_plane.broker_pending_pc_private_rpc import _enabled
from padiem_control_plane.broker_pending_pc_wss import LivePcWssOffer, MAX_PENDING_PC_WSS_PER_DO

PATH = "/internal/connector/pc-offer-4139"
WINDOW = 300
_ID = re.compile(r"^[0-9a-f]{32}$")


class _Socket:
    def __init__(self, ws):
        self.ws = ws
        self.closed = False
    async def send_text(self, value):
        if self.closed:
            raise ValueError("socket closed")
        await self.ws.send_text(value)
    async def close(self, *, code=1008):
        self.closed = True
        if self.ws.application_state != WebSocketState.DISCONNECTED:
            await self.ws.close(code=code)


async def _verify(*, public_key, signature, transcript):
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, transcript)
        return True
    except Exception:
        return False


def _admit(ws, *, secret, storage, now=None):
    try:
        headers = ws.headers
        scope = ws.scope
        if scope.get("path") != PATH or scope.get("query_string"):
            return False
        if (not scope.get("client") or scope["client"][0] not in ("127.0.0.1", "::1")
            or any(headers.get(k) is not None for k in ("origin", "cookie", "authorization", "sec-websocket-protocol"))):
            return False
        raw_names = [name.lower() for name, _ in scope.get("headers", ())]
        names = (b"x-padiem-request-id", b"x-padiem-service-at", b"x-padiem-service-proof")
        if any(raw_names.count(name) != 1 for name in names):
            return False
        rid = headers.get("x-padiem-request-id")
        at_text = headers.get("x-padiem-service-at")
        signature = headers.get("x-padiem-service-proof")
        if not isinstance(rid, str) or not _ID.fullmatch(rid) or not isinstance(at_text, str) or not at_text.isascii() or not at_text.isdigit():
            return False
        at = int(at_text)
        current = int(time.time()) if now is None else now
        if str(at) != at_text or abs(current - at) > WINDOW or not isinstance(signature, str):
            return False
        expected = proof_for(secret, method="GET", path=PATH, at=at, body=rid.encode("ascii"))
        if not hmac.compare_digest(signature, expected):
            return False
        def consume():
            storage.sql.exec("DELETE FROM com2_pc_offer_replay WHERE expires_at < ?", current)
            inserted = storage.sql.exec("INSERT OR IGNORE INTO com2_pc_offer_replay (request_id, expires_at) VALUES (?, ?)", rid, at + WINDOW)
            return inserted.rowsWritten == 1
        return storage.transactionSync(consume)
    except Exception:
        return False


def make_route(*, owner, secret):
    # Only called by an explicitly enabled app; use the same broker database.
    owner._storage.sql.exec("CREATE TABLE IF NOT EXISTS com2_pc_offer_replay (request_id TEXT PRIMARY KEY, expires_at INTEGER NOT NULL)")
    # Match the canonical actor registry used by the identity handoff.
    # This registry belongs to this broker instance, never to a client.
    owner._pending_pc_wss_by_id = {}

    async def endpoint(ws):
        if (not _enabled(owner.env)
            or getattr(owner.env, "LOCAL_AGENT_BROKER_PENDING_PC_WSS_ENABLED", None) != "enabled"
            or len(owner._pending_pc_wss_by_id) >= MAX_PENDING_PC_WSS_PER_DO
            or not _admit(ws, secret=secret, storage=owner._storage)):
            await ws.close(code=1008)
            return
        try:
            owner._pending_pc_live()
        except Exception:
            await ws.close(code=1008)
            return
        sock = _Socket(ws)
        actor = LivePcWssOffer(storage=owner._storage, socket=sock, verifier=_verify)
        # Reserve the slot before the first await so simultaneous upgrades
        # cannot exceed the same-process session cap.
        owner._pending_pc_wss_by_id[actor] = actor
        try:
            await ws.accept()
            while True:
                await actor.message(await ws.receive_text(), owner_do=owner)
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        except Exception:
            pass
        finally:
            actor.mark_disconnected()
            owner._pending_pc_wss_by_id.pop(actor, None)
            if actor._request_ref:
                owner._pending_pc_live_by_ref.pop(actor._request_ref, None)
            await sock.close()
    return endpoint
