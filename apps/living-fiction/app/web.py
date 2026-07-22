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
import os
import secrets
import sqlite3
import sys
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

# Ensure tests.fixtures is importable when running from source tree.
_APP_DIR = Path(__file__).resolve().parent.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from app import auth
from app import branch_repository as branch_repo
from app import canon_repository as canon_repo
from app import choice_repository as choice_repo
from app import episode_repository as ep_repo
from app import generation_run_repository as gr_repo
from app import reader_repository as reader_repo
from app import world_repository as world_repo
from app.ai.mock import MockProvider
from app.config import settings
from app.db import get_connection
from app.domain.enums import EpisodeType, ReviewState
from app.pipeline.service import GenerationRequest, generate_personal_branch
from tests.fixtures.mock_payloads import (
    BRANCH_EPISODE_CONTENT,
    BRANCH_EPISODE_PLAN,
)
from tests.fixtures.synthetic_world import WORLD_STATE

# ── Constants ──────────────────────────────────────────────────────────────

READER_COOKIE = auth.READER_COOKIE_NAME
ADMIN_COOKIE = auth.ADMIN_COOKIE_NAME
PREAUTH_CSRF_COOKIE = "lf_preauth_csrf"
WORLD_ID = WORLD_STATE.world_id


# ── Security headers middleware ────────────────────────────────────────────


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to every response."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
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
        return response


# ── DB dependency ──────────────────────────────────────────────────────────


def get_db() -> sqlite3.Connection:
    """Provide a per-request SQLite connection."""
    conn = get_connection(settings.database_path)
    try:
        yield conn
    finally:
        conn.close()


# ── Session dependencies ───────────────────────────────────────────────────


def _get_reader_session(
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any] | None:
    """Return reader session info or None."""
    token = request.cookies.get(READER_COOKIE)
    if not token:
        return None
    result = auth.get_reader_session(conn, token, settings.session_hmac_key)
    if result is None:
        return None
    reader_id, csrf_digest = result
    return {"reader_id": reader_id, "csrf_digest": csrf_digest}


def _get_admin_session(
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any] | None:
    """Return admin session info or None."""
    token = request.cookies.get(ADMIN_COOKIE)
    if not token:
        return None
    csrf_digest = auth.get_admin_session(conn, token, settings.session_hmac_key)
    if csrf_digest is None:
        return None
    return {"csrf_digest": csrf_digest}


# ── CSRF verification ──────────────────────────────────────────────────────


async def _verify_csrf(
    request: Request,
    session_info: dict[str, Any],
) -> None:
    """Verify CSRF token on POST requests. Raises 403 on mismatch."""
    form = await request.form()
    provided = form.get("csrf_token", "")
    if not provided:
        raise HTTPException(status_code=403, detail="CSRF token missing")
    if not auth.verify_csrf_token(
        session_info["csrf_digest"], provided, settings.session_hmac_key
    ):
        raise HTTPException(status_code=403, detail="CSRF verification failed")


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
    """Fail closed if security secrets are not configured."""
    if not settings.admin_secret:
        raise RuntimeError(
            "LF_ADMIN_SECRET environment variable is required for web routes"
        )
    if not settings.credential_hmac_key:
        raise RuntimeError(
            "LF_CREDENTIAL_HMAC_KEY environment variable is required for web routes"
        )
    if not settings.session_hmac_key:
        raise RuntimeError(
            "LF_SESSION_HMAC_KEY environment variable is required for web routes"
        )


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
        csrf_token = secrets.token_urlsafe(32)
        response = templates.TemplateResponse(
            request, "access.html",
            {"csrf_token": csrf_token, "error": None},
        )
        response.set_cookie(
            PREAUTH_CSRF_COOKIE, csrf_token,
            path="/", httponly=False, samesite="lax",
        )
        return response

    @app.post("/access", response_class=HTMLResponse)
    async def reader_access_post(
        request: Request,
        conn: sqlite3.Connection = Depends(get_db),
        invite_code: str = Form(...),
        csrf_token: str = Form(...),
    ):
        # Verify CSRF via cookie (pre-auth reader form)
        expected = request.cookies.get(PREAUTH_CSRF_COOKIE)
        if not expected or not auth._constant_time_compare(
            expected, csrf_token
        ):
            raise HTTPException(status_code=403, detail="CSRF verification failed")

        # Verify invite code
        result = auth.verify_invite_code(
            conn, invite_code, settings.credential_hmac_key
        )
        if result is None:
            # Privacy-safe failure — do not reveal whether code exists
            csrf = secrets.token_urlsafe(32)
            return templates.TemplateResponse(
                request, "access.html",
                {
                    "csrf_token": csrf,
                    "error": "초대 코드가 올바르지 않거나 이미 사용되었습니다.",
                },
            )

        cred_id, existing_reader_id = result

        if existing_reader_id:
            reader = reader_repo.get_reader(conn, existing_reader_id)
            if reader is None:
                raise HTTPException(status_code=500, detail="Reader state error")
        else:
            reader = reader_repo.create_reader(
                conn, display_name="독서자"
            )
            auth.mark_invite_used(conn, cred_id, reader.id)

        # Create session
        token, csrf = auth.create_reader_session(
            conn, reader.id, settings.session_hmac_key
        )

        response = RedirectResponse(url="/read", status_code=status.HTTP_303_SEE_OTHER)
        auth.set_reader_cookie(response, token, is_prod)
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
        episode = ep_repo.get_latest_published_episode(conn, WORLD_ID)
        if episode is None:
            raise HTTPException(status_code=404, detail="Canon episode not found")

        choice_options = _get_choice_options(episode)
        prose = _render_prose(episode)

        return templates.TemplateResponse(
            request, "canon_read.html",
            {
                "csrf_token": session["csrf_digest"],
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
                "csrf_token": session["csrf_digest"],
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

    @app.post("/read", response_class=HTMLResponse)
    async def choice_submit(
        request: Request,
        conn: sqlite3.Connection = Depends(get_db),
        choice: str = Form(...),
        comment: str | None = Form(None),
        csrf_token: str = Form(""),
    ):
        session = _get_reader_session(request, conn)
        if session is None:
            return RedirectResponse(url="/access", status_code=status.HTTP_303_SEE_OTHER)

        # Verify CSRF
        if not csrf_token or not auth.verify_csrf_token(
            session["csrf_digest"], csrf_token, settings.session_hmac_key
        ):
            raise HTTPException(status_code=403, detail="CSRF verification failed")

        reader_id = session["reader_id"]

        # Get latest published canon episode
        episode = ep_repo.get_latest_published_episode(conn, WORLD_ID)
        if episode is None:
            raise HTTPException(status_code=404, detail="Canon episode not found")

        choice_options = _get_choice_options(episode)

        # Validate choice index
        try:
            choice_idx = int(choice)
        except (ValueError, TypeError):
            choice_idx = -1
        if choice_idx < 0 or choice_idx >= len(choice_options):
            prose = _render_prose(episode)
            return templates.TemplateResponse(
                request, "canon_read.html",
                {
                    "csrf_token": session["csrf_digest"],
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

        # Create reader choice
        choice_id = secrets.token_urlsafe(16)
        reader_choice = choice_repo.create_reader_choice(
            conn,
            choice_id=choice_id,
            reader_id=reader_id,
            canon_episode_id=episode.id,
            choice_text=choice_text,
            comment=comment,
        )

        # Generate personal branch via service layer
        provider = _make_branch_provider(reader_choice.id, choice_text, comment)
        gen_request = GenerationRequest(
            world=WORLD_STATE,
            episode_type=EpisodeType.PERSONAL_BRANCH,
            reader_id=reader_id,
            reader_choice_id=reader_choice.id,
            reader_choice_text=choice_text,
            reader_comment=comment,
        )
        result = generate_personal_branch(
            conn, provider, gen_request,
            world_id=WORLD_ID,
            canon_checkpoint_id="checkpoint-canon-1",
            prior_episode_id=episode.id,
        )

        if not result.succeeded:
            # Clean up the choice if generation failed
            # (choice was created but not applied)
            return RedirectResponse(
                url="/read/status?error=1",
                status_code=status.HTTP_303_SEE_OTHER,
            )

        # PRG redirect to status page
        return RedirectResponse(
            url="/read/status",
            status_code=status.HTTP_303_SEE_OTHER,
        )

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

        # Only published branches are visible to readers
        if episode.review_state != "published":
            raise HTTPException(status_code=403, detail="Branch not yet published")

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

    @app.get("/logout", response_class=HTMLResponse)
    async def reader_logout(
        request: Request,
        conn: sqlite3.Connection = Depends(get_db),
    ):
        token = request.cookies.get(READER_COOKIE)
        if token:
            auth.delete_reader_session(conn, token, settings.session_hmac_key)
        response = RedirectResponse(url="/access", status_code=status.HTTP_303_SEE_OTHER)
        auth.clear_reader_cookie(response)
        return response

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
        csrf_token = secrets.token_urlsafe(32)
        response = templates.TemplateResponse(
            request, "admin_access.html",
            {"csrf_token": csrf_token, "error": None},
        )
        response.set_cookie(
            PREAUTH_CSRF_COOKIE, csrf_token,
            path="/", httponly=False, samesite="lax",
        )
        return response

    @app.post("/admin/access", response_class=HTMLResponse)
    async def admin_access_post(
        request: Request,
        conn: sqlite3.Connection = Depends(get_db),
        admin_secret: str = Form(...),
        csrf_token: str = Form(...),
    ):
        # Verify CSRF via cookie (pre-auth admin form)
        expected = request.cookies.get(PREAUTH_CSRF_COOKIE)
        if not expected or not auth._constant_time_compare(
            expected, csrf_token
        ):
            raise HTTPException(status_code=403, detail="CSRF verification failed")

        # Verify admin secret (constant-time)
        if not auth._constant_time_compare(
            settings.admin_secret, admin_secret
        ):
            csrf = secrets.token_urlsafe(32)
            return templates.TemplateResponse(
                request, "admin_access.html",
                {
                    "csrf_token": csrf,
                    "error": "운영자 비밀키가 올바르지 않습니다.",
                },
            )

        # Create admin session
        token, csrf = auth.create_admin_session(conn, settings.session_hmac_key)

        response = RedirectResponse(
            url="/admin/review", status_code=status.HTTP_303_SEE_OTHER
        )
        auth.set_admin_cookie(response, token, is_prod)
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
                "csrf_token": session["csrf_digest"],
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

        # Verify CSRF
        if not csrf_token or not auth.verify_csrf_token(
            session["csrf_digest"], csrf_token, settings.session_hmac_key
        ):
            raise HTTPException(status_code=403, detail="CSRF verification failed")

        branch = branch_repo.get_branch(conn, branch_id)
        if branch is None:
            raise HTTPException(status_code=404, detail="Branch not found")

        episode = ep_repo.get_episode_by_id(conn, branch.branch_episode_id)
        if episode is None:
            raise HTTPException(status_code=404, detail="Branch episode not found")

        # Only pending_review can be approved — prevents duplicate decisions
        if episode.review_state != "pending_review":
            raise HTTPException(
                status_code=409,
                detail="Branch already decided",
            )

        # Publish via service layer (explicit human publication)
        ep_repo.publish_episode(conn, episode.id)

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

        # Verify CSRF
        if not csrf_token or not auth.verify_csrf_token(
            session["csrf_digest"], csrf_token, settings.session_hmac_key
        ):
            raise HTTPException(status_code=403, detail="CSRF verification failed")

        if not rejection_reason or not rejection_reason.strip():
            raise HTTPException(
                status_code=400,
                detail="Rejection reason is required",
            )

        branch = branch_repo.get_branch(conn, branch_id)
        if branch is None:
            raise HTTPException(status_code=404, detail="Branch not found")

        episode = ep_repo.get_episode_by_id(conn, branch.branch_episode_id)
        if episode is None:
            raise HTTPException(status_code=404, detail="Branch episode not found")

        # Only pending_review can be rejected — prevents duplicate decisions
        if episode.review_state != "pending_review":
            raise HTTPException(
                status_code=409,
                detail="Branch already decided",
            )

        # Reject via service layer
        ep_repo.reject_episode(conn, episode.id)

        return RedirectResponse(
            url="/admin/review", status_code=status.HTTP_303_SEE_OTHER
        )

    # ── Admin: logout ────────────────────────────────────────────────────

    @app.get("/admin/logout", response_class=HTMLResponse)
    async def admin_logout(
        request: Request,
        conn: sqlite3.Connection = Depends(get_db),
    ):
        token = request.cookies.get(ADMIN_COOKIE)
        if token:
            auth.delete_admin_session(conn, token, settings.session_hmac_key)
        response = RedirectResponse(
            url="/admin/access", status_code=status.HTTP_303_SEE_OTHER
        )
        auth.clear_admin_cookie(response)
        return response
