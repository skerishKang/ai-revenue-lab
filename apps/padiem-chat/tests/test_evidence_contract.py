from __future__ import annotations

from padiem_ai_core import Evidence as CoreEvidence

from app.evidence import Evidence


def test_b62_evidence_is_core_contract_and_preserves_positional_constructor():
    item = Evidence(
        "ev_compat_1",
        "Compatibility source",
        "https://example.com/source",
        "Evidence snippet",
        "2026-08-26T00:00:00Z",
        "mock",
        "search",
    )

    assert isinstance(item, CoreEvidence)
    assert item.id == "ev_compat_1"
    assert item.title == "Compatibility source"
    assert item.url == "https://example.com/source"
    assert item.snippet == "Evidence snippet"
    assert item.retrieved_at == "2026-08-26T00:00:00Z"
    assert item.provider == "mock"
    assert item.source_type == "search"


def test_b62_public_dict_and_core_public_dict_remain_equivalent():
    item = Evidence(
        id="ev_compat_2",
        title="Keyword source",
        url="https://example.com/keyword",
        snippet="Keyword construction still works",
        retrieved_at="2026-08-26T00:00:00Z",
        provider="mock",
        source_type="fetch",
    )
    expected = {
        "id": "ev_compat_2",
        "title": "Keyword source",
        "url": "https://example.com/keyword",
        "snippet": "Keyword construction still works",
        "retrieved_at": "2026-08-26T00:00:00Z",
        "provider": "mock",
        "source_type": "fetch",
    }

    assert item.public_dict() == expected
    assert item.to_public_dict() == expected
