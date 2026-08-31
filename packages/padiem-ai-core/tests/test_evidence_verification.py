import pytest

from padiem_ai_core.contracts import Evidence
from padiem_ai_core.evidence_graph import (
    ClaimDerivation,
    ClaimEvidenceLink,
    ClaimEvidenceRelation,
    EvidenceClaim,
    evidence_graph,
)
from padiem_ai_core.evidence_verification import (
    EvidenceVerificationError,
    TrustedVerificationPolicy,
    VerificationDisposition,
    VerificationRequest,
    VerificationVerdict,
    accept_verification_verdict,
)


def source(evidence_id: str) -> Evidence:
    return Evidence(
        id=evidence_id,
        title=evidence_id,
        snippet=f"private {evidence_id}",
        retrieved_at="2026-08-31T00:00:00Z",
        provider="web",
        source_type="web_page",
        url=f"https://example.com/{evidence_id}",
    )


def graph():
    claim = EvidenceClaim(
        id="claim_1",
        text="Contested bounded claim.",
        derivation=ClaimDerivation.GENERATED,
    )
    return evidence_graph(
        sources=[source("support_1"), source("contra_1")],
        claims=[claim],
        links=[
            ClaimEvidenceLink(
                claim_id="claim_1",
                evidence_id="support_1",
                relation=ClaimEvidenceRelation.SUPPORTS,
            ),
            ClaimEvidenceLink(
                claim_id="claim_1",
                evidence_id="contra_1",
                relation=ClaimEvidenceRelation.CONTRADICTS,
            ),
        ],
    )


def policy() -> TrustedVerificationPolicy:
    return TrustedVerificationPolicy(allowed_validator_ids=("validator:independent",))


def request() -> VerificationRequest:
    return VerificationRequest(claim_id="claim_1", producer_id="agent:producer")


def test_independent_verified_verdict_requires_checked_support() -> None:
    verdict = VerificationVerdict(
        verdict_id="verdict_1",
        claim_id="claim_1",
        validator_id="validator:independent",
        disposition=VerificationDisposition.VERIFIED,
        checked_evidence_ids=("support_1",),
        confidence=None,
        summary="Independent source supports the claim.",
    )

    accepted = accept_verification_verdict(
        graph(), request(), verdict, policy=policy()
    )

    assert accepted.verdict.disposition is VerificationDisposition.VERIFIED
    assert accepted.verdict.confidence is None


def test_unknown_confidence_stays_unknown() -> None:
    verdict = VerificationVerdict(
        verdict_id="verdict_unknown",
        claim_id="claim_1",
        validator_id="validator:independent",
        disposition=VerificationDisposition.INCONCLUSIVE,
        confidence=None,
    )

    accepted = accept_verification_verdict(
        graph(), request(), verdict, policy=policy()
    )
    assert accepted.to_public_dict()["confidence"] is None


def test_invalid_numeric_confidence_fails_closed() -> None:
    with pytest.raises(EvidenceVerificationError) as exc_info:
        VerificationVerdict(
            verdict_id="verdict_bad",
            claim_id="claim_1",
            validator_id="validator:independent",
            disposition=VerificationDisposition.INCONCLUSIVE,
            confidence=1.1,
        )
    assert exc_info.value.code == "invalid_verification_confidence"


def test_producer_cannot_self_verify() -> None:
    verdict = VerificationVerdict(
        verdict_id="verdict_self",
        claim_id="claim_1",
        validator_id="agent:producer",
        disposition=VerificationDisposition.VERIFIED,
        checked_evidence_ids=("support_1",),
    )

    with pytest.raises(EvidenceVerificationError) as exc_info:
        accept_verification_verdict(
            graph(),
            request(),
            verdict,
            policy=TrustedVerificationPolicy(
                allowed_validator_ids=("agent:producer",)
            ),
        )
    assert exc_info.value.code == "self_verification_forbidden"


def test_untrusted_validator_fails_closed() -> None:
    verdict = VerificationVerdict(
        verdict_id="verdict_other",
        claim_id="claim_1",
        validator_id="validator:other",
        disposition=VerificationDisposition.VERIFIED,
        checked_evidence_ids=("support_1",),
    )

    with pytest.raises(EvidenceVerificationError) as exc_info:
        accept_verification_verdict(graph(), request(), verdict, policy=policy())
    assert exc_info.value.code == "validator_not_authorized"


def test_verified_requires_support_and_contradicted_requires_contradiction() -> None:
    verified_from_contra = VerificationVerdict(
        verdict_id="verdict_wrong_support",
        claim_id="claim_1",
        validator_id="validator:independent",
        disposition=VerificationDisposition.VERIFIED,
        checked_evidence_ids=("contra_1",),
    )
    with pytest.raises(EvidenceVerificationError) as exc_info:
        accept_verification_verdict(
            graph(), request(), verified_from_contra, policy=policy()
        )
    assert exc_info.value.code == "verified_without_support"

    contradicted_from_support = VerificationVerdict(
        verdict_id="verdict_wrong_contra",
        claim_id="claim_1",
        validator_id="validator:independent",
        disposition=VerificationDisposition.CONTRADICTED,
        checked_evidence_ids=("support_1",),
    )
    with pytest.raises(EvidenceVerificationError) as exc_info:
        accept_verification_verdict(
            graph(), request(), contradicted_from_support, policy=policy()
        )
    assert exc_info.value.code == "contradicted_without_contradiction"


def test_checked_evidence_must_exist_and_be_linked_to_claim() -> None:
    verdict = VerificationVerdict(
        verdict_id="verdict_missing",
        claim_id="claim_1",
        validator_id="validator:independent",
        disposition=VerificationDisposition.VERIFIED,
        checked_evidence_ids=("missing",),
    )
    with pytest.raises(EvidenceVerificationError) as exc_info:
        accept_verification_verdict(graph(), request(), verdict, policy=policy())
    assert exc_info.value.code == "unknown_checked_evidence"

    extra_graph = evidence_graph(
        sources=[source("support_1"), source("unlinked")],
        claims=[
            EvidenceClaim(
                id="claim_1",
                text="Claim.",
                derivation=ClaimDerivation.GENERATED,
            )
        ],
        links=[
            ClaimEvidenceLink(
                claim_id="claim_1",
                evidence_id="support_1",
                relation=ClaimEvidenceRelation.SUPPORTS,
            )
        ],
    )
    verdict = VerificationVerdict(
        verdict_id="verdict_unlinked",
        claim_id="claim_1",
        validator_id="validator:independent",
        disposition=VerificationDisposition.VERIFIED,
        checked_evidence_ids=("unlinked",),
    )
    with pytest.raises(EvidenceVerificationError) as exc_info:
        accept_verification_verdict(
            extra_graph, request(), verdict, policy=policy()
        )
    assert exc_info.value.code == "unlinked_checked_evidence"


def test_validator_verdict_is_not_human_approval() -> None:
    verdict = VerificationVerdict(
        verdict_id="verdict_1",
        claim_id="claim_1",
        validator_id="validator:independent",
        disposition=VerificationDisposition.VERIFIED,
        checked_evidence_ids=("support_1",),
    )
    public = accept_verification_verdict(
        graph(), request(), verdict, policy=policy()
    ).to_public_dict()

    assert public["disposition"] == "verified"
    assert "human_approval" not in public
    assert "approved" not in public


def test_model_generated_claim_can_only_become_verified_via_separate_validator() -> None:
    assert graph().claim("claim_1").derivation is ClaimDerivation.GENERATED

    verdict = VerificationVerdict(
        verdict_id="verdict_independent",
        claim_id="claim_1",
        validator_id="validator:independent",
        disposition=VerificationDisposition.VERIFIED,
        checked_evidence_ids=("support_1",),
    )
    accepted = accept_verification_verdict(
        graph(), request(), verdict, policy=policy()
    )
    assert accepted.verdict.validator_id != request().producer_id
