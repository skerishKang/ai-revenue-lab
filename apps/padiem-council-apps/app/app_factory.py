"""The council apps HTTP surface — static entry only, no second authority.

Routes:

``GET /healthz``   this app's own liveness probe
``GET /``          the independent council apps entry page
``GET /static/*``  the entry page's own assets

There is deliberately no ``/api/*`` route of this app's own. Generation,
storage and login stay with the existing PADIEM services: the browser calls
``POST /api/chat``, ``GET|POST /api/projects*`` and ``GET /api/auth/status``
on the same origin it is deployed into. This app never imports
``padiem_ai_core`` or any other repository package, so shipping it adds no
new execution boundary to the Chat/Claw worker.
"""

from __future__ import annotations

from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route
from starlette.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


async def healthz(request):
    """Liveness only. Reused backend health is observed by the caller."""
    return JSONResponse({"ok": True, "app": "padiem-council-apps"})


async def index(request):
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html")


def create_app() -> Starlette:
    routes = [
        Route("/healthz", healthz, methods=["GET"]),
        Route("/", index, methods=["GET"]),
    ]
    app = Starlette(routes=routes)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    return app


build_app = create_app
