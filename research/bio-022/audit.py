from __future__ import annotations

import numpy as np
from sklearn.metrics import roc_auc_score

from fixture import generate_fixture, fixture_manifest
from models import train_conditions, fingerprint_model
from control_experiment import (
    binary_attack_metrics,
    run_false_positive_control,
    true_label_confidence,
)

ATTACK_AUC_SIGNAL = 0.65
FORBIDDEN_CONCLUSIONS = {
    "PRIVACY_SAFE",
    "EXPORT_APPROVED",
    "LEGAL_COMPLIANT",
    "ANONYMIZED",
    "NO_PRIVACY_RISK",
}


def audit_membership(model, x, y, member_idx, nonmember_idx):
    return binary_attack_metrics(
        true_label_confidence(model, x, y, member_idx),
        true_label_confidence(model, x, y, nonmember_idx),
    )


def subgroup_separation_proxy(model, x, y, subgroup, idx):
    scores = true_label_confidence(model, x, y, idx)
    labels = (subgroup[idx] == 0).astype(int)
    return {
        "proxy_name": "true-label-confidence subgroup-separation AUC",
        "roc_auc": float(roc_auc_score(labels, scores)),
        "warning": "Synthetic bias/control proxy only; not proof of attribute inference or privacy leakage.",
    }


def run_audit():
    x, y, subgroup, splits = generate_fixture()
    models = train_conditions(x, y, splits)
    nonmembers = splits["nonmember_pool"]

    overfit_members = splits["overfit_train"]
    regularized_members = splits["regularized_train"][:600]
    membership = {
        "overfit": audit_membership(
            models["overfit"],
            x,
            y,
            overfit_members,
            nonmembers[: len(overfit_members)],
        ),
        "regularized": audit_membership(
            models["regularized"],
            x,
            y,
            regularized_members,
            nonmembers[: len(regularized_members)],
        ),
    }

    control = run_false_positive_control(
        models["regularized"], x, y, subgroup, splits["control_pool"]
    )

    labels = ["HUMAN_EXPORT_REVIEW_REQUIRED"]
    if membership["overfit"]["roc_auc"] >= ATTACK_AUC_SIGNAL:
        labels += ["ATTACK_SIGNAL_DETECTED", "REMEDIATION_RETEST_REQUIRED"]
    if control["suspected_false_positive"]:
        labels.append("CONTROL_EXPERIMENT_SUSPECTS_FALSE_POSITIVE")
    if (
        membership["overfit"]["roc_auc"] < ATTACK_AUC_SIGNAL
        and not control["suspected_false_positive"]
    ):
        labels.append("NO_MATERIAL_SIGNAL_IDENTIFIED_BY_CURRENT_TESTS")

    if FORBIDDEN_CONCLUSIONS & set(labels):
        raise AssertionError("Forbidden privacy/export conclusion emitted")

    return {
        "schema_version": "0.1",
        "authority": "RESEARCH_DECISION_SUPPORT_ONLY",
        "fixture": fixture_manifest(),
        "threat_model": {
            "attacker_access": "black-box predict_proba-like confidence access in synthetic benchmark",
            "membership_attack": "true-label-confidence ranking attack",
            "limitations": [
                "synthetic fixture",
                "single membership-attack family",
                "subgroup proxy is not an attribute-inference attack",
                "not a legal privacy test",
                "not proof of absence of leakage",
            ],
        },
        "models": {name: fingerprint_model(model) for name, model in models.items()},
        "membership_audit": membership,
        "control_experiment": control,
        "subgroup_separation_proxy": subgroup_separation_proxy(
            models["regularized"], x, y, subgroup, splits["control_pool"][:1000]
        ),
        "support_labels": labels,
        "forbidden_conclusions": sorted(FORBIDDEN_CONCLUSIONS),
    }
