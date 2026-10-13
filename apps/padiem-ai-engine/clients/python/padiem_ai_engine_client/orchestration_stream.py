"""Bounded canonical P01 Engine NDJSON stream parser (#3930).

Transport frames are untrusted. No browser/owner authority is granted here.
The caller must independently validate event/run correlation and project the
terminal orchestration result before any success is committed to a user.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from typing import Any

# Bound the one completed structured result in Worker memory; never cap
# the total number of bytes in an otherwise valid incremental event stream.
MAX_NDJSON_TERMINAL_LINE_BYTES = 8 * 1024 * 1024
MAX_NDJSON_LINE_BYTES = 65_536
MAX_NDJSON_EVENT_COUNT = 128


class EngineNdjsonContractError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


async def decode_orchestration_ndjson(
    chunks: AsyncIterator[bytes],
) -> AsyncIterator[dict[str, Any]]:
    """Incrementally parse events and exactly one EOF-verified result.

    Each intermediate event remains bounded at 64KiB and count <=128. The
    canonical Engine terminal result is a single JSON object, thus it gets
    a finite 8MiB per-record memory budget (not a cumulative model output
    ceiling). A run that yields many valid event lines must not fail because
    their aggregate raw byte count crosses the old 1MiB pilot limit.
    """
    buffered = bytearray()
    count = 0
    terminal = False
    terminal_result: dict[str, Any] | None = None
    # Canonical Engine serializer emits keys in this fixed order. Only this
    # trusted result prefix can opt into the larger *single-record* budget.
    # Unknown or reordered oversized records fail closed at 64KiB.
    canonical_result_prefix = b'{"ok":true,"orchestration":'
    try:
        async for chunk in chunks:
            if terminal:
                raise EngineNdjsonContractError("trailing_data_after_result")
            if not isinstance(chunk, bytes):
                raise EngineNdjsonContractError("invalid_stream_chunk")
            # Always process in small slices. Do not materialize an attacker
            # supplied oversized chunk in the unfinished-line bytearray.
            for start in range(0, len(chunk), MAX_NDJSON_LINE_BYTES):
                buffered.extend(chunk[start:start + MAX_NDJSON_LINE_BYTES])
                while True:
                    newline = buffered.find(b"\n")
                    max_line = (
                        MAX_NDJSON_TERMINAL_LINE_BYTES
                        if buffered.startswith(canonical_result_prefix)
                        else MAX_NDJSON_LINE_BYTES
                    )
                    if newline < 0:
                        if len(buffered) > max_line:
                            raise EngineNdjsonContractError("line_too_large")
                        break
                    if newline > max_line:
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
                        # A late error or trailing bytes must never follow
                        # a publicly delivered success.
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
