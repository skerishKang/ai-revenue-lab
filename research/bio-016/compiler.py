#!/usr/bin/env python3
"""Deterministic research compiler for synthetic medical-AI change deltas.

This module is NOT a regulatory decision engine. Rules are a research scaffold that
must be corrected by qualified RA/QA review before any product or regulatory use.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

FORBIDDEN_LABELS = {"APPROVED", "EXEMPT", "NO_SUBMISSION_REQUIRED"}

IMPACT_MAP = {
    "MODEL_UPDATE": ["PERFORMANCE_VALIDATION", "CLINICAL_EVALUATION", "SOFTWARE_VALIDATION", "POSTMARKET_MONITORING_PLAN"],
    "THRESHOLD_CHANGE": ["PERFORMANCE_VALIDATION", "CLINICAL_EVALUATION", "POSTMARKET_MONITORING_PLAN"],
    "DATASET_REFRESH": ["DATA_CHARACTERIZATION", "PERFORMANCE_VALIDATION", "CLINICAL_EVALUATION", "SOFTWARE_VALIDATION", "POSTMARKET_MONITORING_PLAN"],
    "POPULATION_EXPANSION": ["DATA_CHARACTERIZATION", "PERFORMANCE_VALIDATION", "CLINICAL_EVALUATION", "HUMAN_FACTORS", "LABELING_INTENDED_USE", "POSTMARKET_MONITORING_PLAN"],
    "INTENDED_USE_EXPANSION": ["PERFORMANCE_VALIDATION", "CLINICAL_EVALUATION", "HUMAN_FACTORS", "LABELING_INTENDED_USE"],
    "LLM_PROVIDER_MODEL_SWAP": ["GENERATIVE_COMPONENT_VALIDATION", "PROMPT_VALIDATION", "SOFTWARE_VALIDATION", "CYBERSECURITY", "PERFORMANCE_VALIDATION"],
    "PROMPT_CHANGE": ["GENERATIVE_COMPONENT_VALIDATION", "PROMPT_VALIDATION"],
    "RUNTIME_PATCH": ["SOFTWARE_VALIDATION"],
    "CYBERSECURITY_PATCH": ["CYBERSECURITY", "SOFTWARE_VALIDATION"],
    "UI_COPY_ONLY": [],
    "INPUT_DEVICE_CHANGE": ["INPUT_DEVICE_COMPATIBILITY", "INTEGRATION_VALIDATION", "PERFORMANCE_VALIDATION", "CLINICAL_EVALUATION"],
    "INTEGRATION_API_CHANGE": ["INTEGRATION_VALIDATION", "SOFTWARE_VALIDATION"],
    "MODEL_QUANTIZATION": ["PERFORMANCE_VALIDATION", "SOFTWARE_VALIDATION", "CLINICAL_EVALUATION", "POSTMARKET_MONITORING_PLAN"],
    "INFERENCE_HARDWARE_CHANGE": ["PERFORMANCE_VALIDATION", "SOFTWARE_VALIDATION"],
    "DEPENDENCY_CVE_UPDATE": ["CYBERSECURITY", "SOFTWARE_VALIDATION"],
    "DRIFT_ALERT_NO_CODE_CHANGE": ["PERFORMANCE_VALIDATION", "DATA_CHARACTERIZATION", "POSTMARKET_MONITORING_PLAN"],
    "MODEL_REVERT": ["PERFORMANCE_VALIDATION", "SOFTWARE_VALIDATION", "POSTMARKET_MONITORING_PLAN"],
    "AUDIT_LOG_FORMAT_CHANGE": ["SOFTWARE_VALIDATION"],
    "ENCRYPTION_KEY_ROTATION": ["CYBERSECURITY"],
    "DOCUMENT_TYPO_ONLY": [],
}

REVALIDATION_TYPES = {
    "MODEL_UPDATE", "THRESHOLD_CHANGE", "DATASET_REFRESH", "POPULATION_EXPANSION",
    "INTENDED_USE_EXPANSION", "LLM_PROVIDER_MODEL_SWAP", "PROMPT_CHANGE",
    "RUNTIME_PATCH", "CYBERSECURITY_PATCH", "INPUT_DEVICE_CHANGE",
    "INTEGRATION_API_CHANGE", "MODEL_QUANTIZATION", "INFERENCE_HARDWARE_CHANGE",
    "DEPENDENCY_CVE_UPDATE", "DRIFT_ALERT_NO_CODE_CHANGE",
}

DOCUMENT_TYPES = {
    "POPULATION_EXPANSION", "INTENDED_USE_EXPANSION", "UI_COPY_ONLY",
    "AUDIT_LOG_FORMAT_CHANGE", "DOCUMENT_TYPO_ONLY",
}

STALE_TYPES = {
    "MODEL_UPDATE", "THRESHOLD_CHANGE", "DATASET_REFRESH", "POPULATION_EXPANSION",
    "INTENDED_USE_EXPANSION", "LLM_PROVIDER_MODEL_SWAP", "PROMPT_CHANGE",
    "RUNTIME_PATCH", "INPUT_DEVICE_CHANGE", "INTEGRATION_API_CHANGE",
    "MODEL_QUANTIZATION",
}

NO_ACTION_BY_RULESET_TYPES = {"UI_COPY_ONLY", "DOCUMENT_TYPO_ONLY"}


def compile_change(change: dict) -> dict:
    change_type = change.get("type", "")
    impacted = IMPACT_MAP.get(change_type)

    if impacted is None:
        return {
            "id": change.get("id"),
            "change_type": change_type,
            "impacted_classes": [],
            "labels": ["REVIEW_REQUIRED", "RA_QA_DECISION_REQUIRED"],
            "unknown_rule": True,
            "rationale": ["No research rule exists for this change type; qualified RA/QA review is required."],
        }

    labels = ["REVIEW_REQUIRED"]
    if change_type in REVALIDATION_TYPES:
        labels.append("REVALIDATION_CANDIDATE")
    if change_type in DOCUMENT_TYPES:
        labels.append("DOCUMENT_UPDATE_CANDIDATE")
    if change_type in STALE_TYPES:
        labels.append("EVIDENCE_STALE_OR_SCOPE_MISMATCH")
    if change_type in NO_ACTION_BY_RULESET_TYPES:
        labels.append("NO_ADDITIONAL_ACTION_IDENTIFIED_BY_RULESET")
    labels.append("RA_QA_DECISION_REQUIRED")

    if FORBIDDEN_LABELS & set(labels):
        raise AssertionError("Compiler emitted a forbidden regulatory-authority label")

    rationale = [
        f"Research scaffold maps {change_type} to candidate evidence classes: {', '.join(impacted) if impacted else 'none'}.",
        "Output is decision support only; MFDS/FDA/other regulatory interpretation remains with qualified humans and regulators.",
    ]

    return {
        "id": change["id"],
        "change_type": change_type,
        "impacted_classes": impacted,
        "labels": labels,
        "unknown_rule": False,
        "rationale": rationale,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--changes", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    changes = json.loads(Path(args.changes).read_text(encoding="utf-8"))
    if not baseline.get("synthetic_only") or not changes.get("synthetic_only"):
        raise ValueError("BIO-016 first gate accepts synthetic fixtures only")

    predictions = [compile_change(change) for change in changes["changes"]]
    payload = {
        "schema_version": "1.0",
        "product_id": baseline["product"]["product_id"],
        "authority": "RESEARCH_DECISION_SUPPORT_ONLY",
        "predictions": predictions,
    }
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
