#!/usr/bin/env python3
"""Deterministic scorer for BIO-003 synthetic validation responses."""
from __future__ import annotations

import argparse
import csv
import itertools
import json
from collections import defaultdict
from pathlib import Path


def pairwise_sequence_score(expected, response):
    """Fraction of expected event pairs that remain in the correct order."""
    if not expected:
        return 1.0
    if not isinstance(response, list):
        return 0.0
    positions = {value: index for index, value in enumerate(response)}
    pairs = list(itertools.combinations(expected, 2))
    if not pairs:
        return 1.0
    correct = sum(
        1 for left, right in pairs
        if left in positions and right in positions and positions[left] < positions[right]
    )
    return correct / len(pairs)


def set_f1(expected, response):
    expected_set = set(expected)
    response_set = set(response) if isinstance(response, list) else set()
    if not expected_set and not response_set:
        return 1.0
    if not expected_set or not response_set:
        return 0.0
    true_positive = len(expected_set & response_set)
    precision = true_positive / len(response_set)
    recall = true_positive / len(expected_set)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def false_selection_rate(expected, response, choices):
    expected_set = set(expected)
    response_set = set(response) if isinstance(response, list) else set()
    distractors = set(choices) - expected_set
    if not distractors:
        return 0.0
    selected_distractors = (response_set - expected_set) & distractors
    return len(selected_distractors) / len(distractors)


def score_item(question, response):
    kind = question["type"]
    expected = question["answer"]
    if kind == "single_choice":
        return float(response == expected), 0.0
    if kind == "multi_select":
        return (
            set_f1(expected, response),
            false_selection_rate(expected, response, question["choices"]),
        )
    if kind == "sequence":
        return pairwise_sequence_score(expected, response), 0.0
    raise ValueError(f"Unsupported question type: {kind}")


def load_questions(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return {item["id"]: item for item in payload["questions"]}


def parse_response(raw):
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"response_json must be valid JSON: {raw!r}") from exc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", default="questions.json")
    parser.add_argument("--responses", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    questions = load_questions(args.questions)
    scored_rows = []

    with open(args.responses, encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            question_id = row["question_id"]
            if question_id not in questions:
                raise KeyError(f"Unknown question_id: {question_id}")
            question = questions[question_id]
            if row["case_id"] != question["case_id"]:
                raise ValueError(f"case_id mismatch for {question_id}")
            response = parse_response(row["response_json"])
            score, false_rate = score_item(question, response)
            confidence = row.get("confidence_1_5", "").strip()
            calibration = ""
            if confidence:
                normalized_confidence = float(confidence) / 5.0
                calibration = round(abs(normalized_confidence - score), 6)
            scored_rows.append({
                **row,
                "category": question["category"],
                "score": round(score, 6),
                "false_selection_rate": round(false_rate, 6),
                "confidence_calibration_error": calibration,
            })

    if not scored_rows:
        raise ValueError("No response rows found")

    fields = list(scored_rows[0].keys())
    with open(args.out, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(scored_rows)

    grouped = defaultdict(list)
    for row in scored_rows:
        grouped[(row["condition"], row["category"])].append(float(row["score"]))
    summary = {
        f"{condition}::{category}": round(sum(values) / len(values), 6)
        for (condition, category), values in sorted(grouped.items())
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
