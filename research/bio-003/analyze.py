#!/usr/bin/env python3
"""Condition-level descriptive analysis for the BIO-003 pilot."""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict


def summarize(values):
    if not values:
        return {"n": 0, "mean": None, "median": None}
    return {
        "n": len(values),
        "mean": sum(values) / len(values),
        "median": statistics.median(values),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scored", required=True)
    parser.add_argument("--ratings")
    args = parser.parse_args()

    metric_values = defaultdict(list)
    response_times = defaultdict(list)
    false_rates = defaultdict(list)
    calibration = defaultdict(list)

    with open(args.scored, encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            key = (row["condition"], row["category"])
            metric_values[key].append(float(row["score"]))
            if row.get("response_time_ms", "").strip():
                response_times[key].append(float(row["response_time_ms"]))
            if row.get("false_selection_rate", "").strip():
                false_rates[key].append(float(row["false_selection_rate"]))
            if row.get("confidence_calibration_error", "").strip():
                calibration[key].append(float(row["confidence_calibration_error"]))

    output = {
        "scores": {},
        "response_time_ms": {},
        "false_selection_rate": {},
        "confidence_calibration_error": {},
    }

    for source, name in [
        (metric_values, "scores"),
        (response_times, "response_time_ms"),
        (false_rates, "false_selection_rate"),
        (calibration, "confidence_calibration_error"),
    ]:
        for (condition, category), values in sorted(source.items()):
            output[name][f"{condition}::{category}"] = summarize(values)

    if args.ratings:
        ratings = defaultdict(lambda: {"cognitive_load": [], "usefulness": []})
        with open(args.ratings, encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                condition = row["condition"]
                if row.get("cognitive_load_1_7", "").strip():
                    ratings[condition]["cognitive_load"].append(float(row["cognitive_load_1_7"]))
                if row.get("usefulness_1_7", "").strip():
                    ratings[condition]["usefulness"].append(float(row["usefulness_1_7"]))
        output["ratings"] = {
            condition: {metric: summarize(values) for metric, values in metrics.items()}
            for condition, metrics in sorted(ratings.items())
        }

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
