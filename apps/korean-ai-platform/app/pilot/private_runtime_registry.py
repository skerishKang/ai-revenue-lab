"""Load the B14 canonical registry from a private, immutable R2 object.

The trusted deployment pins a 64-character SHA-256 of the exact JSON bytes.
No public asset, caller URL, unpinned object key or credential may select
a registry. A failed private load blocks the request rather than silently
using the legacy boot snapshot.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from typing import Any

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_BYTES = 128 * 1024
_lock = asyncio.Lock()
_loaded_sha256: str | None = None


class PrivateRegistryUnavailable(RuntimeError):
    """A private registry was selected but was not verifiably installed."""


async def ensure_private_registry(env: Any) -> None:
    """Load once per isolate, atomically after validating a pinned exact body.

    Production must configure both B14_PRIVATE_REGISTRY_SHA256 and the
    PADIEM_B14_PRIVATE_CONFIG R2 bucket binding. Local tests without either
    remain on the existing fixture registry until explicit cutover.
    """
    global _loaded_sha256
    expected = getattr(env, "B14_PRIVATE_REGISTRY_SHA256", None)
    if expected is None or not str(expected).strip():
        return
    expected = str(expected).strip()
    if not _SHA256_RE.fullmatch(expected):
        raise PrivateRegistryUnavailable("invalid private registry pin")
    if _loaded_sha256 == expected:
        return
    async with _lock:
        if _loaded_sha256 == expected:
            return
        bucket = getattr(env, "PADIEM_B14_PRIVATE_CONFIG", None)
        getter = getattr(bucket, "get", None)
        if not callable(getter):
            raise PrivateRegistryUnavailable("private registry binding unavailable")
        try:
            item = await getter("registry/" + expected + ".json")
            if item is None:
                raise PrivateRegistryUnavailable("private registry object missing")
            payload = await item.text()
            if not isinstance(payload, str):
                raise PrivateRegistryUnavailable("private registry is not UTF-8 text")
            raw = payload.encode("utf-8")
            if len(raw) > _MAX_BYTES or hashlib.sha256(raw).hexdigest() != expected:
                raise PrivateRegistryUnavailable("private registry integrity failure")
            data = json.loads(payload)
            from .model_registry_file import validate_registry, install_models
            validated = validate_registry(data)
            # Only mutate catalog after the complete private body is validated.
            install_models(validated)
        except PrivateRegistryUnavailable:
            raise
        except Exception as exc:
            raise PrivateRegistryUnavailable("private registry load failed") from exc
        _loaded_sha256 = expected
