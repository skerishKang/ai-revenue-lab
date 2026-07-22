"""Routes for video actions and viewing state."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.db import get_connection
from app.factory import _build_services, _render_template
from app.services import DiscoveryService, RecordService

router = APIRouter()


@router.get("/videos/{video_id}", response_class=HTMLResponse)
def video_detail(request: Request, video_id: str):
    conn = get_connection(request.app.state.db_path)
    try:
        repos = _build_services(conn)
        video_repo = repos["video"]
        topic_video_repo = repos["topic_video"]
        record_repo = repos["record"]
        proposal_repo = repos["proposal"]

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
            topic_video_repo._row_to_tv(row) for row in tv_rows
        ]

        # Get records for each topic-video
        records = []
        for tv in topic_videos:
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


@router.post("/videos/{video_id}/open")
def open_video(request: Request, video_id: str):
    """Record that the YouTube link was opened (not completed)."""
    conn = get_connection(request.app.state.db_path)
    try:
        repos = _build_services(conn)
        topic_video_repo = repos["topic_video"]
        record_repo = repos["record"]

        # Find all topic-video associations for this video
        tv_rows = conn.execute(
            "SELECT * FROM topic_videos WHERE video_id = ?", (video_id,)
        ).fetchall()

        for row in tv_rows:
            tv = topic_video_repo._row_to_tv(row)
            # Get or create record
            record = record_repo.get_by_topic_video(tv.id)
            if record is None:
                record = record_repo.create(tv.id)
            # Set state to opened (not completed)
            record_repo.update(
                record.id,
                viewing_state="opened",
            )

        return RedirectResponse(
            url=f"/videos/{video_id}", status_code=303
        )
    finally:
        conn.close()


@router.post("/topic-videos/{tv_id}/state")
def update_state(
    request: Request,
    tv_id: str,
    state: str = Form(...),
):
    """Update the viewing state of a topic-video pair."""
    conn = get_connection(request.app.state.db_path)
    try:
        repos = _build_services(conn)
        record_repo = repos["record"]

        record = record_repo.get_by_topic_video(tv_id)
        if record is None:
            record = record_repo.create(tv_id)

        record_repo.update(record.id, viewing_state=state)

        # Redirect back to the topic feed
        topic_id = conn.execute(
            "SELECT topic_id FROM topic_videos WHERE id = ?", (tv_id,)
        ).fetchone()["topic_id"]

        return RedirectResponse(
            url=f"/topics/{topic_id}", status_code=303
        )
    finally:
        conn.close()
