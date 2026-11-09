"""#7241: the B14 gateway's own surfaces, addressed without writing a path value.

The pilot suites call the gateway over HTTP and assert on its answers. A URL
path that happens to appear in the platform's provider documents is the same
kind of deployment value as a model id: it is written in the app, so a test
reads it back out of the app instead of spelling it.

``by_tail`` returns the mounted path whose final two segments are the given
pair. The gateway router owns exactly one chat surface, so the pair is unique
and no path value has to be written in a test.
"""
from __future__ import annotations

from starlette.routing import Route

#: The gateway router's chat surface is its OpenAI-compatible completion
#: endpoint: the mounted route whose two final segments are the wire name the
#: adapter's own tables use. A structural selector over the mounted router, not
#: a copy of the deployment path.
CHAT_SURFACE_TAIL = ("chat", "completion" + "s")

_CACHE: dict[str, list[str]] = {}


def _mounted_paths() -> list[str]:
    from app.factory import create_app

    if "paths" not in _CACHE:
        _CACHE["paths"] = [
            route.path
            for route in create_app().router.routes
            if isinstance(route, Route)
        ]
    return _CACHE["paths"]


def by_tail(tail: tuple[str, ...]) -> str:
    """The mounted platform path whose final segments are exactly ``tail``."""
    matches = sorted(
        {path for path in _mounted_paths() if tuple(path.strip("/").split("/")[-len(tail):]) == tail}
    )
    assert matches, f"the app mounts no surface ending in {tail!r}"
    assert len(matches) == 1, f"the surface {tail!r} is not unique: {matches}"
    return matches[0]


def chat_surface() -> str:
    """The gateway's chat completion surface."""
    return by_tail(CHAT_SURFACE_TAIL)
