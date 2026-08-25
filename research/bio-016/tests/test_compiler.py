import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import compiler


def load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def baseline():
    return load("product_baseline.json")


def change(case_id):
    return next(c for c in load("changes.json")["changes"] if c["id"] == case_id)


def test_fixture_is_synthetic_and_has_twenty_changes():
    base = baseline()
    changes = load("changes.json")
    assert base["synthetic_only"] is True
    assert changes["synthetic_only"] is True
    assert len(changes["changes"]) >= 20
    assert len(base["evidence_inventory"]) >= 12


def test_no_forbidden_authority_labels_are_emitted():
    base = baseline()
    changes = load("changes.json")["changes"]
    for item in changes:
        result = compiler.compile_change(item, base)
        assert not (compiler.FORBIDDEN_LABELS & set(result["labels"]))
        assert "RA_QA_DECISION_REQUIRED" in result["labels"]


def test_model_change_and_document_typo_are_not_treated_the_same():
    base = baseline()
    model = compiler.compile_change(change("C01"), base)
    typo = compiler.compile_change(change("C20"), base)
    assert "REVALIDATION_CANDIDATE" in model["labels"]
    assert "REVALIDATION_CANDIDATE" not in typo["labels"]
    assert typo["impacted_classes"] == []
    assert typo["stale_evidence_ids"] == []


def test_model_update_marks_exact_version_scoped_records_stale():
    result = compiler.compile_change(change("C01"), baseline())
    assert set(result["stale_evidence_ids"]) == {
        "E-PERF-001", "E-CLIN-001", "E-SWVAL-001", "E-MON-001"
    }
    assert "EVIDENCE_STALE_OR_SCOPE_MISMATCH" in result["labels"]


def test_threshold_change_uses_normalized_scope_token():
    result = compiler.compile_change(change("C02"), baseline())
    assert set(result["stale_evidence_ids"]) == {"E-PERF-001", "E-MON-001"}
    delta = next(x for x in result["scope_deltas"] if x["field"] == "decision_threshold")
    assert delta["before_tokens"] == ["threshold-0.65"]
    assert delta["after_tokens"] == ["threshold-0.7"]


def test_intended_use_expansion_routes_to_document_revalidation_and_exact_scope_gap():
    result = compiler.compile_change(change("C05"), baseline())
    assert "CLINICAL_EVALUATION" in result["impacted_classes"]
    assert "LABELING_INTENDED_USE" in result["impacted_classes"]
    assert "DOCUMENT_UPDATE_CANDIDATE" in result["labels"]
    assert "REVALIDATION_CANDIDATE" in result["labels"]
    assert set(result["stale_evidence_ids"]) == {"E-CLIN-001", "E-HF-001", "E-LABEL-001"}


def test_added_input_device_detects_partial_scope_coverage_as_gap():
    result = compiler.compile_change(change("C11"), baseline())
    assert set(result["stale_evidence_ids"]) == {"E-HW-001", "E-INT-001", "E-PERF-001"}
    assert "E-CLIN-001" not in result["stale_evidence_ids"]


def test_security_patch_is_class_impact_not_fake_scope_staleness_when_component_absent():
    result = compiler.compile_change(change("C09"), baseline())
    assert result["stale_evidence_ids"] == []
    relations = {x["evidence_id"]: x["scope_relation"] for x in result["impacted_evidence"]}
    assert relations["E-CYBER-001"] == "CLASS_IMPACT_ONLY_REVIEW"
    assert relations["E-SWVAL-001"] == "CLASS_IMPACT_ONLY_REVIEW"
    assert "EVIDENCE_STALE_OR_SCOPE_MISMATCH" not in result["labels"]


def test_revert_to_baseline_model_is_recognized_as_current_scope_not_stale():
    result = compiler.compile_change(change("C17"), baseline())
    assert result["stale_evidence_ids"] == []
    assert set(result["covered_evidence_ids"]) == {"E-PERF-001", "E-SWVAL-001", "E-MON-001"}
    assert "EVIDENCE_STALE_OR_SCOPE_MISMATCH" not in result["labels"]


def test_unknown_change_fails_safe_to_human_review():
    result = compiler.compile_change({"id": "X", "type": "UNKNOWN_NEW_CHANGE"}, baseline())
    assert result["unknown_rule"] is True
    assert result["impacted_classes"] == []
    assert result["stale_evidence_ids"] == []
    assert result["labels"] == ["REVIEW_REQUIRED", "RA_QA_DECISION_REQUIRED"]


def test_research_oracle_is_explicitly_non_regulatory_and_has_evidence_level_targets():
    gold = load("gold.json")
    assert gold["authority"] == "RESEARCH_ORACLE_NOT_REGULATORY_TRUTH"
    assert len(gold["cases"]) >= 20
    assert all("stale_evidence_ids" in case for case in gold["cases"])
