"""Web routes for Living Fiction Phase 2A — private reader and editorial review.

Security properties:
- Reader and admin sessions use separate cookie names and tables.
- Raw session tokens exist only in cookies; DB stores keyed HMAC digests.
- Invite codes are stored only as keyed HMAC digests.
- All HTML responses carry Cache-Control: no-store.
- iframe embedding is blocked (X-Frame-Options: DENY, CSP frame-ancestors 'none').
- Jinja2 autoescape is enabled; the ``|safe`` filter is never used.
- State-changing forms require CSRF verification.
- Reader IDs are never exposed in URLs.
- Pending branch bodies are blocked from reader view.
- Foreign reader branch access is blocked.
"""

from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from app import auth
from app import branch_repository as branch_repo
from app import canon_repository as canon_repo
from app import choice_repository as choice_repo
from app import choice_service
from app import episode_repository as ep_repo
from app import generation_run_repository as gr_repo
from app import reader_repository as reader_repo
from app import review_service
from app import world_repository as world_repo
from app.ai.mock import MockProvider
from app.config import canonicalize_origin, settings
from app.db import get_connection
from app.preview_data import (
    BRANCH_EPISODE_CONTENT,
    BRANCH_EPISODE_PLAN,
    WORLD_STATE,
)

# ── Constants ──────────────────────────────────────────────────────────────

READER_COOKIE = auth.READER_COOKIE_NAME
ADMIN_COOKIE = auth.ADMIN_COOKIE_NAME
READER_PREAUTH_COOKIE = auth.READER_PREAUTH_COOKIE_NAME
ADMIN_PREAUTH_COOKIE = auth.ADMIN_PREAUTH_COOKIE_NAME
WORLD_ID = WORLD_STATE.world_id
CANON_CHECKPOINT_ID = "checkpoint-canon-1"


# ── Security headers middleware ────────────────────────────────────────────


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Scope security headers by response kind.

    HTML documents receive the full defensive set: ``no-store, private`` plus
    ``Pragma: no-cache`` (legacy caches), ``X-Robots-Tag`` (never indexed),
    ``Referrer-Policy: no-referrer`` (never leak URLs/tokens via Referer),
    framing protection, ``nosniff``, and CSP. Non-HTML responses (the JSON
    health probe and static assets) receive only the minimal ``nosniff`` hint
    so immutable static files are not forced to ``no-store``.
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("text/html"):
            response.headers["Cache-Control"] = "no-store, private"
            response.headers["Pragma"] = "no-cache"
            response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self'; "
                "script-src 'self'; "
                "frame-ancestors 'none'; "
                "base-uri 'self'"
            )
        else:
            response.headers["X-Content-Type-Options"] = "nosniff"
        return response


# ── DB dependency ──────────────────────────────────────────────────────────


def get_db(request: Request) -> sqlite3.Connection:
    """Provide a per-request SQLite connection.

    Uses ``request.app.state.db_path`` (resolved once in the factory) so the
    per-request connection always targets the same database file the startup
    migrations ran against — never a divergent ``settings.database_path``.
    """
    conn = get_connection(request.app.state.db_path)
    try:
        yield conn
    finally:
        conn.close()


# ── Session dependencies ───────────────────────────────────────────────────


def _get_reader_session(
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any] | None:
    """Return reader session info or None.

    Cross-checks the reader is still active on every request: if the reader
    has been deactivated or deleted, the session is destroyed and ``None`` is
    returned so the caller redirects to ``/access`` instead of erroring.
    """
    token = request.cookies.get(READER_COOKIE)
    if not token:
        return None
    reader_id = auth.get_reader_session(conn, token, settings.session_hmac_key)
    if reader_id is None:
        return None
    if not reader_repo.is_reader_active(conn, reader_id):
        # Reader no longer active — invalidate this session and force re-login.
        auth.delete_reader_session(conn, token, settings.session_hmac_key)
        return None
    return {
        "reader_id": reader_id,
        "raw_token": token,
        "csrf_token": auth.compute_session_csrf(
            token, settings.session_hmac_key, auth.CSRF_READER_SESSION
        ),
    }


def _get_admin_session(
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any] | None:
    """Return admin session info or None."""
    token = request.cookies.get(ADMIN_COOKIE)
    if not token:
        return None
    if not auth.get_admin_session(conn, token, settings.session_hmac_key):
        return None
    return {
        "raw_token": token,
        "csrf_token": auth.compute_session_csrf(
            token, settings.session_hmac_key, auth.CSRF_ADMIN_SESSION
        ),
    }


# ── CSRF verification ──────────────────────────────────────────────────────


def _verify_reader_csrf(session: dict[str, Any], provided: str | None) -> None:
    """Verify a reader form's purpose-bound CSRF token. Raises 403 on mismatch."""
    if not auth.verify_session_csrf(
        session["raw_token"],
        settings.session_hmac_key,
        auth.CSRF_READER_SESSION,
        provided,
    ):
        raise HTTPException(status_code=403, detail="CSRF verification failed")


def _verify_admin_csrf(session: dict[str, Any], provided: str | None) -> None:
    """Verify an admin form's purpose-bound CSRF token. Raises 403 on mismatch."""
    if not auth.verify_session_csrf(
        session["raw_token"],
        settings.session_hmac_key,
        auth.CSRF_ADMIN_SESSION,
        provided,
    ):
        raise HTTPException(status_code=403, detail="CSRF verification failed")


# ── Origin / Host verification ─────────────────────────────────────────────


def _expected_origin(request: Request) -> str:
    """Derive the expected origin from the request's own scheme + Host header.

    Never trusts ``X-Forwarded-*`` headers: the scheme comes from the ASGI
    scope (the hop into this process) and the host from the raw ``Host`` header.
    """
    host = request.headers.get("host", "")
    return f"{request.url.scheme}://{host}"


def _verify_request_origin(request: Request) -> None:
    """Reject state-changing requests whose Origin/Host is not this app.

    Defense-in-depth against CSRF and DNS-rebinding, layered on top of the
    per-form CSRF token:

    * With an ``Origin`` header present, it must exactly match a configured
      allowed origin (``LF_ALLOWED_ORIGINS``) or — when none are configured —
      the origin derived from the request's own ``Host``.
    * With no ``Origin`` header (same-origin form posts, some privacy modes),
      the ``Host`` header must be present and, when origins are configured,
      match a configured host. Outside production with no configured origins the
      check is lenient (a present Host is accepted) so local development works
      without configuration; in production with no configured origins it fails
      closed rather than trusting an attacker-controllable Host.

    ``X-Forwarded-*`` headers are never consulted. Every failure raises one
    generic 403 so no condition is revealed.
    """
    configured = {
        canonical
        for canonical in (
            canonicalize_origin(o)
            for o in settings.allowed_origins.split(",")
            if o.strip()
        )
        if canonical
    }
    origin = request.headers.get("origin")
    if origin:
        canonical_origin = canonicalize_origin(origin)
        if configured:
            if canonical_origin is None or canonical_origin not in configured:
                raise HTTPException(
                    status_code=403, detail="Invalid request origin"
                )
            return
        if canonical_origin != canonicalize_origin(_expected_origin(request)):
            raise HTTPException(
                status_code=403, detail="Invalid request origin"
            )
        return
    # No Origin header — fall back to a Host check.
    host = request.headers.get("host")
    if not host:
        raise HTTPException(status_code=403, detail="Invalid request origin")
    if configured:
        allowed_hosts = {o.split("://", 1)[-1] for o in configured}
        if host.lower() not in allowed_hosts:
            raise HTTPException(
                status_code=403, detail="Invalid request origin"
            )
        return
    if settings.is_production:
        # No allowlist to verify against in production: fail closed.
        raise HTTPException(status_code=403, detail="Invalid request origin")
    # Lenient non-production: a present Host is accepted.


# ── Helper functions ───────────────────────────────────────────────────────


def _make_branch_provider(choice_id: str, choice_text: str = "", choice_comment: str | None = None) -> MockProvider:
    """Create a MockProvider that returns branch content with the given values."""
    branch_content = copy.deepcopy(BRANCH_EPISODE_CONTENT)
    branch_content["applied_reader_input"]["reader_choice_id"] = choice_id
    if choice_text:
        branch_content["applied_reader_input"]["choice_text"] = choice_text
    if choice_comment is not None:
        # Use the reader's comment as-is (markup safety validator
        # expects this to match the persisted choice comment).
        branch_content["applied_reader_input"]["comment"] = choice_comment
    return MockProvider(
        task_payloads={
            "episode_plan": BRANCH_EPISODE_PLAN,
            "episode_content": branch_content,
        }
    )


def _privacy_safe_reader_ref(reader_id: str) -> str:
    """Return a privacy-safe reader reference (short prefix only)."""
    return f"reader-{reader_id[:8]}"


def _render_prose(episode) -> list[dict[str, Any]]:
    """Parse episode prose_json into template-friendly beats."""
    prose = json.loads(episode.prose_json)
    scenes = json.loads(episode.scene_list_json)
    scene_titles = {s["scene_id"]: s["title"] for s in scenes}
    beats = []
    for beat in prose:
        scene_id = beat["scene_id"]
        beats.append({
            "scene_id": scene_id,
            "scene_title": scene_titles.get(scene_id, scene_id),
            "paragraphs": beat["paragraphs"],
        })
    return beats


def _get_choice_options(episode) -> list[str]:
    """Parse next_choice_options_json into a list of strings."""
    return json.loads(episode.next_choice_options_json)


def _get_applied_input(episode) -> dict[str, Any] | None:
    """Parse applied_reader_input_json."""
    if episode.applied_reader_input_json is None:
        return None
    return json.loads(episode.applied_reader_input_json)


def _provider_info(conn: sqlite3.Connection, episode) -> tuple[str, str]:
    """Get (provider, model) from the generation run."""
    if episode.generation_run_id:
        run = gr_repo.get_generation_run(conn, episode.generation_run_id)
        if run:
            return run.provider, run.advertised_model
    return "mock", "mock-living-fiction-v1"


def _continuity_status(conn: sqlite3.Connection, episode) -> str:
    """Get continuity validation status from the generation run."""
    if episode.generation_run_id:
        run = gr_repo.get_generation_run(conn, episode.generation_run_id)
        if run:
            if run.validation_status == "passed":
                return "passed"
            elif run.validation_status == "validation_failed":
                return "failed"
            return "not_attempted"
    return "not_attempted"


def _episode_number_label(episode_type: str, episode_number: int) -> str:
    """Return a display label like 'CANON 01' or 'PERSONAL BRANCH 01'."""
    prefix = "CANON" if episode_type == "canon" else "PERSONAL BRANCH"
    return f"{prefix} {episode_number:02d}"


def _ensure_secrets() -> None:
    """Fail closed if security secrets are not configured (or weak in prod)."""
    try:
        settings.validate_web_secrets()
        settings.validate_allowed_origins()
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc


# ── Route registration ─────────────────────────────────────────────────────


def register_web_routes(app: FastAPI) -> None:
    """Register all Phase 2A web routes on the given app."""
    _ensure_secrets()

    is_prod = settings.is_production

    # Static files and templates
    static_dir = str(Path(__file__).resolve().parent / "static")
    templates_dir = str(Path(__file__).resolve().parent / "templates")
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    templates = Jinja2Templates(directory=templates_dir)
    app.state.templates = templates
    app.state.is_production = is_prod

    # Security headers
    app.add_middleware(SecurityHeadersMiddleware)

    # ── Reader: access (invite) ──────────────────────────────────────────

    @app.get("/access", response_class=HTMLResponse)
    async def reader_access_get(
        request: Request,
        conn: sqlite3.Connection = Depends(get_db),
    ):
        # If already logged in, redirect to /read
        session = _get_reader_session(request, conn)
        if session is not None:
            return RedirectResponse(url="/read", status_code=status.HTTP_303_SEE_OTHER)
        csrf_token = auth.issue_preauth_csrf(
            settings.session_hmac_key, auth.CSRF_READER_PREAUTH
        )
        response = templates.TemplateResponse(
            request, "access.html",
            {"csrf_token": csrf_token, "error": None},
        )
        auth.set_preauth_cookie(
            response, READER_PREAUTH_COOKIE, csrf_token, is_prod,
            auth.READER_PREAUTH_COOKIE_PATH,
        )
        return response

    @app.post("/access", response_class=HTMLResponse)
    async def reader_access_post(
        request: Request,
        conn: sqlite3.Connection = Depends(get_db),
        invite_code: str = Form(...),
        csrf_token: str = Form(...),
    ):
        def _access_error() -> HTMLResponse:
            """Render the access form with a single privacy-safe error.

            Every failure path (bad CSRF, unknown/expired/revoked/unbound
            invite, inactive reader) surfaces the same message so no condition
            is revealed to an attacker.
            """
            csrf = auth.issue_preauth_csrf(
                settings.session_hmac_key, auth.CSRF_READER_PREAUTH
            )
            resp = templates.TemplateResponse(
                request, "access.html",
                {
                    "csrf_token": csrf,
                    "error": "초대 코드가 올바르지 않거나 이미 사용되었습니다.",
                },
            )
            auth.set_preauth_cookie(
                resp, READER_PREAUTH_COOKIE, csrf, is_prod,
                auth.READER_PREAUTH_COOKIE_PATH,
            )
            return resp

        # Reject cross-origin submissions before any credential check.
        _verify_request_origin(request)

        # Verify pre-auth CSRF (signed double-submit cookie)
        cookie_value = request.cookies.get(READER_PREAUTH_COOKIE)
        if not auth.verify_preauth_csrf(
            settings.session_hmac_key,
            auth.CSRF_READER_PREAUTH,
            cookie_value,
            csrf_token,
        ):
            raise HTTPException(status_code=403, detail="CSRF verification failed")

        # Verify invite code → bound reader (login never creates a reader)
        bound_reader_id = auth.verify_invite_code(
            conn, invite_code, settings.credential_hmac_key
        )
        if bound_reader_id is None:
            return _access_error()

        reader = reader_repo.get_reader(conn, bound_reader_id)
        if reader is None or not reader_repo.is_reader_active(conn, bound_reader_id):
            return _access_error()

        # Create session
        token = auth.create_reader_session(
            conn, reader.id, settings.session_hmac_key
        )

        response = RedirectResponse(url="/read", status_code=status.HTTP_303_SEE_OTHER)
        auth.set_reader_cookie(response, token, is_prod)
        auth.clear_preauth_cookie(
            response, READER_PREAUTH_COOKIE, auth.READER_PREAUTH_COOKIE_PATH
        )
        return response

    # ── Reader: canon read ───────────────────────────────────────────────

    @app.get("/read", response_class=HTMLResponse)
    async def canon_read_get(
        request: Request,
        conn: sqlite3.Connection = Depends(get_db),
    ):
        session = _get_reader_session(request, conn)
        if session is None:
            return RedirectResponse(url="/access", status_code=status.HTTP_303_SEE_OTHER)

        # Get latest published canon episode
        episode = ep_repo.get_latest_published_canon_episode(conn, WORLD_ID)
        if episode is None:
            raise HTTPException(status_code=404, detail="Canon episode not found")

        choice_options = _get_choice_options(episode)
        prose = _render_prose(episode)

        return templates.TemplateResponse(
            request, "canon_read.html",
            {
                "csrf_token": session["csrf_token"],
                "episode_type_label": "CANON",
                "episode_number_label": _episode_number_label(
                    episode.episode_type, episode.episode_number
                ),
                "episode_title": episode.title,
                "episode_synopsis": episode.synopsis,
                "prose": prose,
                "choice_options": choice_options,
                "error": None,
            },
        )

    @app.get("/read/canon/{episode_id}", response_class=HTMLResponse)
    async def canon_read_by_id(
        request: Request,
        episode_id: str,
        conn: sqlite3.Connection = Depends(get_db),
    ):
        session = _get_reader_session(request, conn)
        if session is None:
            return RedirectResponse(url="/access", status_code=status.HTTP_303_SEE_OTHER)

        episode = ep_repo.get_episode_by_id(conn, episode_id)
        if episode is None:
            raise HTTPException(status_code=404, detail="Episode not found")
        if episode.episode_type != "canon":
            raise HTTPException(status_code=404, detail="Episode not found")

        choice_options = _get_choice_options(episode)
        prose = _render_prose(episode)

        return templates.TemplateResponse(
            request, "canon_read.html",
            {
                "csrf_token": session["csrf_token"],
                "episode_type_label": "CANON",
                "episode_number_label": _episode_number_label(
                    episode.episode_type, episode.episode_number
                ),
                "episode_title": episode.title,
                "episode_synopsis": episode.synopsis,
                "prose": prose,
                "choice_options": choice_options,
                "error": None,
            },
        )

    # ── Reader: choice submission ──────────────────────────────────────────

    def _process_choice_submission(
        request: Request,
        conn: sqlite3.Connection,
        session: dict[str, Any],
        choice: str,
        comment: str | None,
    ):
        """Validate and apply the reader's canon choice via the choice service.

        Shared by the canonical ``POST /read/choice`` route and the
        compatibility ``POST /read`` route so both enforce the identical
        one-choice-per-canon, privacy-safe, generation-recoverable contract.
        """
        reader_id = session["reader_id"]

        episode = ep_repo.get_latest_published_canon_episode(conn, WORLD_ID)
        if episode is None:
            raise HTTPException(status_code=404, detail="Canon episode not found")

        choice_options = _get_choice_options(episode)

        try:
            choice_idx = int(choice)
        except (ValueError, TypeError):
            choice_idx = -1
        if choice_idx < 0 or choice_idx >= len(choice_options):
            prose = _render_prose(episode)
            return templates.TemplateResponse(
                request, "canon_read.html",
                {
                    "csrf_token": session["csrf_token"],
                    "episode_type_label": "CANON",
                    "episode_number_label": _episode_number_label(
                        episode.episode_type, episode.episode_number
                    ),
                    "episode_title": episode.title,
                    "episode_synopsis": episode.synopsis,
                    "prose": prose,
                    "choice_options": choice_options,
                    "error": "유효한 선택지를 선택해주세요.",
                },
            )

        choice_text = choice_options[choice_idx]

        submission = choice_service.submit_reader_choice(
            conn,
            world=WORLD_STATE,
            world_id=WORLD_ID,
            reader_id=reader_id,
            canon_episode_id=episode.id,
            canon_checkpoint_id=CANON_CHECKPOINT_ID,
            choice_text=choice_text,
            comment=comment,
            build_provider=_make_branch_provider,
        )

        if submission.status == "conflict":
            prose = _render_prose(episode)
            return templates.TemplateResponse(
                request, "canon_read.html",
                {
                    "csrf_token": session["csrf_token"],
                    "episode_type_label": "CANON",
                    "episode_number_label": _episode_number_label(
                        episode.episode_type, episode.episode_number
                    ),
                    "episode_title": episode.title,
                    "episode_synopsis": episode.synopsis,
                    "prose": prose,
                    "choice_options": choice_options,
                    "error": "이미 다른 선택을 제출하셨습니다.",
                },
                status_code=409,
            )
        if submission.status == "generation_failed":
            return RedirectResponse(
                url="/read/status?error=1",
                status_code=status.HTTP_303_SEE_OTHER,
            )
        # "submitted" and "already_completed" both land on the status screen.
        return RedirectResponse(
            url="/read/status",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    @app.post("/read/choice", response_class=HTMLResponse)
    async def choice_submit(
        request: Request,
        conn: sqlite3.Connection = Depends(get_db),
        choice: str = Form(...),
        comment: str | None = Form(None),
        csrf_token: str = Form(""),
    ):
        """Canonical reader choice submission (the form's actual target)."""
        session = _get_reader_session(request, conn)
        if session is None:
            return RedirectResponse(url="/access", status_code=status.HTTP_303_SEE_OTHER)

        _verify_request_origin(request)
        _verify_reader_csrf(session, csrf_token)

        return _process_choice_submission(request, conn, session, choice, comment)

    @app.post("/read", response_class=HTMLResponse, include_in_schema=False)
    async def choice_submit_compat(
        request: Request,
        conn: sqlite3.Connection = Depends(get_db),
        choice: str = Form(...),
        comment: str | None = Form(None),
        csrf_token: str = Form(""),
    ):
        """Compatibility alias for ``POST /read/choice`` (identical contract)."""
        session = _get_reader_session(request, conn)
        if session is None:
            return RedirectResponse(url="/access", status_code=status.HTTP_303_SEE_OTHER)

        _verify_request_origin(request)
        _verify_reader_csrf(session, csrf_token)

        return _process_choice_submission(request, conn, session, choice, comment)

    # ── Reader: pending status ───────────────────────────────────────────

    @app.get("/read/status", response_class=HTMLResponse)
    async def reader_status(
        request: Request,
        conn: sqlite3.Connection = Depends(get_db),
    ):
        session = _get_reader_session(request, conn)
        if session is None:
            return RedirectResponse(url="/access", status_code=status.HTTP_303_SEE_OTHER)

        reader_id = session["reader_id"]

        # Get reader's branches
        branches = branch_repo.get_branches_by_reader(conn, reader_id)
        has_published = False
        has_pending = False
        published_branch_id = None

        for branch in branches:
            ep = ep_repo.get_episode_by_id(conn, branch.branch_episode_id)
            if ep is not None:
                if ep.review_state == "published":
                    has_published = True
                    published_branch_id = branch.id
                elif ep.review_state == "pending_review":
                    has_pending = True

        return templates.TemplateResponse(
            request, "status.html",
            {
                "has_published": has_published,
                "has_pending": has_pending,
                "published_branch_id": published_branch_id,
            },
        )

    # ── Reader: published branch ─────────────────────────────────────────

    @app.get("/read/branch/{branch_id}", response_class=HTMLResponse)
    async def read_branch(
        request: Request,
        branch_id: str,
        conn: sqlite3.Connection = Depends(get_db),
    ):
        session = _get_reader_session(request, conn)
        if session is None:
            return RedirectResponse(url="/access", status_code=status.HTTP_303_SEE_OTHER)

        reader_id = session["reader_id"]

        branch = branch_repo.get_branch(conn, branch_id)
        if branch is None:
            raise HTTPException(status_code=404, detail="Branch not found")

        # Ownership check — reader ID not in URL, checked via session
        if branch.reader_id != reader_id:
            raise HTTPException(status_code=403, detail="Access denied")

        episode = ep_repo.get_episode_by_id(conn, branch.branch_episode_id)
        if episode is None:
            raise HTTPException(status_code=404, detail="Branch episode not found")

        # Only published branches are visible to readers. A reader's own
        # not-yet-published branch is reported as 404 (not 403) so its
        # existence and review state are never revealed.
        if episode.review_state != "published":
            raise HTTPException(status_code=404, detail="Branch not found")

        prose = _render_prose(episode)
        applied = _get_applied_input(episode)
        provider, model = _provider_info(conn, episode)

        # Get the canon episode for divergence point
        prior_ep = ep_repo.get_episode_by_id(conn, branch.prior_episode_id)
        divergence = f"{prior_ep.title}" if prior_ep else "Canon"

        return templates.TemplateResponse(
            request, "branch_read.html",
            {
                "episode_type_label": "PERSONAL BRANCH",
                "episode_number_label": _episode_number_label(
                    episode.episode_type, episode.episode_number
                ),
                "episode_title": episode.title,
                "episode_synopsis": episode.synopsis,
                "prose": prose,
                "applied_choice_text": applied["choice_text"] if applied else "",
                "divergence_point": divergence,
                "provider": provider,
                "model": model,
            },
        )

    # ── Reader: logout ───────────────────────────────────────────────────

    @app.post("/logout")
    async def reader_logout_post(
        request: Request,
        conn: sqlite3.Connection = Depends(get_db),
        csrf_token: str = Form(""),
    ):
        _verify_request_origin(request)
        session = _get_reader_session(request, conn)
        if session is not None:
            _verify_reader_csrf(session, csrf_token)
            auth.delete_reader_session(
                conn, session["raw_token"], settings.session_hmac_key
            )
        response = RedirectResponse(url="/access", status_code=status.HTTP_303_SEE_OTHER)
        auth.clear_reader_cookie(response)
        return response

    @app.get("/logout")
    async def reader_logout_get(
        request: Request,
        conn: sqlite3.Connection = Depends(get_db),
    ):
        # Non-mutating: GET never destroys a session (prevents CSRF via
        # links/images). Real logout happens on POST /logout.
        return RedirectResponse(url="/access", status_code=status.HTTP_303_SEE_OTHER)

    # ── Admin: access ────────────────────────────────────────────────────

    @app.get("/admin/access", response_class=HTMLResponse)
    async def admin_access_get(
        request: Request,
        conn: sqlite3.Connection = Depends(get_db),
    ):
        session = _get_admin_session(request, conn)
        if session is not None:
            return RedirectResponse(
                url="/admin/review", status_code=status.HTTP_303_SEE_OTHER
            )
        csrf_token = auth.issue_preauth_csrf(
            settings.session_hmac_key, auth.CSRF_ADMIN_PREAUTH
        )
        response = templates.TemplateResponse(
            request, "admin_access.html",
            {"csrf_token": csrf_token, "error": None},
        )
        auth.set_preauth_cookie(
            response, ADMIN_PREAUTH_COOKIE, csrf_token, is_prod,
            auth.ADMIN_PREAUTH_COOKIE_PATH,
        )
        return response

    @app.post("/admin/access", response_class=HTMLResponse)
    async def admin_access_post(
        request: Request,
        conn: sqlite3.Connection = Depends(get_db),
        admin_secret: str = Form(...),
        csrf_token: str = Form(...),
    ):
        def _admin_access_error() -> HTMLResponse:
            csrf = auth.issue_preauth_csrf(
                settings.session_hmac_key, auth.CSRF_ADMIN_PREAUTH
            )
            resp = templates.TemplateResponse(
                request, "admin_access.html",
                {
                    "csrf_token": csrf,
                    "error": "운영자 비밀키가 올바르지 않습니다.",
                },
            )
            auth.set_preauth_cookie(
                resp, ADMIN_PREAUTH_COOKIE, csrf, is_prod,
                auth.ADMIN_PREAUTH_COOKIE_PATH,
            )
            return resp

        # Reject cross-origin submissions before any credential check.
        _verify_request_origin(request)

        # Verify pre-auth CSRF (signed double-submit cookie)
        cookie_value = request.cookies.get(ADMIN_PREAUTH_COOKIE)
        if not auth.verify_preauth_csrf(
            settings.session_hmac_key,
            auth.CSRF_ADMIN_PREAUTH,
            cookie_value,
            csrf_token,
        ):
            raise HTTPException(status_code=403, detail="CSRF verification failed")

        # Verify admin secret (constant-time)
        if not auth._constant_time_compare(
            settings.admin_secret, admin_secret
        ):
            return _admin_access_error()

        # Create admin session
        token = auth.create_admin_session(conn, settings.session_hmac_key)

        response = RedirectResponse(
            url="/admin/review", status_code=status.HTTP_303_SEE_OTHER
        )
        auth.set_admin_cookie(response, token, is_prod)
        auth.clear_preauth_cookie(
            response, ADMIN_PREAUTH_COOKIE, auth.ADMIN_PREAUTH_COOKIE_PATH
        )
        return response

    # ── Admin: review queue ──────────────────────────────────────────────

    @app.get("/admin/review", response_class=HTMLResponse)
    async def admin_review_queue(
        request: Request,
        conn: sqlite3.Connection = Depends(get_db),
    ):
        session = _get_admin_session(request, conn)
        if session is None:
            return RedirectResponse(
                url="/admin/access", status_code=status.HTTP_303_SEE_OTHER
            )

        pending_episodes = ep_repo.get_pending_branch_episodes(conn)
        branches = []
        for ep in pending_episodes:
            branch = branch_repo.get_branch_by_episode(conn, ep.id)
            if branch is None:
                continue
            choice = choice_repo.get_reader_choice(conn, branch.reader_choice_id)
            canon_ep = ep_repo.get_episode_by_id(conn, branch.prior_episode_id)
            branches.append({
                "branch_id": branch.id,
                "branch_id_prefix": f"branch-{branch.id[:8]}",
                "reader_ref": _privacy_safe_reader_ref(branch.reader_id),
                "canon_episode": canon_ep.title if canon_ep else "?",
                "choice_text": choice.choice_text if choice else "?",
            })

        return templates.TemplateResponse(
            request, "review_queue.html",
            {
                "pending_count": len(branches),
                "branches": branches,
            },
        )

    # ── Admin: review detail ─────────────────────────────────────────────

    @app.get("/admin/review/{branch_id}", response_class=HTMLResponse)
    async def admin_review_detail(
        request: Request,
        branch_id: str,
        conn: sqlite3.Connection = Depends(get_db),
    ):
        session = _get_admin_session(request, conn)
        if session is None:
            return RedirectResponse(
                url="/admin/access", status_code=status.HTTP_303_SEE_OTHER
            )

        branch = branch_repo.get_branch(conn, branch_id)
        if branch is None:
            raise HTTPException(status_code=404, detail="Branch not found")

        episode = ep_repo.get_episode_by_id(conn, branch.branch_episode_id)
        if episode is None:
            raise HTTPException(status_code=404, detail="Branch episode not found")

        choice = choice_repo.get_reader_choice(conn, branch.reader_choice_id)
        canon_ep = ep_repo.get_episode_by_id(conn, branch.prior_episode_id)
        provider, model = _provider_info(conn, episode)
        continuity = _continuity_status(conn, episode)

        prose = _render_prose(episode)

        return templates.TemplateResponse(
            request, "review_detail.html",
            {
                "csrf_token": session["csrf_token"],
                "branch_id": branch.id,
                "branch_id_prefix": f"branch-{branch.id[:8]}",
                "reader_ref": _privacy_safe_reader_ref(branch.reader_id),
                "canon_episode": canon_ep.title if canon_ep else "?",
                "review_state_label": "PENDING REVIEW",
                "episode_type_label": "PERSONAL BRANCH",
                "episode_number_label": _episode_number_label(
                    episode.episode_type, episode.episode_number
                ),
                "branch_title": episode.title,
                "choice_text": choice.choice_text if choice else "?",
                "choice_comment": choice.comment if choice else None,
                "prose": prose,
                "provider": provider,
                "model": model,
                "continuity_status": continuity,
            },
        )

    # ── Admin: approve ───────────────────────────────────────────────────

    @app.post("/admin/review/{branch_id}/approve", response_class=HTMLResponse)
    async def admin_approve(
        request: Request,
        branch_id: str,
        conn: sqlite3.Connection = Depends(get_db),
        csrf_token: str = Form(""),
    ):
        session = _get_admin_session(request, conn)
        if session is None:
            return RedirectResponse(
                url="/admin/access", status_code=status.HTTP_303_SEE_OTHER
            )

        _verify_request_origin(request)
        _verify_admin_csrf(session, csrf_token)

        # Atomic publish + immutable audit trail. The service resolves the
        # episode from the branch and guards the personal_branch +
        # pending_review transition, so a stale, duplicate, mis-targeted, or
        # canon-targeting decision fails cleanly instead of double-applying.
        try:
            review_service.approve_branch(conn, branch_id=branch_id)
        except review_service.ReviewDecisionError:
            raise HTTPException(status_code=409, detail="Branch already decided")

        return RedirectResponse(
            url="/admin/review", status_code=status.HTTP_303_SEE_OTHER
        )

    # ── Admin: reject ────────────────────────────────────────────────────

    @app.post("/admin/review/{branch_id}/reject", response_class=HTMLResponse)
    async def admin_reject(
        request: Request,
        branch_id: str,
        conn: sqlite3.Connection = Depends(get_db),
        csrf_token: str = Form(""),
        rejection_reason: str = Form(...),
    ):
        session = _get_admin_session(request, conn)
        if session is None:
            return RedirectResponse(
                url="/admin/access", status_code=status.HTTP_303_SEE_OTHER
            )

        _verify_request_origin(request)
        _verify_admin_csrf(session, csrf_token)

        # Atomic reject + immutable audit trail. The service resolves the
        # episode from the branch, whitespace-normalizes the reason (rejecting
        # an empty one), and guards the personal_branch + pending_review
        # transition.
        try:
            review_service.reject_branch(
                conn,
                branch_id=branch_id,
                rejection_reason=rejection_reason,
            )
        except review_service.ReviewDecisionError:
            raise HTTPException(status_code=409, detail="Branch already decided")

        return RedirectResponse(
            url="/admin/review", status_code=status.HTTP_303_SEE_OTHER
        )

    # ── Admin: logout ────────────────────────────────────────────────────

    @app.post("/admin/logout")
    async def admin_logout_post(
        request: Request,
        conn: sqlite3.Connection = Depends(get_db),
        csrf_token: str = Form(""),
    ):
        _verify_request_origin(request)
        session = _get_admin_session(request, conn)
        if session is not None:
            _verify_admin_csrf(session, csrf_token)
            auth.delete_admin_session(
                conn, session["raw_token"], settings.session_hmac_key
            )
        response = RedirectResponse(
            url="/admin/access", status_code=status.HTTP_303_SEE_OTHER
        )
        auth.clear_admin_cookie(response)
        return response

    @app.get("/admin/logout")
    async def admin_logout_get(
        request: Request,
        conn: sqlite3.Connection = Depends(get_db),
    ):
        # Non-mutating: GET never destroys a session (prevents CSRF via
        # links/images). Real logout happens on POST /admin/logout.
        return RedirectResponse(
            url="/admin/access", status_code=status.HTTP_303_SEE_OTHER
        )
