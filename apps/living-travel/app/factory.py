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
            # Add no-store for authenticated/private pages
            if request.url.path.startswith(("/operator/", "/traveler/")):
                response.headers["Cache-Control"] = "no-store"
                response.headers["Pragma"] = "no-cache"
            return response

    app.add_middleware(SecurityHeadersMiddleware)

    # Register web routes
    from app.web.routes.operator import router as operator_router
    from app.web.routes.traveler import router as traveler_router
    app.include_router(operator_router)
    app.include_router(traveler_router)

    return app
