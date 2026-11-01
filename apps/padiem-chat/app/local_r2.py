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

__all__ = ["LocalDiskR2", "LocalR2Object"]


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
            or ":" in key
        ):
            raise ValueError("R2 key must be a plain relative object path")
        segments = key.split("/")
        if any(segment in ("", ".", "..") for segment in segments):
            raise ValueError("R2 key must not traverse outside the bucket root")
        if any(any(ord(ch) < 32 for ch in segment) for segment in segments):
            raise ValueError("R2 key must not contain control characters")
        path = self._root.joinpath(*segments).resolve()
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

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(super().delete, key)
