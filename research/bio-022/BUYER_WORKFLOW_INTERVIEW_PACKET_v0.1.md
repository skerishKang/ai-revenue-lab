# BIO-022 — Buyer / Workflow Interview Packet v0.1

Status: **READY FOR WORKFLOW DISCOVERY / RESEARCH ONLY**

Issue: #790  
Draft PR: #792

## 1. Purpose

Determine whether model/artifact export from controlled health-data environments is a **distinct repeated workflow with a real user/budget owner**, rather than merely a technical capability that should be absorbed into B63/B48.

The interview is not a sales pitch and does not assume that membership-inference testing is currently required.

## 2. Public workflow signal

Current public sources support only the following directional facts:

- HIRA provides controlled analysis environments to academic/industrial users;
- HIRA workflows include formal application/review and separate import/export requests;
- HIRA medical-image services are designed so source image data need not be exported while AI models/algorithms can be developed in the controlled environment;
- 2026 medical-AI data voucher activity linked medical-AI SMEs with medical-data-centered hospitals;
- 2026 policy direction includes AI-model validation through medical-data-centered hospitals.

These signals identify interview cohorts. They do **not** prove that model privacy auditing is a current paid requirement.

See `source_manifest.json`.

## 3. Interview cohorts

### Cohort A — Controlled-data environment operator / export reviewer

Examples of role types:

- public health-data analysis center operator;
- hospital data safe-zone / research-data center operator;
- data release/export review administrator;
- privacy/security reviewer supporting controlled analysis.

Primary question:

> What evidence is actually required before an artifact/result can leave the environment, and does a trained model create a distinct privacy/security review problem?

### Cohort B — Medical-AI company applicant / model developer

Role types:

- medical-AI R&D lead;
- ML engineering lead;
- privacy/security lead;
- regulatory/quality lead involved in controlled-data collaborations.

Primary question:

> What friction, delay or uncertainty occurs when trying to export or reuse the trained artifact after working inside a controlled health-data environment?

### Cohort C — Medical-data-centered hospital / data collaboration team

Role types:

- medical-data center PM;
- data governance/privacy team;
- AI validation/clinical data science support team;
- external collaboration manager.

Primary question:

> Is artifact release a repeated service bottleneck, and who currently performs the technical/privacy judgment?

### Cohort D — Independent privacy/security assessor

Use as a technical reality check rather than initial buyer proof.

Primary question:

> Which attack/evidence methods are credible enough to support a release review, and which would create false confidence?

## 4. Interview opening

Do not begin with BIO-022 features.

Use a neutral framing:

> We are studying what happens after a team trains an AI model inside a controlled health-data environment and wants to take an artifact or result outside. We are not assuming a particular privacy tool is needed. We want to understand your current process, evidence and failure modes.

## 5. Workflow discovery questions

### A. Frequency and object

1. How often do artifact/result export requests occur?
2. What kinds of artifacts are requested?
   - tables/figures;
   - analysis code;
   - trained model weights;
   - serialized models;
   - embeddings;
   - synthetic data;
   - logs/features;
   - other.
3. Are trained models treated differently from ordinary aggregate results?
4. Which artifact types are categorically disallowed?

### B. Current decision process

5. Who initiates the request?
6. Who performs first-line review?
7. Who has final release authority?
8. Is an external expert ever required?
9. Is there a written checklist or case-by-case judgment?
10. What evidence is currently collected?

### C. Privacy/security assessment

11. For model artifacts, what risks are considered today?
12. Is training-data memorization or membership leakage explicitly considered?
13. Are model inversion / attribute inference / extraction risks considered?
14. Is only the file/content scanned, or is the model behavior actively tested?
15. How are subgroup/outlier risks handled?
16. What would make a privacy test untrustworthy?

Do not teach the interviewee the desired answer before they describe current practice.

### D. Bottleneck and cost

17. Typical time from export request to decision?
18. What causes the most delay?
19. How often is a request returned for more evidence?
20. How much expert time is spent per request?
21. Are there cases where the model must be retrained/remediated before release?
22. Is this cost borne by the data center/operator, hospital, applicant company, project/grant, or another party?

### E. Product boundary

23. Would a reproducible evidence packet be useful if it included:
   - exact artifact/data/version fingerprint;
   - declared attacker-access assumptions;
   - multiple attacks;
   - all-nonmember null/shift controls;
   - record-level score distributions;
   - uncertainty/limitations;
   - immutable reviewer notes?
24. Which of those are unnecessary?
25. What critical evidence is missing?
26. Would such a tool need to run fully inside the controlled environment?
27. Could any evidence leave the environment, or only aggregate results?
28. What integration is required: notebook, CLI, API, approval portal, report export, other?

### F. Buyer test

29. Who would approve purchase/use?
30. Who owns the budget?
31. Is this something an operator would procure once, or an applicant would pay per project?
32. What existing product/process already solves this?
33. What would make you reject a dedicated solution and keep the process manual?

## 6. Evidence capture

For every interview capture:

```text
organization_type
role_type
workflow_exists = YES / NO / PARTIAL
trained_model_export_occurs = YES / NO / UNKNOWN
frequency_band
model_treated_differently = YES / NO / UNKNOWN
active_privacy_attack_testing_today = YES / NO / UNKNOWN
release_authority_role
budget_owner_role
current_tools/process
main_delay
expert_time_band
must_run_inside_secure_environment = YES / NO / UNKNOWN
repeatable_evidence_gap = HIGH / MEDIUM / LOW / NONE
standalone_product_fit = HIGH / MEDIUM / LOW / NONE
B63_profile_fit = HIGH / MEDIUM / LOW
B48_profile_fit = HIGH / MEDIUM / LOW
critical_quote_or_paraphrase
source/evidence link if public
```

Do not record confidential patient/project details.

## 7. Decision gate

### CONTINUE_STANDALONE_SCREEN

Require evidence such as:

- artifact/model release is a repeated workflow across multiple organizations;
- current review is materially manual/slow/inconsistent;
- trained-model privacy creates a distinct review burden beyond ordinary output checking;
- at least one plausible buyer/budget owner is identifiable;
- solution must combine technical audit + evidence packaging, not just run an attack script;
- need is not already adequately served by generic privacy/red-team products.

### ABSORB_AS_B63_MODEL_ARTIFACT_EGRESS_PROFILE

Prefer if:

- release control is the real product boundary;
- model privacy is one policy/check among several egress checks;
- operators want one governed egress workflow rather than a dedicated privacy product.

### ABSORB_AS_B48_AI_SECURITY_VERIFICATION_PROFILE

Prefer if:

- independent verification is useful;
- there is no distinct release workflow/buyer;
- the main value is reusable model-security evidence rather than healthcare-specific governance.

### KILL

Use if:

- model export is rare or normally prohibited;
- no one performs or values distinct model-privacy review;
- generic tools/processes are sufficient;
- no repeat user or budget owner exists.

## 8. Minimum evidence before standalone promotion

Do not assign a Business number based on the synthetic benchmark.

Before standalone promotion require, at minimum:

```text
3+ independent organizations interviewed
2+ distinct operator/applicant perspectives
1+ repeated real model/artifact release workflow confirmed
1+ plausible budget owner confirmed
clear current-process pain
clear reason generic privacy tooling is insufficient
```

A strong technical benchmark with no repeated workflow resolves to ABSORB or KILL, not a new Business.
