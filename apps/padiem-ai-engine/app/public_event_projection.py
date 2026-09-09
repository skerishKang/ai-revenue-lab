"""The single Engine-safe public UI event projection for every Engine transport.

Core owns the public-safe UI event semantics (``padiem_ai_core.public_ui_events``):
the bounded nine-kind event vocabulary, identifier/summary validation, per-stream
contiguous sequencing, replay idempotency with ID-conflict rejection, monotonic
event time and the leakage-free ``safe_dict`` serialization. The Engine owns only
this bounded transport projection:

* it accepts Core authority values and reuses Core public serialization
  verbatim, so no second Engine UI-event model exists;
* it fails closed on any non-Core value, so private provider/runtime objects can
  never be serialized into public output;
* it keeps per-stream delivery order exactly as Core's contiguous sequence
  defines it; the Engine never re-orders, re-numbers or re-sequences events;
* it never assigns execution authority: an Engine transport consuming this
  projection cannot start, approve, resume or cancel execution by itself.

No wire path is added by this slice; transports adopt this projection in later
wiring. The projection is network-free and deterministic.
"""

from __future__ import annotations

from typing import Any

from padiem_ai_core import PublicUiEvent, PublicUiEventError, PublicUiEventStream

PUBLIC_EVENT_PROJECTION_CONTRACT_VERSION = "padiem-public-ui-event.v1"
PUBLIC_EVENT_STREAM_PROJECTION_CONTRACT_VERSION = "padiem-public-ui-event-stream.v1"


def project_public_ui_event(event: PublicUiEvent) -> dict[str, Any]:
    """Project one Core-owned public UI event for Engine transports.

    Fails closed on anything that is not a Core ``PublicUiEvent`` so private
    runtime objects can never reach a public surface through this chokepoint.
    The Core ``safe_dict()`` block is reused verbatim — the Engine does not
    fork, extend or re-shape it.
    """
    if not isinstance(event, PublicUiEvent):
        raise PublicUiEventError(
            "invalid_public_ui_event", "event must be a Core PublicUiEvent"
        )
    return event.safe_dict()


def project_public_ui_event_stream(
    stream: PublicUiEventStream,
    stream_id: str,
) -> dict[str, Any]:
    """Project one Core-owned public UI event stream for Engine transports.

    Fails closed on non-Core streams. Core owns sequencing and replay rules;
    this projection preserves Core's settled order and membership exactly and
    adds no authority flags beyond Core's own explicit denials.
    """
    if not isinstance(stream, PublicUiEventStream):
        raise PublicUiEventError(
            "invalid_public_ui_event_stream", "stream must be a Core PublicUiEventStream"
        )
    export = stream.safe_export(stream_id)
    export["engine_transport_projection"] = True
    export["grants_execution_authority"] = False
    return export


__all__ = [
    "PUBLIC_EVENT_PROJECTION_CONTRACT_VERSION",
    "PUBLIC_EVENT_STREAM_PROJECTION_CONTRACT_VERSION",
    "project_public_ui_event",
    "project_public_ui_event_stream",
]
