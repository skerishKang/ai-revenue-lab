"""Tests for deterministic grounding checks."""

import pytest

from app.pipeline.errors import GroundingError
from app.pipeline.grounding import (
    GroundingPolicy,
    GroundingViolation,
    check_grounding,
    find_violations,
)


class TestGroundingPolicy:
    def test_empty_policy(self):
        policy = GroundingPolicy()
        assert policy.prohibited_tokens == frozenset()

    def test_policy_normalizes_tokens(self):
        policy = GroundingPolicy(prohibited_tokens=frozenset({" Husband ", "WIFE"}))
        assert "husband" in policy.prohibited_tokens
        assert "wife" in policy.prohibited_tokens

    def test_empty_token_raises(self):
        with pytest.raises(GroundingError, match="non-empty"):
            GroundingPolicy(prohibited_tokens=frozenset({"", "valid"}))

    def test_whitespace_token_raises(self):
        with pytest.raises(GroundingError, match="non-empty"):
            GroundingPolicy(prohibited_tokens=frozenset({"   "}))

    def test_non_string_token_raises(self):
        with pytest.raises(GroundingError, match="non-empty"):
            GroundingPolicy(prohibited_tokens=frozenset({123}))

    def test_allowed_facts_accepted(self):
        policy = GroundingPolicy(
            prohibited_tokens=frozenset({"husband"}),
            allowed_facts=("loves cooking", "started last year"),
        )
        assert "husband" in policy.prohibited_tokens


class TestCheckGrounding:
    def test_no_prohibited_tokens_passes(self):
        policy = GroundingPolicy(prohibited_tokens=frozenset())
        check_grounding(policy=policy, visible_fields={"opening": "This is safe."})

    def test_empty_visible_fields_passes(self):
        policy = GroundingPolicy(prohibited_tokens=frozenset({"husband"}))
        check_grounding(policy=policy, visible_fields={})

    def test_prohibited_token_detected(self):
        policy = GroundingPolicy(prohibited_tokens=frozenset({"husband"}))
        with pytest.raises(GroundingError, match="prohibited invention"):
            check_grounding(
                policy=policy,
                visible_fields={"opening": "My husband and I went to the park"},
            )

    def test_prohibited_token_not_detected_in_non_visible_field(self):
        policy = GroundingPolicy(prohibited_tokens=frozenset({"husband"}))
        check_grounding(policy=policy, visible_fields={"opening": "We went to the park"})

    def test_prohibited_token_part_of_word_not_matched(self):
        policy = GroundingPolicy(prohibited_tokens=frozenset({"date"}))
        check_grounding(policy=policy, visible_fields={"opening": "Please update your profile"})

    def test_case_insensitive_matching(self):
        policy = GroundingPolicy(prohibited_tokens=frozenset({"HUSBAND"}))
        with pytest.raises(GroundingError, match="prohibited invention"):
            check_grounding(
                policy=policy,
                visible_fields={"opening": "My husband is kind"},
            )

    def test_non_string_field_raises(self):
        policy = GroundingPolicy(prohibited_tokens=frozenset({"test"}))
        with pytest.raises(GroundingError, match="must be a string"):
            check_grounding(policy=policy, visible_fields={"count": 42})

    def test_multiple_prohibited_tokens_first_hit_raised(self):
        policy = GroundingPolicy(
            prohibited_tokens=frozenset({"spouse", "doctor", "diagnosis"})
        )
        with pytest.raises(GroundingError, match="prohibited invention"):
            check_grounding(
                policy=policy,
                visible_fields={
                    "opening": "My spouse and I talked to the doctor",
                },
            )

    def test_invalid_visible_fields_raises(self):
        policy = GroundingPolicy(prohibited_tokens=frozenset({"test"}))
        with pytest.raises(GroundingError, match="must be a dict"):
            check_grounding(policy=policy, visible_fields="not a dict")  # type: ignore

    def test_short_token_does_not_match_longer_word(self):
        policy = GroundingPolicy(prohibited_tokens=frozenset({"husband"}))
        check_grounding(
            policy=policy,
            visible_fields={"opening": "This is about husbandry"},
        )


class TestFindViolations:
    def test_no_violations_returns_empty(self):
        policy = GroundingPolicy(prohibited_tokens=frozenset({"husband"}))
        violations = find_violations(
            policy=policy,
            visible_fields={"opening": "Safe text"},
        )
        assert violations == []

    def test_single_violation_found(self):
        policy = GroundingPolicy(prohibited_tokens=frozenset({"husband"}))
        violations = find_violations(
            policy=policy,
            visible_fields={"opening": "My husband is here"},
        )
        assert len(violations) == 1
        assert violations[0].token == "husband"
        assert violations[0].field == "opening"

    def test_multiple_violations_in_one_field(self):
        policy = GroundingPolicy(
            prohibited_tokens=frozenset({"husband", "doctor"})
        )
        violations = find_violations(
            policy=policy,
            visible_fields={"opening": "My husband and my doctor agree"},
        )
        assert len(violations) == 2
        tokens = {v.token for v in violations}
        assert tokens == {"husband", "doctor"}

    def test_violations_in_multiple_fields(self):
        policy = GroundingPolicy(
            prohibited_tokens=frozenset({"spouse", "diagnosis"})
        )
        violations = find_violations(
            policy=policy,
            visible_fields={
                "opening": "My spouse is here",
                "deck": "No diagnosis needed",
            },
        )
        assert len(violations) == 2
        fields = {v.field for v in violations}
        assert fields == {"opening", "deck"}

    def test_none_value_skipped(self):
        policy = GroundingPolicy(prohibited_tokens=frozenset({"husband"}))
        violations = find_violations(
            policy=policy,
            visible_fields={"opening": None, "deck": "Safe text"},
        )
        assert violations == []

    def test_non_string_value_skipped(self):
        policy = GroundingPolicy(prohibited_tokens=frozenset({"husband"}))
        violations = find_violations(
            policy=policy,
            visible_fields={"opening": 42, "deck": "Safe text"},
        )
        assert violations == []

    def test_invalid_fields_raises(self):
        policy = GroundingPolicy(prohibited_tokens=frozenset({"test"}))
        with pytest.raises(GroundingError, match="must be a dict"):
            find_violations(policy=policy, visible_fields=[1, 2, 3])  # type: ignore
