"""Routes for topics and topic feeds."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.db import get_connection
from app.factory import _build_services, _render_template
from app.services import TopicService

router = APIRouter()


def _get_topic_service(request: Request) -> TopicService:
    conn = get_connection(request.app.state.db_path)
    repos = _build_services(conn)
    return TopicService(
        repos["topic"], repos["rule"],
        request.app.state.llm_provider,
    )


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
        # Store the proposal in the session-like state via template context
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
):
    from app.domain.enums import (
        DefaultSort,
        DurationPreference,
        ShortsPreference,
    )
    from app.domain.models import QueryRuleProposal

    def _split(s: str) -> list[str]:
        return [x.strip() for x in s.split(",") if x.strip()]

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
    )

    conn = get_connection(request.app.state.db_path)
    try:
        repos = _build_services(conn)
        service = TopicService(
            repos["topic"], repos["rule"],
            request.app.state.llm_provider,
        )
        rule = service.accept_rule_draft(topic_id, proposal)
        return RedirectResponse(
            url=f"/topics/{topic_id}", status_code=303
        )
    finally:
        conn.close()


@router.get("/topics/{topic_id}", response_class=HTMLResponse)
def topic_feed(request: Request, topic_id: str):
    from app.services import DiscoveryService

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
        feed = discovery_service.get_topic_feed(topic_id)

        return _render_template(
            request, "topics/feed.html",
            {
                "topic": topic,
                "rules": rules,
                "feed": feed,
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
        return RedirectResponse(
            url=f"/topics/{topic_id}", status_code=303
        )
    finally:
        conn.close()
