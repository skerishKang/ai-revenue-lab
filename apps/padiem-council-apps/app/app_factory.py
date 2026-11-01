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

Caching (2026-11-01): the entry HTML is served with ``Cache-Control: no-cache``
so every load revalidates, and each process start rewrites the entry's local
asset references to ``?v=<content hash>`` (``app/asset_versions.py``). Hashed
asset URLs are therefore immutable and ``/static/*`` answers may be cached for
a year — a new deploy can no longer be masked by an old edge cache, which is
what served stale JS/CSS for up to four hours on 2026-11-01.
"""

from __future__ import annotations

from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.staticfiles import StaticFiles

from app.asset_versions import compute_versions, versioned_html

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"

INDEX_CACHE_CONTROL = "no-cache"
ASSET_CACHE_CONTROL = "public, max-age=31536000, immutable"


async def healthz(request):
    """Liveness only. Reused backend health is observed by the caller."""
    return JSONResponse({"ok": True, "app": "padiem-council-apps"})


class LongCacheStaticFiles(StaticFiles):
    """``/static/*`` files are addressed with content-hashed URLs, so a long,
    immutable cache is safe; a deploy changes the URL instead of the file."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = ASSET_CACHE_CONTROL
        return response


def create_app() -> Starlette:
    # 배포 때 자동 갱신: 프로세스 시작마다 정적 파일을 다시 해시해 진입 HTML의
    # 로컬 자산 참조에 ?v=<내용 해시>를 대입한다(별도 빌드 단계가 없어도 항상 새 값).
    versions = compute_versions(STATIC_DIR)
    entry_html = versioned_html(
        (STATIC_DIR / "index.html").read_text(encoding="utf-8"), versions)

    async def index(request):
        return Response(entry_html, media_type="text/html",
                        headers={"Cache-Control": INDEX_CACHE_CONTROL})

    routes = [
        Route("/healthz", healthz, methods=["GET"]),
        Route("/", index, methods=["GET"]),
    ]
    app = Starlette(routes=routes)
    app.mount("/static", LongCacheStaticFiles(directory=str(STATIC_DIR)), name="static")
    return app


build_app = create_app
