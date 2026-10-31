"""Default-off COM2 gateway relay to the single loopback Broker socket owner.

The broker endpoint must verify the signed request ID and reject replays before
accepting. Until that route exists this relay fails closed. No PC messages,
pairing codes or credentials are logged or retained.
"""
import asyncio
import secrets

from starlette.websockets import WebSocketState
from websockets.legacy.client import connect

from .local_service_bridge import service_proof_headers

PATH = "/internal/connector/pc-offer-4139"
MAX_FRAME = 8192


class _NoRedirect(connect):
    def handle_redirect(self, uri):
        raise ValueError("broker redirects are forbidden")


def _upstream(secret):
    request_id = secrets.token_hex(16)
    # The request ID is signed as the v1 GET body. The Broker must atomically
    # consume it in its durable replay store before a successful upgrade.
    headers = service_proof_headers(secret, method="GET", path=PATH,
                                    body=request_id.encode("ascii"))
    headers["x-padiem-request-id"] = request_id
    return _NoRedirect("ws://127.0.0.1:8799" + PATH, extra_headers=headers,
                   max_size=MAX_FRAME, open_timeout=5, close_timeout=2)


async def relay_pc_offer(websocket, broker_binding):
    if any(websocket.headers.get(name) is not None for name in (
        "origin", "cookie", "authorization", "sec-websocket-protocol",
    )):
        await websocket.close(code=1008)
        return
    close_code = 1011
    try:
        secret = object.__getattribute__(broker_binding, "_secret")
        async with _upstream(secret) as upstream:
            await websocket.accept()

            async def to_broker():
                while True:
                    frame = await websocket.receive_text()
                    if len(frame.encode("utf-8")) > MAX_FRAME:
                        raise ValueError("frame too large")
                    await upstream.send(frame)

            async def to_device():
                async for frame in upstream:
                    if type(frame) is not str or len(frame.encode("utf-8")) > MAX_FRAME:
                        raise ValueError("frame invalid")
                    await websocket.send_text(frame)

            tasks = [asyncio.create_task(to_broker()), asyncio.create_task(to_device())]
            try:
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                upstream_code = getattr(upstream, "close_code", None)
                close_code = upstream_code if upstream_code in (1000, 1001, 1008, 1011) else 1011
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
    except Exception:
        # Refuse without exposing upstream response details or secrets.
        pass
    finally:
        if websocket.application_state != WebSocketState.DISCONNECTED:
            try:
                await websocket.close(code=close_code)
            except RuntimeError:
                pass
