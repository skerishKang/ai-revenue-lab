"""Chat 음성 서버 중계 (#6828 원칙, 설계: docs/operations/CHAT_VOICE_RELAY_20261109.md).

브라우저는 같은 출처 ``/api/voice/relay`` WebSocket 만 안다. 이 모듈(컴2 Chat)이
세션 인증 후 음성 프로바이더와 서버측 WebSocket 을 열고 프레임을 양방향 중계한다.
프로바이더 주소·키·모델 이름은 서버에만 존재하며 브라우저 응답·정적 파일·네트워크
경로에 남기지 않는다. 프로바이더 WS 주소는 서버 설정(env)으로 주입한다(공개 코드에
실명 없음). 미설정 시 4503 으로 닫는다.

새 기능은 새 모듈 파일로(#7216). 이 모듈은 app.js 를 건드리지 않는다.
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Protocol

from .voice_stt_routes import RELAY_WS_PATH, _canonical_session
from .same_origin_guard import expected_browser_origins

MAX_CONCURRENT_RELAYS = 8
PROVIDER_ORIGIN_ENV = "PADIEM_VOICE_RELAY_WS_ORIGIN"

_active = 0
_lock = asyncio.Lock()


class RelayUnavailable(Exception):
    """The provider relay is not configured or cannot be reached."""


class ProviderLink(Protocol):
    async def send(self, data: str) -> None: ...
    async def recv(self) -> str | None: ...
    async def close(self) -> None: ...


class RelayConnector(Protocol):
    async def open(self, *, token: str, session: dict) -> ProviderLink: ...


class SettingsRelayConnector:
    """Default connector: provider WS origin from server env, never from code.

    The long-lived key stays in the private STT worker; the ephemeral token is
    minted server-side by the caller and passed in. Uses ``websockets`` when the
    runtime provides it; otherwise the relay reports unavailable.
    """

    def __init__(self, origin: str | None = None) -> None:
        self.origin = origin if origin is not None else os.environ.get(PROVIDER_ORIGIN_ENV, "")

    async def open(self, *, token: str, session: dict) -> ProviderLink:
        if not self.origin:
            raise RelayUnavailable("voice relay origin not configured")
        try:
            import websockets
        except ImportError as exc:  # pragma: no cover - runtime dependent
            raise RelayUnavailable("websocket client unavailable") from exc
        url = self.origin.rstrip("/") + "?access_token=" + token
        socket = await websockets.connect(url)

        class _Link:
            async def send(self, data: str) -> None:
                await socket.send(data)

            async def recv(self) -> str | None:
                try:
                    return await socket.recv()
                except Exception:
                    return None

            async def close(self) -> None:
                await socket.close()

        return _Link()


async def _mint_server_side(app: Any, session: Any) -> tuple[str, dict]:
    transport = getattr(app.state, "voice_stt_transport", None)
    if transport is None:
        raise RelayUnavailable("voice stt unavailable")
    auth_session = session.auth_session
    status, raw = await transport.live_token(
        body={"sessionId": str(auth_session.session_id)},
        product_id=auth_session.product_id,
        session_id=auth_session.session_id,
    )
    if status != 200:
        raise RelayUnavailable("voice live token denied")
    parsed = json.loads(raw.decode("utf-8"))
    token = parsed.get("token")
    live = parsed.get("session")
    if not isinstance(token, str) or not token.strip() or not isinstance(live, dict):
        raise RelayUnavailable("voice live token invalid")
    return token.strip(), live


async def voice_relay_ws(ws: Any, session_resolver=_canonical_session) -> None:
    """Same-origin WebSocket relay. ``ws`` is a Starlette WebSocket (or a test
    double). The resolver is injectable so unit tests need no live identity."""
    global _active
    # Same-origin handshake: the HTTP middleware never sees a websocket scope,
    # so the relay is its own origin authority. Only an exact reviewed public
    # origin may open the relay; anything else is refused before the accept.
    expected = expected_browser_origins(
        getattr(getattr(ws.app, "state", None), "settings", None)
    )
    origin = ""
    try:
        origin = (ws.headers.get("origin") or "").strip()
    except Exception:
        origin = ""
    if not expected or origin not in expected:
        await ws.close(code=1008)  # policy violation: cross-origin handshake
        return
    await ws.accept()
    try:
        session = await session_resolver(ws)
    except Exception:
        session = None
    if session is None:
        await ws.close(code=4401)  # sign-in required
        return

    async with _lock:
        if _active >= MAX_CONCURRENT_RELAYS:
            await ws.close(code=4429)
            return
        _active += 1
    link = None
    try:
        token, live = await _mint_server_side(ws.app, session)
        connector = getattr(ws.app.state, "voice_relay_connector", None) or SettingsRelayConnector()
        link = await connector.open(token=token, session=live)
        model = live.get("model")

        async def browser_to_provider() -> None:
            async for message in ws.iter_text():
                try:
                    data = json.loads(message)
                except (ValueError, TypeError):
                    continue
                if isinstance(data, dict) and isinstance(data.get("setup"), dict) and model:
                    data["setup"]["model"] = "models/" + model
                await link.send(json.dumps(data))

        async def provider_to_browser() -> None:
            while True:
                data = await link.recv()
                if data is None:
                    break
                await ws.send_text(data if isinstance(data, str) else data.decode("utf-8"))

        await asyncio.gather(browser_to_provider(), provider_to_browser())
    except RelayUnavailable:
        await ws.close(code=4503)
    except Exception:
        await ws.close(code=4500)
    finally:
        async with _lock:
            _active -= 1
        if link is not None:
            try:
                await link.close()
            except Exception:
                pass
        if getattr(ws, "closed", None) is None:
            try:
                await ws.close()
            except Exception:
                pass


__all__ = ["RELAY_WS_PATH", "voice_relay_ws", "SettingsRelayConnector",
           "RelayUnavailable", "MAX_CONCURRENT_RELAYS"]
