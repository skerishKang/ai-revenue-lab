import pytest

from padiem_ai_core.subject_identity import (
    PublicSubjectReference,
    SubjectIdentityClass,
    SubjectIdentityError,
    assert_cross_app_unlinkable,
    classify_subject_identity,
    is_direct_account_identifier,
    public_subject_reference_from_trusted_adapter,
)


def test_internal_canonical_subject_is_not_public_safe_by_classification() -> None:
    assert classify_subject_identity("canonical_subject_123") is SubjectIdentityClass.INTERNAL_CANONICAL_SUBJECT
    assert classify_subject_identity("subj_appA_opaque_123") is SubjectIdentityClass.TENANT_APP_SCOPED_PSEUDONYM


def test_direct_account_identifiers_are_prohibited_for_public_subject_reference() -> None:
    for value in (
        "person@example.com",
        "+82-10-1234-5678",
        "google:account:123",
        "oauth_subject_abc",
        "credential-derived-user",
        "token_owner_123",
    ):
        assert is_direct_account_identifier(value) is True
        assert classify_subject_identity(value) is SubjectIdentityClass.PROHIBITED_DIRECT_IDENTIFIER
        with pytest.raises(SubjectIdentityError) as exc_info:
            PublicSubjectReference(app_id="b62", subject_ref=value)
        assert exc_info.value.code == "invalid_public_subject_reference"


def test_public_safe_subject_reference_is_adapter_produced_opaque_and_bounded() -> None:
    ref = public_subject_reference_from_trusted_adapter(
        app_id="b62",
        adapter_subject_ref="psub_Abcdef1234567890",
    )

    assert ref is not None
    assert ref.app_id == "b62"
    assert ref.subject_ref == "psub_Abcdef1234567890"
    assert ref.to_public_dict() == {
        "subject_ref": "psub_Abcdef1234567890",
        "scope": "app",
        "policy": "app_scoped_unlinkable",
    }


def test_default_public_subject_reference_is_omitted_without_adapter_reference() -> None:
    assert public_subject_reference_from_trusted_adapter(app_id="b62", adapter_subject_ref=None) is None


def test_public_subject_reference_cannot_be_derived_from_email_or_phone() -> None:
    with pytest.raises(SubjectIdentityError):
        public_subject_reference_from_trusted_adapter(
            app_id="b62",
            adapter_subject_ref="owner@example.com",
        )

    with pytest.raises(SubjectIdentityError):
        public_subject_reference_from_trusted_adapter(
            app_id="b62",
            adapter_subject_ref="010-1234-5678",
        )


def test_cross_app_public_subject_references_must_not_be_globally_correlatable() -> None:
    app_a = PublicSubjectReference(app_id="b62", subject_ref="psub_AAAAAAAAAAAA")
    app_b_safe = PublicSubjectReference(app_id="b14", subject_ref="psub_BBBBBBBBBBBB")
    app_b_correlated = PublicSubjectReference(app_id="b14", subject_ref="psub_AAAAAAAAAAAA")

    assert_cross_app_unlinkable(app_a, app_b_safe)
    with pytest.raises(SubjectIdentityError) as exc_info:
        assert_cross_app_unlinkable(app_a, app_b_correlated)
    assert exc_info.value.code == "cross_app_subject_correlation"


def test_public_subject_reference_is_presentation_only_not_authority_identity() -> None:
    ref = PublicSubjectReference(app_id="b62", subject_ref="psub_Zyxwv987654321")
    public_projection = ref.to_public_dict()

    assert "app_id" not in public_projection
    assert "canonical" not in public_projection
    assert "subject_id" not in public_projection
    assert "entitlement" not in public_projection
    assert public_projection["subject_ref"].startswith("psub_")


def test_invalid_public_subject_policy_fails_closed() -> None:
    with pytest.raises(SubjectIdentityError) as exc_info:
        PublicSubjectReference(
            app_id="b62",
            subject_ref="psub_Abcdef1234567890",
            policy="globally_correlatable",
        )
    assert exc_info.value.code == "invalid_public_subject_policy"
