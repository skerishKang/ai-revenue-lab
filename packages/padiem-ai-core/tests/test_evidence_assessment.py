import pytest

from padiem_ai_core.contracts import Evidence
from padiem_ai_core.evidence_assessment import (
    ClaimAssessmentState,
    EvidenceAssessmentError,
    assess_claim,
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


def source(evidence_id: str) -> Evidence:
    return Evidence(
        id=evidence_id,
        title=f"Title {evidence_id}",
        snippet=f"private body {evidence_id}",
        retrieved_at="2026-08-31T00:00:00Z",
        provider="web",
        source_type="web_page",
        url=f"https://example.com/{evidence_id}",
    )


def make_graph(*relations: tuple[str, ClaimEvidenceRelation]):
    return evidence_graph(
        sources=[source(evidence_id) for evidence_id, _ in relations],
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
                evidence_id=evidence_id,
                relation=relation,
            )
            for evidence_id, relation in relations
        ],
    )


def accepted_verification(
    graph,
    disposition: VerificationDisposition,
    checked_ids: tuple[str, ...],
    confidence=None,
    *,
    claim_id: str = "claim_1",
):
    request = VerificationRequest(claim_id=claim_id, producer_id="agent:producer")
    verdict = VerificationVerdict(
        verdict_id="verdict_1",
        claim_id=claim_id,
        validator_id="validator:independent",
        disposition=disposition,
        checked_evidence_ids=checked_ids,
        confidence=confidence,
    )
    return accept_verification_verdict(
        graph,
        request,
        verdict,
        policy=TrustedVerificationPolicy(
            allowed_validator_ids=("validator:independent",)
        ),
    )


def test_verified_support_becomes_supported():
    graph = make_graph(("src_support", ClaimEvidenceRelation.SUPPORTS))
    verification = accepted_verification(
        graph, VerificationDisposition.VERIFIED, ("src_support",), confidence=0.75
    )

    assessment = assess_claim(graph, "claim_1", verification=verification)

    assert assessment.state is ClaimAssessmentState.SUPPORTED
    assert assessment.supporting_evidence_ids == ("src_support",)
    assert assessment.missing_supporting_evidence is False
    assert assessment.verification_confidence == 0.75


def test_evidence_without_accepted_verification_remains_unverified():
    graph = make_graph(("src_support", ClaimEvidenceRelation.SUPPORTS))

    assessment = assess_claim(graph, "claim_1")

    assert assessment.state is ClaimAssessmentState.UNVERIFIED
    assert assessment.verification_disposition is None
    assert assessment.verification_confidence is None


def test_verified_contradiction_becomes_contradicted():
    graph = make_graph(("src_contra", ClaimEvidenceRelation.CONTRADICTS))
    verification = accepted_verification(
        graph, VerificationDisposition.CONTRADICTED, ("src_contra",)
    )

    assessment = assess_claim(graph, "claim_1", verification=verification)

    assert assessment.state is ClaimAssessmentState.CONTRADICTED
    assert assessment.contradicting_evidence_ids == ("src_contra",)


def test_support_and_contradiction_always_remain_conflicted():
    graph = make_graph(
        ("src_support", ClaimEvidenceRelation.SUPPORTS),
        ("src_contra", ClaimEvidenceRelation.CONTRADICTS),
    )
    verification = accepted_verification(
        graph, VerificationDisposition.VERIFIED, ("src_support",)
    )

    assessment = assess_claim(graph, "claim_1", verification=verification)

    assert assessment.state is ClaimAssessmentState.CONFLICTED
    assert assessment.supporting_evidence_ids == ("src_support",)
    assert assessment.contradicting_evidence_ids == ("src_contra",)


def test_missing_support_is_explicit_but_contextual_evidence_is_preserved():
    graph = make_graph(("src_context", ClaimEvidenceRelation.CONTEXTUALIZES))

    assessment = assess_claim(graph, "claim_1")

    assert assessment.state is ClaimAssessmentState.UNVERIFIED
    assert assessment.missing_supporting_evidence is True
    assert assessment.contextualizing_evidence_ids == ("src_context",)


def test_no_evidence_is_unverified_with_missing_support():
    graph = make_graph()

    assessment = assess_claim(graph, "claim_1")

    assert assessment.state is ClaimAssessmentState.UNVERIFIED
    assert assessment.supporting_evidence_ids == ()
    assert assessment.missing_supporting_evidence is True


def test_inconclusive_verification_remains_unverified():
    graph = make_graph(("src_context", ClaimEvidenceRelation.CONTEXTUALIZES))
    verification = accepted_verification(
        graph, VerificationDisposition.INCONCLUSIVE, ()
    )

    assessment = assess_claim(graph, "claim_1", verification=verification)

    assert assessment.state is ClaimAssessmentState.UNVERIFIED
    assert assessment.verification_disposition == "inconclusive"
    assert assessment.verification_confidence is None


def test_confidence_is_preserved_not_averaged_or_synthesized():
    graph = make_graph(("src_support", ClaimEvidenceRelation.SUPPORTS))
    verification = accepted_verification(
        graph, VerificationDisposition.VERIFIED, ("src_support",), confidence=0.333
    )

    assessment = assess_claim(graph, "claim_1", verification=verification)

    assert assessment.verification_confidence == 0.333


def test_mismatched_verification_fails_closed():
    graph = make_graph(("src_support", ClaimEvidenceRelation.SUPPORTS))
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
    verification = accepted_verification(
        other_graph,
        VerificationDisposition.VERIFIED,
        ("src_other",),
        claim_id="claim_other",
    )

    with pytest.raises(EvidenceAssessmentError) as exc_info:
        assess_claim(graph, "claim_1", verification=verification)

    assert exc_info.value.code == "assessment_verification_mismatch"


def test_public_projection_contains_no_snippets_or_authority_fields():
    graph = make_graph(("src_support", ClaimEvidenceRelation.SUPPORTS))
    public = assess_claim(graph, "claim_1").to_public_dict()
    rendered = repr(public)

    assert "private body" not in rendered
    assert "snippet" not in public
    assert "human_approval" not in rendered
    assert "authorization" not in rendered
    assert "entitlement" not in rendered
    assert "trust" not in rendered


def test_evidence_id_order_is_deterministic_for_graph_order():
    graph = make_graph(
        ("src_b", ClaimEvidenceRelation.SUPPORTS),
        ("src_a", ClaimEvidenceRelation.SUPPORTS),
    )

    first = assess_claim(graph, "claim_1")
    second = assess_claim(graph, "claim_1")

    assert first.to_public_dict() == second.to_public_dict()
    assert first.supporting_evidence_ids == ("src_b", "src_a")


def test_unknown_claim_fails_closed():
    graph = make_graph(("src_support", ClaimEvidenceRelation.SUPPORTS))

    with pytest.raises(EvidenceAssessmentError) as exc_info:
        assess_claim(graph, "missing_claim")

    assert exc_info.value.code == "unknown_assessment_claim"
