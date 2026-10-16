# BIO-003 My Health Story — Validation Spec

- Date: 2026-08-26
- Status: VALIDATION DESIGN
- Business number: NONE
- Product authority: recovered 2026 ASTERIVE `04_아스테리브_마이헬스스토리_병원스토리북_v1`
- Safety boundary: synthetic cases only for first gate; no diagnosis/treatment recommendation; no real patient audio/records

## 1. Why this is the next Bio/Healthcare candidate

`My Health Story` is not a fresh assistant-generated idea. A sample-data visual prototype already exists with:

- `1 Hospital Visit = 1 Story Book`;
- source-separated chapters;
- physical book interaction;
- `Story ON`;
- timeline;
- related records;
- search;
- Add Visit;
- mobile behavior;
- source vs AI-summary distinction.

The first validation question is therefore not `can we build this?` but `does this interaction grammar produce measurable patient/guardian value beyond existing summary/timeline formats?`

## 2. Market boundary

The broad market is already occupied.

Examples reviewed in 2026 include:

- Korea MyHealthWay / 나의건강기록: national personal-health-record connectivity and record access;
- Guava Health: longitudinal records, labs, visit notes, uploads and AI summaries;
- PicnicHealth: visit timeline, health story organization, trends and sharing;
- Abridge: clinical-conversation capture and patient-facing visit summaries.

Therefore this project must **not** become another generic PHR, record aggregator, note reader or AI medical summary.

### Surviving wedge

> A source-grounded episodic memory layer for patients and guardians that reconstructs each visit as a trusted sequence of what happened, why the next step happened, what the doctor/document actually said, what AI merely organized, what the patient personally noted, and what must be remembered for the next encounter.

## 3. Research rationale

Existing research gives a reason to test, not a reason to assume success.

- A randomized after-visit-summary study found that adding more AVS content did not materially improve recall; medication recall remained modest and did not differ by content condition.
- Large OpenNotes surveys report that many patients perceive note access as valuable for remembering plans, understanding care and preparing for visits.
- Narrative health communication often improves engagement/effectiveness, but effects depend on audience, topic and objective; some experiments favor non-narrative/didactic formats.
- A 2026 randomized inpatient study found AI-generated, clinician-edited AVS improved reading-level and simplified explanations on component measures, but did not demonstrate a significant advantage on its composite primary outcome.

This means My Health Story needs an **information-equivalent head-to-head test** rather than a visual-preference test.

## 4. Core research question

> Compared with a conventional after-visit summary or chronological timeline containing the same facts, does a source-grounded episodic story help a person more accurately reconstruct a hospital visit, distinguish information sources, remember follow-up actions and retrieve past facts without excessive cognitive load?

## 5. Hypotheses

### H1 — Source attribution

Story format improves the ability to distinguish:

- what the patient said;
- what the clinician said;
- what came from a prescription/test/document;
- what AI only organized or summarized;
- what is the user's later personal note.

This is the **primary product hypothesis**.

### H2 — Follow-up action recall

Story format improves recall of next actions such as:

- return visit;
- test-result check;
- question to ask next time;
- document to bring;
- symptom/log to continue.

### H3 — Episodic reconstruction

Story format improves accurate reconstruction of the sequence and causal transitions of the visit without creating false facts.

### H4 — Retrieval

Story format does not materially slow the user when asked to find one past fact.

### H5 — Delayed recall

Any immediate advantage should survive a delayed re-test; a purely aesthetic preference is not sufficient.

## 6. Experimental conditions

All three conditions must contain **the same underlying facts**. No condition may receive extra medical information.

### Condition A — Conventional After-Visit Summary

A concise structured summary resembling a normal patient-facing visit summary:

```text
reason for visit
main discussion
exam/test
medication/prescription instruction
follow-up
```

### Condition B — Timeline

The same facts in chronological cards/time order.

### Condition C — My Health Story

The same facts arranged as chapters:

```text
BEFORE THE VISIT
ARRIVAL
WHAT I TOLD THE DOCTOR
WHAT THE DOCTOR SAID
EXAMS & TESTS
MEDICATION
WHAT I NEED TO REMEMBER
MY NOTE AFTER THE VISIT
WHAT HAPPENED NEXT
```

Every relevant item carries an explicit provenance label:

```text
PATIENT SAID
CLINICIAN SAID
SOURCE DOCUMENT
AI ORGANIZED
MY NOTE
NEEDS REVIEW
```

The first experiment should minimize cinematic effects so the test measures information architecture, not animation preference.

## 7. Synthetic case set

Use at least three fictitious cases with different information structures.

### Case A — Sleep / stress consultation

Purpose: conversation-heavy case.

Include:

- reason for visit;
- multiple patient statements;
- clinician explanation;
- one screening/test event;
- one follow-up action;
- one patient note after the visit.

No real drug name is required.

### Case B — Musculoskeletal / hand pain

Purpose: test + instruction-heavy case.

Include:

- symptom history;
- exam finding sourced to clinician/document;
- imaging/test order or result;
- bounded self-care instruction as a quoted/source fact, not AI advice;
- follow-up trigger;
- document to bring next time.

### Case C — Routine health check

Purpose: document-heavy longitudinal case.

Include:

- several numeric lab/checkup facts;
- one prior-value comparison;
- clinician comment;
- scheduled recheck;
- patient question for next visit.

All numbers and institutions are synthetic.

## 8. Study design — pilot

Recommended first pilot:

- 18–30 adult participants;
- no need to recruit patients for the first usability/memory gate;
- within-subject, counterbalanced design so each participant sees all three formats but on different cases;
- use a Latin-square or equivalent rotation to reduce case/order effects;
- immediate task battery after each case;
- delayed re-test after 24–72 hours if operationally feasible.

This pilot is for product-direction evidence, not clinical efficacy or population-level statistical claims.

## 9. Required measures

### Primary

1. **Source Attribution Accuracy**
   - percentage of facts assigned to the correct source category.

2. **Follow-up Action Recall**
   - percentage of required next actions recalled without false additions.

### Secondary

3. **Factual Recall Accuracy**
   - correct facts / ground-truth facts queried.

4. **False Recall / Hallucinated Fact Rate**
   - recalled claims that were not present in source material.

5. **Visit Sequence Reconstruction**
   - correct order / causal adjacency of key events.

6. **Time to Find a Fact**
   - seconds from query to correct retrieval.

7. **Confidence Calibration**
   - self-rated confidence compared with actual correctness.

8. **Cognitive Load**
   - short 5- or 7-point self-report scale.

9. **Perceived Usefulness / Preference**
   - secondary only; do not let preference override objective errors.

10. **Delayed Recall**
   - repeat a reduced fact/source/follow-up battery after 24–72 hours.

## 10. Scoring rules

Each synthetic case must have a hidden answer key with:

- atomic fact ID;
- exact source;
- event order;
- follow-up status;
- whether the fact is directly stated vs AI-organized;
- acceptable paraphrases;
- forbidden/invented interpretation.

Human scoring should be possible without a model. If an LLM assists scoring, keep the deterministic answer key authoritative and audit a sample manually.

## 11. Product-decision gate

### GO_TO_PRODUCT_PROTOTYPE

Use only if the story format shows a meaningful advantage in **source attribution and/or follow-up memory** without a material penalty in factual accuracy or retrieval time, and participants can explain why the source distinctions matter.

### NARROW

Use if:

- story improves one task but not others;
- only a subset of visits benefits;
- chapter structure is useful but physical-book/cinematic layer is unnecessary;
- caregiver use appears stronger than general patient use;
- source labels help but story sequencing does not.

### ABSORB

Use if the useful part is only a capability that should become a module of ASTERIVE/another product rather than a standalone healthcare product.

### KILL_AS_STANDALONE

Use if an information-equivalent story format does not improve task performance or creates more source confusion/false recall than summary/timeline.

## 12. Safety and privacy boundaries

First gate:

```text
REAL_PATIENT_DATA = NO
REAL_CONSULTATION_AUDIO = NO
REAL_PRESCRIPTION = NO
REAL_MEDICAL_BILL = NO
DIAGNOSIS_GENERATION = NO
TREATMENT_RECOMMENDATION = NO
MEDICATION_CHANGE = NO
EMERGENCY_CLASSIFICATION = NO
```

The test evaluates information organization and memory, not medical judgment.

## 13. Next implementation slice

Create a dataset-free validation pack containing:

1. three synthetic source bundles;
2. information-equivalent A/B/C render data;
3. ground-truth answer keys;
4. task/question bank;
5. scoring script or deterministic score sheet;
6. randomization/counterbalancing manifest;
7. result CSV schema;
8. analysis notebook/script;
9. no real PHI.

Do **not** build another UI until this pack exists.
