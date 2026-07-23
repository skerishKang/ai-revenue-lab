"""Admin/operator routes: authentication, participant overview, generation,
review, editing, publish/reject."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Form, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from app import participant_repository as pt_repo
from app import input_repository as input_repo
from app import edition_repository as ed_repo
from app import feedback_repository as fb_repo
from app import generation_run_repository as gr_repo
from app.auth import (
    create_admin_session,
    decode_admin_session_token,
    generate_csrf_token,
    is_admin_session,
    sign_csrf_token,
    sign_admin_session_token,
    verify_admin_secret,
    verify_csrf_token,
)
from app.config import settings
from app.domain.models import EditionContent
from app.factory import _privacy_headers, _render_template, _set_cookie, _delete_cookie
from app.pipeline.markup import UnsafeMarkupError, check_payload
from app.pipeline.service import GenerationRequest, GenerationService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin")

SESSION_COOKIE = "pe_admin_session"
CSRF_COOKIE = "pe_admin_csrf"

MAP_FEEDBACK_DIRECTION_KO = {
    "continue_direction": "방향 유지",
    "more_practical": "실용성 강화",
    "more_reflective": "성찰·깊이감 강화",
    "deeper_on_section": "선택 섹션 집중",
    "reduce_topic": "주제 비중 축소",
    "exclude_topic": "주제 제외",
    "shorter": "분량 축소",
    "longer": "분량 확대",
    "change_tone": "어조 변경",
    "depth_more": "깊이감 강화",
    "tone_calm": "차분한 어조",
    "practical_focus": "실용성 중심",
    "reflection_more": "성찰 및 되돌아보기",
    "length_shorter": "분량 축소",
    "length_longer": "분량 확대",
}


def _get_admin(request: Request) -> bool:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return False
    session_data = decode_admin_session_token(token)
    if session_data is None:
        return False
    return is_admin_session(session_data)


def _inject_csrf(context: dict[str, Any]) -> tuple[str, str]:
    csrf_token = generate_csrf_token()
    signed = sign_csrf_token(csrf_token)
    context["csrf_token"] = csrf_token
    return csrf_token, signed


def _validate_csrf(request: Request, csrf_field: str) -> bool:
    cookie_val = request.cookies.get(CSRF_COOKIE, "")
    if not cookie_val or not csrf_field:
        return False
    return verify_csrf_token(csrf_field, cookie_val)


def _render_with_csrf(
    request: Request,
    template: str,
    context: dict[str, Any],
) -> tuple[HTMLResponse, str]:
    csrf_token, csrf_signed = _inject_csrf(context)
    resp = _render_template(request, template, context)
    _set_cookie(resp, CSRF_COOKIE, csrf_signed)
    return resp, csrf_signed


def _admin_error_response(request, message, edition=None, content=None,
                          participant=None, feedbacks=None, runs=None):
    context: dict[str, Any] = {
        "edition": edition,
        "content": content,
        "participant": participant,
        "feedbacks": feedbacks or [],
        "generation_runs": runs or [],
        "csrf_token": "",
        "error": message,
        "feedback_map": MAP_FEEDBACK_DIRECTION_KO,
    }
    resp, _ = _render_with_csrf(request, "admin_review.html", context)
    return resp


def _validate_edition_content(structured_content: str) -> tuple[bool, str, EditionContent | None]:
    try:
        parsed = json.loads(structured_content)
    except (json.JSONDecodeError, TypeError):
        return False, "구조화된 콘텐츠의 JSON 형식이 올바르지 않습니다.", None

    try:
        validated = EditionContent.model_validate(parsed)
    except Exception:
        logger.debug("Edition content schema validation rejected")
        return False, "입력한 편집 내용의 필수 항목과 형식을 확인해 주세요.", None

    try:
        check_payload(validated.model_dump())
    except UnsafeMarkupError:
        return False, "콘텐츠에 허용되지 않은 HTML 태그 또는 마크업이 포함되어 있습니다.", None

    return True, "", validated


def _compute_editorial_status(
    participant_id: str,
    inputs: list[Any],
    editions: list[Any],
    feedbacks: list[Any] | None = None,
) -> dict[str, Any]:
    latest_input = inputs[-1] if inputs else None
    latest_edition = editions[-1] if editions else None
    latest_feedback = feedbacks[-1] if feedbacks else None

    if not latest_input:
        return {
            "status_code": "no_input",
            "status_label": "기록 대기",
            "status_class": "status-waiting",
            "recommended_action": "참여자 기록 수신 대기",
            "recommended_action_url": f"/admin/participants/{participant_id}",
            "latest_input": None,
            "latest_edition": None,
            "has_feedback": False,
        }

    if not latest_edition:
        return {
            "status_code": "ready_for_generation",
            "status_label": "생성 준비",
            "status_class": "status-ready",
            "recommended_action": "초안 만들기",
            "recommended_action_url": f"/admin/participants/{participant_id}",
            "latest_input": latest_input,
            "latest_edition": None,
            "has_feedback": False,
        }

    gen_status = latest_edition.generation_status if hasattr(latest_edition, "generation_status") else latest_edition["generation_status"]
    pub_state = latest_edition.publication_state if hasattr(latest_edition, "publication_state") else latest_edition["publication_state"]
    ed_id = latest_edition.id if hasattr(latest_edition, "id") else latest_edition["id"]

    if gen_status in ("generation_failed", "failed"):
        return {
            "status_code": "generation_failed",
            "status_label": "생성 실패",
            "status_class": "status-failed",
            "recommended_action": "오류 확인 및 재시도",
            "recommended_action_url": f"/admin/participants/{participant_id}",
            "latest_input": latest_input,
            "latest_edition": latest_edition,
            "has_feedback": False,
        }

    if pub_state == "published":
        input_time = latest_input.submitted_at if hasattr(latest_input, "submitted_at") else latest_input["submitted_at"]
        pub_time = latest_edition.published_at if hasattr(latest_edition, "published_at") else latest_edition["published_at"]

        if input_time and pub_time and str(input_time) > str(pub_time):
            return {
                "status_code": "next_edition_ready",
                "status_label": "후속 에디션 준비",
                "status_class": "status-ready",
                "recommended_action": "다음 호 초안 만들기",
                "recommended_action_url": f"/admin/participants/{participant_id}",
                "latest_input": latest_input,
                "latest_edition": latest_edition,
                "has_feedback": bool(latest_feedback),
            }

        if latest_feedback:
            return {
                "status_code": "feedback_received",
                "status_label": "피드백 도착",
                "status_class": "status-feedback",
                "recommended_action": "피드백 확인 및 다음 호 준비",
                "recommended_action_url": f"/admin/review/{ed_id}",
                "latest_input": latest_input,
                "latest_edition": latest_edition,
                "has_feedback": True,
            }

        return {
            "status_code": "published",
            "status_label": "발행 완료",
            "status_class": "status-published",
            "recommended_action": "에디션 상태 확인",
            "recommended_action_url": f"/admin/review/{ed_id}",
            "latest_input": latest_input,
            "latest_edition": latest_edition,
            "has_feedback": False,
        }

    if gen_status == "pending_review":
        return {
            "status_code": "pending_review",
            "status_label": "검토 필요",
            "status_class": "status-pending-review",
            "recommended_action": "에디션 검토 및 편집",
            "recommended_action_url": f"/admin/review/{ed_id}",
            "latest_input": latest_input,
            "latest_edition": latest_edition,
            "has_feedback": False,
        }

    if pub_state == "rejected":
        return {
            "status_code": "rejected",
            "status_label": "반려됨",
            "status_class": "status-rejected",
            "recommended_action": "사유 확인 및 재초안 준비",
            "recommended_action_url": f"/admin/participants/{participant_id}",
            "latest_input": latest_input,
            "latest_edition": latest_edition,
            "has_feedback": False,
        }

    return {
        "status_code": "unknown",
        "status_label": "기록 대기",
        "status_class": "status-waiting",
        "recommended_action": "상세 확인",
        "recommended_action_url": f"/admin/participants/{participant_id}",
        "latest_input": latest_input,
        "latest_edition": latest_edition,
        "has_feedback": False,
    }


@router.get("/access")
def admin_access_page(request: Request):
    resp, _ = _render_with_csrf(request, "admin_access.html", {"error": None})
    return resp


@router.post("/access")
def admin_access_submit(
    request: Request,
    secret: str = Form(""),
    csrf_token: str = Form(""),
):
    if not _validate_csrf(request, csrf_token):
        resp, _ = _render_with_csrf(request, "admin_access.html", {
            "error": "양식 토큰이 만료되었거나 올바르지 않습니다. 다시 시도해 주세요.",
        })
        return resp

    secret = secret.strip()
    if not secret or not verify_admin_secret(secret):
        resp, _ = _render_with_csrf(request, "admin_access.html", {
            "error": "올바르지 않은 관리자 비밀번호입니다.",
        })
        return resp

    session_data = create_admin_session()
    signed_token = sign_admin_session_token(session_data)
    resp = RedirectResponse(url="/admin/", status_code=303)
    _set_cookie(resp, SESSION_COOKIE, signed_token)
    return resp


@router.get("/")
def admin_dashboard(request: Request):
    if not _get_admin(request):
        return RedirectResponse(url="/admin/access", status_code=303)

    conn = request.app.state.open_runtime_connection()
    try:
        participants = conn.execute(
            "SELECT id, display_name, preferred_language, status, created_at "
            "FROM participants WHERE status = 'active' ORDER BY created_at"
        ).fetchall()

        queue_items = []
        summary_counts = {
            "pending_review": 0,
            "ready_for_generation": 0,
            "generation_failed": 0,
            "feedback_received": 0,
            "recently_published": 0,
        }

        for p in participants:
            p_id = p["id"]
            inputs = input_repo.get_inputs_by_participant(conn, p_id)
            editions = ed_repo.get_editions_by_participant(conn, p_id)
            latest_input = inputs[-1] if inputs else None
            latest_edition = editions[-1] if editions else None
            feedbacks = (
                fb_repo.get_feedback_by_edition(conn, latest_edition.id)
                if latest_edition else []
            )

            status_info = _compute_editorial_status(p_id, inputs, editions, feedbacks)

            code = status_info["status_code"]
            if code == "pending_review":
                summary_counts["pending_review"] += 1
            elif code in ("ready_for_generation", "next_edition_ready"):
                summary_counts["ready_for_generation"] += 1
            elif code == "generation_failed":
                summary_counts["generation_failed"] += 1
            elif code == "feedback_received":
                summary_counts["feedback_received"] += 1

            if code in ("published", "next_edition_ready", "feedback_received"):
                summary_counts["recently_published"] += 1

            queue_items.append({
                "participant": p,
                "status_info": status_info,
                "latest_input": latest_input,
                "latest_edition": latest_edition,
                "has_feedback": bool(feedbacks),
            })

        recent_runs = conn.execute(
            "SELECT task_type, provider, advertised_model, cost_class, "
            "success, validation_status, latency_seconds, error_category, "
            "started_at "
            "FROM generation_runs ORDER BY started_at DESC LIMIT 10"
        ).fetchall()

        raw_editions = conn.execute(
            "SELECT e.id, e.participant_id, e.edition_number, "
            "e.generation_status, e.publication_state, e.rendered_title, "
            "e.drafted_at, e.published_at, p.display_name "
            "FROM editions e "
            "JOIN participants p ON e.participant_id = p.id "
            "WHERE e.generation_status != 'deleted' "
            "ORDER BY e.drafted_at DESC"
        ).fetchall()
    finally:
        conn.close()

    provider_instance = request.app.state.provider
    actual_provider = getattr(provider_instance, "provider", provider_instance.__class__.__name__.lower())
    actual_model = getattr(provider_instance, "model", settings.ai_model)

    context: dict[str, Any] = {
        "participants": participants,
        "editions": raw_editions,
        "queue_items": queue_items,
        "summary_counts": summary_counts,
        "recent_generation_runs": recent_runs,
        "provider_name": settings.ai_provider,
        "model_name": settings.ai_model,
        "actual_provider": actual_provider,
        "actual_model": actual_model,
    }
    resp, _ = _render_with_csrf(request, "admin_dashboard.html", context)
    return resp


@router.get("/participants/{participant_id}")
def admin_participant_detail(request: Request, participant_id: str, error: str = Query("")):
    if not _get_admin(request):
        return RedirectResponse(url="/admin/access", status_code=303)

    conn = request.app.state.open_runtime_connection()
    try:
        participant = pt_repo.get_participant_by_id(conn, participant_id)
        if participant is None:
            resp, _ = _render_with_csrf(request, "admin_not_found.html", {
                "message": "참여자를 찾을 수 없습니다.",
            })
            return resp

        editions = ed_repo.get_editions_by_participant(conn, participant_id)
        inputs = input_repo.get_inputs_by_participant(conn, participant_id)

        latest_input = inputs[-1] if inputs else None
        latest_edition = editions[-1] if editions else None
        latest_feedbacks = (
            fb_repo.get_feedback_by_edition(conn, latest_edition.id)
            if latest_edition else []
        )

        all_feedbacks = []
        for ed in editions:
            fbs = fb_repo.get_feedback_by_edition(conn, ed.id)
            for f in fbs:
                try:
                    dirs = json.loads(f.direction_choices) if isinstance(f.direction_choices, str) else f.direction_choices
                except Exception:
                    dirs = []
                all_feedbacks.append({
                    "edition": ed,
                    "record": f,
                    "direction": dirs,
                })

        status_info = _compute_editorial_status(
            participant_id,
            inputs,
            editions,
            latest_feedbacks
        )

        gen_runs = conn.execute(
            "SELECT * FROM generation_runs ORDER BY started_at DESC LIMIT 20"
        ).fetchall()
    finally:
        conn.close()

    generation_error = None
    if error == "generation_failed":
        generation_error = {
            "title": "초안을 생성하지 못했습니다.",
            "detail": "기존 기록과 에디션은 변경되지 않았습니다. 기술 정보를 확인한 뒤 다시 시도할 수 있습니다.",
        }

    context: dict[str, Any] = {
        "participant": participant,
        "editions": editions,
        "inputs": inputs,
        "latest_input": latest_input,
        "latest_edition": latest_edition,
        "feedbacks_with_editions": all_feedbacks,
        "status_info": status_info,
        "generation_runs": gen_runs,
        "generation_error": generation_error,
        "feedback_map": MAP_FEEDBACK_DIRECTION_KO,
        "generation_idempotency_key": str(uuid.uuid4()),
    }
    resp, _ = _render_with_csrf(request, "admin_participant_detail.html", context)
    return resp


@router.post("/participants/{participant_id}/generate")
def admin_generate(
    request: Request,
    participant_id: str,
    input_id: str = Form(""),
    allow_short_sample: str = Form("0"),
    idempotency_key: str = Form(""),
    csrf_token: str = Form(""),
):
    if not _get_admin(request):
        return RedirectResponse(url="/admin/access", status_code=303)

    if not _validate_csrf(request, csrf_token):
        return RedirectResponse(
            url=f"/admin/participants/{participant_id}?error=csrf", status_code=303
        )

    idempotency_key_clean = idempotency_key.strip()
    if not idempotency_key_clean or len(idempotency_key_clean) > 64:
        return RedirectResponse(
            url=f"/admin/participants/{participant_id}?error=invalid_idempotency_key",
            status_code=303,
        )
    try:
        uuid.UUID(idempotency_key_clean)
    except ValueError:
        return RedirectResponse(
            url=f"/admin/participants/{participant_id}?error=invalid_idempotency_key",
            status_code=303,
        )

    conn = request.app.state.open_runtime_connection()
    error_code = None
    try:
        participant = pt_repo.get_participant_by_id(conn, participant_id)
        if participant is None:
            resp, _ = _render_with_csrf(request, "admin_not_found.html", {
                "message": "참여자를 찾을 수 없습니다.",
            })
            return resp

        service: GenerationService = request.app.state.generation_service
        gen_request = GenerationRequest(
            participant_id=participant_id,
            input_id=input_id,
            allow_short_sample=(allow_short_sample == "1"),
            idempotency_key=idempotency_key_clean,
        )
        result = service.generate_edition(conn, request=gen_request)
        if not result.succeeded:
            logger.warning("Generation succeeded=False for participant %s", participant_id)
            error_code = "generation_failed"
    except Exception as exc:
        logger.error("Generation failed for participant %s: %s", participant_id, exc)
        error_code = "generation_failed"
    finally:
        conn.close()

    if error_code:
        return RedirectResponse(
            url=f"/admin/participants/{participant_id}?error={error_code}", status_code=303
        )

    return RedirectResponse(
        url=f"/admin/participants/{participant_id}", status_code=303
    )


@router.get("/review/{edition_id}")
def admin_review_page(request: Request, edition_id: str):
    if not _get_admin(request):
        return RedirectResponse(url="/admin/access", status_code=303)

    conn = request.app.state.open_runtime_connection()
    try:
        edition = ed_repo.get_edition_by_id(conn, edition_id)
        if edition is None:
            resp, _ = _render_with_csrf(request, "admin_not_found.html", {
                "message": "에디션을 찾을 수 없습니다.",
            })
            return resp

        content = None
        if edition.structured_content:
            try:
                content = json.loads(edition.structured_content)
            except Exception:
                content = None

        participant = pt_repo.get_participant_by_id(
            conn, edition.participant_id
        )

        feedbacks = fb_repo.get_feedback_by_edition(conn, edition_id)
        parsed_feedbacks = []
        for f in feedbacks:
            try:
                dirs = json.loads(f.direction_choices) if isinstance(f.direction_choices, str) else f.direction_choices
            except Exception:
                dirs = []
            parsed_feedbacks.append({
                "record": f,
                "direction": dirs,
                "submitted_at": f.submitted_at,
                "selected_section_id": f.selected_section_id,
                "free_text": f.free_text,
            })

        runs = conn.execute(
            "SELECT * FROM generation_runs ORDER BY started_at DESC"
        ).fetchall()
    finally:
        conn.close()

    context: dict[str, Any] = {
        "edition": edition,
        "content": content,
        "participant": participant,
        "feedbacks": parsed_feedbacks,
        "generation_runs": runs,
        "feedback_map": MAP_FEEDBACK_DIRECTION_KO,
    }
    resp, _ = _render_with_csrf(request, "admin_review.html", context)
    return resp


@router.post("/review/{edition_id}/edit")
def admin_review_edit(
    request: Request,
    edition_id: str,
    response: Response,
    structured_content: str = Form(""),
    field_publication_title: str = Form(""),
    field_deck: str = Form(""),
    field_opening: str = Form(""),
    field_highlighted_insight: str = Form(""),
    field_continuity_note: str = Form(""),
    field_provenance_note: str = Form(""),
    field_next_edition_question: str = Form(""),
    field_next_edition_choices: str = Form(""),
    section_0_title: str = Form(""),
    section_0_paragraphs: str = Form(""),
    section_1_title: str = Form(""),
    section_1_paragraphs: str = Form(""),
    section_2_title: str = Form(""),
    section_2_paragraphs: str = Form(""),
    section_3_title: str = Form(""),
    section_3_paragraphs: str = Form(""),
    rendered_title: str = Form(""),
    reviewer_notes: str = Form(""),
    csrf_token: str = Form(""),
):
    if not _get_admin(request):
        return RedirectResponse(url="/admin/access", status_code=303)

    if not _validate_csrf(request, csrf_token):
        return RedirectResponse(
            url=f"/admin/review/{edition_id}", status_code=303
        )

    conn = request.app.state.open_runtime_connection()
    try:
        edition = ed_repo.get_edition_by_id(conn, edition_id)
        if edition is None:
            resp, _ = _render_with_csrf(request, "admin_not_found.html", {
                "message": "에디션을 찾을 수 없습니다.",
            })
            return resp

        target_json_str = structured_content.strip()

        # If individual field parameters were submitted, build updated JSON payload
        if field_publication_title.strip() or field_opening.strip() or field_deck.strip():
            base_dict = {}
            if edition.structured_content:
                try:
                    base_dict = json.loads(edition.structured_content)
                except Exception:
                    base_dict = {}

            if not base_dict.get("content_version"):
                base_dict["content_version"] = "1.0"
            if not base_dict.get("language"):
                base_dict["language"] = "ko"

            base_dict["publication_title"] = field_publication_title.strip()
            base_dict["edition_title"] = field_publication_title.strip()
            base_dict["deck"] = field_deck.strip()
            base_dict["opening"] = field_opening.strip()
            base_dict["highlighted_insight"] = field_highlighted_insight.strip()

            if field_continuity_note.strip():
                base_dict["continuity_note"] = field_continuity_note.strip()
            else:
                base_dict["continuity_note"] = None

            if field_provenance_note.strip():
                base_dict["provenance_note"] = field_provenance_note.strip()

            if field_next_edition_question.strip():
                choices = [c.strip() for c in field_next_edition_choices.split(",") if c.strip()]
                base_dict["next_edition_prompt"] = {
                    "question": field_next_edition_question.strip(),
                    "choices": choices,
                }
            elif "next_edition_prompt" in base_dict and not field_next_edition_question.strip():
                base_dict["next_edition_prompt"] = None

            # Reconstruct sections array
            existing_sections = base_dict.get("sections", [])
            new_sections = []
            section_inputs = [
                (section_0_title, section_0_paragraphs),
                (section_1_title, section_1_paragraphs),
                (section_2_title, section_2_paragraphs),
                (section_3_title, section_3_paragraphs),
            ]

            for idx, (title_val, paras_val) in enumerate(section_inputs):
                if not title_val.strip() and not paras_val.strip() and idx >= 2:
                    continue

                paras = [p.strip() for p in paras_val.split("\n") if p.strip()]
                sec_id = f"section-{idx+1}"
                source_seg_ids = ["segment-1"]
                contains_interp = False

                if idx < len(existing_sections):
                    sec_id = existing_sections[idx].get("section_id", sec_id)
                    source_seg_ids = existing_sections[idx].get("source_segment_ids", source_seg_ids)
                    contains_interp = existing_sections[idx].get("contains_interpretation", False)

                new_sections.append({
                    "section_id": sec_id,
                    "title": title_val.strip(),
                    "paragraphs": paras,
                    "source_segment_ids": source_seg_ids,
                    "contains_interpretation": contains_interp,
                })

            if new_sections:
                base_dict["sections"] = new_sections

            target_json_str = json.dumps(base_dict, ensure_ascii=False)

        is_valid, error_msg, validated_model = _validate_edition_content(target_json_str)
        if not is_valid:
            content_to_show = None
            if target_json_str:
                try:
                    content_to_show = json.loads(target_json_str)
                except Exception:
                    pass
            if content_to_show is None and edition.structured_content:
                try:
                    content_to_show = json.loads(edition.structured_content)
                except Exception:
                    pass

            return _admin_error_response(
                request, error_msg,
                edition=edition, content=content_to_show,
                participant=(
                    pt_repo.get_participant_by_id(conn, edition.participant_id)
                    if edition else None
                ),
                feedbacks=(
                    fb_repo.get_feedback_by_edition(conn, edition_id)
                    if edition else []
                ),
                runs=conn.execute(
                    "SELECT * FROM generation_runs ORDER BY started_at DESC"
                ).fetchall(),
            )

        canonical_content = validated_model.model_dump_json()
        final_rendered_title = rendered_title.strip() if rendered_title.strip() else validated_model.publication_title

        ed_repo.update_edition_content(
            conn,
            edition_id,
            structured_content=canonical_content,
            rendered_title=final_rendered_title,
            reviewer_notes=reviewer_notes.strip() if reviewer_notes.strip() else None,
        )
    finally:
        conn.close()

    return RedirectResponse(
        url=f"/admin/review/{edition_id}", status_code=303
    )


@router.post("/review/{edition_id}/publish")
def admin_publish(
    request: Request,
    edition_id: str,
    csrf_token: str = Form(""),
):
    if not _get_admin(request):
        return RedirectResponse(url="/admin/access", status_code=303)

    if not _validate_csrf(request, csrf_token):
        return RedirectResponse(
            url=f"/admin/review/{edition_id}", status_code=303
        )

    conn = request.app.state.open_runtime_connection()
    try:
        ed_repo.update_edition_publication(
            conn, edition_id, "published"
        )
    finally:
        conn.close()

    return RedirectResponse(
        url=f"/admin/review/{edition_id}", status_code=303
    )


@router.post("/review/{edition_id}/reject")
def admin_reject(
    request: Request,
    edition_id: str,
    csrf_token: str = Form(""),
):
    if not _get_admin(request):
        return RedirectResponse(url="/admin/access", status_code=303)

    if not _validate_csrf(request, csrf_token):
        return RedirectResponse(
            url=f"/admin/review/{edition_id}", status_code=303
        )

    conn = request.app.state.open_runtime_connection()
    try:
        ed_repo.update_edition_publication(
            conn, edition_id, "rejected"
        )
    finally:
        conn.close()

    return RedirectResponse(
        url=f"/admin/review/{edition_id}", status_code=303
    )


@router.post("/logout")
def admin_logout(request: Request, csrf_token: str = Form("")):
    if not _validate_csrf(request, csrf_token):
        return RedirectResponse(url="/admin/", status_code=303)
    resp = RedirectResponse(url="/admin/access", status_code=303)
    _delete_cookie(resp, SESSION_COOKIE)
    _delete_cookie(resp, CSRF_COOKIE)
    return resp
