"""Routes for private viewing records."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.db import get_connection
from app.factory import _build_services, _render_template
from app.services import RecordService

router = APIRouter()


@router.get("/records/{record_id}", response_class=HTMLResponse)
def record_detail(request: Request, record_id: str):
    conn = get_connection(request.app.state.db_path)
    try:
        repos = _build_services(conn)
        record_service = RecordService(
            repos["topic_video"], repos["record"],
            repos["proposal"],
            request.app.state.llm_provider,
        )

        record = repos["record"].get(record_id)
        if record is None:
            return _render_template(
                request, "error.html",
                {"message": "Record not found", "code": 404},
                status_code=404,
            )

        tv = repos["topic_video"].get(record.topic_video_id)
        video = repos["video"].get(tv.video_id) if tv else None
        timestamps = repos["record"].list_timestamp_refs(record_id)

        # Get pending proposals for this record
        pending_proposals = repos["proposal"].list_pending()
        pending_proposals = [
            p for p in pending_proposals if p.record_id == record_id
        ]

        return _render_template(
            request, "records/detail.html",
            {
                "record": record,
                "topic_video": tv,
                "video": video,
                "timestamps": timestamps,
                "pending_proposals": pending_proposals,
            },
        )
    finally:
        conn.close()


@router.post("/records/{record_id}/update")
def update_record(
    request: Request,
    record_id: str,
    viewing_state: str = Form("unseen"),
    rating: str = Form(""),
    reflection: str = Form(""),
    learned_point: str = Form(""),
    agreement: str = Form(""),
    disagreement: str = Form(""),
    uncertainty: str = Form(""),
    follow_up_plan: str = Form(""),
    free_form_note: str = Form(""),
    tags: str = Form(""),
    opened_date: str = Form(""),
    completed_date: str = Form(""),
):
    conn = get_connection(request.app.state.db_path)
    try:
        repos = _build_services(conn)
        record_service = RecordService(
            repos["topic_video"], repos["record"],
            repos["proposal"],
            request.app.state.llm_provider,
        )

        # Validate viewing_state
        from app.domain.enums import ViewingState
        if viewing_state not in [s.value for s in ViewingState]:
            return _render_template(
                request, "error.html",
                {"message": f"Invalid viewing state: {viewing_state}", "code": 400},
                status_code=400,
            )

        # Parse and validate tags
        raw_tags = [t.strip() for t in tags.split(",") if t.strip()]
        from app.domain.models import validate_tags
        try:
            validated_tags = validate_tags(raw_tags)
        except ValueError as exc:
            return _render_template(
                request, "error.html",
                {"message": str(exc), "code": 400},
                status_code=400,
            )

        updates = {
            "viewing_state": viewing_state,
            "reflection": reflection,
            "learned_point": learned_point,
            "agreement": agreement,
            "disagreement": disagreement,
            "uncertainty": uncertainty,
            "follow_up_plan": follow_up_plan,
            "free_form_note": free_form_note,
            "tags": validated_tags,
        }
        if rating:
            try:
                r = int(rating)
                if r < 0 or r > 5:
                    raise ValueError
                updates["rating"] = r
            except ValueError:
                return _render_template(
                    request, "error.html",
                    {"message": "Rating must be an integer 0-5", "code": 400},
                    status_code=400,
                )
        if opened_date:
            updates["opened_date"] = opened_date
        if completed_date:
            updates["completed_date"] = completed_date

        record_service.update_record(record_id, **updates)

        return RedirectResponse(
            url=f"/records/{record_id}", status_code=303
        )
    finally:
        conn.close()


@router.post("/records/{record_id}/timestamps")
def add_timestamp(
    request: Request,
    record_id: str,
    time_input: str = Form(...),
    label: str = Form(""),
):
    """Add a timestamp reference to a record.

    time_input can be:
    - "08:24" (MM:SS or HH:MM:SS)
    - "504" (seconds)
    """
    conn = get_connection(request.app.state.db_path)
    try:
        repos = _build_services(conn)
        record_service = RecordService(
            repos["topic_video"], repos["record"],
            repos["proposal"],
            request.app.state.llm_provider,
        )

        record = repos["record"].get(record_id)
        if record is None:
            return _render_template(
                request, "error.html",
                {"message": "Record not found", "code": 404},
                status_code=404,
            )

        # Parse time input
        seconds = _parse_time_input(time_input)
        if seconds is None or seconds < 0:
            return _render_template(
                request, "error.html",
                {"message": "Invalid time format. Use MM:SS, HH:MM:SS, or seconds.", "code": 400},
                status_code=400,
            )

        record_service.add_timestamp_ref(record_id, seconds, label)

        return RedirectResponse(
            url=f"/records/{record_id}", status_code=303
        )
    finally:
        conn.close()


@router.post("/records/{record_id}/timestamps/{ts_id}/delete")
def delete_timestamp(
    request: Request,
    record_id: str,
    ts_id: str,
):
    """Delete a timestamp reference from a record."""
    conn = get_connection(request.app.state.db_path)
    try:
        repos = _build_services(conn)
        record_service = RecordService(
            repos["topic_video"], repos["record"],
            repos["proposal"],
            request.app.state.llm_provider,
        )

        record = repos["record"].get(record_id)
        if record is None:
            return _render_template(
                request, "error.html",
                {"message": "Record not found", "code": 404},
                status_code=404,
            )

        # Verify the timestamp belongs to this record
        timestamps = repos["record"].list_timestamp_refs(record_id)
        if ts_id not in [ts.id for ts in timestamps]:
            return _render_template(
                request, "error.html",
                {"message": "Timestamp not found for this record", "code": 404},
                status_code=404,
            )

        record_service.delete_timestamp_ref(ts_id)

        return RedirectResponse(
            url=f"/records/{record_id}", status_code=303
        )
    finally:
        conn.close()


@router.post("/records/{record_id}/propose-structure")
def propose_structure(
    request: Request,
    record_id: str,
    rough_notes: str = Form(...),
):
    conn = get_connection(request.app.state.db_path)
    try:
        repos = _build_services(conn)
        record_service = RecordService(
            repos["topic_video"], repos["record"],
            repos["proposal"],
            request.app.state.llm_provider,
        )
        proposal = record_service.propose_structure(record_id, rough_notes)
        return RedirectResponse(
            url=f"/records/{record_id}", status_code=303
        )
    finally:
        conn.close()


@router.post("/proposals/{proposal_id}/accept")
def accept_proposal(request: Request, proposal_id: str):
    conn = get_connection(request.app.state.db_path)
    try:
        repos = _build_services(conn)
        record_service = RecordService(
            repos["topic_video"], repos["record"],
            repos["proposal"],
            request.app.state.llm_provider,
        )
        try:
            record_service.accept_structure_proposal(proposal_id)
        except ValueError as exc:
            return _render_template(
                request, "error.html",
                {"message": str(exc), "code": 400},
                status_code=400,
            )

        # Redirect back to the record
        proposal = repos["proposal"].get(proposal_id)
        if proposal and proposal.record_id:
            return RedirectResponse(
                url=f"/records/{proposal.record_id}", status_code=303
            )
        return RedirectResponse(url="/", status_code=303)
    finally:
        conn.close()


@router.post("/proposals/{proposal_id}/reject")
def reject_proposal(request: Request, proposal_id: str):
    conn = get_connection(request.app.state.db_path)
    try:
        repos = _build_services(conn)
        record_service = RecordService(
            repos["topic_video"], repos["record"],
            repos["proposal"],
            request.app.state.llm_provider,
        )
        try:
            record_service.reject_structure_proposal(proposal_id)
        except ValueError as exc:
            return _render_template(
                request, "error.html",
                {"message": str(exc), "code": 400},
                status_code=400,
            )

        proposal = repos["proposal"].get(proposal_id)
        if proposal and proposal.record_id:
            return RedirectResponse(
                url=f"/records/{proposal.record_id}", status_code=303
            )
        return RedirectResponse(url="/", status_code=303)
    finally:
        conn.close()


@router.get("/records", response_class=HTMLResponse)
def search_records(
    request: Request,
    topic_id: str | None = None,
    state: str | None = None,
    tags: str | None = None,
    q: str | None = None,
):
    conn = get_connection(request.app.state.db_path)
    try:
        repos = _build_services(conn)
        record_service = RecordService(
            repos["topic_video"], repos["record"],
            repos["proposal"],
            request.app.state.llm_provider,
        )

        tag_list = [t.strip() for t in tags.split(",")] if tags else None
        results = record_service.search_records(
            topic_id=topic_id, state=state, tags=tag_list, query=q
        )

        return _render_template(
            request, "records/search.html",
            {
                "results": results,
                "filters": {
                    "topic_id": topic_id,
                    "state": state,
                    "tags": tags,
                    "q": q,
                },
            },
        )
    finally:
        conn.close()


def _parse_time_input(time_input: str) -> int | None:
    """Parse time input in MM:SS, HH:MM:SS, or seconds format.

    Returns seconds, or None if invalid.
    """
    s = time_input.strip()
    if not s:
        return None

    # Try HH:MM:SS format
    parts = s.split(":")
    if len(parts) == 3:
        try:
            h, m, sec = int(parts[0]), int(parts[1]), int(parts[2])
            if h < 0 or m < 0 or m > 59 or sec < 0 or sec > 59:
                return None
            return h * 3600 + m * 60 + sec
        except ValueError:
            return None

    # Try MM:SS format
    if len(parts) == 2:
        try:
            m, sec = int(parts[0]), int(parts[1])
            if m < 0 or sec < 0 or sec > 59:
                return None
            return m * 60 + sec
        except ValueError:
            return None

    # Try plain seconds
    try:
        val = int(s)
        return val if val >= 0 else None
    except ValueError:
        return None
