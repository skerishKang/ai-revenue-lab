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
        pending_proposals = []
        prop_rows = conn.execute(
            "SELECT * FROM proposals WHERE record_id = ? AND status = 'pending'",
            (record_id,),
        ).fetchall()
        for row in prop_rows:
            pending_proposals.append(
                repos["proposal"]._row_to_proposal(row)
            )

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


@router.get("/records/{record_id}/edit", response_class=HTMLResponse)
def edit_record(request: Request, record_id: str):
    conn = get_connection(request.app.state.db_path)
    try:
        repos = _build_services(conn)
        record = repos["record"].get(record_id)
        if record is None:
            return _render_template(
                request, "error.html",
                {"message": "Record not found", "code": 404},
                status_code=404,
            )
        return _render_template(
            request, "records/edit.html",
            {"record": record},
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

        updates = {
            "viewing_state": viewing_state,
            "reflection": reflection,
            "learned_point": learned_point,
            "agreement": agreement,
            "disagreement": disagreement,
            "uncertainty": uncertainty,
            "follow_up_plan": follow_up_plan,
            "free_form_note": free_form_note,
            "tags": [t.strip() for t in tags.split(",") if t.strip()],
        }
        if rating:
            updates["rating"] = int(rating)
        if opened_date:
            updates["opened_date"] = opened_date
        if completed_date:
            updates["completed_date"] = completed_date

        record_service.update_record(record_id, **updates)

        record = repos["record"].get(record_id)
        tv = repos["topic_video"].get(record.topic_video_id) if record else None
        topic_id = tv.topic_id if tv else ""

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
        record_service.accept_structure_proposal(proposal_id)

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
        record_service.reject_structure_proposal(proposal_id)

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
