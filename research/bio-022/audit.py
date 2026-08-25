from __future__ import annotations

import numpy as np
from sklearn.metrics import roc_auc_score

from fixture import generate_fixture, fixture_manifest
from models import train_conditions, fingerprint_model
from control_experiment import (
    binary_attack_metrics,
    run_covariate_shift_control,
    run_exchangeable_null_control,
    true_label_confidence,
)

SYNTHETIC_POSITIVE_AUC = 0.75
SYNTHETIC_POSITIVE_MARGIN_VS_REGULARIZED = 0.20
SYNTHETIC_POSITIVE_MARGIN_VS_SHIFT_CONTROL = 0.15
SHIFT_CONTROL_WARNING_AUC = 0.58
NULL_CONTROL_MAX_DEVIATION_FROM_CHANCE = 0.08

FORBIDDEN_CONCLUSIONS = {
    "PRIVACY_SAFE",
    "EXPORT_APPROVED",
    "LEGAL_COMPLIANT",
    "ANONYMIZED",
    "NO_PRIVACY_RISK",
}


def audit_membership(model, x, y, member_idx, nonmember_idx, bootstrap_seed):
    return binary_attack_metrics(
        true_label_confidence(model, x, y, member_idx),
        true_label_confidence(model, x, y, nonmember_idx),
        bootstrap_seed=bootstrap_seed,
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

    membership = {
        "overfit": audit_membership(
            models["overfit"],
            x,
            y,
            splits["paired_train"],
            splits["membership_nonmember"],
            bootstrap_seed=101,
        ),
        "regularized": audit_membership(
            models["regularized"],
            x,
            y,
            splits["paired_train"],
            splits["membership_nonmember"],
            bootstrap_seed=103,
        ),
    }

    null_control = run_exchangeable_null_control(
        models["regularized"], x, y, splits["null_control_pool"]
    )
    shift_control = run_covariate_shift_control(
        models["regularized"], x, y, subgroup, splits["shift_control_pool"]
    )

    overfit_auc = membership["overfit"]["roc_auc"]
    regularized_auc = membership["regularized"]["roc_auc"]
    shift_auc = shift_control["roc_auc"]
    null_auc = null_control["roc_auc"]

    labels = ["HUMAN_EXPORT_REVIEW_REQUIRED"]

    positive_fixture_signal = (
        overfit_auc >= SYNTHETIC_POSITIVE_AUC
        and overfit_auc - regularized_auc >= SYNTHETIC_POSITIVE_MARGIN_VS_REGULARIZED
        and overfit_auc - shift_auc >= SYNTHETIC_POSITIVE_MARGIN_VS_SHIFT_CONTROL
    )
    if positive_fixture_signal:
        labels += ["ATTACK_SIGNAL_DETECTED", "REMEDIATION_RETEST_REQUIRED"]

    if shift_auc >= SHIFT_CONTROL_WARNING_AUC:
        labels.append("CONTROL_EXPERIMENT_SUSPECTS_FALSE_POSITIVE")

    null_control_unstable = abs(null_auc - 0.5) > NULL_CONTROL_MAX_DEVIATION_FROM_CHANCE
    if null_control_unstable:
        labels.append("INSUFFICIENT_EVIDENCE")

    if not positive_fixture_signal and not null_control_unstable:
        labels.append("NO_MATERIAL_SIGNAL_IDENTIFIED_BY_CURRENT_TESTS")

    if FORBIDDEN_CONCLUSIONS & set(labels):
        raise AssertionError("Forbidden privacy/export conclusion emitted")

    train_idx = splits["paired_train"]
    return {
        "schema_version": "0.2",
        "authority": "RESEARCH_DECISION_SUPPORT_ONLY",
        "fixture": fixture_manifest(),
        "threat_model": {
            "attacker_access": "black-box predict_proba-like confidence access plus true label in synthetic benchmark",
            "membership_attack": "true-label-confidence ranking attack",
            "limitations": [
                "synthetic fixture",
                "single membership-attack family",
                "true-label knowledge assumed",
                "subgroup proxy is not an attribute-inference attack",
                "not a legal privacy test",
                "not proof of absence of leakage",
            ],
        },
        "paired_condition_design": {
            "same_training_indices": True,
            "same_model_family": True,
            "difference_under_test": "capacity/regularization configuration only",
        },
        "models": {
            name: fingerprint_model(name, model, train_idx)
            for name, model in models.items()
        },
        "membership_audit": membership,
        "controls": {
            "exchangeable_null": null_control,
            "covariate_shift_false_positive": shift_control,
        },
        "subgroup_separation_proxy": subgroup_separation_proxy(
            models["regularized"], x, y, subgroup, splits["shift_control_pool"]
        ),
        "synthetic_signal_checks": {
            "overfit_minus_regularized_auc": float(overfit_auc - regularized_auc),
            "overfit_minus_shift_control_auc": float(overfit_auc - shift_auc),
            "null_deviation_from_chance": float(abs(null_auc - 0.5)),
            "positive_fixture_signal": bool(positive_fixture_signal),
            "null_control_unstable": bool(null_control_unstable),
        },
        "support_labels": labels,
        "forbidden_conclusions": sorted(FORBIDDEN_CONCLUSIONS),
    }
