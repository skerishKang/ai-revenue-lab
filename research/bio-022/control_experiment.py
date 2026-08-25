from __future__ import annotations

import numpy as np
from sklearn.metrics import roc_auc_score, roc_curve

CONTROL_AUC_WARNING = 0.57


def true_label_confidence(model, x, y, idx):
    probabilities = model.predict_proba(x[idx])
    return probabilities[np.arange(len(idx)), y[idx]]


def binary_attack_metrics(member_scores, nonmember_scores):
    labels = np.concatenate(
        [np.ones(len(member_scores)), np.zeros(len(nonmember_scores))]
    )
    scores = np.concatenate([member_scores, nonmember_scores])
    auc = float(roc_auc_score(labels, scores))
    fpr, tpr, _ = roc_curve(labels, scores)
    valid = np.where(fpr <= 0.10)[0]
    tpr_at_fpr10 = float(tpr[valid].max()) if len(valid) else 0.0
    return {
        "roc_auc": auc,
        "tpr_at_fpr_le_0_10": tpr_at_fpr10,
        "member_mean_score": float(np.mean(member_scores)),
        "nonmember_mean_score": float(np.mean(nonmember_scores)),
        "n_member": int(len(member_scores)),
        "n_nonmember": int(len(nonmember_scores)),
    }


def run_false_positive_control(model, x, y, subgroup, control_pool):
    easy = control_pool[subgroup[control_pool] == 0][:500]
    hard = control_pool[subgroup[control_pool] == 1][:500]

    result = binary_attack_metrics(
        true_label_confidence(model, x, y, easy),
        true_label_confidence(model, x, y, hard),
    )
    result.update(
        {
            "truth": "BOTH_GROUPS_NONMEMBERS",
            "construction": "pseudo-member=synthetic-easy holdout; pseudo-nonmember=synthetic-hard holdout",
            "suspected_false_positive": bool(result["roc_auc"] >= CONTROL_AUC_WARNING),
            "warning": "Elevated control AUC demonstrates split/difficulty bias susceptibility; it is not a true membership attack.",
        }
    )
    return result
