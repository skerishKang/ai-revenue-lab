"""Contract tests for the #6061 parliament rule mapping.

These prove the shape of the authority, not the legal correctness of any
provision: every registered record is complete and sourced, unregistered
coordinate lookups fail closed, an unverified value is never presented as a
fact, and no configuration forces a second human on a member who works alone.
"""
from __future__ import annotations

import pytest

from parliament_rules import (
    ApprovalBasis,
    Country,
    DocumentKind,
    InstitutionTier,
    Verification,
    approver_required,
    registered_keys,
    rule_for,
    rules_for_country,
    staffing_for,
    unresolved_keys,
    workflow_steps,
)


def test_every_registered_record_names_its_country_tier_and_kind():
    keys = registered_keys()
    assert keys, "the registry must not be empty"
    for key in keys:
        country, tier, kind = key
        assert Country(country) and InstitutionTier(tier) and DocumentKind(kind)


def test_a_verified_record_carries_a_primary_source_with_an_access_date():
    for key in registered_keys():
        rule = rule_for(*key)
        if rule.verification is not Verification.VERIFIED:
            continue
        assert rule.sources, f"{key} claims VERIFIED without a source"
        for src in rule.sources:
            assert src.url.startswith("https://"), f"{key} source lacks a URL"
            assert src.accessed, f"{key} source lacks an access date"
            assert src.locator, f"{key} source lacks a provision or edition locator"


def test_partial_and_unverified_records_always_name_their_gap():
    for key in registered_keys():
        rule = rule_for(*key)
        if rule.verification is Verification.VERIFIED:
            assert not rule.gaps, f"{key} is VERIFIED but lists gaps"
            continue
        assert rule.gaps, f"{key} is {rule.verification} without saying what is missing"
        for gap in rule.gaps:
            assert gap.reason.strip(), f"{key} gap {gap.field} has no reason"


def test_is_safe_to_use_as_fact_refuses_a_record_with_a_gap():
    korean_draft = rule_for(Country.KR, InstitutionTier.KR_METROPOLITAN, DocumentKind.LEGISLATIVE_DRAFT)
    assert korean_draft.verification is Verification.PARTIAL
    assert not korean_draft.is_safe_to_use_as_fact()
    assert korean_draft.unverified_fields == ("initiation quorum",)

    gangjin = rule_for("kr", "kr_local", "legislative_draft")
    assert gangjin.is_safe_to_use_as_fact()
    assert "재적 5분의 1" in gangjin.notes


def test_an_unregistered_coordinate_fails_closed_instead_of_guessing():
    rule = rule_for("kr", "kr_national", "sns")
    assert rule.verification is Verification.UNVERIFIED
    assert rule.coordinate_kinds == ()
    assert rule.terms == ()
    assert rule.approval is ApprovalBasis.NOT_RESEARCHED
    assert not rule.is_safe_to_use_as_fact()
    assert "no research registered" in rule.gaps[0].reason


def test_an_unknown_country_is_rejected_rather_than_defaulted():
    with pytest.raises(KeyError):
        rule_for("de", "kr_national", "speech")


def test_a_key_is_never_registered_twice():
    keys = registered_keys()
    assert len(keys) == len(set(keys))


def test_a_solo_member_never_gains_a_phantom_reviewer():
    for tier, kind in (
        ("kr_metropolitan", "scrutiny"),
        ("us_local", "legislative_draft"),
        ("uk_councillor", "casework"),
        ("fr_commune", "stored_document"),
    ):
        rule = rule_for(_country_for_tier(tier), tier, kind)
        assert not approver_required(rule), f"{tier}/{kind} must stay approver-free"
        actors = [step.actor for step in workflow_steps(rule, staffed=True)]
        assert "staff" not in actors, f"{tier}/{kind} invented a reviewer"


def test_a_staffed_workflow_with_a_real_approval_basis_keeps_the_review_stage():
    rule = rule_for("kr", "kr_national", "legislative_draft")
    assert approver_required(rule)
    staffed = [s.actor for s in workflow_steps(rule, staffed=True)]
    assert "staff" in staffed
    unstaffed = [s.actor for s in workflow_steps(rule, staffed=False)]
    assert "staff" not in unstaffed, "the same record must work when there is no staff"
    assert unstaffed[-2] == "member"


def test_every_workflow_ends_with_member_approval_and_storage():
    for key in registered_keys():
        rule = rule_for(*key)
        actors = [s.actor for s in workflow_steps(rule, staffed=True)]
        assert actors[0] == "user"
        assert "member" in actors
        assert actors[-1] == "parliament ai"
        assert sum(1 for a in actors if a == "member") == 1, f"{key} duplicates the approval step"


def test_country_specific_coordinates_are_not_shared_across_countries():
    korean = rule_for("kr", "kr_local", "legislative_draft").coordinate_kinds
    french = rule_for("fr", "fr_national", "legislative_draft").coordinate_kinds
    assert korean and french
    assert set(korean).isdisjoint(french), "one citation model cannot serve both legal systems"


def test_staffing_models_record_the_unit_of_support_per_tier():
    kr_local = staffing_for("kr", "kr_local")
    assert kr_local is not None
    assert "의장" in kr_local.headcount_rule or "없음" in kr_local.headcount_rule
    fr_commune = staffing_for("fr", "fr_commune")
    assert "30%" in fr_commune.headcount_rule
    assert fr_commune.sources[0].url.startswith("https://www.collectivites-locales.gouv.fr/")


def test_staffing_gaps_are_visible_for_the_tiers_we_only_measured_once():
    for key in (("uk", "uk_devolved"), ("us", "us_local"), ("kr", "kr_national")):
        model = staffing_for(*key)
        assert model is not None
        if model.verification is not Verification.VERIFIED:
            assert model.gaps, f"{key} staffing is partial without a stated gap"


def test_unresolved_keys_are_reportable_as_a_list():
    unresolved = unresolved_keys()
    assert unresolved
    for key in unresolved:
        assert key in registered_keys()


def test_a_country_view_only_returns_that_country():
    for rule in rules_for_country(Country.UK):
        assert rule.country is Country.UK
    assert len(rules_for_country("kr")) < len(registered_keys())


def _country_for_tier(tier: str) -> Country:
    return {
        "kr": Country.KR, "us": Country.US, "uk": Country.UK, "fr": Country.FR,
    }[tier.split("_")[0]]


def test_two_different_laws_never_share_one_identifier():
    """A copied ``lsiSeq`` silently cites the wrong statute.

    #6062 review caught 국회법 and 「행정업무의 운영 및 혁신에 관한 규정」 pointing
    at the same law.go.kr sequence number, so the pairing is now asserted.
    """
    seen = {}
    for key in registered_keys():
        for src in rule_for(*key).sources:
            identity = src.url.split("?")[-1]
            if src.title in seen:
                assert seen[src.title] == identity, f"{src.title} is cited by two different identifiers"
            elif identity in seen.values():
                same = next(k for k, v in seen.items() if v == identity)
                raise AssertionError(f"{src.title} and {same} share identifier {identity}")
            seen[src.title] = identity


def test_every_korean_source_carries_an_identifier_and_an_effective_date():
    """law.go.kr has two citation forms and both must stay identifiable.

    ``lsInfoP.do?lsiSeq=`` names a statute version, ``lawService.do?...&MST=``
    names a retrieved 자치법규 body. Either is acceptable; an unqualified
    homepage link is not.
    """
    for key in registered_keys():
        for src in rule_for(*key).sources:
            if "law.go.kr" not in src.url:
                continue
            assert "lsiSeq=" in src.url or "MST=" in src.url, f"{key}: {src.url}"
            if "lsiSeq=" in src.url and src.title != "행정업무의 운영 및 혁신에 관한 규정":
                assert "efYd=" in src.url, f"{key} cites a statute version without its effective date"


def test_the_decree_is_not_cited_under_the_assembly_act_identifier():
    assembly = rule_for("kr", "kr_national", "legislative_draft").sources[0]
    decree = rule_for("kr", "kr_national", "formatted_official").sources[0]
    assert "lsiSeq=289167" in assembly.url
    assert "lsiSeq=290525" in decree.url
    assert assembly.url != decree.url


def test_the_document_format_record_keeps_its_open_question_visible():
    rule = rule_for("kr", "kr_local", "formatted_official")
    assert rule.verification is Verification.PARTIAL
    assert "applicability" in rule.unverified_fields
    assert not rule.is_safe_to_use_as_fact()
    assert any("행정업무의 운영" in s.title for s in rule.sources)
