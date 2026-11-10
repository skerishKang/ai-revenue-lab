"""#5034 Web Push HTTP adapter — one implementation for both runtimes.

The sender only ever performs one POST to a push endpoint, so this adapter
exposes exactly ``post()`` over an injected transport instead of handing the
sender a general-purpose client. The endpoint is a device capability URL: it is
never logged here, and only the status code is returned.

It used to live inside ``worker.py``, which left the CPython host with no way to
compose a push sender at all: the factory refuses to build one without a
transport, so the capability route reported ``not_configured`` even when the
deployment had VAPID material. Relocating it here keeps a single authority for
both the Worker and the host.
"""
from __future__ import annotations

from typing import Any

import httpx


class PushHttpTransport:
    """The bounded single-POST surface the Web Push sender needs.

    Exactly one POST, and never a redirect hop: the raw transport layer below
    this class does not follow redirects (the Worker's fetch adapter runs with
    ``redirect: "manual"``), so a push service's 3xx answer is surfaced as a
    status code instead of becoming a second outbound request to a
    subscription-controlled destination.
    """

    def __init__(self, transport: Any, *, timeout_seconds: float = 10.0) -> None:
        self._transport = transport
        self._timeout_seconds = timeout_seconds

    async def post(
        self, url: str, *, content: bytes, headers: dict[str, str]
    ) -> Any:
        request = httpx.Request(
            "POST",
            url,
            content=content,
            headers=headers,
            extensions={"timeout": {"read": self._timeout_seconds}},
        )
        response = await self._transport.handle_async_request(request)
        try:
            await response.aread()
        finally:
            await response.aclose()
        return response


def build_host_push_transport() -> Any:
    """Build the host push transport, or None when the runtime cannot fetch.

    A missing transport is reported honestly as ``not_configured`` by the
    sender; it never becomes a false delivery claim.
    """

    try:
        return PushHttpTransport(httpx.AsyncHTTPTransport())
    except Exception:
        return None
