"""The COM2 host's ``voice_stt_transport`` over the Chat-Worker RPC (#7228).

The host has no Service Binding to the private STT Worker, so this transport
forwards the exact ``live_token``/``transcribe`` contract of
``CloudflareVoiceSttServiceTransport`` over the authenticated Chat-Worker RPC
(``app/voice_stt_rpc.py``) using the host's existing ``HttpRpcBinding`` client.
The STT Worker's own bounded status codes travel through unchanged so the
public routes keep answering truthfully; an RPC transport failure surfaces as
``ServiceBindingResponseError``, which the routes map to the fail-closed 503.
"""
from __future__ import annotations

from typing import Any

from .service_binding_response import ServiceBindingResponseError


class HostVoiceSttRpcTransport:
    """``app.state.voice_stt_transport`` for the host, backed by one RPC."""

    def __init__(self, binding: Any) -> None:
        self._binding = binding

    async def live_token(
        self, *, body: dict[str, Any], product_id: str, session_id: str
    ) -> tuple[int, bytes]:
        # The public route sends body={"sessionId": ...} with the same value in
        # session_id; the RPC envelope carries it once.
        return await self._call(
            {"op": "live_token", "productId": product_id, "sessionId": session_id}
        )

    async def transcribe(
        self, *, body: dict[str, Any], product_id: str, session_id: str
    ) -> tuple[int, bytes]:
        return await self._call(
            {
                "op": "transcribe",
                "productId": product_id,
                "sessionId": session_id,
                "language": body.get("language"),
                "audioDataUrl": body.get("audioDataUrl"),
            }
        )

    async def _call(self, payload: dict[str, Any]) -> tuple[int, bytes]:
        try:
            data = await self._binding.voice_stt(payload)
        except ServiceBindingResponseError:
            raise
        except Exception as exc:
            # A non-200 RPC envelope (auth, replay, storage) is the same
            # "binding refused the call" shape the routes already map to 503.
            raise ServiceBindingResponseError(
                f"voice stt rpc refused: {type(exc).__name__}"
            ) from exc
        status = data.get("status")
        text = data.get("body")
        if not isinstance(status, int) or isinstance(status, bool) or \
                not isinstance(text, str):
            raise ServiceBindingResponseError("voice stt rpc answered a bad envelope")
        return status, text.encode("utf-8")
