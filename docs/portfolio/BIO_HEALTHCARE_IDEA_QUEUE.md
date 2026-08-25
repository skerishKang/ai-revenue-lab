# Bio / Healthcare AI R&D Idea Queue

- Updated: 2026-08-26
- Parent portfolio ledger: `docs/portfolio/IDEA_LEDGER.md`
- Recovery note: `docs/portfolio/research/BIO_HEALTHCARE_IDEA_RECOVERY_AND_PRIORITY_2026-08-26.md`
- Project lineage: `07_BioR&D`
- Business-number authority: `docs/portfolio/BUSINESS_REGISTRY.md`

## Operating principle

This Bio/Healthcare track exists to learn an unfamiliar domain by testing **present-day product hypotheses** against PADIEM's actual capabilities. Historical IP is supporting evidence, not an automatic priority signal.

```text
recover recent owner ideas + existing prototypes
→ duplicate / absorption check
→ current market / buyer / regulatory screen
→ smallest truthful validation
→ GO / NARROW / PAUSE / KILL / ABSORB
→ product promotion only when warranted
```

## Current priority queue

### P1 — My Health Story / 병원 스토리북 — `DEMO → VALIDATION`

This is the strongest current next candidate because a real sample-only prototype already exists.

Core product grammar:

```text
one hospital visit = one story book

why I went
→ what I told the doctor
→ what the doctor said
→ exams / tests
→ medication / prescription source
→ what I need to remember
→ my note
→ what happens next
```

Trust grammar:

```text
SOURCE
AI SUMMARY
MY NOTE
NEEDS REVIEW
```

Existing ASTERIVE prototype includes bookshelf entry, physical book interaction, Story ON, timeline, related records, Add Visit, search and mobile behavior. It is explicitly patient/guardian-facing and does not replace diagnosis/treatment.

Current market screen says the broad category is crowded:

- MyHealthWay / 나의건강기록 already provides national personal medical-record access;
- Guava Health provides records, longitudinal views and AI summaries;
- PicnicHealth provides visit timelines, trends and patient-centered record organization;
- Abridge provides patient visit summaries from clinical conversations.

Therefore the product thesis is **not** `another PHR or medical-record organizer`.

Surviving wedge:

> source-grounded episodic reconstruction of each hospital visit so the patient/guardian can accurately remember what happened, why the next step happened, what came from the doctor/document, what AI only organized, and what must be remembered for the next visit.

Current execution:

- Issue #772 — validation contract;
- Draft PR #774 — three fully synthetic cases, information-equivalent summary/timeline/story representations, question bank, counterbalancing, response schemas and deterministic scoring/analysis.

Next gate: exact-head fixture validation, then a bounded participant pilot measuring source attribution, follow-up recall, factual/sequence recall, retrieval time, cognitive load and delayed recall.

### P2 — Foreign Patient Medical Coordination — `IDEA → NEXT SCREEN`

Potential separate lane leveraging PADIEM multilingual speech/translation/dubbing assets.

Product boundary must be workflow coordination across:

- intake documents;
- appointments;
- consultation explanations;
- follow-up instructions;
- institution handoffs;
- source-grounded multilingual records.

Generic translation alone is not enough.

### P3 — Event Story Engine / Recovery Story — `PLATFORM SCREENING`

Recovered common grammar across My Health Story and 사실로:

```text
recordings / documents / evidence
→ event chronology
→ source-grounded chapters
→ why-next transitions
→ current state
→ next required action
→ longitudinal volumes
```

The Home Rehab screen adds a healthcare continuity variant:

```text
hospital visit / clinician plan
→ home recovery attempts
→ observable movement/session evidence
→ patient uncertainty / adherence
→ changes over time
→ questions for next visit
```

Treat both as reusable PADIEM capabilities before treating either as a standalone Business.

## Screened / absorbed — Home Rehab Observer Coach

### Generic thesis — `DEPRIORITIZED / KILL AS NEW STANDALONE`

Owner-originated concept: observe a person doing rehabilitation alone, identify movement problems, give correction and adapt/design the session.

Current screen found:

- Business 38 already owns general movement observations, form cues, session planning and adaptive movement-plan concepts while explicitly excluding rehabilitation/physiotherapy;
- Sword Health already provides AI-supported at-home physiotherapy, movement guidance, progress monitoring and therapist plan adjustment;
- Hinge Health TrueMotion provides full-body computer-vision guidance, objective movement analysis and care-team plan modification;
- Kaia Motion Coach provides camera-based posture/movement analysis and real-time corrective feedback;
- Kemtai already targets prescribed home-exercise protocols with camera guidance;
- Korea's Dr.Answer 3.0 postoperative rehabilitation lane targets smartphone On-device AI, posture/joint analysis, real-time feedback, clinician-prescribed protocols and regulatory development.

Therefore:

```text
GENERIC_CAMERA_REHAB_COACH = DO_NOT_BUILD_NOW
PADIEM_DIFFERENTIATION_AS_STATED = LOW
```

### Surviving angle — `Recovery Story / Between-Visits layer`

Absorb into BIO-003 / PLAT-001 research rather than create another Business.

Question:

> Can AI make the period between clinical visits observable and memorable enough that patient and clinician can reconstruct what was attempted, what changed, what was uncertain, and what should be discussed next?

No autonomous rehabilitation prescription changes are authorized.

## Existing / paused

### Clinical AI Egress Control Plane — `PROMOTED / PAUSED`

- proposed B63 under Issue #731;
- concept demo complete;
- next evidence requires real hospital/HIS validation.

## Modules / likely absorbed directions

### Longitudinal Patient CareGraph

Treat as the future relation/data layer under My Health Story unless a distinct B2B product/buyer emerges.

### Patient Communication AI

Likely capability inside My Health Story, discharge/follow-up or foreign-patient coordination. Keep source boundaries explicit.

### Health-check Trend AI

Likely longitudinal module; avoid creating a separate product until a unique user/buyer problem is proven.

### Medical Record Intelligence Workspace

Likely overlaps ASTERIVE document search/source/relationship capabilities and My Health Story. New standalone workspace requires a materially different workflow/buyer.

## Preserved but not current priority

### NIR / vein-finder / venipuncture training — `DEPRIORITIZED HISTORICAL`

- historical PADIEM technical/IP lineage preserved;
- owner clarified this roughly decade-old idea should not lead current discovery;
- Issue #769 closed `not_planned`;
- PR #770 closed unmerged.

### Ambient Medical AI / Scribe — `DEPRIORITIZED`

Crowded clinician workflow category.

### AI Drug Discovery — `DEPRIORITIZED`

Too broad/domain-capital intensive for current first entry.

### Radiology Diagnosis AI — `DEPRIORITIZED`

Crowded/high-regulatory; weak current PADIEM differentiation.

### Genomics AI — `DEPRIORITIZED`

Specialized data/domain capability not yet established.

### Bio Evidence Graph — `DEPRIORITIZED`

Preserve as later biotech R&D-operations candidate; do not let later assistant-generated ideas displace recovered owner-originated 2026 ideas.

## Screening dimensions

Every standalone candidate should be assessed on:

1. current market / prior art;
2. PADIEM-specific wedge;
3. reusable asset fit;
4. data accessibility;
5. regulatory/safety boundary;
6. actual user/buyer;
7. government R&D / demonstration fit;
8. truthful demo/validation feasibility.

## Next-candidate rule

When the owner asks for the next Bio/Healthcare task:

1. read this queue first;
2. continue the highest-priority existing candidate unless evidence says to stop;
3. recover recent conversation/prototype evidence before inventing a new idea;
4. check Business Registry, GitHub, Drive/File Library and prior sessions for overlap;
5. record GO / NARROW / PAUSE / KILL / DUPLICATE / ABSORB before moving on.
