# BIO-014 Home Rehab Observer Coach — Current-Market / Portfolio Screen

- Date: 2026-08-26
- Status: SCREEN COMPLETE
- Business number: NONE
- Owner-originated 2026 idea: AI observes a person doing rehabilitation/exercise alone, identifies movement problems, gives correction and adapts/designs the session.

## 1. Portfolio overlap — Business 38

Existing proposed Business 38 `AI Exercise Coach / AI 운동 코치` already owns:

- movement observations;
- session sequencing;
- plain-language form cues;
- regression/progression options;
- exertion/comfort checks;
- adaptive movement-plan review.

But B38 explicitly excludes:

- injury rehabilitation;
- physiotherapy;
- clinical exercise prescription;
- medical diagnosis/treatment;
- autonomous camera pose certification.

Therefore the rehab idea is **not automatically a B38 duplicate**, but generic movement/form coaching is already portfolio territory. A new healthcare product would need a genuinely clinical-rehabilitation workflow boundary, not simply the word `rehab`.

## 2. Current external market

The generic thesis is already heavily occupied.

### Sword Health

Current AI-supported physiotherapy includes:

- at-home physiotherapy;
- real-time movement guidance;
- progress tracking between visits;
- personalised programmes;
- AI movement tracking;
- physiotherapist review and plan adjustment.

### Hinge Health

Current TrueMotion / Movement Analysis includes:

- phone/tablet computer vision;
- full-body movement tracking;
- joint-angle/symmetry/endurance measurement;
- real-time guidance;
- clinician/care-team monitoring and plan modification.

### Kaia Health

Motion Coach uses the phone/tablet front camera for:

- body-landmark tracking;
- posture/form analysis;
- real-time audiovisual corrective feedback;
- repetitions / movement guidance;
- functional measurements and progress.

### Kemtai

Remote PT already positions camera-based computer vision as:

- real-time exercise feedback;
- prescribed home exercise protocols;
- digital assessments;
- adherence/engagement support.

### Korea — Dr.Answer 3.0 / postoperative rehabilitation

The current Korean public R&D programme includes a postoperative rehabilitation lane with hospitals and AI company participation. The published target includes:

- smartphone camera On-device AI;
- joint/posture analysis;
- real-time feedback;
- physician-prescribed rehabilitation protocols;
- patient-specific home rehabilitation;
- AI-agent adaptation;
- digital-therapeutics regulatory pathway.

A 2026 Korean hospital report also describes exploratory randomized pilot work on an AI digital rehabilitation platform using smartphone 2D camera motion analysis for postoperative/shoulder rehabilitation.

## 3. Technical research state

A 2025 systematic review of computer-vision physiotherapy movement assessment found substantial work across local, clinical and remote settings. Important remaining research limitations include:

- real-world validation;
- dataset diversity;
- generalization across environments and populations.

A 2026 public physiotherapy dataset (MobiPhysio) also provides thousands of 2D exercise videos with expert-guided movement quality scores, lowering the barrier to generic movement-assessment research.

Therefore `pose estimation + exercise-quality score + live cue` is not a sufficient PADIEM wedge.

## 4. Disposition

```text
GENERIC_HOME_REHAB_OBSERVER_COACH = KILL_AS_NEW_STANDALONE_THESIS
B38_GENERIC_EXERCISE_OVERLAP = HIGH
CLINICAL_REHAB_MARKET_COMPETITION = VERY_HIGH
TECHNICAL_FEASIBILITY = HIGH
PADIEM_DIFFERENTIATION_AS_STATED = LOW
NEW_BUSINESS_NUMBER = NO
```

Do not develop a generic camera rehab coach now.

## 5. Surviving PADIEM-specific angle — Recovery Story / continuity layer

The owner-originated rehab idea becomes more interesting when connected to the other recovered 2026 idea: `My Health Story`.

Instead of trying to beat mature digital-PT platforms at live motion coaching, test a continuity problem:

```text
hospital visit / clinician plan
→ home recovery sessions
→ what exercise was attempted
→ observable movement evidence
→ user-reported comfort/uncertainty
→ adherence / skipped sessions
→ changes over time
→ questions that emerged
→ next clinical encounter
```

Potential representation:

> **A hospital visit is one volume; home recovery becomes the chapters between that volume and the next visit.**

This could reuse:

- My Health Story episodic/source-grounded timeline;
- Event Story Engine WHY/NEXT grammar;
- PADIEM movement-analysis experience;
- B38 general movement-cue assets where legally/safely reusable;
- explicit human/clinician review boundaries.

### Important boundary

This surviving angle should **not** autonomously prescribe clinical rehabilitation changes.

A safer first product question is:

> Can AI make the period between clinical visits observable and memorable enough that a patient and clinician can reconstruct what was actually attempted, what changed, what was uncertain, and what should be discussed next?

This is closer to PADIEM's differentiated evidence/story/memory stack than generic real-time pose correction.

## 6. Portfolio recommendation

```text
BIO-014 standalone = DEPRIORITIZE / KILL_GENERIC
LIVE_CAMERA_REHAB_COACH = DO_NOT_BUILD_NOW
RECOVERY_STORY_LAYER = ABSORB_INTO_BIO-003 / PLAT-001 RESEARCH
```

If future evidence shows a Korean clinical partner specifically needs a motion-analysis component, that component can be revisited as a bounded technical module rather than re-opening the generic product thesis.
