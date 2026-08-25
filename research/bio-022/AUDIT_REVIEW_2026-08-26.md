# BIO-022 Benchmark Audit Review — 2026-08-26

Status: **v0.1 methodological confounds identified; v0.2 correction validated locally**

Issue: #790  
Draft PR: #792

## Findings in v0.1

The original synthetic benchmark successfully produced an intentionally strong membership signal and an all-nonmember false-positive control, but a review found three material weaknesses.

### 1. Comparison confounded model family and training-set size

The original positive/regularized comparison used:

```text
overfit = RandomForest on 300 records
regularized = LogisticRegression on 1,400 records
```

Therefore the observed membership-AUC gap could not be cleanly attributed to overfitting/capacity alone.

### 2. No same-distribution null control

The original control compared synthetic easy vs hard nonmembers. That is useful for demonstrating covariate/split-bias susceptibility, but it does not verify that the audit remains near chance when two groups are exchangeable nonmembers drawn from the same held-out distribution.

### 3. Evidence packet was too aggregate

The issue requires a useful record-level risk distribution. v0.1 exposed aggregate AUC/mean metrics but not enough distributional evidence to distinguish a broad signal from a few extreme records.

## v0.2 corrections

### Paired model design

Both conditions now use:

```text
same 600 training indices
same RandomForestClassifier family
same n_estimators
same random_state
```

Only the intended research capacity/regularization parameters differ:

```text
overfit:
  max_depth = unlimited
  min_samples_leaf = 1

regularized:
  max_depth = 5
  min_samples_leaf = 12
```

### Two independent negative controls

```text
exchangeable null control
= random split of one all-nonmember held-out pool

covariate-shift control
= synthetic easy nonmembers vs synthetic hard nonmembers
```

The first checks that the audit is near chance under exchangeability. The second deliberately demonstrates how non-membership covariate differences can imitate a privacy signal.

### Distributional evidence

For member/nonmember record-level scores the report now includes:

- n;
- mean / standard deviation;
- p05 / p25 / p50 / p75 / p95;
- 10-bin histogram;
- ROC-AUC;
- deterministic bootstrap 95% ROC-AUC interval;
- TPR at FPR <= 0.10.

No metric is converted into a legal/privacy/export clearance.

## Local v0.2 validation result

Using the exact v0.2 code staged for the branch:

```text
overfit membership ROC-AUC      ≈ 0.8822
regularized membership ROC-AUC ≈ 0.5886
exchangeable null ROC-AUC      ≈ 0.4552
covariate-shift control AUC    ≈ 0.6537
pytest                          = 8 passed
```

Interpretation:

- the positive condition remains materially stronger after removing the original model-family/training-size confound;
- the exchangeable null remains close to chance;
- an all-nonmember covariate shift can still create an elevated naive AUC, preserving the required false-positive warning.

## Authority boundary

These are synthetic benchmark mechanics only.

They do **not** establish:

```text
PRIVACY_SAFE
EXPORT_APPROVED
LEGAL_COMPLIANT
ANONYMIZED
NO_PRIVACY_RISK
```

A real product decision still requires a real export-review workflow/buyer and qualified privacy/security review.
