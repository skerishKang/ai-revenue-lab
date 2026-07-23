"""Routes for topics and topic feeds."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.db import get_connection
from app.factory import _build_services, _locale_prefix, _render_template
from app.services import DiscoveryService, TopicService

router = APIRouter()

# Valid feed state filters
FEED_STATES = [
    "all", "unseen", "opened", "saved", "in_progress",
    "completed", "revisit", "irrelevant",
]


@router.get("/topics", response_class=HTMLResponse)
def list_topics(request: Request):
    conn = get_connection(request.app.state.db_path)
    try:
        repos = _build_services(conn)
        service = TopicService(
            repos["topic"], repos["rule"],
            request.app.state.llm_provider,
        )
        topics = service.list_topics()
        return _render_template(request, "topics/list.html", {"topics": topics})
    finally:
        conn.close()


@router.get("/topics/new", response_class=HTMLResponse)
def new_topic(request: Request):
    return _render_template(request, "topics/new.html")


@router.post("/topics")
def create_topic(
    request: Request,
    name: str = Form(...),
    intent: str = Form(...),
):
    conn = get_connection(request.app.state.db_path)
    try:
        repos = _build_services(conn)
        service = TopicService(
            repos["topic"], repos["rule"],
            request.app.state.llm_provider,
        )
        topic, proposal = service.create_topic(name=name, intent=intent)
        return _render_template(
            request,
            "topics/review_rule.html",
            {
                "topic": topic,
                "proposal": proposal,
            },
        )
    finally:
        conn.close()


@router.post("/topics/{topic_id}/accept-rule")
def accept_rule(
    request: Request,
    topic_id: str,
    primary_query: str = Form(...),
    related_queries: str = Form(""),
    required_terms: str = Form(""),
    excluded_terms: str = Form(""),
    preferred_languages: str = Form(""),
    included_channels: str = Form(""),
    excluded_channels: str = Form(""),
    duration_preference: str = Form("any"),
    shorts_preference: str = Form("include"),
    default_sort: str = Form("newest"),
    date_window_start: str = Form(""),
    date_window_end: str = Form(""),
):
    from app.domain.enums import (
        DefaultSort,
        DurationPreference,
        ShortsPreference,
    )
    from app.domain.models import QueryRuleProposal

    def _split(s: str) -> list[str]:
        return [x.strip() for x in s.split(",") if x.strip()]

    # Validate date window
    from datetime import datetime
    dws = date_window_start.strip() if date_window_start else None
    dwe = date_window_end.strip() if date_window_end else None
    if dws:
        try:
            datetime.strptime(dws, "%Y-%m-%d")
        except ValueError:
            return _render_template(
                request, "error.html",
                {"message": "Invalid date_window_start format (use YYYY-MM-DD)", "code": 400},
                status_code=400,
            )
    if dwe:
        try:
            datetime.strptime(dwe, "%Y-%m-%d")
        except ValueError:
            return _render_template(
                request, "error.html",
                {"message": "Invalid date_window_end format (use YYYY-MM-DD)", "code": 400},
                status_code=400,
            )
    if dws and dwe:
        if datetime.strptime(dws, "%Y-%m-%d") > datetime.strptime(dwe, "%Y-%m-%d"):
            return _render_template(
                request, "error.html",
                {"message": "date_window_start must not be after date_window_end", "code": 400},
                status_code=400,
            )

    proposal = QueryRuleProposal(
        primary_query=primary_query,
        related_queries=_split(related_queries),
        required_terms=_split(required_terms),
        excluded_terms=_split(excluded_terms),
        preferred_languages=_split(preferred_languages),
        included_channels=_split(included_channels),
        excluded_channels=_split(excluded_channels),
        duration_preference=DurationPreference(duration_preference),
        shorts_preference=ShortsPreference(shorts_preference),
        default_sort=DefaultSort(default_sort),
        date_window_start=dws,
        date_window_end=dwe,
    )

    conn = get_connection(request.app.state.db_path)
    try:
        repos = _build_services(conn)
        service = TopicService(
            repos["topic"], repos["rule"],
            request.app.state.llm_provider,
        )
        rule = service.accept_rule_draft(topic_id, proposal)
        lp = _locale_prefix(request)
        return RedirectResponse(
            url=f"{lp}/topics/{topic_id}", status_code=303
        )
    finally:
        conn.close()


@router.get("/topics/{topic_id}", response_class=HTMLResponse)
def topic_feed(
    request: Request,
    topic_id: str,
    state: str = "all",
    sync_failed: str = "",
):
    conn = get_connection(request.app.state.db_path)
    try:
        repos = _build_services(conn)
        topic_service = TopicService(
            repos["topic"], repos["rule"],
            request.app.state.llm_provider,
        )
        discovery_service = DiscoveryService(
            repos["topic"], repos["rule"], repos["video"],
            repos["topic_video"], repos["sync"], repos["quota"],
            request.app.state.discovery_provider,
            request.app.state.llm_provider,
        )

        topic = topic_service.get_topic(topic_id)
        if topic is None:
            return _render_template(
                request, "error.html",
                {"message": "Topic not found", "code": 404},
                status_code=404,
            )

        rules = topic_service.get_active_rule(topic_id)

        # Normalize state filter
        if state not in FEED_STATES:
            state = "all"

        state_filter = None if state == "all" else state
        feed = discovery_service.get_topic_feed(
            topic_id, state_filter=state_filter
        )

        return _render_template(
            request, "topics/feed.html",
            {
                "topic": topic,
                "rules": rules,
                "feed": feed,
                "current_state_filter": state,
                "feed_states": FEED_STATES,
                "sync_failed": bool(sync_failed),
            },
        )
    finally:
        conn.close()


@router.post("/topics/{topic_id}/sync")
def sync_topic(request: Request, topic_id: str):
    from app.services import DiscoveryService

    conn = get_connection(request.app.state.db_path)
    try:
        repos = _build_services(conn)
        discovery_service = DiscoveryService(
            repos["topic"], repos["rule"], repos["video"],
            repos["topic_video"], repos["sync"], repos["quota"],
            request.app.state.discovery_provider,
            request.app.state.llm_provider,
        )
        run, feed = discovery_service.sync_topic(topic_id)
        lp = _locale_prefix(request)
        return RedirectResponse(
            url=f"{lp}/topics/{topic_id}", status_code=303
        )
    except Exception:
        # Provider unavailable or sync failure: the SyncRun is already marked
        # failed by sync_topic's except block and existing feed data is
        # preserved. Redirect to the feed with a user-facing flag so the UI
        # can show a clear provider-unavailable message. No internal
        # exception text, path, or secret is exposed.
        lp = _locale_prefix(request)
        return RedirectResponse(
            url=f"{lp}/topics/{topic_id}?sync_failed=1", status_code=303
        )
    finally:
        conn.close()
