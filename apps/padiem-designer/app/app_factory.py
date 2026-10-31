"""The Designer HTTP surface.

Routes:

``GET  /``                        the preview page
``GET  /static/*``                the preview's own assets
``GET  /api/designer/health``     what is actually configured and bound
``POST /api/designer/turn``       one Designer turn
``GET  /api/designer/sandbox``    the sandbox document for a generated UI
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles

from .config import Settings, load_settings
from .contracts import DesignerError, InteractionState, UiRequest, UiTurnResult
from .designer_prompt import SYSTEM_PROMPT
from .identity import SESSION_COOKIE, resolve_identity
from .model_route import ModelRoute, build_model_route, ui_from_tool_arguments
from .sandbox import build_sandbox_document

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"

#: How the interaction state is handed to the model on a follow-up turn.
_INTERACTION_HEADER = "PADIEM Designer — current UI state"


def _error_response(error: DesignerError) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": error.code, "message": error.message}},
        status_code=error.status_code,
    )


def _identity(request: Request, settings: Settings) -> Any:
    return resolve_identity(
        session_token=request.cookies.get(SESSION_COOKIE),
        settings=settings,
    )


def _user_prompt(request: UiRequest) -> tuple[str, dict[str, Any]]:
    """Build the user message, including the interaction state when there is one.

    The state the app sends is returned so a caller can see exactly what the
    model was told. That is what makes a follow-up turn verifiable.
    """

    prompt = request.prompt
    state = request.interaction_state
    context: dict[str, Any] = {}
    if not state.is_empty():
        context = {
            "values": dict(state.values),
            "prompt": state.prompt,
        }
        rendered = json.dumps(context, ensure_ascii=False, sort_keys=True)
        prompt = f"{prompt}\n\n{_INTERACTION_HEADER}\n{rendered}"
    return prompt, context


async def turn(request: Request) -> Response:
    """Run one Designer turn."""

    settings: Settings = request.app.state.settings
    route: ModelRoute = request.app.state.model_route
    identity = _identity(request, settings)

    try:
        payload = await request.json()
    except (json.JSONDecodeError, ValueError):
        return _error_response(DesignerError(400, "body_not_json", "The body must be JSON."))
    if not isinstance(payload, Mapping):
        return _error_response(DesignerError(400, "body_invalid", "The body must be an object."))

    try:
        ui_request = UiRequest.from_payload(payload)
    except DesignerError as error:
        return _error_response(error)

    if not route.supports_tool_calls:
        return _error_response(
            DesignerError(
                501,
                "model_route_lacks_tool_channel",
                f"The {route.kind} route cannot carry the generative-UI tool "
                "contract, so a Designer turn cannot run over it.",
            )
        )

    prompt, context = _user_prompt(ui_request)
    history = tuple(ui_request.history)

    try:
        from .model_route import ModelRequest

        turn_result = await route.generate(
            ModelRequest(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=prompt,
                history=history,
                interaction_state=context or None,
            )
        )
    except DesignerError as error:
        return _error_response(error)

    ui = None
    for call in turn_result.tool_calls:
        function = call.get("function") if isinstance(call, Mapping) else None
        name = function.get("name") if isinstance(function, Mapping) else None
        if name != "generateSandboxedUi":
            continue
        arguments = call.get("function", {}).get("arguments")
        from .model_route import _tool_arguments

        try:
            ui = ui_from_tool_arguments(_tool_arguments({"function": {"arguments": arguments}}))
        except DesignerError as error:
            return _error_response(error)
        break

    result = UiTurnResult(
        text=turn_result.text,
        ui=ui,
        model_id=turn_result.model_id,
        route_kind=turn_result.route_kind,
        tool_called=ui is not None,
        context_sent=context,
    )
    body = result.to_public_dict()
    body["ok"] = True
    body["identity"] = identity.to_public_dict()
    body["sandboxUrl"] = "/api/designer/sandbox"
    return JSONResponse(body)


async def sandbox(request: Request) -> Response:
    """Return the sandboxed document for a generated UI."""

    settings: Settings = request.app.state.settings
    _identity(request, settings)

    try:
        payload = await request.json()
    except (json.JSONDecodeError, ValueError):
        return _error_response(DesignerError(400, "body_not_json", "The body must be JSON."))
    if not isinstance(payload, Mapping):
        return _error_response(DesignerError(400, "body_invalid", "The body must be an object."))
    ui_payload = payload.get("ui")
    if not isinstance(ui_payload, Mapping):
        return _error_response(DesignerError(400, "ui_required", "The body must carry a ui object."))

    from .contracts import GeneratedUi

    ui = GeneratedUi(
        html=str(ui_payload.get("html") or ""),
        css=str(ui_payload.get("css") or ""),
        js_functions=str(ui_payload.get("jsFunctions") or ""),
        js_expressions=tuple(ui_payload.get("jsExpressions") or ()),
        title=str(ui_payload.get("title") or ""),
    )
    document = build_sandbox_document(ui)
    return Response(
        document,
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


async def health(request: Request) -> Response:
    """Report what is actually configured, bound and available."""

    settings: Settings = request.app.state.settings
    route: ModelRoute = request.app.state.model_route
    authority_available = request.app.state.session_authority_available
    return JSONResponse(
        {
            "ok": True,
            "app": "padiem-designer",
            "settings": settings.to_public_dict(),
            "route": {
                "kind": route.kind,
                "supportsToolCalls": route.supports_tool_calls,
            },
            "sessionAuthorityAvailable": authority_available,
            "upstream": {
                "project": "CopilotKit/OpenIntelligentUI",
                "commit": "8391a94c1c3939c679e40ddd7bfc08a9ef690e70",
                "license": "MIT",
            },
        }
    )


async def index(request: Request) -> Response:
    settings: Settings = request.app.state.settings
    _identity(request, settings)
    return FileResponse(STATIC_DIR / "index.html")


async def designer_error_handler(request: Request, exc: Exception) -> Response:
    """Turn one Designer refusal into its own HTTP answer.

    A refusal is a normal outcome here — a missing session, a route that
    cannot carry the tool contract, a body that is not JSON — so it is
    answered as a status code and a stable error code, never as a traceback.
    """

    if not isinstance(exc, DesignerError):  # pragma: no cover - defensive
        raise exc
    return _error_response(exc)


def build_app(
    *,
    settings: Settings | None = None,
    model_route: ModelRoute | None = None,
) -> Starlette:
    """Build the Designer application."""

    from .identity import load_session_authority

    effective = settings or load_settings()
    route = model_route or build_model_route(effective)

    routes = [
        Route("/", index),
        Route("/api/designer/health", health),
        Route("/api/designer/turn", turn, methods=["POST"]),
        Route("/api/designer/sandbox", sandbox, methods=["POST"]),
        Mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static"),
    ]
    app = Starlette(
        routes=routes,
        exception_handlers={DesignerError: designer_error_handler},
    )
    app.state.settings = effective
    app.state.model_route = route
    app.state.session_authority_available = load_session_authority() is not None
    return app


def build_app_factory() -> Callable[[], Starlette]:
    """A factory for the ASGI server."""

    return build_app
