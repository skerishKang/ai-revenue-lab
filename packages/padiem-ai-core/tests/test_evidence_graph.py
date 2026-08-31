import pytest

from padiem_ai_core.contracts import Evidence
from padiem_ai_core.evidence_graph import (
    ClaimDerivation,
    ClaimEvidenceLink,
    ClaimEvidenceRelation,
    EvidenceClaim,
    EvidenceGraph,
    EvidenceGraphError,
    evidence_graph,
)


def source(
    evidence_id: str = "src_1",
    *,
    snippet: str = "private retrieved source text",
) -> Evidence:
    return Evidence(
        id=evidence_id,
        title="Source",
        snippet=snippet,
        retrieved_at="2026-08-31T00:00:00Z",
        provider="web",
        source_type="web_page",
        url=f"https://example.com/{evidence_id}",
    )


def test_observed_claim_requires_direct_supporting_source() -> None:
    claim = EvidenceClaim(
        id="claim_1",
        text="The source states the bounded fact.",
        derivation=ClaimDerivation.OBSERVED,
    )
    graph = evidence_graph(
        sources=[source()],
        claims=[claim],
        links=[
            ClaimEvidenceLink(
                claim_id="claim_1",
                evidence_id="src_1",
                relation=ClaimEvidenceRelation.SUPPORTS,
            )
        ],
    )

    assert isinstance(graph, EvidenceGraph)
    assert graph.links_for_claim("claim_1")[0].relation is ClaimEvidenceRelation.SUPPORTS


def test_observed_claim_without_support_fails_closed() -> None:
    claim = EvidenceClaim(
        id="claim_1",
        text="Unanchored observation.",
        derivation=ClaimDerivation.OBSERVED,
    )

    with pytest.raises(EvidenceGraphError) as exc_info:
        evidence_graph(sources=[source()], claims=[claim], links=[])

    assert exc_info.value.code == "observed_claim_missing_source"


def test_inferred_claim_can_derive_only_from_earlier_claims() -> None:
    first = EvidenceClaim(
        id="claim_1",
        text="Direct observation.",
        derivation=ClaimDerivation.OBSERVED,
    )
    second = EvidenceClaim(
        id="claim_2",
        text="Bounded inference.",
        derivation=ClaimDerivation.INFERRED,
        derived_from_claim_ids=("claim_1",),
    )

    graph = evidence_graph(
        sources=[source()],
        claims=[first, second],
        links=[
            ClaimEvidenceLink(
                claim_id="claim_1",
                evidence_id="src_1",
                relation=ClaimEvidenceRelation.SUPPORTS,
            )
        ],
    )
    assert graph.claim("claim_2").derived_from_claim_ids == ("claim_1",)

    with pytest.raises(EvidenceGraphError) as exc_info:
        evidence_graph(
            sources=[source()],
            claims=[second, first],
            links=[
                ClaimEvidenceLink(
                    claim_id="claim_1",
                    evidence_id="src_1",
                    relation=ClaimEvidenceRelation.SUPPORTS,
                )
            ],
        )

    assert exc_info.value.code == "invalid_claim_derivation"


def test_unknown_source_or_claim_link_fails_closed() -> None:
    claim = EvidenceClaim(
        id="claim_1",
        text="Claim.",
        derivation=ClaimDerivation.INFERRED,
    )

    with pytest.raises(EvidenceGraphError) as exc_info:
        evidence_graph(
            sources=[source()],
            claims=[claim],
            links=[
                ClaimEvidenceLink(
                    claim_id="claim_1",
                    evidence_id="missing",
                    relation=ClaimEvidenceRelation.SUPPORTS,
                )
            ],
        )
    assert exc_info.value.code == "unknown_evidence_source"

    with pytest.raises(EvidenceGraphError) as exc_info:
        evidence_graph(
            sources=[source()],
            claims=[claim],
            links=[
                ClaimEvidenceLink(
                    claim_id="missing",
                    evidence_id="src_1",
                    relation=ClaimEvidenceRelation.SUPPORTS,
                )
            ],
        )
    assert exc_info.value.code == "unknown_evidence_claim"


def test_contradiction_is_represented_not_silently_removed() -> None:
    claim = EvidenceClaim(
        id="claim_1",
        text="Contested claim.",
        derivation=ClaimDerivation.INFERRED,
    )
    graph = evidence_graph(
        sources=[source("src_1"), source("src_2")],
        claims=[claim],
        links=[
            ClaimEvidenceLink(
                claim_id="claim_1",
                evidence_id="src_1",
                relation=ClaimEvidenceRelation.SUPPORTS,
            ),
            ClaimEvidenceLink(
                claim_id="claim_1",
                evidence_id="src_2",
                relation=ClaimEvidenceRelation.CONTRADICTS,
            ),
        ],
    )

    relations = {link.relation for link in graph.links_for_claim("claim_1")}
    assert relations == {
        ClaimEvidenceRelation.SUPPORTS,
        ClaimEvidenceRelation.CONTRADICTS,
    }


def test_duplicate_source_claim_and_exact_link_ids_fail_closed() -> None:
    claim = EvidenceClaim(
        id="claim_1",
        text="Claim.",
        derivation=ClaimDerivation.INFERRED,
    )
    link = ClaimEvidenceLink(
        claim_id="claim_1",
        evidence_id="src_1",
        relation=ClaimEvidenceRelation.SUPPORTS,
    )

    with pytest.raises(EvidenceGraphError) as exc_info:
        evidence_graph(
            sources=[source(), source()],
            claims=[claim],
            links=[link],
        )
    assert exc_info.value.code == "duplicate_evidence_source"

    with pytest.raises(EvidenceGraphError) as exc_info:
        evidence_graph(
            sources=[source()],
            claims=[claim, claim],
            links=[link],
        )
    assert exc_info.value.code == "duplicate_evidence_claim"

    with pytest.raises(EvidenceGraphError) as exc_info:
        evidence_graph(
            sources=[source()],
            claims=[claim],
            links=[link, link],
        )
    assert exc_info.value.code == "duplicate_evidence_link"


def test_public_graph_omits_raw_source_snippet_and_verification_claims() -> None:
    secret = "private-source-body-should-not-be-public"
    claim = EvidenceClaim(
        id="claim_1",
        text="Public-safe claim text.",
        derivation=ClaimDerivation.OBSERVED,
    )
    graph = evidence_graph(
        sources=[source(snippet=secret)],
        claims=[claim],
        links=[
            ClaimEvidenceLink(
                claim_id="claim_1",
                evidence_id="src_1",
                relation=ClaimEvidenceRelation.SUPPORTS,
            )
        ],
    )

    public = graph.to_public_dict()
    assert public["sources"][0]["id"] == "src_1"
    assert "snippet" not in public["sources"][0]
    assert secret not in repr(public)
    assert "verified" not in public["claims"][0]
    assert "confidence" not in public["claims"][0]


def test_generated_claim_does_not_become_observed_or_verified_by_construction() -> None:
    claim = EvidenceClaim(
        id="claim_model",
        text="Model-generated candidate claim.",
        derivation=ClaimDerivation.GENERATED,
    )
    graph = evidence_graph(sources=[], claims=[claim], links=[])

    assert graph.claim("claim_model").derivation is ClaimDerivation.GENERATED
    assert set(graph.claim("claim_model").to_public_dict()) == {
        "id",
        "text",
        "derivation",
        "derived_from_claim_ids",
    }
