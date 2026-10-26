"""Which B14 transport this Worker composes (#5784 PR-2).

The decision is one deployment variable and lives in one place so the product
callers can switch between the Cloudflare B14 Worker and the same application
running on COM2 without a second client, a second retry policy, or a second
caller proof.

Default is the Service Binding — byte-identical to what has always been composed
here. ``https`` signs the same exact body the same way and sends it to the origin
the switch validated, over whatever outbound transport the caller supplies. It
never falls back to the binding the deployment just turned off: a silently
reverted upstream would look like a working B14 while calling a different one.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from padiem_ai_core.b14_execution import (
    MAX_CONFIGURED_B14_RESPONSE_BYTES,
    B14_CHAT_COMPLETIONS_PATH,
)
from padiem_ai_core.b14_streaming import (
    B14_AUTO_STREAM_PREVIEW_PATH,
    B14_STREAM_PREVIEW_PATH,
)
from padiem_ai_core.b14_upstream import (
    MODE_HTTPS,
    B14HttpsPostJson,
    B14HttpsTransport,
)

from app.b14_service_proof import service_proof_headers

# The paths B14 may be asked for, whichever upstream answers. Model execution and
# the two bounded model-authority reads the product already performs.
B14_UPSTREAM_POST_PATHS = frozenset({
    B14_CHAT_COMPLETIONS_PATH,
    B14_STREAM_PREVIEW_PATH,
    B14_AUTO_STREAM_PREVIEW_PATH,
})
B14_UPSTREAM_READ_PATHS = frozenset({
    "/api/pilot/models",
    "/api/pilot/provider-readiness",
})
B14_UPSTREAM_PATHS = B14_UPSTREAM_POST_PATHS | B14_UPSTREAM_READ_PATHS


def request_correlation_headers() -> dict[str, str]:
    """Carry the active request id across the B14 hop, value-checked first."""
    try:
        from app.request_telemetry import current_request_id, is_safe_request_id

        value = current_request_id()
        return {"X-Request-Id": value} if is_safe_request_id(value) else {}
    except ImportError:
        return {}


def compose_b14_transports(
    *,
    upstream_mode: str,
    origin: str | None,
    binding: Any,
    proof_secret: str | None,
    service_binding_factory: Callable[[Any, str | None], Any],
    stream_binding_factory: Callable[[Any, str | None], Any],
    https_client_factory: Callable[[], Any],
    correlation_headers: Callable[[], Mapping[str, str]] | None = None,
) -> tuple[Any, Any]:
    """Return ``(completion_transport, stream_transport)`` for one upstream.

    The two binding transports are passed in as factories rather than imported:
    they own the Service Binding call shape and live with the Worker composition,
    while this decision stays importable and testable on either side.
    """
    if upstream_mode != MODE_HTTPS:
        if binding is None:
            return None, None
        return (
            service_binding_factory(binding, proof_secret),
            stream_binding_factory(binding, proof_secret),
        )
    if not origin:
        raise ValueError("b14_upstream_url_required")
    transport = B14HttpsTransport(
        origin=origin,
        allowed_paths=B14_UPSTREAM_PATHS,
        headers_for_body=lambda body: service_proof_headers(proof_secret, body),
        correlation_headers=correlation_headers,
        client=https_client_factory(),
    )
    return (
        B14HttpsPostJson(transport=transport, max_bytes=MAX_CONFIGURED_B14_RESPONSE_BYTES),
        transport,
    )
