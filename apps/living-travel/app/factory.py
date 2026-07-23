"""Application factory for FastAPI."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import Settings
from app.db import apply_migrations


_STATIC_DIR = Path(__file__).resolve().parent / "web" / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    from app.config import get_settings

    if settings is None:
        settings = get_settings()

    app = FastAPI(title="Living Travel", version="0.2.0")

    apply_migrations(settings.database_url)

    # Serve local static assets (CSS only, no external CDN)
    if _STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # Add security headers to private pages
    from starlette.middleware.base import BaseHTTPMiddleware

    class SecurityHeadersMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            response = await call_next(request)
            # Add no-store for authenticated/private pages and the JSON API
            if request.url.path.startswith(("/operator/", "/traveler/", "/api/v1/")):
                response.headers["Cache-Control"] = "no-store"
                response.headers["Pragma"] = "no-cache"
            return response

    app.add_middleware(SecurityHeadersMiddleware)

    # Restrictive CORS for the JSON API (bearer-token only, no cookies).
    if settings.allowed_origin_list:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.allowed_origin_list,
            allow_methods=["GET", "POST", "PUT"],
            allow_headers=["Authorization", "Content-Type"],
            allow_credentials=False,
        )

    # Always register the authenticated JSON API.
    from app.api.router import build_api_router

    app.include_router(build_api_router())

    # Legacy server-rendered routes are kept for local/test (legacy auth mode)
    # but are NOT exposed in Firebase staging mode (fail-closed: no shared-secret
    # operator login or traveler session-token bypass on staging).
    if settings.auth_mode == "legacy":
        from app.web.routes.operator import router as operator_router
        from app.web.routes.traveler import router as traveler_router

        app.include_router(operator_router)
        app.include_router(traveler_router)

    return app
