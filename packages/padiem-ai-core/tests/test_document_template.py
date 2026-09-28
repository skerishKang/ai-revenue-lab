import dataclasses
import json

import pytest

from padiem_ai_core.document_template import (
    DOCUMENT_TEMPLATE_SCHEMA_VERSION,
    MAX_TEMPLATE_COLLECTION_ITEMS,
    MAX_TEMPLATE_NESTING_DEPTH,
    MAX_TEMPLATE_STRING_CHARS,
    DocumentTemplateApproval,
    DocumentTemplateCandidate,
    DocumentTemplateError,
    DocumentTemplateProfile,
    DocumentTemplateSourceProvenance,
    FrozenTemplateObject,
    approve_document_template_candidate,
)


def provenance(**overrides):
    values = dict(
        source_type="uploaded_document",
        source_ref="private:document_1",
        media_type="application/pdf",
        content_sha256="a" * 64,
        trace_id="trace_1",
    )
    values.update(overrides)
    return DocumentTemplateSourceProvenance(**values)


def candidate(**overrides):
    values = dict(
        candidate_id="candidate_1",
        schema_version=DOCUMENT_TEMPLATE_SCHEMA_VERSION,
        template_kind="generic_document",
        name="Reference layout",
        source_provenance=provenance(),
        structure_profile={"sections": ["header", "body"], "table": {"columns": ["item", "amount"]}},
        style_profile={"alignment": "left", "border": {"width": 1}, "font": {"size": 10.5}},
        fixed_content={"footer_text": "Terms apply."},
        variable_slots=[{"slot_id": "document_title", "kind": "text"}, {"slot_id": "line_items", "kind": "table"}],
        renderer_contract_ref="renderer:document-template@1",
        warnings=("low_confidence_logo",),
    )
    values.update(overrides)
    return DocumentTemplateCandidate(**values)


def approved(**overrides):
    return approve_document_template_candidate(
        candidate(**overrides),
        template_id="template_1",
        approved_by_ref="actor:owner",
        approved_at="2026-09-28T03:00:00Z",
    )


def test_candidate_and_approved_profile_are_distinct() -> None:
    item = candidate()
    assert not isinstance(item, DocumentTemplateProfile)
    assert item.to_public_dict()["approved"] is False
    assert not hasattr(item, "template_id")
    assert not hasattr(item, "active")
    assert approved().to_public_dict()["approved"] is True


def test_explicit_approval_preserves_candidate_content_and_provenance() -> None:
    source = candidate()
    profile = approve_document_template_candidate(
        source,
        template_id="template_9",
        approved_by_ref="actor:reviewer",
        approved_at="2026-09-28T03:01:02Z",
    )
    assert profile.approval.candidate_id == source.candidate_id
    assert profile.approval.candidate_fingerprint == source.fingerprint
    assert profile.fingerprint == source.fingerprint
    assert profile.source_provenance == source.source_provenance
    assert profile.structure_profile == source.structure_profile


def test_missing_or_mismatched_approval_fails_closed() -> None:
    source = candidate()
    values = dict(
        template_id="template_1",
        schema_version=source.schema_version,
        template_kind=source.template_kind,
        name=source.name,
        source_provenance=source.source_provenance,
        structure_profile=source.structure_profile,
        style_profile=source.style_profile,
        fixed_content=source.fixed_content,
        variable_slots=source.variable_slots,
        renderer_contract_ref=source.renderer_contract_ref,
        fingerprint=source.fingerprint,
        created_at="2026-09-28T03:00:00Z",
        updated_at="2026-09-28T03:00:00Z",
    )
    with pytest.raises(DocumentTemplateError) as missing:
        DocumentTemplateProfile(approval=None, **values)
    assert missing.value.code == "document_template_approval_required"

    mismatch = DocumentTemplateApproval(
        candidate_id=source.candidate_id,
        candidate_fingerprint="b" * 64,
        approved_by_ref="actor:owner",
        approved_at="2026-09-28T03:00:00Z",
    )
    with pytest.raises(DocumentTemplateError) as wrong:
        DocumentTemplateProfile(approval=mismatch, **values)
    assert wrong.value.code == "document_template_approval_mismatch"


def test_fingerprint_is_deterministic_render_content_identity() -> None:
    left = candidate(
        name="First name",
        source_provenance=provenance(source_ref="private:one"),
        structure_profile={"b": 2, "a": 1},
        warnings=("one_warning",),
    )
    right = candidate(
        candidate_id="candidate_2",
        name="Renamed copy",
        source_provenance=provenance(source_ref="private:two"),
        structure_profile={"a": 1, "b": 2},
        warnings=(),
    )
    assert left.fingerprint == right.fingerprint
    assert candidate(structure_profile={"a": 1, "b": 3}).fingerprint != left.fingerprint


@pytest.mark.parametrize("bad_version", [0, 2, -1, True, "1"])
def test_schema_version_rejection(bad_version) -> None:
    with pytest.raises(DocumentTemplateError) as exc:
        candidate(schema_version=bad_version)
    assert exc.value.code in {"invalid_document_template_schema", "unsupported_document_template_schema"}


def test_nested_and_encoded_data_are_bounded() -> None:
    nested = "leaf"
    for index in range(MAX_TEMPLATE_NESTING_DEPTH + 1):
        nested = {f"level_{index}": nested}
    with pytest.raises(DocumentTemplateError) as depth:
        candidate(structure_profile={"root": nested})
    assert depth.value.code == "template_data_budget_exceeded"

    with pytest.raises(DocumentTemplateError) as text:
        candidate(fixed_content={"text": "x" * (MAX_TEMPLATE_STRING_CHARS + 1)})
    assert text.value.code == "template_data_budget_exceeded"

    with pytest.raises(DocumentTemplateError) as count:
        candidate(structure_profile={f"key_{i}": i for i in range(MAX_TEMPLATE_COLLECTION_ITEMS + 1)})
    assert count.value.code == "template_data_budget_exceeded"

    with pytest.raises(DocumentTemplateError) as malformed:
        candidate(style_profile={"unsupported": {1, 2}})
    assert malformed.value.code == "invalid_document_template_data"


@pytest.mark.parametrize(
    "key",
    ["authorization", "permissions", "tool_grants", "allowed-tool-ids",
     "connector_requirement_ids", "entitlement_ref", "access_token", "api.key",
     "credentials", "secret", "provider_id", "model-policy-ref"],
)
def test_nested_authority_and_secret_fields_are_rejected(key) -> None:
    with pytest.raises(DocumentTemplateError) as exc:
        candidate(style_profile={"safe": {key: "value"}})
    assert exc.value.code == "template_authority_surface_forbidden"


def test_preconstructed_wrapper_cannot_bypass_authority_validation() -> None:
    malicious = FrozenTemplateObject((("tool_grants", "anything"),))
    with pytest.raises(DocumentTemplateError) as exc:
        candidate(style_profile=malicious)
    assert exc.value.code == "template_authority_surface_forbidden"


def test_contract_has_no_authorization_or_product_business_fields() -> None:
    fields = {
        field.name.lower()
        for cls in (DocumentTemplateCandidate, DocumentTemplateProfile, DocumentTemplateApproval)
        for field in dataclasses.fields(cls)
    }
    for forbidden in ("tool_grants", "connector_grants", "permissions", "credentials",
                      "provider_id", "model_id", "vat", "supplier", "recipient", "quote_number"):
        assert forbidden not in fields

    serialized = json.dumps(approved().to_public_dict(), sort_keys=True)
    for forbidden in ("allowed_tool_ids", "connector_requirement_ids", "entitlement_ref",
                      "provider_id", "model_id", "access_token", "credentials", "source_ref"):
        assert forbidden not in serialized


def test_provenance_retained_while_private_ref_is_not_public() -> None:
    source = provenance(source_ref="private:document_77")
    item = candidate(source_provenance=source)
    profile = approved(source_provenance=source)
    assert item.source_provenance.source_ref == "private:document_77"
    assert profile.source_provenance.source_ref == "private:document_77"
    assert "source_ref" not in source.to_public_dict()


def test_profile_fingerprint_and_timestamp_tampering_fails_closed() -> None:
    source = candidate()
    approval = DocumentTemplateApproval(
        candidate_id=source.candidate_id,
        candidate_fingerprint="b" * 64,
        approved_by_ref="actor:owner",
        approved_at="2026-09-28T03:00:00Z",
    )
    with pytest.raises(DocumentTemplateError) as fingerprint:
        DocumentTemplateProfile(
            template_id="template_1", schema_version=1, template_kind=source.template_kind,
            name=source.name, source_provenance=source.source_provenance,
            structure_profile=source.structure_profile, style_profile=source.style_profile,
            fixed_content=source.fixed_content, variable_slots=source.variable_slots,
            renderer_contract_ref=source.renderer_contract_ref, fingerprint="b" * 64,
            approval=approval, created_at="2026-09-28T03:00:00Z",
            updated_at="2026-09-28T03:00:00Z",
        )
    assert fingerprint.value.code == "document_template_fingerprint_mismatch"

    with pytest.raises(DocumentTemplateError):
        approve_document_template_candidate(
            source, template_id="template_1", approved_by_ref="actor:owner",
            approved_at="2026-09-28 03:00:00",
        )


def test_frozen_profile_has_no_activation_state() -> None:
    item = approved()
    with pytest.raises(dataclasses.FrozenInstanceError):
        item.name = "changed"
    assert not hasattr(item, "active")
    assert not hasattr(item, "enabled")
    assert not hasattr(item, "default")


def test_package_root_exports_contract() -> None:
    import padiem_ai_core
    for name in (
        "DocumentTemplateCandidate", "DocumentTemplateProfile",
        "DocumentTemplateSourceProvenance", "DocumentTemplateApproval",
        "DocumentTemplateError", "approve_document_template_candidate",
    ):
        assert name in padiem_ai_core.__all__
        assert hasattr(padiem_ai_core, name)
