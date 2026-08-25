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

NO_ACTION_BY_RULESET_TYPES = {"UI_COPY_ONLY", "DOCUMENT_TYPO_ONLY"}

# Synthetic-fixture aliases only. These normalize the human-readable change fixture
# into the exact scope tokens already present in product_baseline.json. They are not
# regulatory rules and must never be generalized to real products without review.
SYNTHETIC_SCOPE_ALIASES = {
    "review-support-v1": "intended-use-v1",
    "recommendation-draft-v2": "intended-use-v2",
}


def _scope_tokens(field: str, value) -> set[str]:
    """Normalize one synthetic change value to evidence-scope tokens."""
    if value is None:
        return set()
    if field == "decision_threshold":
        return {f"threshold-{float(value):g}"}
    if field == "intended_use":
        return {SYNTHETIC_SCOPE_ALIASES.get(str(value), str(value))}
    if field == "input_interface" and value == "device-adapter-1.0+2.0":
        return {"device-adapter-1.0", "device-adapter-2.0"}
    if isinstance(value, list):
        tokens: set[str] = set()
        for item in value:
            tokens |= _scope_tokens(field, item)
        return tokens
    return {str(value)}


def _change_scope_deltas(change: dict) -> list[dict]:
    deltas = []
    for field, pair in change.get("changed", {}).items():
        if not isinstance(pair, list) or len(pair) != 2:
            continue
        before, after = pair
        deltas.append({
            "field": field,
            "before_tokens": sorted(_scope_tokens(field, before)),
            "after_tokens": sorted(_scope_tokens(field, after)),
        })
    return deltas


def _assess_evidence(impacted_classes: list[str], baseline: dict | None, change: dict) -> tuple[list[dict], list[str], list[str], list[str]]:
    """Assess exact evidence records against the synthetic before/after scope delta.

    A class can be impacted even when its current evidence scope does not contain the
    changed component. In that case we retain CLASS_IMPACT_ONLY_REVIEW rather than
    pretending the record is stale. A record is marked stale/scope-mismatched only
    when it explicitly covers a before-token but does not cover the corresponding
    after-token(s). A revert to a token already in current evidence can therefore be
    recognized as COVERED_BY_CURRENT_SCOPE.
    """
    inventory = (baseline or {}).get("evidence_inventory", [])
    deltas = _change_scope_deltas(change)
    impacted_evidence = []
    stale_ids: list[str] = []
    covered_ids: list[str] = []

    for evidence in inventory:
        if evidence.get("class") not in impacted_classes:
            continue
        scope = set(evidence.get("scope", []))
        stale_fields = []
        covered_fields = []
        for delta in deltas:
            before = set(delta["before_tokens"])
            after = set(delta["after_tokens"])
            if before and scope.intersection(before):
                if after and not after.issubset(scope):
                    stale_fields.append(delta["field"])
                elif after and after.issubset(scope):
                    covered_fields.append(delta["field"])
            elif after and scope.intersection(after):
                covered_fields.append(delta["field"])

        if stale_fields:
            relation = "STALE_OR_SCOPE_MISMATCH"
            stale_ids.append(evidence["evidence_id"])
        elif covered_fields:
            relation = "COVERED_BY_CURRENT_SCOPE"
            covered_ids.append(evidence["evidence_id"])
        else:
            relation = "CLASS_IMPACT_ONLY_REVIEW"

        impacted_evidence.append({
            "evidence_id": evidence["evidence_id"],
            "class": evidence["class"],
            "version": evidence.get("version"),
            "status": evidence.get("status"),
            "scope": evidence.get("scope", []),
            "scope_relation": relation,
            "matched_changed_fields": sorted(set(stale_fields + covered_fields)),
        })

    inventory_classes = {e.get("class") for e in inventory}
    unmapped_classes = sorted(set(impacted_classes) - inventory_classes)
    return impacted_evidence, sorted(stale_ids), sorted(covered_ids), unmapped_classes


def compile_change(change: dict, baseline: dict | None = None) -> dict:
    change_type = change.get("type", "")
    impacted = IMPACT_MAP.get(change_type)

    if impacted is None:
        return {
            "id": change.get("id"),
            "change_type": change_type,
            "impacted_classes": [],
            "impacted_evidence": [],
            "stale_evidence_ids": [],
            "covered_evidence_ids": [],
            "unmapped_impacted_classes": [],
            "scope_deltas": _change_scope_deltas(change),
            "labels": ["REVIEW_REQUIRED", "RA_QA_DECISION_REQUIRED"],
            "unknown_rule": True,
            "rationale": ["No research rule exists for this change type; qualified RA/QA review is required."],
        }

    impacted_evidence, stale_ids, covered_ids, unmapped_classes = _assess_evidence(impacted, baseline, change)

    labels = ["REVIEW_REQUIRED"]
    if change_type in REVALIDATION_TYPES:
        labels.append("REVALIDATION_CANDIDATE")
    if change_type in DOCUMENT_TYPES:
        labels.append("DOCUMENT_UPDATE_CANDIDATE")
    if stale_ids:
        labels.append("EVIDENCE_STALE_OR_SCOPE_MISMATCH")
    if change_type in NO_ACTION_BY_RULESET_TYPES:
        labels.append("NO_ADDITIONAL_ACTION_IDENTIFIED_BY_RULESET")
    labels.append("RA_QA_DECISION_REQUIRED")

    if FORBIDDEN_LABELS & set(labels):
        raise AssertionError("Compiler emitted a forbidden regulatory-authority label")

    rationale = [
        f"Research scaffold maps {change_type} to candidate evidence classes: {', '.join(impacted) if impacted else 'none'}.",
        f"Exact synthetic evidence-scope check found {len(stale_ids)} stale/scope-mismatched record(s), {len(covered_ids)} record(s) already covering an after-token, and {len(unmapped_classes)} impacted class(es) absent from the inventory.",
        "Output is decision support only; MFDS/FDA/other regulatory interpretation remains with qualified humans and regulators.",
    ]

    return {
        "id": change["id"],
        "change_type": change_type,
        "impacted_classes": impacted,
        "impacted_evidence": impacted_evidence,
        "stale_evidence_ids": stale_ids,
        "covered_evidence_ids": covered_ids,
        "unmapped_impacted_classes": unmapped_classes,
        "scope_deltas": _change_scope_deltas(change),
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

    predictions = [compile_change(change, baseline) for change in changes["changes"]]
    payload = {
        "schema_version": "1.1",
        "product_id": baseline["product"]["product_id"],
        "authority": "RESEARCH_DECISION_SUPPORT_ONLY",
        "predictions": predictions,
    }
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
