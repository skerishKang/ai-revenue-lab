import pytest

from padiem_ai_core.contracts import Evidence
from padiem_ai_core.evidence_citation import (
    EvidenceCitationError,
    project_grounded_citations,
)
from padiem_ai_core.evidence_graph import (
    ClaimDerivation,
    ClaimEvidenceLink,
    ClaimEvidenceRelation,
    EvidenceClaim,
    evidence_graph,
)
from padiem_ai_core.evidence_verification import (
    TrustedVerificationPolicy,
    VerificationDisposition,
    VerificationRequest,
    VerificationVerdict,
    accept_verification_verdict,
)


def source(evidence_id: str, *, snippet: str | None = None) -> Evidence:
    return Evidence(
        id=evidence_id,
        title=f"Title {evidence_id}",
        snippet=snippet or f"private body {evidence_id}",
        retrieved_at="2026-08-31T00:00:00Z",
        provider="web",
        source_type="web_page",
        url=f"https://example.com/{evidence_id}",
    )


def graph():
    return evidence_graph(
        sources=[source("src_support"), source("src_contra")],
        claims=[
            EvidenceClaim(
                id="claim_1",
                text="A bounded claim.",
                derivation=ClaimDerivation.GENERATED,
            )
        ],
        links=[
            ClaimEvidenceLink(
                claim_id="claim_1",
                evidence_id="src_support",
                relation=ClaimEvidenceRelation.SUPPORTS,
            ),
            ClaimEvidenceLink(
                claim_id="claim_1",
                evidence_id="src_contra",
                relation=ClaimEvidenceRelation.CONTRADICTS,
            ),
        ],
    )


def accepted_verification():
    request = VerificationRequest(claim_id="claim_1", producer_id="agent:producer")
    verdict = VerificationVerdict(
        verdict_id="verdict_1",
        claim_id="claim_1",
        validator_id="validator:independent",
        disposition=VerificationDisposition.VERIFIED,
        checked_evidence_ids=("src_support",),
        confidence=None,
    )
    return accept_verification_verdict(
        graph(),
        request,
        verdict,
        policy=TrustedVerificationPolicy(
            allowed_validator_ids=("validator:independent",)
        ),
    )


def test_projection_preserves_support_and_contradiction_relations() -> None:
    bundle = project_grounded_citations(graph(), "claim_1")

    assert [citation.relation for citation in bundle.citations] == [
        ClaimEvidenceRelation.SUPPORTS,
        ClaimEvidenceRelation.CONTRADICTS,
    ]
    assert bundle.verification_disposition is None


def test_public_citations_omit_raw_evidence_snippets() -> None:
    secret = "private-source-content-should-never-be-in-citation"
    custom = evidence_graph(
        sources=[source("src_support", snippet=secret)],
        claims=[
            EvidenceClaim(
                id="claim_1",
                text="Claim text.",
                derivation=ClaimDerivation.OBSERVED,
            )
        ],
        links=[
            ClaimEvidenceLink(
                claim_id="claim_1",
                evidence_id="src_support",
                relation=ClaimEvidenceRelation.SUPPORTS,
            )
        ],
    )

    public = project_grounded_citations(custom, "claim_1").to_public_dict()
    assert secret not in repr(public)
    assert "snippet" not in public["citations"][0]


def test_accepted_verification_attaches_at_claim_level_only() -> None:
    bundle = project_grounded_citations(
        graph(),
        "claim_1",
        verification=accepted_verification(),
    )
    public = bundle.to_public_dict()

    assert public["verification"] == {
        "disposition": "verified",
        "validator_id": "validator:independent",
        "confidence": None,
    }
    assert bundle.citations[0].checked_by_validator is True
    assert bundle.citations[1].checked_by_validator is False
    assert "human_approval" not in repr(public)


def test_citation_presence_without_verification_does_not_imply_verified() -> None:
    public = project_grounded_citations(graph(), "claim_1").to_public_dict()

    assert public["verification"] is None
    assert all(
        citation["checked_by_validator"] is False
        for citation in public["citations"]
    )


def test_verification_for_other_claim_fails_closed() -> None:
    other_graph = evidence_graph(
        sources=[source("src_other")],
        claims=[
            EvidenceClaim(
                id="claim_other",
                text="Other claim.",
                derivation=ClaimDerivation.OBSERVED,
            )
        ],
        links=[
            ClaimEvidenceLink(
                claim_id="claim_other",
                evidence_id="src_other",
                relation=ClaimEvidenceRelation.SUPPORTS,
            )
        ],
    )
    request = VerificationRequest(
        claim_id="claim_other",
        producer_id="agent:producer",
    )
    verdict = VerificationVerdict(
        verdict_id="verdict_other",
        claim_id="claim_other",
        validator_id="validator:independent",
        disposition=VerificationDisposition.VERIFIED,
        checked_evidence_ids=("src_other",),
    )
    accepted = accept_verification_verdict(
        other_graph,
        request,
        verdict,
        policy=TrustedVerificationPolicy(
            allowed_validator_ids=("validator:independent",)
        ),
    )

    with pytest.raises(EvidenceCitationError) as exc_info:
        project_grounded_citations(
            graph(),
            "claim_1",
            verification=accepted,
        )
    assert exc_info.value.code == "citation_verification_mismatch"


def test_claim_without_evidence_links_has_no_grounded_citations() -> None:
    ungrounded = evidence_graph(
        sources=[],
        claims=[
            EvidenceClaim(
                id="claim_1",
                text="Ungrounded model candidate.",
                derivation=ClaimDerivation.GENERATED,
            )
        ],
        links=[],
    )

    with pytest.raises(EvidenceCitationError) as exc_info:
        project_grounded_citations(ungrounded, "claim_1")
    assert exc_info.value.code == "no_grounded_citations"
