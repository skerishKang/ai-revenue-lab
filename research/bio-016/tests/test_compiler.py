import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import compiler


def load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_fixture_is_synthetic_and_has_twenty_changes():
    baseline = load("product_baseline.json")
    changes = load("changes.json")
    assert baseline["synthetic_only"] is True
    assert changes["synthetic_only"] is True
    assert len(changes["changes"]) >= 20


def test_no_forbidden_authority_labels_are_emitted():
    changes = load("changes.json")["changes"]
    for change in changes:
        result = compiler.compile_change(change)
        assert not (compiler.FORBIDDEN_LABELS & set(result["labels"]))
        assert "RA_QA_DECISION_REQUIRED" in result["labels"]


def test_model_change_and_document_typo_are_not_treated_the_same():
    changes = {c["id"]: c for c in load("changes.json")["changes"]}
    model = compiler.compile_change(changes["C01"])
    typo = compiler.compile_change(changes["C20"])
    assert "REVALIDATION_CANDIDATE" in model["labels"]
    assert "REVALIDATION_CANDIDATE" not in typo["labels"]
    assert typo["impacted_classes"] == []


def test_intended_use_expansion_routes_to_document_and_revalidation_review():
    change = next(c for c in load("changes.json")["changes"] if c["id"] == "C05")
    result = compiler.compile_change(change)
    assert "CLINICAL_EVALUATION" in result["impacted_classes"]
    assert "LABELING_INTENDED_USE" in result["impacted_classes"]
    assert "DOCUMENT_UPDATE_CANDIDATE" in result["labels"]
    assert "REVALIDATION_CANDIDATE" in result["labels"]


def test_unknown_change_fails_safe_to_human_review():
    result = compiler.compile_change({"id": "X", "type": "UNKNOWN_NEW_CHANGE"})
    assert result["unknown_rule"] is True
    assert result["impacted_classes"] == []
    assert result["labels"] == ["REVIEW_REQUIRED", "RA_QA_DECISION_REQUIRED"]


def test_research_oracle_is_explicitly_non_regulatory():
    gold = load("gold.json")
    assert gold["authority"] == "RESEARCH_ORACLE_NOT_REGULATORY_TRUTH"
    assert len(gold["cases"]) >= 20
