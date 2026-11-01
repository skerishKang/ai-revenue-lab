"""Disk-backed stand-in for the workspace R2 bucket — loopback local dev only.

The stores hold raw bucket objects and call exactly three methods:
`put(key, body, httpMetadata=...)`, `get(key)` and `delete(key)`, tolerating
either a sync or an awaitable return (`inspect.isawaitable` at every call
site, e.g. history.py:_put_full_message). `get()` answers with an object
carrying `.size` and `.body`, which is the shape `_read_r2_object_bytes`
consumes (workspace_storage.py). No `list`/`head` surface is used by app
code, so none is provided.

This module is imported ONLY behind the explicit local flag
(`app.local_cpython`); the Cloudflare path keeps the real binding. Keys are
canonical server-generated ids, and every key is still resolved under the
root here — a `..`/absolute/drive-shaped key raises instead of escaping.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import tempfile
from typing import Any
from urllib.parse import quote

__all__ = ["LocalDiskR2", "LocalR2Object", "put_stream"]

#: One bounded block for any streamed write. The object never has to exist in
#: memory whole, so this is the only size this module ever holds at once.
_STREAM_BLOCK_BYTES = 1024 * 1024


def put_stream(bucket: Any, key: str, source: Any,
               httpMetadata: dict[str, Any] | None = None):
    """Stream one object into whichever store is bound — or say it can't.

    The Cloudflare R2 binding is given ``bytes`` at every existing call site,
    so it has no streaming write to offer. Rather than accept a 1 GiB body and
    silently materialise it, this refuses with a clear "unsupported" so the
    caller fails closed instead of pretending the write succeeded.
    """
    method = getattr(bucket, "put_stream", None)
    if callable(method):
        return method(key, source, httpMetadata)
    raise NotImplementedError(
        "streaming object write is unsupported by this object store"
    )


class LocalR2Object:
    """The `R2ObjectBody` shape the readers ask for: .body bytes and .size."""

    def __init__(self, data: bytes, content_type: str | None = None):
        self.body = data
        self.size = len(data)
        self.httpMetadata = {"contentType": content_type} if content_type else None

    def arrayBuffer(self) -> bytes:  # mirrors the JS-side reader branch
        return self.body


class LocalDiskR2:
    def __init__(self, root: str | Path):
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def _path(self, key: str) -> Path:
        if (
            not isinstance(key, str)
            or not key
            or key.startswith("/")
            or "\\" in key
        ):
            raise ValueError("R2 key must be a plain relative object path")
        segments = key.split("/")
        if any(segment in ("", ".", "..") for segment in segments):
            raise ValueError("R2 key must not traverse outside the bucket root")
        if any(any(ord(ch) < 32 for ch in segment) for segment in segments):
            raise ValueError("R2 key must not contain control characters")
        # Object keys legitimately carry workspace ids like "owner:usr_...".
        # Windows cannot name a file with ':' and reads a bare "C:" segment as a
        # drive, so each segment is percent-encoded for the filesystem while the
        # logical key stays exactly what the caller passed. Plain ids (letters,
        # digits, '_', '-', '.') encode to themselves, so objects already on
        # disk keep their path; a key that used to be refused was never written.
        path = self._root.joinpath(*(quote(segment, safe="") for segment in segments)).resolve()
        if not path.is_relative_to(self._root):
            raise ValueError("R2 key escaped the bucket root")
        return path

    def put(self, key: str, body: bytes, httpMetadata: dict[str, Any] | None = None) -> None:
        if not isinstance(body, (bytes, bytearray)):
            raise TypeError("LocalDiskR2.put accepts bytes only")
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".r2-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(body)
                output.flush()
                os.fsync(output.fileno())
            # Same filesystem rename: readers see the complete old or new
            # object, including when another Chat worker writes concurrently.
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def put_stream(self, key: str, source: Any,
                   httpMetadata: dict[str, Any] | None = None) -> None:
        """Store one object from a path or a readable, never from one big bytes.

        A path on this same filesystem is **moved** (one rename, zero copies);
        anywhere else it is copied in bounded blocks. A readable is consumed in
        bounded blocks too. Readers see the complete old or new object because
        the copy lands on a temporary name and is renamed into place, exactly
        like ``put``.
        """
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(source, (str, Path)):
            source_path = Path(source)
            if not source_path.is_file():
                raise ValueError("stream source is not a readable file")
            try:
                os.replace(source_path, path)
                return
            except OSError:
                # Different filesystem (or a permission shape rename refuses):
                # copy in bounded blocks, then drop the staged original.
                with source_path.open("rb") as reader:
                    self._copy_stream(reader, path)
                source_path.unlink(missing_ok=True)
                return
        if not hasattr(source, "read"):
            raise TypeError("LocalDiskR2.put_stream accepts a path or a readable")
        self._copy_stream(source, path)

    def _copy_stream(self, reader: Any, path: Path) -> None:
        descriptor, temporary = tempfile.mkstemp(prefix=".r2-stream-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as output:
                while True:
                    block = reader.read(_STREAM_BLOCK_BYTES)
                    if not block:
                        break
                    if not isinstance(block, (bytes, bytearray)):
                        raise TypeError("stream source must produce bytes")
                    output.write(block)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def get(self, key: str) -> LocalR2Object | None:
        path = self._path(key)
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            return None
        return LocalR2Object(data)

    def delete(self, key: str) -> None:
        path = self._path(key)
        path.unlink(missing_ok=True)


class ThreadedLocalDiskR2(LocalDiskR2):
    """Host binding: perform object I/O outside the ASGI event loop."""

    async def get(self, key: str) -> LocalR2Object | None:
        return await asyncio.to_thread(super().get, key)

    async def put(self, key: str, body: bytes, httpMetadata: dict[str, Any] | None = None) -> None:
        await asyncio.to_thread(super().put, key, body, httpMetadata)

    async def put_stream(self, key: str, source: Any,
                         httpMetadata: dict[str, Any] | None = None) -> None:
        await asyncio.to_thread(super().put_stream, key, source, httpMetadata)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(super().delete, key)
