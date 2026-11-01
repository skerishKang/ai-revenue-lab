"""Owner-scoped disk storage for command output; offsets and lengths are bytes.

The preview uses Hermes Agent's 40/60 head/tail split.  Full output remains
available through an opaque handle.  There is no engine or PC integration here.

Module functions use PADIEM_OUTPUT_STORE_DIR and
PADIEM_OUTPUT_STORE_RETENTION_SECONDS; applications can instead construct an
OutputStore with an explicit directory and retention period.
"""
from __future__ import annotations

import codecs
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import time

_HANDLE = re.compile(r"^[0-9a-f]{64}$")
HEAD_RATIO = 0.4  # Hermes tools/tool_output_truncate.py, MIT.


def head_tail_split(budget: int) -> tuple[int, int]:
    """Character budgets using Hermes' 40% head / 60% tail split."""
    head = int(budget * HEAD_RATIO)
    return head, budget - head


class OutputStore:
    def __init__(self, directory, *, retention_seconds=7 * 24 * 60 * 60,
                 preview_chars=4096, clock=time.time):
        if retention_seconds <= 0 or preview_chars < 2:
            raise ValueError("retention must be positive and preview_chars at least 2")
        self.directory = Path(directory)
        self.retention_seconds = retention_seconds
        self.preview_chars = preview_chars
        self._clock = clock

    @staticmethod
    def _owner_key(owner):
        if not isinstance(owner, str) or not owner:
            raise ValueError("owner must be a non-empty string")
        return hashlib.sha256(owner.encode("utf-8")).hexdigest()

    def _path(self, handle, owner):
        if not isinstance(handle, str) or not _HANDLE.fullmatch(handle):
            raise ValueError("invalid output handle")
        return self.directory / self._owner_key(owner) / (handle + ".bin")

    def cleanup(self):
        """Remove expired output and metadata. Runs automatically on operations."""
        cutoff = self._clock() - self.retention_seconds
        if not self.directory.exists():
            return
        for path in self.directory.glob("*/*.bin"):
            try:
                if path.stat().st_mtime <= cutoff:
                    path.unlink()
                    path.with_suffix(".json").unlink(missing_ok=True)
            except FileNotFoundError:
                pass

    def store(self, output: bytes | str, *, owner: str, source: str):
        if not isinstance(output, (bytes, str)):
            raise TypeError("output must be bytes or str")
        if not isinstance(source, str) or not source:
            raise ValueError("source must be a non-empty string")
        self.cleanup()
        raw = output.encode("utf-8") if isinstance(output, str) else output
        handle = secrets.token_hex(32)
        path = self._path(handle, owner)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Exclusive creation prevents handle collisions from overwriting output.
        with path.open("xb") as stream:
            stream.write(raw)
        try:
            path.with_suffix(".json").write_text(
                json.dumps({"source": source}, ensure_ascii=False), encoding="utf-8"
            )
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        text = raw.decode("utf-8", errors="replace")
        truncated = len(text) > self.preview_chars
        if truncated:
            head_size, tail_size = head_tail_split(self.preview_chars)
            head, tail = text[:head_size], text[-tail_size:]
        else:
            head, tail = text, ""
        return {"handle": handle, "size": len(raw), "head": head,
                "tail": tail, "truncated": truncated}

    def read(self, handle: str, *, owner: str, offset: int, length: int) -> str:
        """Read [offset, offset+length), omitting partial UTF-8 boundary chars."""
        if type(offset) is not int or type(length) is not int or offset < 0 or length < 0:
            raise ValueError("offset and length must be non-negative integers")
        self.cleanup()
        with self._path(handle, owner).open("rb") as stream:
            stream.seek(offset)
            data = stream.read(length)
        # An offset in the middle of a character starts at the next character.
        while data and data[0] & 0xC0 == 0x80:
            data = data[1:]
        # final=False buffers a partial character at the end of this range.
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        return decoder.decode(data, final=False)

    def search(self, handle: str, *, owner: str, pattern: str, max_hits: int):
        """Literal UTF-8 search; offsets are the byte positions of matches."""
        if not isinstance(pattern, str) or not pattern:
            raise ValueError("pattern must be a non-empty string")
        if type(max_hits) is not int or max_hits < 0:
            raise ValueError("max_hits must be a non-negative integer")
        self.cleanup()
        hits = []
        needle = pattern.encode("utf-8")
        with self._path(handle, owner).open("rb") as stream:
            position = 0
            for line in stream:
                if len(hits) >= max_hits:
                    break
                start = 0
                while len(hits) < max_hits:
                    index = line.find(needle, start)
                    if index < 0:
                        break
                    hits.append({"offset": position + index,
                                 "line": line.decode("utf-8", errors="replace").rstrip("\r\n")})
                    start = index + len(needle)
                position += len(line)
        return hits


def _default_store():
    directory = os.environ.get("PADIEM_OUTPUT_STORE_DIR") or str(
        Path(tempfile.gettempdir()) / "padiem-output-store"
    )
    retention = float(os.environ.get("PADIEM_OUTPUT_STORE_RETENTION_SECONDS", 7 * 24 * 60 * 60))
    return OutputStore(directory, retention_seconds=retention)


def store(output: bytes | str, *, owner: str, source: str):
    return _default_store().store(output, owner=owner, source=source)


def read(handle: str, *, owner: str, offset: int, length: int) -> str:
    return _default_store().read(handle, owner=owner, offset=offset, length=length)


def search(handle: str, *, owner: str, pattern: str, max_hits: int):
    return _default_store().search(handle, owner=owner, pattern=pattern, max_hits=max_hits)
