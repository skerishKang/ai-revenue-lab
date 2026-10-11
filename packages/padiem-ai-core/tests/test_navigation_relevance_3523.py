"""#3523 official-site Korean navigational queries: exact topical grounding."""
from padiem_ai_core.contracts import Evidence
from padiem_ai_core.source_quality import (
    SourceQualityPolicy, assess_source_quality, select_grounding_evidence,
    _significant_query_tokens,
)


def evidence(title, url="https://www.seoul.go.kr/", snippet="시민참여, 주요서비스, 새소식"):
    return Evidence(
        id="official-1", title=title, url=url, snippet=snippet,
        retrieved_at="2026-10-10T00:00:00Z",
        provider="tinyfish", source_type="search",
    )


def test_city_official_homepage_result_is_not_lost_due_to_navigation_words():
    query="서울특별시 공식 누리집"
    item=evidence("삶의 질 특별시 서울 | 서울특별시")
    assessment=assess_source_quality(query,item)
    assert _significant_query_tokens(query)==("서울특별시",)
    assert assessment.relevance_score>=0.18
    assert [x.id for x in select_grounding_evidence(query,[item]).evidence]==["official-1"]


def test_nav_word_suppression_never_changes_entity_exact_match():
    wrong=evidence("서울시 안내",url="https://www.seoul.go.kr/")
    assert select_grounding_evidence("서울특별시 공식 누리집",[wrong]).evidence == ()
    assert _significant_query_tokens("피타고라스 공식")==("피타고라스","공식")
    assert _significant_query_tokens("공식 누리집")==("공식","누리집")


def test_unrelated_official_websites_still_fail_query_relevance():
    wrong=evidence("부산광역시 공식 누리집",url="https://www.busan.go.kr/")
    assert select_grounding_evidence("서울특별시 공식 누리집",[wrong]).evidence==()


def test_generic_topic_without_navigation_remains_unchanged():
    assert _significant_query_tokens("서울특별시 인구 통계")==("서울특별시","인구","통계")
