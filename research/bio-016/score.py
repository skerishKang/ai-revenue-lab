#!/usr/bin/env python3
"""Score BIO-016 research predictions against the non-regulatory research oracle."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def f1(expected, predicted):
    e, p = set(expected), set(predicted)
    if not e and not p:
        return 1.0
    if not e or not p:
        return 0.0
    tp = len(e & p)
    precision = tp / len(p)
    recall = tp / len(e)
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)


def recall(expected, predicted):
    e, p = set(expected), set(predicted)
    if not e:
        return 1.0
    return len(e & p) / len(e)


def false_positive_rate(expected, predicted):
    e, p = set(expected), set(predicted)
    if not p:
        return 0.0
    return len(p - e) / len(p)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", required=True)
    parser.add_argument("--predictions", required=True)
    args = parser.parse_args()

    gold = json.loads(Path(args.gold).read_text(encoding="utf-8"))
    pred = json.loads(Path(args.predictions).read_text(encoding="utf-8"))
    gold_by_id = {x["id"]: x for x in gold["cases"]}
    pred_by_id = {x["id"]: x for x in pred["predictions"]}

    if set(gold_by_id) != set(pred_by_id):
        raise ValueError("Gold/prediction case IDs differ")

    rows = []
    for case_id in sorted(gold_by_id):
        g, p = gold_by_id[case_id], pred_by_id[case_id]
        rows.append({
            "id": case_id,
            "evidence_recall": recall(g["impacted_classes"], p["impacted_classes"]),
            "evidence_f1": f1(g["impacted_classes"], p["impacted_classes"]),
            "unnecessary_impact_rate": false_positive_rate(g["impacted_classes"], p["impacted_classes"]),
            "label_f1": f1(g["labels"], p["labels"]),
        })

    summary = {
        "n_cases": len(rows),
        "mean_impacted_evidence_recall": sum(x["evidence_recall"] for x in rows) / len(rows),
        "mean_impacted_evidence_f1": sum(x["evidence_f1"] for x in rows) / len(rows),
        "mean_unnecessary_impact_rate": sum(x["unnecessary_impact_rate"] for x in rows) / len(rows),
        "mean_support_label_f1": sum(x["label_f1"] for x in rows) / len(rows),
        "warning": "Scores measure agreement with a research oracle, not regulatory correctness.",
    }
    print(json.dumps({"summary": summary, "cases": rows}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
