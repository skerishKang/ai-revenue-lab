"""MockProvider fixture payloads for canon and branch episodes.

The deterministic canon/branch payloads now live in ``app.preview_data`` so
that production runtime code never imports from ``tests/**``. This module
re-exports those payloads and keeps the adversarial, test-only payloads here
under ``tests/``.
"""

from app.preview_data import (
    BRANCH_EPISODE_CONTENT,
    BRANCH_EPISODE_PLAN,
    CANON_EPISODE_1_CONTENT,
    CANON_EPISODE_1_PLAN,
)

__all__ = [
    "BRANCH_EPISODE_CONTENT",
    "BRANCH_EPISODE_PLAN",
    "CANON_EPISODE_1_CONTENT",
    "CANON_EPISODE_1_PLAN",
    "ADVERSARIAL_CANON_REWRITE_CONTENT",
    "ADVERSARIAL_FOREIGN_CHOICE",
    "ADVERSARIAL_IMPOSSIBLE_LOCATION_CONTENT",
    "ADVERSARIAL_DUPLICATE_ID_PLAN",
    "ADVERSARIAL_UNSAFE_MARKUP_CONTENT",
    "ADVERSARIAL_PROHIBITED_NAME_CONTENT",
    "ADVERSARIAL_INVALID_REJOIN",
    "ADVERSARIAL_AUTO_PUBLISH_CONTENT",
]

# ── Adversarial payloads (test-only) ──────────────────────────────────────

# Canon rewrite attempt — tries to mutate immutable canon facts
ADVERSARIAL_CANON_REWRITE_CONTENT = {
    **CANON_EPISODE_1_CONTENT,
    "world_state_delta": {
        **CANON_EPISODE_1_CONTENT["world_state_delta"],
        "character_knowledge_added": {
            "char-mina-seo": [
                "사라진 한 시간의 원인을 완전히 알게 되었다",  # premature canon resolution
            ],
        },
        "clues_resolved": ["clue-ledger", "clue-room-thirteen"],  # resolving unresolved canon clues
    },
}

# Foreign reader choice — choice from a different reader
ADVERSARIAL_FOREIGN_CHOICE = {
    "reader_choice_id": "choice-foreign-reader",
    "choice_text": "신중하게 조사한다",
    "comment": "foreign reader comment",
    "applied_evidence": "should not be applied to this branch",
}

# Impossible continuity — character in two places at once
ADVERSARIAL_IMPOSSIBLE_LOCATION_CONTENT = {
    **BRANCH_EPISODE_CONTENT,
    "world_state_delta": {
        **BRANCH_EPISODE_CONTENT["world_state_delta"],
        "character_location_changed": {
            "char-mina-seo": "loc-basement-archive",  # moves to sealed archive
        },
        "character_knowledge_added": {
            "char-mina-seo": [
                "13호실 안의 내용을 직접 확인했다",  # impossible without opening
            ],
        },
    },
}

# Duplicate IDs — duplicate scene_id
ADVERSARIAL_DUPLICATE_ID_PLAN = {
    **CANON_EPISODE_1_PLAN,
    "scenes": [
        CANON_EPISODE_1_PLAN["scenes"][0],
        {**CANON_EPISODE_1_PLAN["scenes"][0]},  # duplicate scene_id
    ],
}

# Unsafe markup — HTML/script injection
ADVERSARIAL_UNSAFE_MARKUP_CONTENT = {
    **CANON_EPISODE_1_CONTENT,
    "prose": [
        {
            "scene_id": "scene-archive-midnight",
            "paragraphs": [
                "<script>alert('xss')</script>서민아가 마지막 기록에 도장을 찍었다.",
            ],
        },
    ],
}

# Prohibited franchise/person identifier
ADVERSARIAL_PROHIBITED_NAME_CONTENT = {
    **CANON_EPISODE_1_CONTENT,
    "prose": [
        {
            "scene_id": "scene-archive-midnight",
            "paragraphs": [
                "서민아는 마치 셜록 홈즈처럼 사건을 추리하기 시작했다.",  # Sherlock Holmes
            ],
        },
    ],
}

# Invalid rejoin — discards unresolved consequences without explanation
ADVERSARIAL_INVALID_REJOIN = {
    "branch_id": "branch-test-1",
    "target_checkpoint_id": "checkpoint-future-1",
    "unresolved_consequences": ["13호실의 비밀이 미해결 상태로 남음"],
    "explanation": None,  # no explanation for discarding consequences
}

# Auto-publication attempt — tries to auto-publish
ADVERSARIAL_AUTO_PUBLISH_CONTENT = {
    **CANON_EPISODE_1_CONTENT,
    "review_state": "published",  # should be rejected — no auto-publication
}
