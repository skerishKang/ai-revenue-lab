"""B7: the Core auto-stream client is retired with the b14/auto lane.

The staged auto preview endpoint and its Core client (``stream_auto``,
``auto_stream_preview_url``, ``B14_AUTO_STREAM_PREVIEW_PATH``) are gone. The
shared SSE transport behaviors the auto tests used to exercise (status
normalization, content-type and done-frame guards, cumulative byte cap,
timeout/transport error secrecy, consumer close) remain pinned on the manual
surface by ``test_b14_streaming.py``.
"""
from __future__ import annotations

import padiem_ai_core.b14_streaming as b14_streaming
from padiem_ai_core.b14_streaming import B14StreamingClient


def test_auto_stream_client_is_gone() -> None:
    assert not hasattr(B14StreamingClient, "stream_auto")
    assert not hasattr(B14StreamingClient, "auto_stream_preview_url")
    assert not hasattr(b14_streaming, "B14_AUTO_STREAM_PREVIEW_PATH")
    assert not hasattr(b14_streaming, "_validate_auto_stream_request")


def test_auto_stream_preview_path_is_not_a_known_b14_path() -> None:
    import padiem_ai_core.b14_execution as b14_execution

    known = {
        getattr(b14_execution, name)
        for name in dir(b14_execution)
        if name.startswith("B14_") and name.endswith("PATH")
    }
    assert "/api/pilot/v1/chat/completions/auto-stream-preview" not in known


def test_manual_stream_client_is_still_the_only_stream_surface() -> None:
    client_methods = B14StreamingClient.__dict__
    assert "stream" in client_methods
    assert "stream_auto" not in client_methods
