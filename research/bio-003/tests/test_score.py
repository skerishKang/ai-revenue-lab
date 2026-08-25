import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import score


def load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def rendering_text(rendering):
    if not rendering:
        return ""
    if isinstance(rendering[0], str):
        return "\n".join(rendering)
    return "\n".join(item["text"] for item in rendering)


def fact_dependencies(entry):
    if isinstance(entry, list):
        return set(entry)
    return set(entry["facts"])


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
    payload = load("cases.json")
    assert payload["synthetic_only"] is True
    assert len(payload["cases"]) >= 3
    for case in payload["cases"]:
        assert set(case["renderings"]) == {"summary", "timeline", "story"}
        assert case["facts"]


def test_condition_fact_coverage_equals_canonical_fact_set():
    cases = {case["case_id"]: case for case in load("cases.json")["cases"]}
    contract = load("fact_coverage.json")["cases"]

    assert set(contract) == set(cases)
    for case_id, case in cases.items():
        canonical_from_case = {fact["id"] for fact in case["facts"]}
        canonical_from_contract = set(contract[case_id]["canonical_fact_ids"])
        assert canonical_from_contract == canonical_from_case

        conditions = contract[case_id]["conditions"]
        assert set(conditions) == {"summary", "timeline", "story"}
        for condition, anchors_by_fact in conditions.items():
            assert set(anchors_by_fact) == canonical_from_case
            text = rendering_text(case["renderings"][condition])
            for fact_id, anchor in anchors_by_fact.items():
                assert anchor in text, (
                    f"{case_id}/{condition} claims {fact_id} coverage but anchor is missing: {anchor!r}"
                )


def test_question_fact_map_is_complete_and_supported_by_every_condition():
    cases = {case["case_id"]: case for case in load("cases.json")["cases"]}
    questions = load("questions.json")["questions"]
    question_map = load("question_fact_map.json")["questions"]
    coverage = load("fact_coverage.json")["cases"]

    question_ids = {question["id"] for question in questions}
    assert set(question_map) == question_ids

    for question in questions:
        case_id = question["case_id"]
        required = fact_dependencies(question_map[question["id"]])
        canonical = {fact["id"] for fact in cases[case_id]["facts"]}
        assert required
        assert required <= canonical
        for condition, anchors_by_fact in coverage[case_id]["conditions"].items():
            assert required <= set(anchors_by_fact), (
                f"{question['id']} depends on facts absent from {case_id}/{condition}: "
                f"{sorted(required - set(anchors_by_fact))}"
            )


def test_delayed_recall_subset_has_three_balanced_items_per_case():
    questions = {q["id"]: q for q in load("questions.json")["questions"]}
    question_map = load("question_fact_map.json")["questions"]

    delayed = [qid for qid, meta in question_map.items() if meta.get("delayed_recall_recommended") is True]
    assert len(delayed) == 9

    for case_id in ("A", "B", "C"):
        case_delayed = [qid for qid in delayed if questions[qid]["case_id"] == case_id]
        assert len(case_delayed) == 3
        assert {questions[qid]["category"] for qid in case_delayed} == {
            "source_attribution", "follow_up", "retrieval"
        }


def test_questions_cover_primary_categories_for_each_case():
    payload = load("questions.json")
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
    payload = load("counterbalancing.json")
    for group in payload["groups"]:
        assert {item["case_id"] for item in group["order"]} == {"A", "B", "C"}
        assert {item["condition"] for item in group["order"]} == {"summary", "timeline", "story"}
