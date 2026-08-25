import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from audit import FORBIDDEN_CONCLUSIONS, run_audit
from fixture import fixture_manifest


def test_fixture_is_wholly_synthetic_and_fingerprinted():
    manifest = fixture_manifest()
    assert manifest["synthetic_only"] is True
    assert manifest["fixture_id"] == "HEALTHLIKE-SYNTH-001"
    assert len(manifest["fingerprint_sha256"]) == 64


def test_overfit_condition_has_stronger_membership_signal_than_regularized_condition():
    report = run_audit()
    overfit = report["membership_audit"]["overfit"]["roc_auc"]
    regularized = report["membership_audit"]["regularized"]["roc_auc"]
    assert overfit >= 0.80
    assert regularized <= 0.60
    assert overfit - regularized >= 0.25


def test_negative_control_exposes_split_bias_susceptibility():
    control = run_audit()["control_experiment"]
    assert control["truth"] == "BOTH_GROUPS_NONMEMBERS"
    assert control["roc_auc"] >= 0.57
    assert control["suspected_false_positive"] is True


def test_human_review_is_mandatory_and_clearance_language_is_forbidden():
    report = run_audit()
    labels = set(report["support_labels"])
    assert "HUMAN_EXPORT_REVIEW_REQUIRED" in labels
    assert "ATTACK_SIGNAL_DETECTED" in labels
    assert "CONTROL_EXPERIMENT_SUSPECTS_FALSE_POSITIVE" in labels
    assert not (FORBIDDEN_CONCLUSIONS & labels)


def test_report_is_deterministic_for_metrics_and_fixture_identity():
    first = run_audit()
    second = run_audit()
    assert first["fixture"]["fingerprint_sha256"] == second["fixture"]["fingerprint_sha256"]
    assert first["membership_audit"] == second["membership_audit"]
    assert first["control_experiment"] == second["control_experiment"]
