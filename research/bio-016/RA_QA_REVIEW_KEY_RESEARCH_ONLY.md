# BIO-016 RA/QA Stage-2 Research Prediction Key

Authority: **RESEARCH_ORACLE_NOT_REGULATORY_TRUTH**

Do not show this file before the reviewer completes Stage 1 of `RA_QA_REVIEW_PACKET_v0.1.md`.

The mappings below mirror the current synthetic `gold.json` and are intended only to compare software output with qualified human review.

## C01 — MODEL_UPDATE

Current research prediction:

```text
impacted classes:
- PERFORMANCE_VALIDATION
- CLINICAL_EVALUATION
- SOFTWARE_VALIDATION
- POSTMARKET_MONITORING_PLAN

candidate stale/scope-mismatched evidence:
- E-PERF-001
- E-CLIN-001
- E-SWVAL-001
- E-MON-001

support labels:
- REVIEW_REQUIRED
- REVALIDATION_CANDIDATE
- EVIDENCE_STALE_OR_SCOPE_MISMATCH
- RA_QA_DECISION_REQUIRED
```

## C05 — INTENDED_USE_EXPANSION

```text
impacted classes:
- PERFORMANCE_VALIDATION
- CLINICAL_EVALUATION
- HUMAN_FACTORS
- LABELING_INTENDED_USE

candidate stale/scope-mismatched evidence:
- E-CLIN-001
- E-HF-001
- E-LABEL-001

support labels:
- REVIEW_REQUIRED
- REVALIDATION_CANDIDATE
- DOCUMENT_UPDATE_CANDIDATE
- EVIDENCE_STALE_OR_SCOPE_MISMATCH
- RA_QA_DECISION_REQUIRED
```

Important review question: should `E-PERF-001` also be reopened for this intended-use expansion even though the current exact-scope detector does not mark it stale? A qualified reviewer disagreement here is especially useful evidence.

## C06 — LLM_PROVIDER_MODEL_SWAP

```text
impacted classes:
- GENERATIVE_COMPONENT_VALIDATION
- PROMPT_VALIDATION
- SOFTWARE_VALIDATION
- CYBERSECURITY
- PERFORMANCE_VALIDATION

candidate stale/scope-mismatched evidence:
- E-SWVAL-001
- E-CYBER-001
- E-LLM-001
- E-PROMPT-001

support labels:
- REVIEW_REQUIRED
- REVALIDATION_CANDIDATE
- EVIDENCE_STALE_OR_SCOPE_MISMATCH
- RA_QA_DECISION_REQUIRED
```

Important review question: whether and under what context the generic performance evidence should be reopened when only the generative component/provider changes.

## C09 — CYBERSECURITY_PATCH

```text
impacted classes:
- CYBERSECURITY
- SOFTWARE_VALIDATION

candidate stale/scope-mismatched evidence:
- NONE identified at exact evidence-record level

support labels:
- REVIEW_REQUIRED
- REVALIDATION_CANDIDATE
- RA_QA_DECISION_REQUIRED
```

The current inventory has no exact `sec-lib-4.1` scope token. The desired behavior is class-level review without inventing a specific stale evidence relation.

## C20 — DOCUMENT_TYPO_ONLY

```text
impacted classes:
- NONE

candidate stale/scope-mismatched evidence:
- NONE

support labels:
- REVIEW_REQUIRED
- DOCUMENT_UPDATE_CANDIDATE
- NO_ADDITIONAL_ACTION_IDENTIFIED_BY_RULESET
- RA_QA_DECISION_REQUIRED
```

This is a hard-negative control against over-triggering.

## How to use disagreements

Do **not** score the human reviewer against this file as ground truth.

Instead classify disagreement as:

```text
SYSTEM_MISSED_REQUIRED_EVIDENCE
SYSTEM_REOPENED_UNNECESSARY_EVIDENCE
SYSTEM_CLASSIFICATION_TOO_BROAD
SYSTEM_CLASSIFICATION_TOO_NARROW
MISSING_CONTEXT_PREVENTS_DECISION
RESEARCH_ORACLE_NEEDS_CORRECTION
REVIEWER_VARIATION_REQUIRES_SECOND_OPINION
```

Then update the synthetic benchmark only after the disagreement is documented with rationale.
