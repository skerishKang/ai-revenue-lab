"""Deterministic fixtures for the static UI preview.

All video data uses real, publicly available YouTube videos verified via
oEmbed.  Every id and timestamp is a fixed constant so that repeated
builds produce byte-identical output (a hard requirement for the preview
build).

The fixtures reuse the real domain models so the preview renders exactly
the same shapes the live templates consume.
"""

from __future__ import annotations

import json

from app.domain.enums import (
    DefaultSort,
    DurationPreference,
    ProposalStatus,
    ProposalType,
    ShortsPreference,
    ValidationStatus,
    ViewingState,
)
from app.domain.models import (
    DiscoveredVideo,
    PrivateViewingRecord,
    ProposalRecord,
    QueryRule,
    QueryRuleProposal,
    TimestampReference,
    Topic,
    TopicVideo,
)

# Kept for backward compatibility; videos now use real YouTube thumbnails.
THUMBNAIL_URL = "/static/preview-thumb.svg"

_CREATED_AT = "2026-01-21T00:00:00Z"


# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------

def make_topics() -> list[Topic]:
    return [
        Topic(
            id="pv-topic-0001",
            name="AI 기초",
            intent=(
                "신경망, 트랜스포머, 딥러닝 기초를 다루는 강의와 튜토리얼. "
                "영어 또는 한국어."
            ),
            is_archived=False,
            created_at="2026-01-05T09:00:00Z",
            updated_at="2026-01-05T09:00:00Z",
        ),
        Topic(
            id="pv-topic-0002",
            name="소프트웨어 개발",
            intent=(
                "파이썬, 자바스크립트, 러스트 등 실무 프로그래밍 영상. "
                "영어 또는 한국어."
            ),
            is_archived=False,
            created_at="2026-01-08T11:30:00Z",
            updated_at="2026-01-08T11:30:00Z",
        ),
        Topic(
            id="pv-topic-0003",
            name="보관된 토픽",
            intent="보관 처리된 토픽 (영상 없음).",
            is_archived=True,
            created_at="2025-11-20T08:00:00Z",
            updated_at="2025-12-01T08:00:00Z",
        ),
    ]


def make_topic(topic_id: str = "pv-topic-0001") -> Topic:
    for topic in make_topics():
        if topic.id == topic_id:
            return topic
    return make_topics()[0]


# ---------------------------------------------------------------------------
# Query rule + LLM rule proposal
# ---------------------------------------------------------------------------

def make_query_rule() -> QueryRule:
    return QueryRule(
        id="pv-rule-0001",
        topic_id="pv-topic-0001",
        primary_query="neural network tutorial",
        related_queries=["deep learning basics", "transformer attention"],
        required_terms=["neural network"],
        excluded_terms=["shorts", "reaction"],
        preferred_languages=["en", "ko"],
        included_channels=[],
        excluded_channels=[],
        duration_preference=DurationPreference.MEDIUM,
        shorts_preference=ShortsPreference.EXCLUDE,
        default_sort=DefaultSort.NEWEST,
        is_active=True,
        created_at="2026-01-05T09:05:00Z",
        updated_at="2026-01-05T09:05:00Z",
    )


def make_query_rule_proposal() -> QueryRuleProposal:
    return QueryRuleProposal(
        primary_query="neural network tutorial",
        related_queries=["deep learning basics", "transformer attention"],
        required_terms=["neural network"],
        excluded_terms=["shorts", "reaction"],
        preferred_languages=["en", "ko"],
        included_channels=[],
        excluded_channels=[],
        duration_preference=DurationPreference.MEDIUM,
        shorts_preference=ShortsPreference.EXCLUDE,
        default_sort=DefaultSort.NEWEST,
        date_window_start="2017-01-01",
        date_window_end=None,
        rationale=(
            "신경망 기초를 다루는 중급 길이 영상을 최신순으로 검색하며, "
            "숏츠와 리액션 콘텐츠는 제외합니다."
        ),
    )


# ---------------------------------------------------------------------------
# Videos — real, oEmbed-verified YouTube videos
# ---------------------------------------------------------------------------

def _make_real_video(
    internal_id: str,
    yt_id: str,
    title: str,
    channel_title: str,
    channel_id: str,
    published_at: str,
    duration_seconds: int,
    view_count: int,
    description: str = "",
) -> DiscoveredVideo:
    return DiscoveredVideo(
        id=internal_id,
        provider="youtube",
        provider_video_id=yt_id,
        canonical_url=f"https://www.youtube.com/watch?v={yt_id}",
        title=title,
        description=description,
        channel_id=channel_id,
        channel_title=channel_title,
        published_at=published_at,
        duration_seconds=duration_seconds,
        view_count=view_count,
        like_count=None,
        thumbnail_url=f"https://i.ytimg.com/vi/{yt_id}/hqdefault.jpg",
        tags=[],
        created_at=_CREATED_AT,
        updated_at=_CREATED_AT,
    )


def make_topic1_videos() -> list[DiscoveredVideo]:
    """AI 기초: 1 completed + 2 unseen."""
    return [
        _make_real_video(
            "pv-video-0001",
            "aircAruvnKk",
            "But what is a neural network? | Deep learning chapter 1",
            "3Blue1Brown",
            "@3blue1brown",
            "2017-10-05T00:00:00Z",
            1120,
            23700000,
            "The most intuitive explanation of neural networks.",
        ),
        _make_real_video(
            "pv-video-0002",
            "eMlx5fFNoYc",
            "Attention in transformers, step-by-step | Deep Learning Chapter 6",
            "3Blue1Brown",
            "@3blue1brown",
            "2024-04-07T00:00:00Z",
            1569,
            4300000,
            "How attention works in transformer models.",
        ),
        _make_real_video(
            "pv-video-0003",
            "OIY2tWT3HHI",
            "전공생이 알려주는 AI(인공지능) 필수지식, 누구든 10분이면 이해 끝 | [허성범의 AI학개론]  -1강",
            "허성범 Horang",
            "@horangwave",
            "2025-02-23T00:00:00Z",
            1210,
            644000,
            "AI 필수 지식을 10분 만에 이해하기.",
        ),
    ]


def make_topic2_videos() -> list[DiscoveredVideo]:
    """소프트웨어 개발: in_progress, opened, revisit, saved, irrelevant."""
    return [
        _make_real_video(
            "pv-video-0004",
            "rfscVS0vtbw",
            "Learn Python - Full Course for Beginners [Tutorial]",
            "freeCodeCamp.org",
            "@freecodecamp",
            "2018-07-11T00:00:00Z",
            16012,
            49000000,
            "Complete Python course for beginners.",
        ),
        _make_real_video(
            "pv-video-0005",
            "lkIFF4maKMU",
            "100+ JavaScript Concepts you Need to Know",
            "Fireship",
            "@Fireship",
            "2022-11-22T00:00:00Z",
            743,
            3000000,
            "Every JavaScript concept explained in 12 minutes.",
        ),
        _make_real_video(
            "pv-video-0006",
            "5C_HPTJg5ek",
            "Rust in 100 Seconds",
            "Fireship",
            "@Fireship",
            "2021-10-12T00:00:00Z",
            149,
            2500000,
            "Rust explained in 100 seconds.",
        ),
        _make_real_video(
            "pv-video-0007",
            "kWiCuklohdY",
            "파이썬 코딩 무료 강의 (기본편) - 6시간 뒤면 여러분도 개발자가 될 수 있어요 [나도코딩]",
            "나도코딩",
            "@nadocoding",
            "2020-02-20T00:00:00Z",
            21687,
            5900000,
            "6시간 파이썬 기본 강의.",
        ),
        _make_real_video(
            "pv-video-0008",
            "SzJ46YA_RaA",
            "Map of Computer Science",
            "Domain of Science",
            "@ScienceMaps",
            "2017-09-06T00:00:00Z",
            658,
            6800000,
            "A map of the entire field of computer science.",
        ),
    ]


# ---------------------------------------------------------------------------
# Topic-video associations
# ---------------------------------------------------------------------------

def _make_topic_video(
    n: int,
    topic_id: str,
    video_id: str,
    match_score: float | None,
    match_reasons: list[str],
    first_matched_at: str,
) -> TopicVideo:
    return TopicVideo(
        id=f"pv-tv-{n:04d}",
        topic_id=topic_id,
        video_id=video_id,
        first_matched_at=first_matched_at,
        last_matched_at=first_matched_at,
        match_score=match_score,
        match_reasons=match_reasons,
        is_excluded=False,
        created_at=first_matched_at,
        updated_at=first_matched_at,
    )


def make_topic1_topic_videos() -> list[TopicVideo]:
    videos = make_topic1_videos()
    return [
        _make_topic_video(
            1, "pv-topic-0001", videos[0].id, 0.95,
            ["신경망 기초를 명확하게 설명", "시각적 설명이 뛰어남"],
            "2026-01-21T00:05:00Z",
        ),
        _make_topic_video(
            2, "pv-topic-0001", videos[1].id, 0.91,
            ["트랜스포머 어텐션 메커니즘 설명"],
            "2026-01-21T00:05:00Z",
        ),
        _make_topic_video(
            3, "pv-topic-0001", videos[2].id, 0.87,
            ["한국어 AI 입문 강의", "10분 요약 형식"],
            "2026-01-21T00:05:00Z",
        ),
    ]


def make_topic2_topic_videos() -> list[TopicVideo]:
    videos = make_topic2_videos()
    return [
        _make_topic_video(
            4, "pv-topic-0002", videos[0].id, 0.93,
            ["파이썬 입문 전체 과정"],
            "2026-01-21T00:06:00Z",
        ),
        _make_topic_video(
            5, "pv-topic-0002", videos[1].id, 0.88,
            ["자바스크립트 핵심 개념 정리"],
            "2026-01-21T00:06:00Z",
        ),
        _make_topic_video(
            6, "pv-topic-0002", videos[2].id, 0.82,
            ["러스트 언어 개요"],
            "2026-01-21T00:06:00Z",
        ),
        _make_topic_video(
            7, "pv-topic-0002", videos[3].id, 0.90,
            ["한국어 파이썬 기본 강의", "6시간 전체 과정"],
            "2026-01-21T00:06:00Z",
        ),
        _make_topic_video(
            8, "pv-topic-0002", videos[4].id, 0.75,
            ["컴퓨터 과학 전체 지도"],
            "2026-01-21T00:06:00Z",
        ),
    ]


# ---------------------------------------------------------------------------
# Private viewing records
# ---------------------------------------------------------------------------

def make_record_completed() -> PrivateViewingRecord:
    """An accepted, fully structured private record (aircAruvnKk)."""
    return PrivateViewingRecord(
        id="pv-rec-0001",
        topic_video_id="pv-tv-0001",
        viewing_state=ViewingState.COMPLETED,
        rating=5,
        reflection=(
            "신경망의 기본 구조를 시각적으로 설명해주는 최고의 영상. "
            "가중치와 편향이 어떻게 학습되는지 직관적으로 이해할 수 있었다."
        ),
        learned_point=(
            "역전파는 체인 룰을 반복 적용하는 것이며, "
            "경사 하강법이 매개변수를 업데이트하는 핵심 메커니즘이다."
        ),
        agreement="시각적 비유가 수학적 개념을 이해하는 데 매우 효과적이다.",
        disagreement="활성화 함수 선택에 대한 논의가 부족했다.",
        uncertainty="배치 정규화가 학습 안정성에 미치는 정확한 영향.",
        follow_up_plan="3Blue1Brown 시리즈 나머지 영상도 시청하기.",
        free_form_note=(
            "원본 메모: 가중치 행렬 곱셈 → 편향 추가 → 활성화 함수 순서. "
            "이 텍스트는 AI 제안에 의해 덮어쓰이지 않는다."
        ),
        tags=["neural-network", "deep-learning"],
        opened_date="2026-01-21",
        completed_date="2026-01-22",
        timestamp_references=[],
        created_at="2026-01-21T10:00:00Z",
        updated_at="2026-01-22T18:00:00Z",
    )


def make_record_in_progress() -> PrivateViewingRecord:
    """A record mid-viewing with rough notes and a pending AI proposal (rfscVS0vtbw)."""
    return PrivateViewingRecord(
        id="pv-rec-0002",
        topic_video_id="pv-tv-0004",
        viewing_state=ViewingState.IN_PROGRESS,
        rating=None,
        reflection="",
        learned_point="",
        agreement="",
        disagreement="",
        uncertainty="",
        follow_up_plan="",
        free_form_note=(
            "메모: 변수, 자료형, 조건문, 반복문, 함수, 클래스 순서로 진행. "
            "리스트 내포 표현 다시 보기 필요."
        ),
        tags=["python"],
        opened_date="2026-01-21",
        completed_date=None,
        timestamp_references=[],
        created_at="2026-01-21T11:00:00Z",
        updated_at="2026-01-21T11:30:00Z",
    )


def make_record_in_progress_2() -> PrivateViewingRecord:
    """A second in_progress record for continue-watching (eMlx5fFNoYc)."""
    return PrivateViewingRecord(
        id="pv-rec-0007",
        topic_video_id="pv-tv-0002",
        viewing_state=ViewingState.IN_PROGRESS,
        rating=None,
        reflection="",
        learned_point="",
        agreement="",
        disagreement="",
        uncertainty="",
        follow_up_plan="",
        free_form_note="메모: 어텐션 메커니즘 시각화 부분 다시 보기.",
        tags=["transformer", "attention"],
        opened_date="2026-01-22",
        completed_date=None,
        timestamp_references=[],
        created_at="2026-01-22T09:00:00Z",
        updated_at="2026-01-22T10:00:00Z",
    )


def make_record_saved() -> PrivateViewingRecord:
    """A minimal saved record (kWiCuklohdY)."""
    return PrivateViewingRecord(
        id="pv-rec-0003",
        topic_video_id="pv-tv-0007",
        viewing_state=ViewingState.SAVED,
        rating=4,
        reflection="",
        learned_point="",
        agreement="",
        disagreement="",
        uncertainty="",
        follow_up_plan="주말에 함수 파트부터 다시 보기.",
        free_form_note="나중에 보기 위해 저장 — 파이썬 기본 문법 복습용.",
        tags=["python", "korean"],
        opened_date=None,
        completed_date=None,
        timestamp_references=[],
        created_at="2026-01-21T12:00:00Z",
        updated_at="2026-01-21T12:00:00Z",
    )


def make_record_opened() -> PrivateViewingRecord:
    """A minimal opened record (lkIFF4maKMU)."""
    return PrivateViewingRecord(
        id="pv-rec-0004",
        topic_video_id="pv-tv-0005",
        viewing_state=ViewingState.OPENED,
        rating=None,
        reflection="",
        learned_point="",
        agreement="",
        disagreement="",
        uncertainty="",
        follow_up_plan="",
        free_form_note="",
        tags=[],
        opened_date="2026-01-22",
        completed_date=None,
        timestamp_references=[],
        created_at="2026-01-22T09:00:00Z",
        updated_at="2026-01-22T09:00:00Z",
    )


def make_record_revisit() -> PrivateViewingRecord:
    """A minimal revisit record (5C_HPTJg5ek)."""
    return PrivateViewingRecord(
        id="pv-rec-0005",
        topic_video_id="pv-tv-0006",
        viewing_state=ViewingState.REVISIT,
        rating=3,
        reflection="",
        learned_point="",
        agreement="",
        disagreement="",
        uncertainty="",
        follow_up_plan="소유권 개념 부분 다시 보기.",
        free_form_note="짧지만 핵심 요약. 소유권 부분 복습 필요.",
        tags=["rust"],
        opened_date="2026-01-20",
        completed_date=None,
        timestamp_references=[],
        created_at="2026-01-20T14:00:00Z",
        updated_at="2026-01-20T14:00:00Z",
    )


def make_record_irrelevant() -> PrivateViewingRecord:
    """A minimal irrelevant record (SzJ46YA_RaA)."""
    return PrivateViewingRecord(
        id="pv-rec-0006",
        topic_video_id="pv-tv-0008",
        viewing_state=ViewingState.IRRELEVANT,
        rating=None,
        reflection="",
        learned_point="",
        agreement="",
        disagreement="",
        uncertainty="",
        follow_up_plan="",
        free_form_note="전체 CS 지도 — 현재 학습 목표와 직접 관련 없음.",
        tags=[],
        opened_date=None,
        completed_date=None,
        timestamp_references=[],
        created_at="2026-01-21T15:00:00Z",
        updated_at="2026-01-21T15:00:00Z",
    )


def make_timestamps() -> list[TimestampReference]:
    return [
        TimestampReference(
            id="pv-ts-0001",
            record_id="pv-rec-0001",
            timestamp_seconds=125,
            label="뉴런 구조 설명",
            created_at="2026-01-22T18:00:00Z",
        ),
        TimestampReference(
            id="pv-ts-0002",
            record_id="pv-rec-0001",
            timestamp_seconds=754,
            label="역전파 시각화",
            created_at="2026-01-22T18:00:00Z",
        ),
    ]


# ---------------------------------------------------------------------------
# LLM structure proposal (pending)
# ---------------------------------------------------------------------------

def make_structure_proposal() -> ProposalRecord:
    proposed = {
        "title": "파이썬 입문 전체 과정",
        "summary": "변수부터 클래스까지 파이썬 기초를 다루는 4시간 강의.",
        "reflection": "리스트 내포 표현이 가장 유용했다.",
        "learned_point": "함수의 기본 인자는 가변 객체를 피해야 한다.",
        "agreement": "실습 위주 구성이 이해에 도움이 된다.",
        "disagreement": "",
        "uncertainty": "제너레이터와 이터레이터의 차이.",
        "follow_up_plan": "함수 파트를 다시 보고 노트 정리.",
        "tags": ["python", "tutorial"],
        "rating": 4,
    }
    return ProposalRecord(
        id="pv-prop-0001",
        topic_id=None,
        record_id="pv-rec-0002",
        proposal_type=ProposalType.RECORD_STRUCTURE,
        status=ProposalStatus.PENDING,
        input_text=(
            "메모: 변수, 자료형, 조건문, 반복문, 함수, 클래스 순서로 진행. "
            "리스트 내포 표현 다시 보기 필요."
        ),
        proposed_json=json.dumps(proposed, ensure_ascii=False, indent=2, sort_keys=True),
        validation_status=ValidationStatus.VALID,
        validation_error="",
        created_at="2026-01-21T11:45:00Z",
        decided_at=None,
    )


# ---------------------------------------------------------------------------
# Feed assembly helpers
# ---------------------------------------------------------------------------

def make_topic1_feed() -> list[tuple[TopicVideo, DiscoveredVideo, PrivateViewingRecord | None]]:
    """AI 기초 feed: 1 completed + 2 unseen."""
    videos = make_topic1_videos()
    tvs = make_topic1_topic_videos()
    rec_completed = make_record_completed()
    records_by_tv = {
        "pv-tv-0001": rec_completed,
    }
    return [
        (tvs[i], videos[i], records_by_tv.get(tvs[i].id))
        for i in range(len(videos))
    ]


def make_topic2_feed() -> list[tuple[TopicVideo, DiscoveredVideo, PrivateViewingRecord | None]]:
    """소프트웨어 개발 feed: in_progress, opened, revisit, saved, irrelevant."""
    videos = make_topic2_videos()
    tvs = make_topic2_topic_videos()
    records_by_tv = {
        "pv-tv-0004": make_record_in_progress(),
        "pv-tv-0005": make_record_opened(),
        "pv-tv-0006": make_record_revisit(),
        "pv-tv-0007": make_record_saved(),
        "pv-tv-0008": make_record_irrelevant(),
    }
    return [
        (tvs[i], videos[i], records_by_tv.get(tvs[i].id))
        for i in range(len(videos))
    ]


def filter_feed_by_state(
    feed: list[tuple[TopicVideo, DiscoveredVideo, PrivateViewingRecord | None]],
    state: str,
) -> list[tuple[TopicVideo, DiscoveredVideo, PrivateViewingRecord | None]]:
    """Mirror the app's viewing-state filter for the preview."""
    out = []
    for tv, video, record in feed:
        record_state = record.viewing_state.value if record else ViewingState.UNSEEN.value
        if record_state == state:
            out.append((tv, video, record))
    return out


def make_search_results() -> list[tuple[PrivateViewingRecord, TopicVideo, DiscoveredVideo]]:
    topic1_videos = make_topic1_videos()
    topic1_tvs = make_topic1_topic_videos()
    topic2_videos = make_topic2_videos()
    topic2_tvs = make_topic2_topic_videos()
    return [
        (make_record_completed(), topic1_tvs[0], topic1_videos[0]),
        (make_record_in_progress(), topic2_tvs[0], topic2_videos[0]),
        (make_record_saved(), topic2_tvs[3], topic2_videos[3]),
    ]
