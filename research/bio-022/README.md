# BIO-022 Health Model Egress Privacy Auditor — Synthetic Validation Pack

Status: **synthetic / research-only / no export clearance authority**

Issue: #790  
Draft PR: #792

## Product question

Can a controlled-health-data environment produce a useful, reproducible privacy evidence packet before exporting a trained model/artifact, while keeping the final export/privacy decision with a qualified human reviewer?

The possible product wedge is **not** a new membership-inference algorithm. Existing attack primitives are used as evidence inside an artifact-export workflow.

## Workflow under test

```text
controlled source data stays inside
→ exact model/data/split fingerprint
→ declared threat model
→ privacy attack(s)
→ exchangeable null control
→ covariate-shift false-positive control
→ record-level score distributions + uncertainty
→ evidence packet
→ HUMAN_EXPORT_REVIEW_REQUIRED
```

## v0.2 methodological repair

Read `AUDIT_REVIEW_2026-08-26.md`.

The original v0.1 comparison was confounded because the overfit and regularized conditions used different model families and different training-set sizes.

v0.2 now uses:

```text
same 600 training records
same RandomForestClassifier family
same n_estimators / random_state
only capacity/regularization differs
```

Two all-nonmember controls are separated:

```text
exchangeable null
= random split from one held-out distribution

covariate-shift control
= synthetic easy holdout vs synthetic hard holdout
```

This distinction is essential: an elevated attack score under covariate shift must not be treated automatically as true membership leakage.

## Current synthetic v0.2 result

Local execution of the exact staged v0.2 code:

```text
overfit membership ROC-AUC      ≈ 0.8822
regularized membership ROC-AUC ≈ 0.5886
exchangeable null ROC-AUC      ≈ 0.4552
covariate-shift control AUC    ≈ 0.6537
pytest                          = 8 passed
```

The report also includes deterministic bootstrap 95% ROC-AUC intervals, TPR at FPR <= 0.10, and record-level score distributions summarized as quantiles and decile histograms.

These values are **fixture behavior only**. They are not universal privacy thresholds.

## Files

- `fixture.py` — wholly synthetic health-like fixture and disjoint split fingerprints;
- `models.py` — paired RandomForest conditions using identical training indices;
- `control_experiment.py` — attack metrics, bootstrap CI, score distributions, null/shift controls;
- `audit.py` — bounded evidence packet and support labels;
- `report.py` — JSON report writer;
- `tests/test_privacy_gate.py` — 8 benchmark/safety contracts;
- `source_manifest.json` — public workflow/research motivation;
- `AUDIT_REVIEW_2026-08-26.md` — methodological defect and correction record.

## Threat-model boundary

Current first attack assumes:

```text
black-box predict_proba-like confidence access
+
true label known to the synthetic attacker
```

Limitations are explicit:

- wholly synthetic fixture;
- one membership-attack family;
- true-label knowledge assumption;
- subgroup separation is only a bias/control proxy;
- no legal/privacy compliance inference;
- no claim that absence of current signal means absence of leakage.

## Support labels

Allowed:

```text
ATTACK_SIGNAL_DETECTED
CONTROL_EXPERIMENT_SUSPECTS_FALSE_POSITIVE
INSUFFICIENT_EVIDENCE
REMEDIATION_RETEST_REQUIRED
NO_MATERIAL_SIGNAL_IDENTIFIED_BY_CURRENT_TESTS
HUMAN_EXPORT_REVIEW_REQUIRED
```

Forbidden:

```text
PRIVACY_SAFE
EXPORT_APPROVED
LEGAL_COMPLIANT
ANONYMIZED
NO_PRIVACY_RISK
```

## Run

```bash
python -m pip install -r requirements.txt
python -m pytest -q
python report.py --out evidence_packet.json
```

## Current gate

```text
SYNTHETIC_TECHNICAL_MECHANICS = PASS LOCALLY
PAIRED_MODEL_CONFOUND = CLOSED
EXCHANGEABLE_NULL_CONTROL = PRESENT
COVARIATE_SHIFT_FALSE_POSITIVE_CONTROL = PRESENT
RECORD_LEVEL_DISTRIBUTION_EVIDENCE = PRESENT
EXACT_HEAD_GITHUB_ACTIONS = NOT CONFIGURED
REAL_PATIENT_DATA = NONE
REAL_EXPORT_WORKFLOW_VALIDATION = PENDING
BUYER / BUDGET OWNER = NOT PROVEN
```

## Decision path

BIO-022 is not promoted to a Business from synthetic performance alone.

Next decision after workflow/buyer validation:

```text
CONTINUE_STANDALONE_SCREEN
ABSORB_AS_B63_MODEL_ARTIFACT_EGRESS_PROFILE
ABSORB_AS_B48_AI_SECURITY_VERIFICATION_PROFILE
KILL
```
