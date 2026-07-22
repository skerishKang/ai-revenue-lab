"""Routes for LLM proposals (rule changes and structure proposals)."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.db import get_connection
from app.factory import _build_services, _render_template
from app.services import ProposalService

router = APIRouter()


@router.get("/proposals", response_class=HTMLResponse)
def list_proposals(request: Request, topic_id: str | None = None):
    conn = get_connection(request.app.state.db_path)
    try:
        repos = _build_services(conn)
        proposal_service = ProposalService(
            repos["topic"], repos["rule"],
            repos["proposal"],
            request.app.state.llm_provider,
        )

        if topic_id:
            proposals = repos["proposal"].list_pending(topic_id)
        else:
            proposals = repos["proposal"].list_pending()

        return _render_template(
            request, "proposals/list.html",
            {"proposals": proposals},
        )
    finally:
        conn.close()


@router.post("/proposals/{proposal_id}/accept-rule-change")
def accept_rule_change(request: Request, proposal_id: str):
    conn = get_connection(request.app.state.db_path)
    try:
        repos = _build_services(conn)
        proposal_service = ProposalService(
            repos["topic"], repos["rule"],
            repos["proposal"],
            request.app.state.llm_provider,
        )
        proposal_service.accept_rule_change(proposal_id)

        proposal = repos["proposal"].get(proposal_id)
        if proposal and proposal.topic_id:
            return RedirectResponse(
                url=f"/topics/{proposal.topic_id}", status_code=303
            )
        return RedirectResponse(url="/", status_code=303)
    finally:
        conn.close()


@router.post("/proposals/{proposal_id}/reject-rule-change")
def reject_rule_change(request: Request, proposal_id: str):
    conn = get_connection(request.app.state.db_path)
    try:
        repos = _build_services(conn)
        proposal_service = ProposalService(
            repos["topic"], repos["rule"],
            repos["proposal"],
            request.app.state.llm_provider,
        )
        proposal_service.reject_rule_change(proposal_id)

        proposal = repos["proposal"].get(proposal_id)
        if proposal and proposal.topic_id:
            return RedirectResponse(
                url=f"/topics/{proposal.topic_id}", status_code=303
            )
        return RedirectResponse(url="/", status_code=303)
    finally:
        conn.close()
