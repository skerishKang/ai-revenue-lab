from __future__ import annotations

import numpy as np
from sklearn.metrics import roc_auc_score, roc_curve

NULL_SEED = 314159
N_BOOTSTRAP = 400


def true_label_confidence(model, x, y, idx):
    probabilities = model.predict_proba(x[idx])
    return probabilities[np.arange(len(idx)), y[idx]]


def score_distribution(scores):
    values = np.asarray(scores, dtype=float)
    quantiles = np.quantile(values, [0.05, 0.25, 0.5, 0.75, 0.95])
    hist, edges = np.histogram(values, bins=np.linspace(0.0, 1.0, 11))
    return {
        "n": int(len(values)),
        "mean": float(np.mean(values)),
        "std": float(np.std(values)),
        "quantiles": {
            "p05": float(quantiles[0]),
            "p25": float(quantiles[1]),
            "p50": float(quantiles[2]),
            "p75": float(quantiles[3]),
            "p95": float(quantiles[4]),
        },
        "histogram_0_to_1_deciles": hist.astype(int).tolist(),
        "histogram_edges": edges.tolist(),
    }


def bootstrap_auc_ci(member_scores, nonmember_scores, seed=20260826, n_bootstrap=N_BOOTSTRAP):
    member_scores = np.asarray(member_scores)
    nonmember_scores = np.asarray(nonmember_scores)
    rng = np.random.default_rng(seed)
    aucs = []
    for _ in range(n_bootstrap):
        m = member_scores[rng.integers(0, len(member_scores), len(member_scores))]
        n = nonmember_scores[rng.integers(0, len(nonmember_scores), len(nonmember_scores))]
        labels = np.concatenate([np.ones(len(m)), np.zeros(len(n))])
        scores = np.concatenate([m, n])
        aucs.append(roc_auc_score(labels, scores))
    low, high = np.quantile(aucs, [0.025, 0.975])
    return [float(low), float(high)]


def binary_attack_metrics(member_scores, nonmember_scores, bootstrap_seed=20260826):
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
        "roc_auc_bootstrap_95ci": bootstrap_auc_ci(
            member_scores, nonmember_scores, seed=bootstrap_seed
        ),
        "tpr_at_fpr_le_0_10": tpr_at_fpr10,
        "member_scores": score_distribution(member_scores),
        "nonmember_scores": score_distribution(nonmember_scores),
    }


def run_exchangeable_null_control(model, x, y, control_pool):
    rng = np.random.default_rng(NULL_SEED)
    permuted = rng.permutation(control_pool)
    pseudo_member = permuted[:250]
    pseudo_nonmember = permuted[250:500]
    result = binary_attack_metrics(
        true_label_confidence(model, x, y, pseudo_member),
        true_label_confidence(model, x, y, pseudo_nonmember),
        bootstrap_seed=17,
    )
    result.update(
        {
            "truth": "BOTH_GROUPS_NONMEMBERS_SAME_POOL",
            "construction": "random split of one held-out nonmember pool",
            "expected_interpretation": "AUC should remain near chance; large deviation indicates unstable audit mechanics or split artifact.",
        }
    )
    return result


def run_covariate_shift_control(model, x, y, subgroup, control_pool):
    easy = control_pool[subgroup[control_pool] == 0][:250]
    hard = control_pool[subgroup[control_pool] == 1][:250]
    result = binary_attack_metrics(
        true_label_confidence(model, x, y, easy),
        true_label_confidence(model, x, y, hard),
        bootstrap_seed=19,
    )
    result.update(
        {
            "truth": "BOTH_GROUPS_NONMEMBERS_COVARIATE_SHIFT",
            "construction": "pseudo-member=synthetic-easy holdout; pseudo-nonmember=synthetic-hard holdout",
            "warning": "Elevated control AUC demonstrates difficulty/covariate-shift susceptibility; it is not a true membership attack.",
        }
    )
    return result
