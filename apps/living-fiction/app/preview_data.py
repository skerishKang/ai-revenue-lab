"""Application-owned preview/seed data for Living Fiction Phase 2A.

This module owns the deterministic, network-free world and episode payloads
used by the dev seed and the preview web routes. It lives in the ``app``
package so that production runtime code (``app.web``, ``app.dev_seed``) never
needs to import from ``tests/**``.

The test fixtures (``tests/fixtures/synthetic_world.py`` and
``tests/fixtures/mock_payloads.py``) re-export these values so existing tests
keep working, while adversarial test-only payloads remain under ``tests/``.

All content is fully synthetic: original characters, locations, and clues. No
real person, copyrighted franchise, real company, or existing fictional
character is used.
"""

from __future__ import annotations

from app.domain.models import (
    CharacterRef,
    ClueRef,
    LocationRef,
    RelationshipRef,
    WorldRule,
    WorldState,
)

WORLD_ID = "world-seorin-district"
WORLD_VERSION = "v1"

WORLD_STATE = WorldState(
    world_id=WORLD_ID,
    version=WORLD_VERSION,
    premise=(
        "매일 밤 자정, 서린 구의 공공 기억과 공식 기록에서 정확히 한 시간이 사라진다. "
        "시계는 움직이지만 주민들은 그 사이에 일어난 일을 기억하지 못한다. "
        "한 기록 보관 담당자가 일부 사람들이 사라진 시간 동안 의식을 유지한다는 "
        "필기 기록을 발견한다."
    ),
    genre="urban_mystery",
    world_rules=[
        WorldRule(
            rule_id="rule-missing-hour",
            description="매일 밤 자정에 서린 구에서 정확히 한 시간이 사라진다.",
        ),
        WorldRule(
            rule_id="rule-no-memory",
            description="대부분의 주민은 사라진 시간을 기억하지 못한다.",
        ),
        WorldRule(
            rule_id="rule-conscious-few",
            description="극소수의 사람들은 사라진 시간 동안 의식을 유지한다.",
        ),
        WorldRule(
            rule_id="rule-sealed-archive",
            description="봉인된 지하 기록 보관소가 존재한다.",
        ),
    ],
    characters=[
        CharacterRef(
            character_id="char-mina-seo",
            canonical_name="서민아",
            role="기록 보관 담당자",
            location_id="loc-municipal-archive",
            status="active",
            knowledge=[
                "사라진 시간을 부분적으로 기억한다",
                "봉인된 기록 보관소에서 누군가의 노크 소리를 들었다",
                "내일 날짜가 적힌 장부를 발견했다",
            ],
            relationships=[
                RelationshipRef(other_character_id="char-director-han", label="관련 인물"),
                RelationshipRef(other_character_id="char-jun-park", label="동료"),
            ],
            possessions=["기록 보관 열쇠", "미발견 장부"],
            injuries=[],
        ),
        CharacterRef(
            character_id="char-director-han",
            canonical_name="한국장",
            role="서린 구 기록국장",
            location_id="loc-municipal-archive",
            status="active",
            knowledge=[
                "사라진 시간의 존재를 예상한다",
                "13호실을 두려워한다",
                "장부의 제본을 인식한다",
            ],
            relationships=[
                RelationshipRef(other_character_id="char-mina-seo", label="상사"),
            ],
            possessions=["지하 마스터 열쇠"],
            injuries=[],
        ),
        CharacterRef(
            character_id="char-jun-park",
            canonical_name="박준",
            role="기록 기술자",
            location_id="loc-security-office",
            status="active",
            knowledge=[
                "보안 영상의 한 시간 공백을 알고 있다",
                "서민아의 동료이다",
            ],
            relationships=[
                RelationshipRef(other_character_id="char-mina-seo", label="신뢰 관계"),
            ],
            possessions=[],
            injuries=[],
        ),
    ],
    locations=[
        LocationRef(
            location_id="loc-municipal-archive",
            name="서린 구 기록 보관소",
            current_state="야간 영업 중",
            connected_locations=["loc-basement-archive", "loc-security-office"],
        ),
        LocationRef(
            location_id="loc-basement-archive",
            name="봉인된 지하 기록 보관소",
            current_state="봉인됨, 13호실 포함",
            connected_locations=["loc-municipal-archive"],
        ),
    ],
    clues=[
        ClueRef(
            clue_id="clue-ledger",
            description="내일 날짜와 서민아 필체의 경고 문구가 적힌 장부",
            resolved=False,
        ),
        ClueRef(
            clue_id="clue-room-thirteen",
            description="현재 도면에서 누락된 13호실의 존재",
            resolved=False,
        ),
        ClueRef(
            clue_id="clue-audio-frame",
            description="보안 영상의 한 시간 공백 속 서민아의 음성 프레임",
            resolved=False,
        ),
    ],
    canonical_timeline=[
        "자정 전: 서민아가 마지막 공공 기록에 도장을 찍는다",
        "자정: 모든 시계가 오전 2시로 점프한다",
        "자정 후: 서민아가 봉인된 기록 보관소에서 노크 소리를 듣는다",
    ],
    unresolved_global_questions=[
        "사라진 한 시간 동안 무슨 일이 일어나는가",
        "13호실에는 무엇이 있는가",
        "장부의 경고를 누가, 왜 썼는가",
    ],
    current_canon_episode=0,
)

# ── First canon episode plan ──────────────────────────────────────────────

CANON_EPISODE_1_PLAN = {
    "plan_version": "living-fiction-plan-v1",
    "world_id": WORLD_STATE.world_id,
    "world_version": WORLD_STATE.version,
    "episode_type": "canon",
    "episode_number": 1,
    "title": "사라진 한 시간",
    "synopsis": (
        "서민아가 마지막 공공 기록에 도장을 찍는 순간, 자정이 되고 "
        "모든 시계가 오전 2시로 점프한다. 그녀는 봉인된 지하 기록 보관소에서 "
        "노크 소리를 듣고, 내일 날짜가 적힌 장부를 발견한다."
    ),
    "canon_checkpoint_id": None,
    "prior_episode_id": None,
    "scenes": [
        {
            "scene_id": "scene-archive-midnight",
            "title": "기록 보관소의 자정",
            "purpose": "서민아가 마지막 기록에 도장을 찍고 자정을 맞이한다",
            "participating_character_ids": ["char-mina-seo"],
            "location_id": "loc-municipal-archive",
        },
        {
            "scene_id": "scene-knock-discovery",
            "title": "봉인된 문 너머의 노크",
            "purpose": "서민아가 봉인된 지하 기록 보관소에서 노크 소리를 듣는다",
            "participating_character_ids": ["char-mina-seo"],
            "location_id": "loc-municipal-archive",
        },
        {
            "scene_id": "scene-ledger-finding",
            "title": "내일의 장부",
            "purpose": "서민아가 내일 날짜와 자신의 필체 경고가 적힌 장부를 발견한다",
            "participating_character_ids": ["char-mina-seo"],
            "location_id": "loc-municipal-archive",
        },
    ],
    "participating_character_ids": ["char-mina-seo"],
    "location_ids": ["loc-municipal-archive"],
    "clue_refs": ["clue-ledger", "clue-room-thirteen"],
    "next_choice_options": [
        "혼자 지하 기록 보관소에 들어간다",
        "동료 박준에게 연락한다",
    ],
    "content_classification": "adult",
}

# ── First canon episode content ───────────────────────────────────────────

CANON_EPISODE_1_CONTENT = {
    "content_version": "living-fiction-content-v1",
    "world_id": WORLD_STATE.world_id,
    "episode_type": "canon",
    "episode_number": 1,
    "title": "사라진 한 시간",
    "synopsis": (
        "서민아가 마지막 공공 기록에 도장을 찍는 순간, 자정이 되고 "
        "모든 시계가 오전 2시로 점프한다. 그녀는 봉인된 지하 기록 보관소에서 "
        "노크 소리를 듣고, 내일 날짜가 적힌 장부를 발견한다."
    ),
    "canon_snapshot_id": None,
    "canon_checkpoint_id": None,
    "prior_episode_id": None,
    "reader_id": None,
    "scenes": CANON_EPISODE_1_PLAN["scenes"],
    "prose": [
        {
            "scene_id": "scene-archive-midnight",
            "paragraphs": [
                "오전 12시 59분, 기록 보관 담당자 서민아가 그날의 마지막 공공 기록에 도장을 찍었다. 초침이 자정을 넘어섰다. 건물 안의 모든 시계가 오전 2시로 점프했다.",
                "동료들은 아무 일도 없었다는 듯 짐을 쌌다. 서민아만이 봉인된 지하 기록 보관소 안에서 누군가 노크하는 소리를 기억했다.",
            ],
        },
        {
            "scene_id": "scene-knock-discovery",
            "paragraphs": [
                "봉인된 문 너머에서 들려오는 노크 소리. 서민아는 숨을 죽이고 귀를 기울였다. 세 번, 또 세 번. 규칙적인 간격이었다.",
                "그녀는 문을 열지 않았다. 대신 기록 보관소의 재고 목록을 확인했다. 현재 도면에는 13호실이 존재하지 않았다.",
            ],
        },
        {
            "scene_id": "scene-ledger-finding",
            "paragraphs": [
                "서민아의 책상 위에 그녀가 가져오지 않은 장부가 놓여 있었다. 첫 페이지에는 내일 날짜와 한 문장이 적혀 있었다.",
                "그녀 자신의 필체였다. 적혀 있는 문장은 단 하나: 한국장이 13호실을 열지 못하게 하라.",
            ],
        },
    ],
    "clue_refs": ["clue-ledger", "clue-room-thirteen"],
    "world_state_delta": {
        "character_knowledge_added": {
            "char-mina-seo": [
                "봉인된 기록 보관소에서 노크 소리를 들었다",
                "내일 날짜와 자신의 필체 경고가 적힌 장부를 발견했다",
            ],
        },
        "character_knowledge_sources": {
            "char-mina-seo": [
                "scene-archive-midnight: 기록 보관소에서 노크 소리 관찰",
                "scene-ledger-finding: 장부 발견",
            ],
        },
        "character_location_changed": {},
        "character_injuries_added": {},
        "character_possessions_added": {
            "char-mina-seo": ["미발견 장부"],
        },
        "clues_introduced": [],
        "clues_resolved": [],
        "unresolved_threads": [
            "사라진 한 시간 동안 무슨 일이 일어나는가",
            "13호실에는 무엇이 있는가",
            "장부의 경고를 누가, 왜 썼는가",
        ],
        "branch_only_facts": [],
    },
    "applied_reader_input": None,
    "unresolved_threads": [
        "사라진 한 시간 동안 무슨 일이 일어나는가",
        "13호실에는 무엇이 있는가",
        "장부의 경고를 누가, 왜 썼는가",
    ],
    "next_choice_options": [
        "혼자 지하 기록 보관소에 들어간다",
        "동료 박준에게 연락한다",
    ],
    "content_classification": "adult",
    "review_state": "pending_review",
}

# ── Personal branch episode plan ──────────────────────────────────────────

BRANCH_EPISODE_PLAN = {
    "plan_version": "living-fiction-plan-v1",
    "world_id": WORLD_STATE.world_id,
    "world_version": WORLD_STATE.version,
    "episode_type": "personal_branch",
    "episode_number": 1,
    "title": "신중한 조사",
    "synopsis": (
        "서민아는 장부를 숨기고, 13호실이 과거 도면에 존재했는지 확인한다. "
        "한국장이 지하 마스터 열쇠를 요청하지만, 서민아는 정면 대결을 피한다."
    ),
    "canon_checkpoint_id": "checkpoint-canon-1",
    "prior_episode_id": "episode-canon-1",
    "scenes": [
        {
            "scene_id": "scene-inventory-check",
            "title": "도면 확인",
            "purpose": "서민아가 기록 보관 재고를 확인하고 13호실의 과거 존재를 발견한다",
            "participating_character_ids": ["char-mina-seo"],
            "location_id": "loc-municipal-archive",
        },
        {
            "scene_id": "scene-key-request",
            "title": "국장의 요청",
            "purpose": "한국장이 이유 없이 지하 마스터 열쇠를 요청한다",
            "participating_character_ids": ["char-mina-seo", "char-director-han"],
            "location_id": "loc-municipal-archive",
        },
        {
            "scene_id": "scene-ledger-hidden",
            "title": "장부를 숨기다",
            "purpose": "서민아는 장부를 정면 대결 대신 숨긴다",
            "participating_character_ids": ["char-mina-seo"],
            "location_id": "loc-municipal-archive",
        },
    ],
    "participating_character_ids": ["char-mina-seo", "char-director-han"],
    "location_ids": ["loc-municipal-archive"],
    "clue_refs": ["clue-ledger", "clue-room-thirteen", "clue-audio-frame"],
    "next_choice_options": [
        "보안 영상의 공백을 확인한다",
        "박준에게 연락한다",
    ],
    "content_classification": "adult",
}

# ── Personal branch episode content ───────────────────────────────────────

BRANCH_EPISODE_CONTENT = {
    "content_version": "living-fiction-content-v1",
    "world_id": WORLD_STATE.world_id,
    "episode_type": "personal_branch",
    "episode_number": 1,
    "title": "신중한 조사",
    "synopsis": (
        "서민아는 장부를 숨기고, 13호실이 과거 도면에 존재했는지 확인한다. "
        "한국장이 지하 마스터 열쇠를 요청하지만, 서민아는 정면 대결을 피한다."
    ),
    "canon_snapshot_id": None,
    "canon_checkpoint_id": "checkpoint-canon-1",
    "prior_episode_id": "episode-canon-1",
    "reader_id": "reader-test-1",
    "scenes": BRANCH_EPISODE_PLAN["scenes"],
    "prose": [
        {
            "scene_id": "scene-inventory-check",
            "paragraphs": [
                "서민아는 기록 보관 재고를 꺼냈다. 현재 도면에는 13호실이 없었다. 하지만 21년 전의 종이 도면에는 그 방이 표시되어 있었고, '21년 전 폐쇄'라고 적혀 있었다.",
                "그녀는 장부를 책상 서랍 깊숙이 넣었다. 독자의 선택에 따라 신중하게 조사하기로 했다.",
            ],
        },
        {
            "scene_id": "scene-key-request",
            "paragraphs": [
                "한국장이 복도에서 서민아를 불렀다. 지하 마스터 열쇠를 달라고 했다. 이유를 대지 않았다.",
                "서민아는 장부에 대해 말하지 않았다. 대신 열쇠는 보안실에 있다고 말했다.",
            ],
        },
        {
            "scene_id": "scene-ledger-hidden",
            "paragraphs": [
                "서민아는 장부를 개인 사물함 안쪽에 숨겼다. 보안 영상에는 한 시간의 공백이 있었지만, 그 공백 속 서민아의 음성 프레임 하나가 남아 있었다.",
                "그녀가 인식하지 못하는 이름을 말하는 음성이었다.",
            ],
        },
    ],
    "clue_refs": ["clue-ledger", "clue-room-thirteen", "clue-audio-frame"],
    "world_state_delta": {
        "character_knowledge_added": {
            "char-mina-seo": [
                "13호실이 21년 전 도면에 존재했음을 확인했다",
                "보안 영상에 한 시간 공백과 음성 프레임이 있음을 알게 되었다",
            ],
            "char-director-han": [
                "지하 마스터 열쇠를 요청했으나 거절당했다",
            ],
        },
        "character_knowledge_sources": {
            "char-mina-seo": [
                "scene-inventory-check: 도면에서 13호실 과거 존재 확인",
                "scene-ledger-hidden: 보안 영상 공백과 음성 프레임 발견",
            ],
            "char-director-han": [
                "scene-key-request: 복도에서 마스터 열쇠 요청",
            ],
        },
        "character_location_changed": {},
        "character_injuries_added": {},
        "character_possessions_added": {
            "char-mina-seo": ["숨겨진 장부", "미발견 장부", "기록 보관 열쇠"],
        },
        "clues_introduced": [],
        "clues_resolved": [],
        "unresolved_threads": [
            "13호실은 왜 21년 전에 폐쇄되었는가",
            "보안 영상 공백 속 음성 프레임의 정체는 무엇인가",
            "한국장은 13호실에 무엇을 하려 하는가",
        ],
        "branch_only_facts": [
            "서민아가 장부를 개인 사물함에 숨겼다",
            "서민아가 13호실의 과거 도면 존재를 확인했다",
        ],
    },
    "applied_reader_input": {
        "reader_choice_id": "choice-cautious-investigation",
        "choice_text": "신중하게 조사한다",
        "comment": "한국장을 직접 대면하지 말고 증거를 먼저 확보해",
        "applied_evidence": (
            "독자의 '신중한 조사' 선택에 따라 서민아는 장부를 숨기고 "
            "13호실의 과거 존재를 확인하며, 한국장과의 정면 대결을 피했다. "
            "독자의 댓글대로 증거를 먼저 확보하는 행동을 취했다."
        ),
    },
    # NOTE: The reader_choice_id above is a FIXED fixture ID.
    # Tests that need a different choice_id should override this payload.
    "unresolved_threads": [
        "사라진 한 시간 동안 무슨 일이 일어나는가",
        "13호실에는 무엇이 있는가",
        "장부의 경고를 누가, 왜 썼는가",
        "13호실은 왜 21년 전에 폐쇄되었는가",
        "보안 영상 공백 속 음성 프레임의 정체는 무엇인가",
        "한국장은 13호실에 무엇을 하려 하는가",
    ],
    "next_choice_options": [
        "보안 영상의 공백을 확인한다",
        "박준에게 연락한다",
    ],
    "content_classification": "adult",
    "review_state": "pending_review",
}
