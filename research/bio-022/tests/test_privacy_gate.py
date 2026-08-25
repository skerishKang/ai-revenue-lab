import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from audit import FORBIDDEN_CONCLUSIONS, run_audit
from fixture import fixture_manifest


def test_fixture_is_wholly_synthetic_fingerprinted_and_split_disjoint():
    manifest = fixture_manifest()
    assert manifest["synthetic_only"] is True
    assert manifest["fixture_id"] == "HEALTHLIKE-SYNTH-002"
    assert len(manifest["fingerprint_sha256"]) == 64
    assert manifest["split_sets_pairwise_disjoint"] is True


def test_comparison_uses_same_training_records_and_same_model_family():
    report = run_audit()
    overfit = report["models"]["overfit"]
    regularized = report["models"]["regularized"]
    assert overfit["training_index_sha256"] == regularized["training_index_sha256"]
    assert overfit["model_type"] == regularized["model_type"] == "RandomForestClassifier"
    assert report["paired_condition_design"]["same_training_indices"] is True
    assert report["paired_condition_design"]["same_model_family"] is True


def test_overfit_condition_has_stronger_membership_signal_than_regularized_condition():
    report = run_audit()
    overfit = report["membership_audit"]["overfit"]["roc_auc"]
    regularized = report["membership_audit"]["regularized"]["roc_auc"]
    assert overfit >= 0.80
    assert regularized <= 0.62
    assert overfit - regularized >= 0.20


def test_exchangeable_null_control_is_near_chance():
    control = run_audit()["controls"]["exchangeable_null"]
    assert control["truth"] == "BOTH_GROUPS_NONMEMBERS_SAME_POOL"
    assert abs(control["roc_auc"] - 0.5) <= 0.08


def test_covariate_shift_control_exposes_false_positive_susceptibility():
    control = run_audit()["controls"]["covariate_shift_false_positive"]
    assert control["truth"] == "BOTH_GROUPS_NONMEMBERS_COVARIATE_SHIFT"
    assert control["roc_auc"] >= 0.58


def test_record_level_score_distributions_are_exposed_without_clearance_claim():
    report = run_audit()
    for condition in ("overfit", "regularized"):
        metrics = report["membership_audit"][condition]
        for group in ("member_scores", "nonmember_scores"):
            dist = metrics[group]
            assert dist["n"] == 600
            assert set(dist["quantiles"]) == {"p05", "p25", "p50", "p75", "p95"}
            assert len(dist["histogram_0_to_1_deciles"]) == 10


def test_human_review_is_mandatory_and_clearance_language_is_forbidden():
    report = run_audit()
    labels = set(report["support_labels"])
    assert "HUMAN_EXPORT_REVIEW_REQUIRED" in labels
    assert "ATTACK_SIGNAL_DETECTED" in labels
    assert "CONTROL_EXPERIMENT_SUSPECTS_FALSE_POSITIVE" in labels
    assert "INSUFFICIENT_EVIDENCE" not in labels
    assert not (FORBIDDEN_CONCLUSIONS & labels)


def test_report_is_deterministic_for_metrics_fixture_and_model_fingerprints():
    first = run_audit()
    second = run_audit()
    assert first["fixture"]["fingerprint_sha256"] == second["fixture"]["fingerprint_sha256"]
    assert first["membership_audit"] == second["membership_audit"]
    assert first["controls"] == second["controls"]
    assert first["models"] == second["models"]
