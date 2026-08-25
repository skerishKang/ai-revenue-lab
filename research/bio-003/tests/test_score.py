import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import score


def test_single_choice():
    question = {"type": "single_choice", "answer": "A"}
    assert score.score_item(question, "A")[0] == 1.0
    assert score.score_item(question, "B")[0] == 0.0


def test_multiselect_penalizes_distractor():
    question = {
        "type": "multi_select",
        "answer": ["A", "B"],
        "choices": ["A", "B", "C"],
    }
    item_score, false_rate = score.score_item(question, ["A", "B", "C"])
    assert 0.0 < item_score < 1.0
    assert false_rate == 1.0


def test_sequence_pairwise_partial_credit():
    question = {"type": "sequence", "answer": ["A", "B", "C"]}
    item_score, _ = score.score_item(question, ["A", "C", "B"])
    assert 0.0 < item_score < 1.0


def test_cases_are_synthetic_and_have_all_conditions():
    payload = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))
    assert payload["synthetic_only"] is True
    assert len(payload["cases"]) >= 3
    for case in payload["cases"]:
        assert set(case["renderings"]) == {"summary", "timeline", "story"}
        assert case["facts"]


def test_questions_cover_primary_categories_for_each_case():
    payload = json.loads((ROOT / "questions.json").read_text(encoding="utf-8"))
    by_case = {}
    for question in payload["questions"]:
        by_case.setdefault(question["case_id"], set()).add(question["category"])
    for case_id in ("A", "B", "C"):
        assert "source_attribution" in by_case[case_id]
        assert "follow_up" in by_case[case_id]
        assert "factual_recall" in by_case[case_id]
        assert "sequence" in by_case[case_id]
        assert "retrieval" in by_case[case_id]


def test_counterbalancing_covers_each_case_and_condition_once_per_group():
    payload = json.loads((ROOT / "counterbalancing.json").read_text(encoding="utf-8"))
    for group in payload["groups"]:
        assert {item["case_id"] for item in group["order"]} == {"A", "B", "C"}
        assert {item["condition"] for item in group["order"]} == {"summary", "timeline", "story"}
