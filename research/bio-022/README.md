# BIO-022 Health Model Egress Privacy Auditor — Synthetic Benchmark

Issue: #790

Status: **research scaffold only**. This is not legal/privacy advice, not an export approval engine, and not proof that an artifact is safe.

## Research question

When sensitive health-like source data remain inside a controlled environment but a trained AI artifact is proposed for export, can a reproducible pre-export evidence gate:

1. fingerprint the exact synthetic dataset, split and model artifact;
2. run a bounded membership-inference-style audit;
3. compare an intentionally overfit condition with a regularized condition;
4. run a negative/control experiment that can expose split/difficulty bias and false-positive susceptibility;
5. surface uncertainty and limitations rather than reduce privacy to one scalar score;
6. leave the final export/privacy decision to a human reviewer?

## Fixture

`HEALTHLIKE-SYNTH-001` is wholly synthetic and contains no patient, hospital, HIRA, proprietary or restricted data. A synthetic difficulty subgroup is included only to create a controlled false-positive demonstration; it is not a real demographic attribute.

Three benchmark roles are used:

```text
A. intentionally overfit RandomForest model
B. regularized LogisticRegression model
C. negative/control comparison where both sides are non-members but synthetic difficulty composition differs
```

## Threat model

The first gate assumes black-box `predict_proba`-like confidence access and uses a simple true-label-confidence membership ranking attack. This is intentionally narrow. It does not claim coverage of all membership, inversion, memorization, extraction or property-inference attacks.

A subgroup confidence-separation metric is included only as a **bias/control proxy** to explain why an apparently elevated attack score can arise from distribution/difficulty differences. It is not presented as an attribute-inference attack.

## Expected synthetic behavior

With the pinned environment used during implementation-level validation:

```text
overfit membership ROC-AUC      ≈ 0.906
regularized membership ROC-AUC ≈ 0.511
non-member control ROC-AUC     ≈ 0.596
```

The control comparison is deliberately misleading if interpreted naively: both groups are non-members, but synthetic difficulty imbalance creates an elevated score. The correct support output therefore includes `CONTROL_EXPERIMENT_SUSPECTS_FALSE_POSITIVE` rather than treating every elevated AUC as privacy leakage.

These values validate benchmark mechanics only; they are not regulatory or privacy thresholds.

## Output labels

Allowed decision-support labels:

```text
ATTACK_SIGNAL_DETECTED
CONTROL_EXPERIMENT_SUSPECTS_FALSE_POSITIVE
INSUFFICIENT_EVIDENCE
REMEDIATION_RETEST_REQUIRED
NO_MATERIAL_SIGNAL_IDENTIFIED_BY_CURRENT_TESTS
HUMAN_EXPORT_REVIEW_REQUIRED
```

Forbidden conclusions:

```text
PRIVACY_SAFE
EXPORT_APPROVED
LEGAL_COMPLIANT
ANONYMIZED
NO_PRIVACY_RISK
```

## Files

- `fixture.py` — deterministic wholly synthetic health-like fixture and split fingerprints.
- `models.py` — intentionally overfit and regularized model conditions plus model fingerprinting.
- `control_experiment.py` — membership score metrics and deliberate non-member split-bias control.
- `audit.py` — bounded audit orchestration, support labels and limitations.
- `report.py` — emits a reproducible JSON evidence packet.
- `source_manifest.json` — public sources motivating the workflow and methodological caution.
- `requirements.txt` — pinned research environment.
- `tests/test_privacy_gate.py` — deterministic synthetic benchmark assertions.

## Run

```bash
python -m pip install -r requirements.txt
python report.py --out evidence_report.json
python -m pytest -q
```

## What this can prove

- the artifact/data/split identity can be fingerprinted;
- a deliberately overfit condition can be distinguished from a regularized condition by this narrow attack;
- a deliberately biased non-member control can expose false-positive susceptibility;
- evidence packets carry threat-model assumptions, metrics, limitations and mandatory human review;
- forbidden clearance language is not emitted.

## What this cannot prove

- that a real medical-AI model is privacy-safe;
- that one attack family is sufficient for export review;
- that absence of a detected signal means absence of privacy leakage;
- that HIRA, a hospital or another controlled-data operator would accept this methodology;
- legal compliance, anonymization or export approval;
- commercial value.

## Decision gate

After this synthetic gate and later buyer/domain review:

```text
CONTINUE_STANDALONE_SCREEN
ABSORB_AS_B63_MODEL_ARTIFACT_EGRESS_PROFILE
ABSORB_AS_B48_AI_SECURITY_VERIFICATION_PROFILE
KILL
```

```text
BUSINESS_NUMBER = NONE
REAL_PATIENT_DATA = FORBIDDEN
PRODUCTION = NO
DEPLOYMENT = NONE
ISSUE_778_PORTAL_MUTATION = NO
```
