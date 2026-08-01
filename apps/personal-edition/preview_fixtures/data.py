"""Synthetic fixture data for the Cloudflare Pages UI preview.

All data is clearly synthetic and contains no real personal information.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from app.domain.enums import FeedbackDirection

PARTICIPANT_ID = "modal-preview-user"
EDITION_ID = "modal-preview-edition"


def make_participant() -> SimpleNamespace:
    return SimpleNamespace(
        id=PARTICIPANT_ID,
        display_name="모달 프리뷰 사용자",
        preferred_language="ko",
        status="active",
        created_at="2024-01-01T00:00:00",
    )


def make_edition_content() -> dict:
    return {
        "content_version": "personal-edition-v1",
        "language": "ko",
        "publication_title": "개인의 편지",
        "edition_title": "속도에서 개인화로",
        "deck": "한 창업자가 고객과의 대화를 통해 진짜 가치를 발견한 이야기",
        "opening": (
            "처음에는 단순했습니다. 빠르게 배달하면 고객이 만족할 것이라 믿었습니다. "
            "하지만 고객들을 직접 만나면서 그 단순한 믿음이 흔들리기 시작했습니다."
        ),
        "sections": [
            {
                "section_id": "section-1",
                "title": "속도라는 첫 가설",
                "paragraphs": [
                    "창업 초기, 빠른 배송이 곧 경쟁력이라고 생각했습니다. "
                    "모든 문제를 속도로 해결하려 했습니다. 고객이 빨리 받으면 만족할 것이라 믿었죠.",
                    "하지만 이 믿음은 고객들을 만나면서 점점 흔들렸습니다. "
                    "한 고객은 빠른 배송에도 불구하고 자신의 취향을 몰라준다며 아쉬워했습니다.",
                ],
                "source_segment_ids": ["s001"],
                "contains_interpretation": False,
            },
            {
                "section_id": "section-2",
                "title": "고객과의 만남이 바꾼 것",
                "paragraphs": [
                    "다른 고객은 속도보다 자신에게 맞는 제안이 더 중요하다고 말했습니다. "
                    "그 말을 듣는 순간 속도는 수단이지 목적이 아니라는 것을 깨달았습니다.",
                    "진짜 가치는 고객 한 사람 한 사람을 이해하는 데 있었습니다. "
                    "그래서 방향을 바꾸기로 했습니다. 개인화된 경험을 우선하기로 결정했습니다.",
                ],
                "source_segment_ids": ["s002"],
                "contains_interpretation": True,
            },
        ],
        "highlighted_insight": "비즈니스 모델은 고객과의 대화 속에서 진화한다",
        "continuity_note": None,
        "applied_feedback": None,
        "next_edition_prompt": {
            "question": "개인화 경험이 구체적으로 어떻게 구현되고 있는지 더 깊이 알고 싶으신가요?",
            "choices": ["네, 더 자세히", "아니요, 다른 주제로"],
        },
        "provenance_note": "This edition was created from material supplied by the reader.",
    }


def make_edition(
    publication_state: str = "published",
    generation_status: str = "published",
) -> SimpleNamespace:
    content = make_edition_content()
    return SimpleNamespace(
        id=EDITION_ID,
        participant_id=PARTICIPANT_ID,
        # Display 호수 (issue number) shown to the participant.
        edition_number=1,
        # URL/output-path slug identity (kept separate from the display 호수
        # so the on-screen issue number is "제1호"/"#1", never the slug).
        edition_uid=EDITION_ID,
        rendered_title="속도에서 개인화로",
        generation_status=generation_status,
        publication_state=publication_state,
        structured_content=json.dumps(content, ensure_ascii=False),
        published_at="2024-01-15T10:00:00",
        drafted_at="2024-01-10T10:00:00",
        reviewer_notes="",
        display_name="모달 프리뷰 사용자",
        deck=content["deck"],
        applied_feedback=None,
    )


def make_inputs() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            id="input-1",
            sequence_number=1,
            raw_text=(
                "처음에는 빠른 배송이 핵심 경쟁력이라고 생각했습니다. "
                "모든 문제를 속도로 해결하려 했습니다. 고객이 빨리 받으면 만족할 것이라 믿었죠. "
                "하지만 고객들을 직접 만나면서 그 믿음이 흔들리기 시작했습니다."
            ),
            submitted_at="2024-01-05T10:00:00",
            consent_confirmed=1,
        ),
        SimpleNamespace(
            id="input-2",
            sequence_number=2,
            raw_text=(
                "개인화된 경험을 우선하기로 결정했습니다. "
                "이제는 각 고객의 상황과 취향을 먼저 파악합니다. "
                "속도는 여전히 신경 쓰지만, 더 이상 첫 번째 기준이 아닙니다."
            ),
            submitted_at="2024-01-08T14:30:00",
            consent_confirmed=1,
        ),
    ]


def make_generation_runs() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            task_type="plan",
            provider="mock",
            advertised_model="mock-personal-edition-v1",
            validation_status="valid",
            input_tokens=500,
            output_tokens=800,
            retry_count=0,
            latency_seconds=1.23,
            success=True,
            error_category=None,
            started_at="2024-01-10T09:00:00",
        ),
        SimpleNamespace(
            task_type="draft",
            provider="mock",
            advertised_model="mock-personal-edition-v1",
            validation_status="valid",
            input_tokens=1200,
            output_tokens=1500,
            retry_count=1,
            latency_seconds=2.45,
            success=True,
            error_category=None,
            started_at="2024-01-10T10:00:00",
        ),
    ]


def make_feedback_directions() -> list[tuple[str, str]]:
    return [
        (d.value, d.value.replace("_", " ").title())
        for d in FeedbackDirection
    ]


def make_feedback_map() -> dict[str, str]:
    return {
        d.value: d.value.replace("_", " ").title()
        for d in FeedbackDirection
    }


def make_status_info() -> dict:
    return {
        "status_class": "status-pending-review",
        "status_label": "검토 대기",
        "recommended_action_url": "/admin/review/modal-preview-edition",
        "recommended_action": "검토 및 편집",
    }


def make_summary_counts() -> dict:
    return {
        "pending_review": 1,
        "ready_for_generation": 0,
        "generation_failed": 0,
        "feedback_received": 0,
        "recently_published": 1,
    }


def make_queue_items(
    participant: SimpleNamespace,
    edition: SimpleNamespace,
    latest_input: SimpleNamespace | None,
) -> list[dict]:
    return [
        {
            "participant": participant,
            "status_info": make_status_info(),
            "latest_input": latest_input,
            "latest_edition": edition,
            "has_feedback": False,
        }
    ]


def make_feedbacks() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            submitted_at="2024-01-12T15:00:00",
            direction=["more_reflective"],
            selected_section_id="section-1",
            free_text="개인화가 구체적으로 어떻게 실천되는지 더 깊이 알고 싶습니다.",
        ),
    ]


def make_feedbacks_with_editions(
    participant: SimpleNamespace,
    edition: SimpleNamespace,
    feedback: SimpleNamespace,
) -> list[dict]:
    return [
        {
            "edition": edition,
            "record": feedback,
            "direction": feedback.direction,
        }
    ]


def make_pending_edition() -> SimpleNamespace:
    return SimpleNamespace(
        id="pending-edition",
        participant_id=PARTICIPANT_ID,
        edition_number=1,
        rendered_title="초안 구성 중",
        generation_status="pending_review",
        publication_state="pending",
        structured_content=None,
        published_at=None,
        drafted_at="2024-01-10T10:00:00",
        reviewer_notes="",
    )
