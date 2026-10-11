"""Bounded canonical P01 Engine NDJSON stream parser (#3930).

Transport frames are untrusted. No browser/owner authority is granted here.
The caller must independently validate event/run correlation and project the
terminal orchestration result before any success is committed to a user.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from typing import Any

MAX_NDJSON_BYTES = 1_048_576
MAX_NDJSON_LINE_BYTES = 65_536
MAX_NDJSON_EVENT_COUNT = 128


class EngineNdjsonContractError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


async def decode_orchestration_ndjson(
    chunks: AsyncIterator[bytes],
) -> AsyncIterator[dict[str, Any]]:
    """Incrementally parse events and exactly one terminal, with hard ceilings.

    A non-terminal stream failure never becomes a successful completion.
    Consumers MUST discard partial events if a terminal error is raised.
    """
    buffered = bytearray()
    total = 0
    count = 0
    terminal = False
    terminal_result: dict[str, Any] | None = None
    try:
        async for chunk in chunks:
            if terminal:
                raise EngineNdjsonContractError("trailing_data_after_result")
            if not isinstance(chunk, bytes):
                raise EngineNdjsonContractError("invalid_stream_chunk")
            total += len(chunk)
            if total > MAX_NDJSON_BYTES:
                raise EngineNdjsonContractError("stream_too_large")
            buffered.extend(chunk)
            while True:
                newline = buffered.find(b"\n")
                if newline < 0:
                    if len(buffered) > MAX_NDJSON_LINE_BYTES:
                        raise EngineNdjsonContractError("line_too_large")
                    break
                if newline > MAX_NDJSON_LINE_BYTES:
                    raise EngineNdjsonContractError("line_too_large")
                raw = bytes(buffered[:newline])
                del buffered[:newline + 1]
                if not raw:
                    raise EngineNdjsonContractError("empty_stream_line")
                try:
                    record = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise EngineNdjsonContractError("invalid_stream_json") from exc
                if not isinstance(record, dict):
                    raise EngineNdjsonContractError("invalid_stream_record")
                if record.get("ok") is False:
                    raise EngineNdjsonContractError("engine_stream_error")
                if record.get("ok") is not True:
                    raise EngineNdjsonContractError("invalid_stream_record")
                if set(record) == {"ok", "event"} and isinstance(record["event"], Mapping):
                    count += 1
                    if count > MAX_NDJSON_EVENT_COUNT:
                        raise EngineNdjsonContractError("too_many_events")
                    yield {"event": dict(record["event"])}
                elif set(record) == {"ok", "orchestration"} and isinstance(record["orchestration"], Mapping):
                    if terminal or not count:
                        raise EngineNdjsonContractError("invalid_stream_terminal")
                    terminal = True
                    terminal_result = dict(record["orchestration"])
                    # Only expose a successful terminal AFTER physical EOF,
                    # so late error/trailing bytes can never follow success.
                    if buffered:
                        raise EngineNdjsonContractError("trailing_data_after_result")
                    break
                else:
                    raise EngineNdjsonContractError("invalid_stream_record")
        if buffered or not terminal or terminal_result is None:
            raise EngineNdjsonContractError("truncated_stream")
        yield {"orchestration": terminal_result}
    finally:
        close = getattr(chunks, "aclose", None)
        if callable(close):
            await close()
