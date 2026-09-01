from __future__ import annotations

from padiem_ai_core.contracts import Evidence
from padiem_ai_core.search_decision import decide_search
from padiem_ai_core.source_quality import (
    SourceQualityPolicy,
    SourceTier,
    assess_source_quality,
    select_grounding_evidence,
)


def _ev(
    evidence_id: str,
    *,
    title: str,
    snippet: str,
    url: str,
    provider: str = "daum",
) -> Evidence:
    return Evidence(
        id=evidence_id,
        title=title,
        snippet=snippet,
        retrieved_at="2026-09-01T00:00:00Z",
        provider=provider,
        source_type="search",
        url=url,
    )


def test_exact_korean_entity_token_rejects_substring_near_match() -> None:
    good = _ev(
        "good",
        title="Padiem 파디엠 AI",
        snippet="파디엠의 공식 제품 안내",
        url="https://padiem.net/",
    )
    bad = _ev(
        "bad",
        title="모 딸님의 영어로 민주 디엠",
        snippet="가입하자마자 디엠이 왔어요",
        url="https://example.com/dm",
    )

    selection = select_grounding_evidence("파디엠", [bad, good])

    assert [item.id for item in selection.evidence] == ["good"]
    bad_assessment = assess_source_quality("파디엠", bad)
    assert bad_assessment.relevance_score == 0.0
    assert "no_exact_query_token_match" in bad_assessment.reasons


def test_authoritative_hint_outranks_community_for_current_fact() -> None:
    query = "현재 한국은행 기준금리"
    policy = SourceQualityPolicy(authoritative_domains=("bok.or.kr",))
    community = _ev(
        "community",
        title="한국은행 기준금리 현재 전망",
        snippet="한국은행 기준금리 관련 이용자 글",
        url="https://www.fmkorea.com/123",
    )
    official = _ev(
        "official",
        title="한국은행 기준금리",
        snippet="현재 한국은행 기준금리 안내",
        url="https://www.bok.or.kr/portal/singl/baseRate/list.do",
    )

    selection = select_grounding_evidence(query, [community, official], policy=policy)

    assert [item.id for item in selection.evidence][:2] == ["official", "community"]
    assert selection.assessments[0].tier is SourceTier.PRIMARY
    assert selection.assessments[1].tier is SourceTier.COMMUNITY
    assert selection.assessments[0].total_score > selection.assessments[1].total_score


def test_generic_go_kr_is_primary_signal() -> None:
    evidence = _ev(
        "gov",
        title="정부 정책 안내",
        snippet="현재 정부 정책의 공식 안내입니다",
        url="https://www.example.go.kr/policy",
    )

    assessment = assess_source_quality("현재 정부 정책", evidence)

    assert assessment.tier is SourceTier.PRIMARY
    assert "official_domain_pattern" in assessment.reasons


def test_community_source_remains_eligible_for_sentiment_intent() -> None:
    query = "금리 인상에 대한 커뮤니티 반응 후기"
    community = _ev(
        "community",
        title="금리 인상 커뮤니티 반응 후기",
        snippet="이용자들이 남긴 금리 인상 경험과 반응",
        url="https://www.reddit.com/r/korea/comments/example",
    )

    assessment = assess_source_quality(query, community, decision=decide_search(query))
    selection = select_grounding_evidence(query, [community])

    assert assessment.tier is SourceTier.COMMUNITY
    assert assessment.authority_score == 0.72
    assert "community_intent" in assessment.reasons
    assert [item.id for item in selection.evidence] == ["community"]


def test_irrelevant_results_are_removed_before_selection() -> None:
    relevant = _ev(
        "relevant",
        title="Node.js LTS version guide",
        snippet="Node.js LTS version information",
        url="https://nodejs.org/en/about/previous-releases",
    )
    irrelevant = _ev(
        "irrelevant",
        title="오늘의 저녁 메뉴",
        snippet="간단한 요리 추천",
        url="https://example.com/dinner",
    )

    selection = select_grounding_evidence("현재 Node.js LTS version", [irrelevant, relevant])

    assert [item.id for item in selection.evidence] == ["relevant"]
    assert selection.rejected_count == 1


def test_canonical_url_duplicates_are_deduplicated() -> None:
    first = _ev(
        "first",
        title="한국은행 기준금리",
        snippet="한국은행 기준금리 안내",
        url="https://www.bok.or.kr/rate#top",
    )
    duplicate = _ev(
        "duplicate",
        title="한국은행 기준금리",
        snippet="같은 페이지의 다른 조각 링크",
        url="https://www.bok.or.kr/rate#detail",
    )

    selection = select_grounding_evidence("한국은행 기준금리", [first, duplicate])

    assert [item.id for item in selection.evidence] == ["first"]


def test_all_irrelevant_candidates_fail_to_select_evidence() -> None:
    items = [
        _ev(
            "one",
            title="저녁 메뉴 추천",
            snippet="오늘 먹을 음식",
            url="https://example.com/food",
        ),
        _ev(
            "two",
            title="축구 경기 후기",
            snippet="경기 관람 후기",
            url="https://www.reddit.com/r/soccer/comments/example",
        ),
    ]

    selection = select_grounding_evidence("파디엠", items)

    assert selection.evidence == ()
    assert selection.assessments == ()
    assert selection.rejected_count == 2


def test_trusted_secondary_hint_is_bounded_and_explicit() -> None:
    policy = SourceQualityPolicy(trusted_secondary_domains=("example-news.test",))
    evidence = _ev(
        "news",
        title="한국은행 기준금리 뉴스",
        snippet="한국은행 기준금리 관련 보도",
        url="https://economy.example-news.test/article/1",
    )

    assessment = assess_source_quality("한국은행 기준금리", evidence, policy=policy)

    assert assessment.tier is SourceTier.TRUSTED_SECONDARY
    assert assessment.authority_score == 0.78


def test_domain_hints_do_not_accept_urls_or_overlapping_authority() -> None:
    try:
        SourceQualityPolicy(authoritative_domains=("https://bok.or.kr",))
    except ValueError as exc:
        assert "plain hostname" in str(exc)
    else:
        raise AssertionError("URL-shaped domain hint must be rejected")

    try:
        SourceQualityPolicy(
            authoritative_domains=("bok.or.kr",),
            trusted_secondary_domains=("bok.or.kr",),
        )
    except ValueError as exc:
        assert "both authoritative and trusted-secondary" in str(exc)
    else:
        raise AssertionError("overlapping domain authority must be rejected")
