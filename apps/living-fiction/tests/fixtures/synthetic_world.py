"""Synthetic world fixture for Living Fiction Phase 1.

A fully synthetic near-future Korean city district with original characters,
locations, and clues. No real person, copyrighted franchise, real company,
or existing fictional character is used.

Working title: "The City That Loses an Hour"
All names are project-created placeholders.
"""

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
