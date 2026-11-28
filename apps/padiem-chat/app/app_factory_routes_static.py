from __future__ import annotations

from starlette.routing import Mount, Route, WebSocketRoute

from .app_factory_health_static import (
    STATIC_DIR,
    COUNCILLOR_REDIRECT_PATH,
    councillor_redirect,
    health,
    _health_detail_allowed,
    _health_detail,
    CachedStaticFiles,
)

def register_static_routes(routes: list) -> None:
    routes.extend([
        Route(COUNCILLOR_REDIRECT_PATH, councillor_redirect, methods=["GET"]),
        # Static answers carry a short fresh window plus background
        # revalidation: the static URLs are not content-versioned, so a long
        # immutable lifetime would pin a stale UI after a deploy. 300s keeps a
        # session's repeat navigations off the network (the ~150-request
        # first-load spike) while stale-while-revalidate serves the last good
        # copy instantly and refreshes it in the background. HTML is never
        # cached: it must pick up a new deploy.
        Mount("/", app=CachedStaticFiles(directory=str(STATIC_DIR), html=True), name="static"),
    ])
