from padiem_ai_core.evidence_assessment import ClaimAssessmentState, assess_claim
from padiem_ai_core.evidence_graph import (
    ClaimDerivation,
    ClaimEvidenceLink,
    ClaimEvidenceRelation,
    EvidenceClaim,
    evidence_graph,
)
from padiem_ai_core.evidence_verification import (
    AcceptedVerification,
    VerificationDisposition,
    VerificationRequest,
    VerificationVerdict,
)
from padiem_ai_core.contracts import Evidence


def source(source_id: str, title: str = "Source") -> Evidence:
    return Evidence(
        id=source_id,
        title=title,
        snippet="bounded snippet",
        retrieved_at="2026-08-30T12:00:00+00:00",
        provider="test-provider",
        source_type="web",
        url="https://example.com/source",
    )


def claim(claim_id: str = "claim:1") -> EvidenceClaim:
    return EvidenceClaim(id=claim_id, text="The sky is blue.", derivation=ClaimDerivation.OBSERVED)


def graph_for(*relations: ClaimEvidenceRelation) -> object:
    sources = tuple(source(f"ev:{index}") for index, _ in enumerate(relations, start=1))
    claims = (claim(),)
    links = tuple(
        ClaimEvidenceLink(
            claim_id="claim:1",
            evidence_id=f"ev:{index}",
            relation=relation,
        )
        for index, relation in enumerate(relations, start=1)
    )
    return evidence_graph(sources=sources, claims=claims, links=links)


def accepted(disposition: VerificationDisposition, *evidence_ids: str, confidence=None) -> AcceptedVerification:
    request = VerificationRequest(claim_id="claim:1", producer_id="producer:1")
    verdict = VerificationVerdict(
        verdict_id="verdict:1" if disposition is VerificationDisposition.VERIFIED else "verdict:2",
        claim_id="claim:1",
        validator_id="validator:1",
        disposition=disposition,
        checked_evidence_ids=tuple(evidence_ids),
        confidence=confidence,
    )
    return AcceptedVerification(request=request, verdict=verdict)


def test_supporting_graph_link_yields_supported() -> None:
    assessment = assess_claim(graph_for(ClaimEvidenceRelation.SUPPORTS), "claim:1")
    assert assessment.state is ClaimAssessmentState.SUPPORTED
    assert assessment.supporting_evidence_ids == ("ev:1",)
    assert assessment.missing_evidence is False


def test_contradicting_graph_link_yields_contradicted() -> None:
    assessment = assess_claim(graph_for(ClaimEvidenceRelation.CONTRADICTS), "claim:1")
    assert assessment.state is ClaimAssessmentState.CONTRADICTED
    assert assessment.contradicting_evidence_ids == ("ev:1",)


def test_no_evidence_link_is_unverified_and_missing() -> None:
    # Observed claims must carry a support link in the graph contract, so use an
    # inferred claim for the unverified/missing-evidence assessment case.
    inferred = EvidenceClaim(id="claim:2", text="Possible inference.", derivation=ClaimDerivation.INFERRED)
    graph = evidence_graph(sources=(), claims=(inferred,), links=())
    assessment = assess_claim(graph, "claim:2")
    assert assessment.state is ClaimAssessmentState.UNVERIFIED
    assert assessment.missing_evidence is True


def test_accepted_verified_verdict_yields_supported() -> None:
    assessment = assess_claim(
        graph_for(ClaimEvidenceRelation.SUPPORTS),
        "claim:1",
        accepted_verifications=(accepted(VerificationDisposition.VERIFIED, "ev:1", confidence=0.8),),
    )
    assert assessment.state is ClaimAssessmentState.SUPPORTED
    assert assessment.checked_evidence_ids == ("ev:1",)
    assert assessment.confidence == 0.8


def test_accepted_contradicted_verdict_yields_contradicted() -> None:
    assessment = assess_claim(
        graph_for(ClaimEvidenceRelation.CONTRADICTS),
        "claim:1",
        accepted_verifications=(accepted(VerificationDisposition.CONTRADICTED, "ev:1", confidence=0.9),),
    )
    assert assessment.state is ClaimAssessmentState.CONTRADICTED
    assert assessment.confidence == 0.9


def test_support_and_contradiction_yield_conflicted() -> None:
    assessment = assess_claim(
        graph_for(ClaimEvidenceRelation.SUPPORTS, ClaimEvidenceRelation.CONTRADICTS),
        "claim:1",
    )
    assert assessment.state is ClaimAssessmentState.CONFLICTED
    assert assessment.confidence is None


def test_conflicting_verdicts_keep_confidence_unknown() -> None:
    graph = graph_for(ClaimEvidenceRelation.SUPPORTS, ClaimEvidenceRelation.CONTRADICTS)
    assessment = assess_claim(
        graph,
        "claim:1",
        accepted_verifications=(
            accepted(VerificationDisposition.VERIFIED, "ev:1", confidence=0.8),
            AcceptedVerification(
                request=VerificationRequest(claim_id="claim:1", producer_id="producer:2"),
                verdict=VerificationVerdict(
                    verdict_id="verdict:3",
                    claim_id="claim:1",
                    validator_id="validator:2",
                    disposition=VerificationDisposition.CONTRADICTED,
                    checked_evidence_ids=("ev:2",),
                    confidence=0.6,
                ),
            ),
        ),
    )
    assert assessment.state is ClaimAssessmentState.CONFLICTED
    assert assessment.confidence is None


def test_identical_explicit_confidence_is_preserved() -> None:
    graph = graph_for(ClaimEvidenceRelation.SUPPORTS)
    assessment = assess_claim(
        graph,
        "claim:1",
        accepted_verifications=(
            accepted(VerificationDisposition.VERIFIED, "ev:1", confidence=0.75),
            AcceptedVerification(
                request=VerificationRequest(claim_id="claim:1", producer_id="producer:2"),
                verdict=VerificationVerdict(
                    verdict_id="verdict:3",
                    claim_id="claim:1",
                    validator_id="validator:2",
                    disposition=VerificationDisposition.VERIFIED,
                    checked_evidence_ids=("ev:1",),
                    confidence=0.75,
                ),
            ),
        ),
    )
    assert assessment.confidence == 0.75


def test_public_assessment_contains_no_authorization_or_approval_fields() -> None:
    assessment = assess_claim(graph_for(ClaimEvidenceRelation.SUPPORTS), "claim:1")
    public = assessment.to_public_dict()
    assert "authorization" not in public
    assert "approval" not in public
    assert "credentials" not in public
