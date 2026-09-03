# Bio / Healthcare Idea Recovery & Priority — 2026-08-26

## Why this document exists

The current Bio/Healthcare exploration began because the domain is unfamiliar and PADIEM wanted to discover where its existing AI, multimodal, source-grounding, storytelling, search, workflow and multilingual capabilities could become a credible healthcare product.

The operating error to avoid is selecting an old PADIEM asset merely because it has historical IP evidence, or inventing a fresh idea each session while forgetting the ideas and prototypes generated the day before.

This note reconstructs the actual 2026 idea set and resets priority around present-day product evidence.

## Recovered 2026 ideas / product directions

### 1. My Health Story / 병원 스토리북 — ACTIVE VALIDATION CANDIDATE

Evidence already exists beyond an idea:

- ASTERIVE work order: `04_아스테리브_마이헬스스토리_병원스토리북_v1`
- role: Patient Health Journey Storybook + Personal Medical Record Experience + Longitudinal Health Archive UI
- prototype concept: `1 Hospital Visit = 1 Story Book`
- source inputs: consultation recording, prescription, bill, tests, photos, documents, user notes
- chapter grammar: Before the Visit → Arrival → What I Told the Doctor → What the Doctor Said → Exams & Tests → Medication → What I Need to Remember → My Note After the Visit
- trust grammar: SOURCE / AI SUMMARY / MY NOTE / NEEDS REVIEW
- relationship/timeline/search extensions
- prototype QA evidence exists with sample-only data, book interaction, Story ON, timeline, related view, Add Visit and mobile behavior.

Important product boundary:

This is **not** an EMR, diagnosis engine or generic health-data dashboard. It is a patient/guardian memory and visit-reconstruction experience.

### 2. Home Rehab Observer Coach / 혼자 재활할 때 보는 AI 코치 — SCREENING

Owner-originated idea:

- observe a person exercising or rehabilitating alone;
- identify what is going wrong in movement;
- guide/correct the movement;
- design or adapt the exercise sequence.

This is not automatically a new Business. It must first be checked against PADIEM's existing AI Exercise Coach / Business 38 / pose-analysis lineage. A separate product boundary would need to come from the **rehabilitation workflow**, prescribed-plan adherence, recovery progression, or clinician handoff—not merely from adding the word `rehab` to pose coaching.

### 3. Event Story Engine / 사건·병원 여정 스토리 엔진 — CROSS-DOMAIN PLATFORM CONCEPT

The same interaction grammar appeared in two owner-originated directions:

- healthcare: a hospital visit becomes a story showing why the visit happened, what was said, what tests/medications occurred, and what comes next;
- FactLaw / 사실로: an incident becomes a story showing what evidence to collect, what documents to organize, what happens before complaint, statement/evidence stages, investigation/referral/prosecution, civil litigation and what comes next.

This suggests a reusable PADIEM capability rather than two unrelated UI ideas:

```text
raw evidence / recordings / documents
→ event chronology
→ source-grounded chapters
→ WHY/NEXT causal transitions
→ current state
→ next required actions
→ evidence/source links
→ longitudinal volumes
```

Healthcare can be one vertical of this engine; FactLaw can be another. This platform concept does not receive a Business number from this note.

### 4. Clinical AI Egress Control Plane — PAUSED

B63 concept demo is complete. Technical work is paused pending real hospital/HIS validation.

### 5. Longitudinal Patient CareGraph — ARCHITECTURE / FUTURE LAYER

This should not be treated as the next standalone product by default. The ASTERIVE health-story prototype already contains `RELATED`, timeline and future longitudinal data structures. CareGraph may become the underlying relationship/data layer if My Health Story survives validation.

### 6. Patient Communication AI — MODULE / SCREENING

Plain-language, multilingual, source-preserving explanation remains useful, but on current evidence it is more naturally a capability inside My Health Story, discharge/follow-up workflows, or foreign-patient coordination than a standalone Business.

### 7. Health-check Trend AI — MODULE / SCREENING

Longitudinal test/checkup changes can be valuable, but should first be treated as a My Health Story / longitudinal health layer rather than automatically creating another product.

### 8. Foreign Patient Medical Coordination — SEPARATE CANDIDATE

This remains a plausible separate lane because PADIEM has multilingual speech/translation/dubbing assets. The distinct product question is workflow coordination across documents, appointments, explanations and handoffs—not translation alone.

### 9. Medical Record Intelligence Workspace — LIKELY ABSORBED

Much of this capability overlaps ASTERIVE's document search, source state, notes, relationships and the My Health Story prototype. Do not create a second generic medical-record workspace without a materially different buyer/workflow.

### 10. Bio Evidence Graph / R&D Reproducibility Copilot — LOWER PRIORITY

This was generated as a later research candidate and remains worth preserving, but it was not the center of the owner's original healthcare exploration and should not displace recovered owner-originated ideas.

## Historical asset disposition

### NIR / vein-finder / injection-assistance technology

PADIEM's historical asset and patent lineage are real, but the owner clarified that this is roughly a decade-old idea and is not a useful center of the current discovery effort.

```text
BIO-001 = DEPRIORITIZED_HISTORICAL
PR #770 = CLOSED_UNMERGED
Issue #769 = CLOSED_NOT_PLANNED
future reuse = allowed only if a new partner / dataset / funding / technical wedge materially changes the opportunity
```

## Current market screen — My Health Story

The category is not empty:

- Korea's MyHealthWay / `나의건강기록` already provides national personal-health-record access and FHIR-based data connectivity across many institutions.
- Guava Health aggregates records, labs, visit notes, wearables and uploaded documents, offers longitudinal views, AI summaries and a patient app.
- PicnicHealth provides visit timelines, longitudinal records, trends, sharing and explicitly frames part of the experience as helping patients tell/understand their health story.
- Abridge generates patient visit summaries from clinical conversations and extends the clinical workflow before/during/after encounters.

Therefore the broad thesis **“AI organizes all my medical records” is not differentiated enough.**

The surviving wedge is narrower:

> **A source-grounded episodic memory layer for the patient: reconstruct each hospital visit as a trusted story of what happened, why the next step happened, what came from the original source, what the AI merely organized, and what the patient should remember for the next encounter.**

The product should complement—not duplicate—national PHR infrastructure or EHR systems.

## Why My Health Story should be the next validation target

1. A working visual prototype already exists, so this is not speculative ideation.
2. It reuses ASTERIVE, StoryMemory/LoveTree storytelling, source/provenance and search capabilities.
3. It can be tested with fully synthetic visit recordings/documents before any hospital integration or real PHI.
4. The core user problem—remembering and understanding what happened across medical visits—is visible to ordinary patients/guardians, not only hospital IT buyers.
5. The competitive gap is testable: does episodic story reconstruction + explicit source trust create more value than a conventional timeline or summary?

## Next validation question

Do not build more UI first. Test this claim:

> Compared with a conventional after-visit summary/timeline, does a source-grounded visit story help a patient or guardian more accurately reconstruct what happened, distinguish doctor statements from AI organization and personal notes, remember follow-up tasks, and prepare for the next visit?

A first validation can use synthetic visit cases and compare:

- ordinary summary;
- ordinary timeline;
- My Health Story chapter format.

Possible measures:

- factual recall;
- source attribution accuracy;
- follow-up task recall;
- time-to-find a past fact;
- confidence vs actual accuracy;
- perceived usefulness / cognitive load;
- preference after delayed re-test.

No diagnosis, treatment recommendation or real patient data is needed for this first gate.

## Current priority

```text
P1 = MY_HEALTH_STORY_VALIDATION
P2 = HOME_REHAB_OBSERVER_COACH_SCREENING_AGAINST_B38
P3 = FOREIGN_PATIENT_MEDICAL_COORDINATION_SCREENING
P4 = EVENT_STORY_ENGINE_PLATFORM_REUSE_MODEL
B63 = PAUSED_HOSPITAL_VALIDATION
NIR = DEPRIORITIZED_HISTORICAL
BROAD_DRUG_DISCOVERY_RADIOLOGY_GENOMICS = DEPRIORITIZED
```
