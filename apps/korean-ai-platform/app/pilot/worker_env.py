"""Worker binding helpers shared by the Cloudflare entrypoint and tests."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


async def collect_env_overrides(
    env: Any,
    keys: Iterable[str],
) -> dict[str, str]:
    """Resolve configured Worker bindings without exposing secret metadata.

    Plain Worker vars are read directly. Secrets Store bindings expose an
    async ``get()`` method and must be resolved through it; stringifying the
    binding object would only capture runtime metadata, not the secret value.
    """
    overrides: dict[str, str] = {}
    for key in keys:
        value = getattr(env, key, None)
        if value is None:
            continue
        getter = getattr(value, "get", None)
        if callable(getter):
            value = await getter()
        if value is not None:
            overrides[key] = str(value)
    return overrides
