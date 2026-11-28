from __future__ import annotations

from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse
from starlette.staticfiles import StaticFiles

from .config import LOCAL_DEV_LOOPBACK_HOSTS, Settings
from .file_lane import BINARY_KINDS, KINDS
from .usage_gate import UsageGate

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


# 2026-11-01: the old councillor profile wrapper is retired. Its one product
# surface is the independent council app; the alias answers here so both the
# Worker and the COM2 host redirect, and no second profile screen is served.
COUNCILLOR_REDIRECT_PATH = "/councillor/"


async def councillor_redirect(request: Request) -> RedirectResponse:
    return RedirectResponse("/apps/council/", status_code=302)


async def health(request: Request) -> JSONResponse:
    """The public health answer carries no configuration detail.

    Readiness booleans describe how this deployment is composed (what is
    bound, which modes are on) and are none of an anonymous caller's
    business. The public body is the bounded liveness answer; the detail view
    stays available to the machine's own view — direct loopback callers
    (the local QA and monitor lanes), the in-process test harness and a
    signed-in admin — and never to a request forwarded through the public
    edge.
    """
    if not await _health_detail_allowed(request):
        return JSONResponse({"status": "ok", "app": "padiem-chat"})
    return JSONResponse(_health_detail(request))


async def _health_detail_allowed(request: Request) -> bool:
    # The machine's own view: a direct loopback caller (the local QA and
    # monitor lanes) or the in-process test harness, neither carrying a
    # forwarding header. Anything forwarded through the public edge — and any
    # other direct caller — only passes as a signed-in admin.
    forwarded = bool(request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip"))
    client_host = (request.client.host if request.client else "") or ""
    if not forwarded and (
        client_host in LOCAL_DEV_LOOPBACK_HOSTS or client_host == "testclient"
    ):
        return True
    from .auth_routes import current_user_id

    uid = current_user_id(request)
    if not uid:
        return False
    store = getattr(request.app.state, "b66_member_admin_store", None)
    if store is None:
        return False
    try:
        return bool(await store.is_google_admin(uid))
    except Exception:
        return False


def _health_detail(request: Request) -> dict:
    settings: Settings = request.app.state.settings
    usage_gate: UsageGate = request.app.state.usage_gate
    # Config validation already requires keys for live web providers. This is
    # configuration readiness, not proof of upstream provider availability.
    web_ready = settings.web_provider in {"mock", "firecrawl", "daum", "tinyfish", "tinyfish_daum"}
    research_ready = settings.runtime_mode == "b14" and settings.web_provider in {"mock", "firecrawl"}
    abuse_ready = usage_gate.ready
    return {
        "status": "ok", "app": "padiem-chat", "runtime": settings.runtime_mode,
        "b14_configured": bool(settings.b14_base_url),
        "web_tools_ready": web_ready,
        "deep_research_ready": research_ready,
        "image_attachment_ready": True,
        "text_document_attachment_ready": True,
        "binary_document_attachment_ready": bool(request.app.state.file_lane_client.ready and BINARY_KINDS <= KINDS.keys()),
        "auth_configured": settings.auth_mode != "off" or getattr(request.app.state, "shared_login_flow", None) is not None,
        "history_store_bound": request.app.state.history_store is not None,
        "projects_code_ready": True,
        "project_files_code_ready": True,
        "project_file_store_bound": request.app.state.project_file_store is not None,
        "saved_outputs_code_ready": True,
        "saved_output_store_bound": request.app.state.saved_output_store is not None,
        "quota_store_bound": usage_gate.quota_store_bound,
        "live_abuse_gate_ready": abuse_ready,
        "live_enabled": settings.runtime_mode == "b14" and abuse_ready,
        "canonical_identity_bound": request.app.state.control_plane_identity_authority is not None,
        "identity_shadow_bound": request.app.state.identity_shadow_store is not None,
        # #1975: per-request telemetry is wired at composition time, so this
        # reports whether the deployed build actually carries the channel. It is
        # a boolean only — no counters, no per-isolate numbers.
        "request_telemetry_enabled": getattr(
            request.app.state, "request_telemetry_enabled", False
        ),
        "voice_stt_available": getattr(request.app.state, "voice_stt_transport", None) is not None,
    }


class CachedStaticFiles(StaticFiles):
    """Static answers carry a short fresh window plus background revalidation.

    The static URLs are not content-versioned, so a long immutable lifetime
    would pin a stale UI after a deploy. 300s keeps a session's repeat
    navigations off the network (the ~150-request first-load spike) while
    (no stale-while-revalidate: unversioned URLs must not outlive a deploy past 5 minutes) refreshes
    it in the background. HTML is never cached: it must pick up a new deploy.
    """

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        content_type = response.headers.get("content-type", "")
        if response.status_code != 200:
            return response
        if "text/html" in content_type:
            # HTML must pick up a new deploy on the next navigation. Say
            # no-cache explicitly: leaving the header empty lets mobile
            # browsers fall back to heuristic caching, and index.html is the
            # file that pins which asset version a tab runs.
            response.headers["cache-control"] = "no-cache"
        else:
            response.headers["cache-control"] = (
                "private, max-age=300"
            )
        return response
