"""Application factory for the Korean AI API Provider Phase 0 Demo (Starlette)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route
from starlette.staticfiles import StaticFiles

from app.config import settings

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def _build_root_static_routes() -> list[Route]:
    """Build root-level routes for static files (Worker [assets] compat)."""
    _ROOT_STATIC = {
        "app.css": "text/css",
        "workspace-console.css": "text/css",
        "workspace-console-responsive.css": "text/css",
        "app.js": "application/javascript",
        "workspace.js": "application/javascript",
        "start.js": "application/javascript",
        "start.css": "text/css",
    }

    def _make_handler(filename: str, media_type: str):
        async def _handler(request: Request):
            file_path = _STATIC_DIR / filename
            if file_path.is_file():
                return HTMLResponse(
                    content=file_path.read_bytes(), media_type=media_type
                )
            return HTMLResponse("Not Found", status_code=404)

        return _handler

    routes: list[Route] = []
    for name, mime in _ROOT_STATIC.items():
        routes.append(Route(f"/{name}", endpoint=_make_handler(name, mime), methods=["GET"]))
    return routes


def _build_jinja_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    json_kwargs = dict(env.policies.get("json.dumps_kwargs", {}))
    json_kwargs["ensure_ascii"] = False
    env.policies["json.dumps_kwargs"] = json_kwargs

    def _krw(value: float | int) -> str:
        return f"{value:,.1f}원" if value < 100 else f"{value:,.0f}원"

    env.filters["krw"] = _krw
    env.globals["demo_mode"] = settings.demo_mode

    from app.pilot.config import pilot_settings
    env.globals["pilot_configured"] = pilot_settings.configured

    from app.pilot.openrouter_config import openrouter_config
    env.globals["b14_provider_mode"] = openrouter_config.provider_mode
    env.globals["b14_has_key"] = openrouter_config.has_key
    env.globals["b14_site_name"] = openrouter_config.site_name

    return env


async def _health(request: Request) -> JSONResponse:
    return JSONResponse({
        "status": "ok",
        "app": "korean-ai-platform",
        "phase": "api-provider-phase0",
        "demo_mode": settings.demo_mode,
    })


def create_app() -> Starlette:
    jinja_env = _build_jinja_env()

    routes: list[Any] = [
        Route("/health", endpoint=_health, methods=["GET"]),
    ]

    app = Starlette(routes=routes, on_startup=None)
    app.state.jinja_env = jinja_env

    if _STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
        # Also serve static files at root for Worker [assets] compatibility
        _static_routes = _build_root_static_routes()
        for sr in _static_routes:
            app.router.routes.append(sr)

    from app import routes as phase0_routes
    app.router.routes.extend(phase0_routes.router.routes)

    # Phase 1: BYOK Gateway Pilot. The multimodal contract is installed as a
    # narrow wrapper around the existing deep validator so all text-only
    # requests continue to use the original validation path unchanged.
    from app.pilot import gateway as pilot_gateway
    from app.pilot.multimodal_contract import install_gateway_multimodal_contract

    install_gateway_multimodal_contract(pilot_gateway)
    pilot_api_router = pilot_gateway.router

    # Slice 12: preview-only manual-route streaming surface. Import after the
    # multimodal contract installation so its reuse of the canonical validator
    # observes the same installed validation authority as the main gateway.
    from app.pilot.stream_gateway import router as pilot_stream_router

    # Slice 16: staged Router-owned b14/auto streaming preview. Keep this
    # separate from both the manual preview and canonical endpoint promotion.
    from app.pilot.auto_stream_gateway import router as pilot_auto_stream_router

    from app.pilot.ui import router as pilot_ui_router
    from starlette.routing import Route as StarletteRoute

    for route in [
        *pilot_api_router.routes,
        *pilot_stream_router.routes,
        *pilot_auto_stream_router.routes,
    ]:
        new_route = StarletteRoute(
            path="/api/pilot" + route.path,
            endpoint=route.endpoint,
            methods=list(route.methods) if route.methods else ["GET"],
        )
        app.router.routes.append(new_route)
    for route in pilot_ui_router.routes:
        app.router.routes.append(route)

    # Phase 3: Korean session workspace
    from app.pilot.workspace import router as workspace_router
    app.router.routes.extend(workspace_router.routes)

    return app


def render_template(
    request: Request,
    template_name: str,
    context: dict[str, Any] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    jinja_env = request.app.state.jinja_env
    template = jinja_env.get_template(template_name)
    ctx = dict(context or {})
    ctx["request"] = request
    return HTMLResponse(template.render(ctx), status_code=status_code)
