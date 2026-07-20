"""Adversarial fixtures for CTO repair tests.

These fixtures test production-path rejection of:
- silent canon rewrite;
- impossible location movement;
- unexplained knowledge;
- removed injury or possession;
- relationship contradiction;
- duplicate clue;
- unresolved thread disappearance;
- foreign-world checkpoint;
- incompatible checkpoint;
- checkpoint before divergence;
- unexplained consequence;
- already-rejoined branch;
- invalid rejoin;
- payer identity;
- account/card numbers;
- phone/email;
- credentials/API keys/tokens;
- private reader comments;
- raw generated prose;
- auto-publication;
- duplicate IDs.
"""

from __future__ import annotations

import copy

from tests.fixtures.synthetic_world import WORLD_STATE
from tests.fixtures.mock_payloads import (
    BRANCH_EPISODE_PLAN,
    BRANCH_EPISODE_CONTENT,
    CANON_EPISODE_1_PLAN,
    CANON_EPISODE_1_CONTENT,
)


def make_branch_content_with_choice_id(choice_id: str) -> dict:
    """Return a deep copy of BRANCH_EPISODE_CONTENT with the given choice_id."""
    content = copy.deepcopy(BRANCH_EPISODE_CONTENT)
    content["applied_reader_input"]["reader_choice_id"] = choice_id
    return content


# ── Adversarial: Silent canon rewrite ──────────────────────────────────────
# Branch tries to resolve all known canon clues
ADVERSARIAL_SILENT_CANON_REWRITE = copy.deepcopy(BRANCH_EPISODE_CONTENT)
ADVERSARIAL_SILENT_CANON_REWRITE["applied_reader_input"]["reader_choice_id"] = "choice-test-silent-rewrite"
ADVERSARIAL_SILENT_CANON_REWRITE["world_state_delta"]["clues_resolved"] = [
    "clue-ledger", "clue-room-thirteen", "clue-audio-frame",
]

# ── Adversarial: Impossible location movement ──────────────────────────────
# Character moves to a non-connected location without explanation
ADVERSARIAL_IMPOSSIBLE_MOVEMENT = copy.deepcopy(BRANCH_EPISODE_CONTENT)
ADVERSARIAL_IMPOSSIBLE_MOVEMENT["applied_reader_input"]["reader_choice_id"] = "choice-test-impossible-move"
ADVERSARIAL_IMPOSSIBLE_MOVEMENT["world_state_delta"]["character_location_changed"] = {
    "char-jun-park": "loc-basement-archive",  # jun-park is at loc-security-office, not connected to basement
}
ADVERSARIAL_IMPOSSIBLE_MOVEMENT["world_state_delta"]["branch_only_facts"] = []

# ── Adversarial: Unexplained knowledge ─────────────────────────────────────
# Character gains knowledge without any evidence or acquisition source
ADVERSARIAL_UNEXPLAINED_KNOWLEDGE = copy.deepcopy(BRANCH_EPISODE_CONTENT)
ADVERSARIAL_UNEXPLAINED_KNOWLEDGE["applied_reader_input"]["reader_choice_id"] = "choice-test-unexplained-knowledge"
ADVERSARIAL_UNEXPLAINED_KNOWLEDGE["world_state_delta"]["character_knowledge_added"] = {
    "char-director-han": [
        "서민아가 장부를 숨겼다는 것을 알고 있다",  # impossible — no scene shows this
    ],
}

# ── Adversarial: Removed injury ────────────────────────────────────────────
# (Using possessions for this test since the fixture has no injuries)
ADVERSARIAL_REMOVED_POSSESSION = copy.deepcopy(BRANCH_EPISODE_CONTENT)
ADVERSARIAL_REMOVED_POSSESSION["applied_reader_input"]["reader_choice_id"] = "choice-test-removed-poss"
# The branch tries to remove a possession by not listing it
# (This is tested by comparing delta with prior episode state)

# ── Adversarial: Relationship contradiction ────────────────────────────────
ADVERSARIAL_RELATIONSHIP_CONTRADICTION = copy.deepcopy(BRANCH_EPISODE_CONTENT)
ADVERSARIAL_RELATIONSHIP_CONTRADICTION["applied_reader_input"]["reader_choice_id"] = "choice-test-rel-contradiction"
# Characters who shouldn't be together appear in the same scene
ADVERSARIAL_RELATIONSHIP_CONTRADICTION["scenes"][1]["participating_character_ids"] = [
    "char-mina-seo", "char-jun-park",  # jun-park is at security office, not archive
]

# ── Adversarial: Duplicate clue ────────────────────────────────────────────
ADVERSARIAL_DUPLICATE_CLUE = copy.deepcopy(BRANCH_EPISODE_CONTENT)
ADVERSARIAL_DUPLICATE_CLUE["applied_reader_input"]["reader_choice_id"] = "choice-test-dup-clue"
ADVERSARIAL_DUPLICATE_CLUE["world_state_delta"]["clues_introduced"] = [
    {"clue_id": "clue-ledger", "description": "duplicate clue", "resolved": False},
]

# ── Adversarial: Unresolved thread disappearance ───────────────────────────
ADVERSARIAL_THREAD_DISAPPEARANCE = copy.deepcopy(BRANCH_EPISODE_CONTENT)
ADVERSARIAL_THREAD_DISAPPEARANCE["applied_reader_input"]["reader_choice_id"] = "choice-test-thread-disappear"
ADVERSARIAL_THREAD_DISAPPEARANCE["unresolved_threads"] = []  # all threads dropped
ADVERSARIAL_THREAD_DISAPPEARANCE["world_state_delta"]["unresolved_threads"] = []

# ── Adversarial: Identical output (no material change) ─────────────────────
ADVERSARIAL_IDENTICAL_OUTPUT = copy.deepcopy(BRANCH_EPISODE_CONTENT)
ADVERSARIAL_IDENTICAL_OUTPUT["applied_reader_input"]["reader_choice_id"] = "choice-test-identical"
# Same scenes and prose as the canon episode
ADVERSARIAL_IDENTICAL_OUTPUT["scenes"] = copy.deepcopy(CANON_EPISODE_1_CONTENT["scenes"])
ADVERSARIAL_IDENTICAL_OUTPUT["prose"] = copy.deepcopy(CANON_EPISODE_1_CONTENT["prose"])

# ── Adversarial: Metadata-only change ──────────────────────────────────────
ADVERSARIAL_METADATA_ONLY = copy.deepcopy(BRANCH_EPISODE_CONTENT)
ADVERSARIAL_METADATA_ONLY["applied_reader_input"]["reader_choice_id"] = "choice-test-meta-only"
# Same content, only title changed
ADVERSARIAL_METADATA_ONLY["title"] = "메타데이터만 변경됨"
ADVERSARIAL_METADATA_ONLY["scenes"] = copy.deepcopy(CANON_EPISODE_1_CONTENT["scenes"])
ADVERSARIAL_METADATA_ONLY["prose"] = copy.deepcopy(CANON_EPISODE_1_CONTENT["prose"])

# ── Privacy violation payloads ─────────────────────────────────────────────
ADVERSARIAL_PAYER_IDENTITY = {
    "payer_name": "홍길동",
    "amount": 4900,
    "is_hypothesis": True,
}

ADVERSARIAL_CARD_NUMBER = {
    "card_number": "1234-5678-9012-3456",
    "amount": 4900,
}

ADVERSARIAL_PHONE_EMAIL = {
    "reader_phone": "010-1234-5678",
    "reader_email": "reader@example.com",
}

ADVERSARIAL_API_KEY = {
    "api_key": "sk-1234567890abcdef1234567890abcdef",
    "model": "gpt-4",
}

ADVERSARIAL_PRIVATE_COMMENT = {
    "reader_comment": "이 부분이 너무 무서워요",
    "rating": 5,
}

ADVERSARIAL_RAW_PROSE = {
    "raw_generated_text": "서민아는 봉인된 문을 열었다. 그 안에는...",
    "episode_number": 1,
}

# ── Adversarial: Revenue payment claim ─────────────────────────────────────
ADVERSARIAL_PAYMENT_CLAIM = {
    "amount": 4900,
    "status": "paid",
    "payment_received": True,
}

# ── Adversarial: Auto-publication ──────────────────────────────────────────
ADVERSARIAL_AUTO_PUBLISH = copy.deepcopy(CANON_EPISODE_1_CONTENT)
ADVERSARIAL_AUTO_PUBLISH["review_state"] = "published"
