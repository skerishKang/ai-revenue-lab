"""Routes for video actions and viewing state."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.db import get_connection
from app.domain.enums import ViewingState
from app.factory import _build_services, _render_template
from app.services import RecordService

router = APIRouter()


@router.get("/videos/{video_id}", response_class=HTMLResponse)
def video_detail(request: Request, video_id: str):
    conn = get_connection(request.app.state.db_path)
    try:
        repos = _build_services(conn)
        video_repo = repos["video"]
        topic_video_repo = repos["topic_video"]
        record_repo = repos["record"]

        video = video_repo.get(video_id)
        if video is None:
            return _render_template(
                request, "error.html",
                {"message": "Video not found", "code": 404},
                status_code=404,
            )

        # Find topic-video associations for this video
        # (a video can belong to multiple topics)
        tv_rows = conn.execute(
            "SELECT * FROM topic_videos WHERE video_id = ?", (video_id,)
        ).fetchall()
        topic_videos = [
            topic_video_repo.get(row["id"]) for row in tv_rows
        ]

        # Get records for each topic-video
        records = []
        for tv in topic_videos:
            if tv is not None:
                record = record_repo.get_by_topic_video(tv.id)
                records.append((tv, record))

        return _render_template(
            request, "videos/detail.html",
            {
                "video": video,
                "topic_videos": topic_videos,
                "records": records,
            },
        )
    finally:
        conn.close()


@router.post("/topic-videos/{tv_id}/open")
def open_topic_video(request: Request, tv_id: str):
    """Record that the YouTube link was opened (not completed).

    Only affects the specific topic-video association, not all topics
    that share the same video.
    """
    conn = get_connection(request.app.state.db_path)
    try:
        repos = _build_services(conn)
        topic_video_repo = repos["topic_video"]
        record_repo = repos["record"]

        tv = topic_video_repo.get(tv_id)
        if tv is None:
            return _render_template(
                request, "error.html",
                {"message": "Topic-video not found", "code": 404},
                status_code=404,
            )

        # Get or create record for this specific topic-video
        record = record_repo.get_by_topic_video(tv_id)
        if record is None:
            record = record_repo.create(tv_id)

        # The outbound-link action only records `opened`. It must never
        # downgrade an explicit user state: saved / in_progress / completed /
        # revisit / irrelevant are user-controlled (product contract), so a
        # simple link click promotes only an `unseen` record to `opened` and
        # leaves every other state untouched. `opened` stays `opened`.
        if record.viewing_state == ViewingState.UNSEEN:
            record_repo.update(
                record.id,
                viewing_state=ViewingState.OPENED.value,
            )

        # Redirect to the canonical YouTube URL (new tab via frontend)
        video = repos["video"].get(tv.video_id)
        if video:
            return RedirectResponse(
                url=video.canonical_url, status_code=303
            )
        return RedirectResponse(
            url=f"/topic-videos/{tv_id}", status_code=303
        )
    finally:
        conn.close()


@router.post("/topic-videos/{tv_id}/records")
def create_record_for_topic_video(request: Request, tv_id: str):
    """Get-or-create a record for a topic-video and redirect to it."""
    conn = get_connection(request.app.state.db_path)
    try:
        repos = _build_services(conn)
        record_service = RecordService(
            repos["topic_video"], repos["record"],
            repos["proposal"],
            request.app.state.llm_provider,
        )

        tv = repos["topic_video"].get(tv_id)
        if tv is None:
            return _render_template(
                request, "error.html",
                {"message": "Topic-video not found", "code": 404},
                status_code=404,
            )

        record = record_service.get_or_create_record(tv_id)
        return RedirectResponse(
            url=f"/records/{record.id}", status_code=303
        )
    finally:
        conn.close()


@router.post("/topic-videos/{tv_id}/state")
def update_state(
    request: Request,
    tv_id: str,
    state: str = Form(...),
    return_state: str = Form("all"),
):
    """Update the viewing state of a topic-video pair."""
    # Validate the state against the ViewingState enum before touching the DB.
    # An invalid value is a handled 400 and leaves the database unchanged.
    if state not in {s.value for s in ViewingState}:
        return _render_template(
            request, "error.html",
            {"message": f"Invalid viewing state: {state}", "code": 400},
            status_code=400,
        )

    conn = get_connection(request.app.state.db_path)
    try:
        repos = _build_services(conn)
        record_repo = repos["record"]

        tv = repos["topic_video"].get(tv_id)
        if tv is None:
            return _render_template(
                request, "error.html",
                {"message": "Topic-video not found", "code": 404},
                status_code=404,
            )

        record = record_repo.get_by_topic_video(tv_id)
        if record is None:
            record = record_repo.create(tv_id)

        record_repo.update(record.id, viewing_state=state)

        # Redirect back to the topic feed, preserving the active filter.
        topic_id = conn.execute(
            "SELECT topic_id FROM topic_videos WHERE id = ?", (tv_id,)
        ).fetchone()["topic_id"]

        return RedirectResponse(
            url=f"/topics/{topic_id}?state={return_state}", status_code=303
        )
    finally:
        conn.close()
