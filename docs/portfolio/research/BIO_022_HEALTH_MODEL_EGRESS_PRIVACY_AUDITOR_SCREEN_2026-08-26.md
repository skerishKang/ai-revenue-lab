# BIO-022 Health Model Egress Privacy Auditor — Screen

- Date: 2026-08-26
- Status: `NARROW / SCREENING`
- Business number: none
- Purpose: test whether privacy-risk review of AI artifacts leaving controlled health-data environments is a distinct product wedge.

## Problem signal

HIRA operates controlled environments where medical image data cannot be exported while AI models/algorithms may be exported after review.

Official public sources:

- HIRA 2026 role/functions report states that medical image data are analyzed in a closed environment; AI models/algorithms may be exported, image data may not, and external expert review may be used for export review.
- HIRA Open Data service describes a GPU environment that lets companies build AI models without exporting the source medical images.

Sources:

- https://www.hira.or.kr/ebooksc/2025/12/BZ202512232703963.pdf
- https://opendata.hira.or.kr/op/opb/selectHelhMedDataInfoView.do?divId=cust

This creates a specific boundary:

```text
sensitive health data stays inside
→ trained model / algorithm / embedding / synthetic artifact wants to leave
→ source data is not directly exported
→ but the artifact may still leak properties of training records
→ export reviewer needs reproducible privacy-risk evidence
```

## Why this is technically real

Membership-inference and related attacks can reveal whether particular records or patients were part of training data. Recent medical-AI work continues to show that patient-level privacy risk can be materially different from aggregate risk.

Relevant research / tooling:

- Privacy Meter — open-source ML privacy auditing, including membership-inference-based privacy assessment.
- Dreadnode — commercial/offensive AI red-team tooling includes membership inference and model inversion against classifiers.
- 2026 medical-AI research reports patient-level membership-inference risk that can be much higher than aggregate metrics suggest.
- 2026 MIE work also warns that membership-inference audits can produce false positives from data-split bias, so control experiments are necessary.

Representative sources:

- https://github.com/privacytrustlab/ml_privacy_meter
- https://docs.dreadnode.io/ai-red-teaming/learning-guide/membership-inference/
- https://pmc.ncbi.nlm.nih.gov/articles/PMC13442007/
- https://pubmed.ncbi.nlm.nih.gov/42174933/

## Why the generic idea is not enough

`membership inference tool` is not a new product category. Open-source libraries and AI red-team platforms already implement the attack primitives.

The possible wedge is the **operational export gate**, not the attack algorithm:

```text
artifact proposed for export
+ approved training/data metadata
+ declared threat model
+ allowed model interface
→ repeatable privacy attacks + control experiments
→ memorization / membership / inversion / subgroup-leakage evidence
→ attack assumptions + query budget + uncertainty
→ residual-risk packet
→ human export-review decision
→ immutable audit record
```

The system must distinguish:

```text
ATTACK_SIGNAL_DETECTED
CONTROL_EXPERIMENT_SUSPECTS_FALSE_POSITIVE
INSUFFICIENT_EVIDENCE
REMEDIATION_RETEST_REQUIRED
HUMAN_EXPORT_REVIEW_REQUIRED
```

It must not emit an autonomous legal/privacy clearance decision.

## PADIEM fit

Potential reuse:

- B48 — exact-version verification / evidence assertions;
- B63 — governed egress concept, but current B63 is primarily clinical text/data egress to external AI;
- B42 — controlled execution and gate workflow;
- evidence/audit primitives already used elsewhere in AI Revenue Lab.

Possible future boundary:

- if buyers treat model-artifact export as the same policy surface as B63, absorb as `B63 Model Artifact Egress Profile`;
- if controlled health-data operators buy a distinct pre-export privacy assurance workflow, standalone promotion may remain possible.

## Likely buyer / partner

Hypothesis only; not validated:

- public health-data safe center / analysis center;
- hospital data safe haven / research data platform;
- medical-AI consortium handling restricted training data;
- institution that approves trained model/algorithm export from controlled data.

## Smallest truthful technical validation

No real patient data is required for the first gate.

Use a public/synthetic health-like tabular fixture and train at least:

```text
A. intentionally overfit model
B. regularized model
C. control split with no true membership distinction
```

Then run multiple privacy checks and ask whether the system can reproducibly produce:

- attack TPR/FPR / AUC or equivalent metric;
- patient/record-level risk distribution;
- control-experiment result;
- false-positive warning when the control behaves similarly;
- exact model/data/version fingerprint;
- repeatable evidence packet;
- human-review routing.

The gate is about **privacy-audit mechanics and evidence quality**, not claiming that one attack score proves legal safety.

## Main risks

- generic AI security / red-team tools may cover enough of the workflow;
- export-review buyers may be too few for a standalone SaaS;
- privacy attack methodology is evolving and can be brittle;
- a credible product needs threat-model discipline and expert validation;
- healthcare specificity must come from workflow/evidence/governance, not marketing language.

## Current disposition

```text
REAL_PROBLEM_SIGNAL = YES
GENERIC_ATTACK_TOOL_NOVELTY = NO
CONTROLLED_HEALTH_MODEL_EXPORT_WEDGE = PLAUSIBLE
SYNTHETIC_FIRST_VALIDATION = YES
BUYER_PROOF = NOT_DONE
B63_OVERLAP = MATERIAL_BUT_NOT_IDENTICAL
DISPOSITION = NARROW / SCREENING
```

Do not assign a Business number before technical benchmark plus buyer validation.
