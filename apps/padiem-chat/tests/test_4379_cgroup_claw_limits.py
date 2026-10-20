"""#4379 C-group 3rd slice: the Claw request and context byte totals.

C6: the Claw request body, the browser request body and the owned prior
context carry no PADIEM byte total. The reader stays incremental, so the
platform's own request limit is the only ceiling.
"""
from __future__ import annotations


def test_the_claw_routes_declare_no_padiem_byte_total() -> None:
    from app.claw_general_routes import (
        MAX_CLAW_GENERAL_BODY_BYTES,
        P01_ENGINE_REQUEST_ENVELOPE_BYTES,
    )
    from app.request_contract import MAX_BROWSER_BODY_BYTES

    assert MAX_CLAW_GENERAL_BODY_BYTES is None
    assert P01_ENGINE_REQUEST_ENVELOPE_BYTES is None
    assert MAX_BROWSER_BODY_BYTES is None


def test_the_request_reader_stays_incremental_without_a_total() -> None:
    import asyncio

    from app.bounded_request_body import read_bounded_request_body

    class _Request:
        def __init__(self) -> None:
            self.headers = {}
            self.yield_count = 0

        def stream(self):
            async def _iter():
                for chunk in (b"ab", b"cd", b"ef"):
                    self.yield_count += 1
                    yield chunk

            return _iter()

    request = _Request()
    body = asyncio.run(read_bounded_request_body(request, max_bytes=None))

    assert body == b"abcdef"
    assert request.yield_count == 3
