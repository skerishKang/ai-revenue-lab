# BIO-003 My Health Story — Bounded Synthetic Participant Pilot v0.1

Status: **READY FOR PARTICIPANT RECRUITMENT AFTER OWNER REVIEW**

Issue: #772  
Draft PR: #774

## 1. Purpose

Test one narrow product hypothesis:

> Does source-grounded episodic reconstruction help ordinary users distinguish where information came from and remember what must happen next, compared with information-equivalent summary/timeline presentations?

This is a product/UX validation using fictional cases. It is not a clinical trial, diagnostic study, treatment study, or medical-advice study.

## 2. Conditions

Each participant sees all three fictional cases and all three presentation conditions once, using the existing counterbalancing groups:

```text
SUMMARY
TIMELINE
STORY
```

The canonical facts are locked by `fact_coverage.json`; no condition may contain extra factual content.

## 3. Suggested first pilot size

```text
N = 12 participants
G1 = 4
G2 = 4
G3 = 4
```

This is a small directional product pilot, not a powered confirmatory study.

If results are noisy or dominated by one case, increase only after reviewing failure modes rather than treating more participants as a substitute for fixture quality.

## 4. Participant profile

Primary:

- Korean-speaking adult;
- not involved in creating the fixtures;
- comfortable reading ordinary patient-facing material;
- no medical expertise required.

Track but do not use as exclusion by default:

- age band;
- self-rated comfort with medical documents;
- whether they often help a family member manage hospital visits;
- healthcare professional / non-professional status.

Do not collect diagnosis history, actual medical records, or sensitive health details.

## 5. Session flow

### A. Introduction

Tell the participant:

- all cases are fictional;
- this is testing information presentation, not medical knowledge;
- do not use outside search;
- answer from what they remember/read;
- some questions ask where information came from.

Do not tell them that STORY is the candidate product or that one condition is expected to be better.

### B. Case exposure

For each assigned case/condition:

1. show the rendering;
2. allow normal reading at the participant's own pace;
3. record exposure/read time;
4. remove/hide the rendering;
5. administer immediate questions from `questions.json`;
6. record confidence 1–5 after each answer;
7. collect condition ratings only after the objective questions.

Do not allow back-navigation to the case while answering immediate recall questions.

### C. Delayed recall

After all three case blocks and a neutral filler interval of approximately 10–15 minutes, ask a reduced delayed set without re-showing the renderings.

Recommended delayed items per case:

```text
1 source-attribution item
1 follow-up action item
1 factual retrieval item
```

Use items already represented in `questions.json`; do not introduce new facts.

## 6. Primary measures

### Primary 1 — Source attribution accuracy

Questions where the participant must identify:

```text
PATIENT_SAID
CLINICIAN_SAID
SOURCE_DOCUMENT
MY_NOTE
```

Primary comparison:

```text
STORY vs SUMMARY
STORY vs TIMELINE
```

### Primary 2 — Follow-up memory

Whether the participant correctly recalls the next action, appointment, preparation, or note without adding false actions.

False recall is an important counter-signal.

## 7. Secondary measures

- factual recall;
- sequence recall;
- retrieval accuracy;
- false-selection rate;
- confidence calibration;
- reading time;
- perceived mental effort (1–5);
- usefulness (1–5);
- trust in knowing where information came from (1–5);
- preference rank only as a secondary descriptive measure.

Preference alone cannot justify GO.

## 8. Hard failure signals

Do not promote the idea if apparent preference is accompanied by materially worse factual behavior.

Examples:

```text
STORY preferred but source-attribution accuracy not improved
STORY preferred but false follow-up recall increases
STORY takes materially longer with no objective benefit
one case drives nearly all observed advantage
participants confuse AI-organized text with clinician statements
```

## 9. Directional decision gate

### GO_TO_PRODUCT_PROTOTYPE

Only if all are directionally true in the bounded pilot:

- STORY improves source attribution versus both alternatives or shows a clear, consistent advantage on the intended provenance task;
- follow-up recall is at least non-inferior and preferably improved;
- false recall does not increase materially;
- benefit appears across more than one case type;
- participant feedback identifies a concrete use moment, not just visual preference.

### NARROW

Use when benefit appears only for a particular case/problem, for example:

- conversation-heavy visits;
- document-heavy follow-up;
- caregiver-managed visits;
- visits with multiple sources that are easy to confuse.

### ABSORB_AS_CAPABILITY

Use when provenance/source labels help but the episodic story format itself adds little. In that case source-grounding may belong inside an existing health-record/visit-summary product rather than becoming a standalone product.

### KILL_AS_STANDALONE

Use when objective memory/source outcomes do not justify the additional product layer.

## 10. Data handling

Collect only study-operation fields needed for the synthetic pilot.

Allowed examples:

```text
participant_code
counterbalance_group
case_id
condition
question_id
response
confidence
read_time
rating fields
```

Do not store names, resident numbers, real hospital records, diagnosis histories, medication lists, recordings of real consultations, or other unnecessary sensitive data.

## 11. Reproducibility

Before each pilot batch, record:

```text
Git commit SHA
cases.json SHA
fact_coverage.json SHA
questions.json SHA
question_fact_map.json SHA
counterbalancing.json SHA
score.py SHA
```

Do not mix responses collected from materially different fixture versions in one analysis without version stratification.

## 12. Current readiness

```text
SYNTHETIC_FIXTURE = READY
INFORMATION_PARITY = PASS AT MECHANICS LEVEL
QUESTION_DEPENDENCY_CONTRACT = PASS AT MECHANICS LEVEL
COUNTERBALANCING = PASS AT MECHANICS LEVEL
EXACT_HEAD_GITHUB_ACTIONS = NOT CONFIGURED
REAL_PARTICIPANT_DATA = NONE
HUMAN_BENEFIT = UNPROVEN
```
