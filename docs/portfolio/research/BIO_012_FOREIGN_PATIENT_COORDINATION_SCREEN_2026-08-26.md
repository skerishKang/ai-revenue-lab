# BIO-012 Foreign Patient Medical Coordination — 2026 Screen

- Date: 2026-08-26
- Status: `NARROW / ABSORB_EXISTING_CAPABILITY`
- Business number: NONE

## 1. Original direction

Use PADIEM multilingual speech/translation capability to support an international patient through:

```text
pre-visit documents
→ appointment / intake
→ consultation
→ explanation
→ follow-up
→ cross-institution / cross-country handoff
```

## 2. External market result

Korean international-patient demand is substantial, but the broad product space is already crowded.

Current products/services already cover large parts of:

- foreign-patient search / booking / interpretation / payment / records;
- multilingual medical-tourism coordination and aftercare;
- real-time medical interpretation and documentation;
- translated portable medical packets and cross-border records.

Therefore:

```text
GENERIC_MEDICAL_TOURISM_PLATFORM = KILL_AS_NEW_THESIS
GENERIC_AI_MEDICAL_TRANSLATOR = KILL_AS_NEW_PADIEM_PRODUCT
GENERIC_MULTILINGUAL_SCRIBE = HIGH_COMPETITION
```

## 3. Internal duplicate / reuse discovery

The key finding is that PADIEM already has the core trust/evaluation grammar needed for the most interesting part of this idea.

### Existing proposed Business 39 — 112 Real-Time Interpretation

GitHub Issue #261 defines:

```text
caller speech
→ unverified transcript
→ interpretation draft
→ critical term / uncertainty markers
→ operator clarification
→ human correction
→ bilingual relay summary
→ HUMAN-VERIFIED BILINGUAL CALL RECORD
```

It already requires explicit handling of:

- critical terms;
- negation risk;
- numbers;
- locations;
- speaker/source separation;
- uncertainty;
- human clarification/correction;
- provenance between source speech, machine output and final human-confirmed wording.

A full static B39 reference implementation also exists under:

`reference/business-39-112-real-time-interpretation-v1/`

Therefore a new healthcare interpretation engine would duplicate existing portfolio capability.

### Existing 112 research evidence in Drive

Current Drive evidence includes:

- `2026_박사학위논문_외국인112신고대응_AI통역·멀티모달긴급도분류_HITL운영모델.pdf`;
- 2026 Korean Association for Public Administration presentation materials on AI interpretation and multimodal urgency classification;
- prior comparative work on AI interpretation versus human interpretation in the 112 / first-response context.

The medical lane should reuse that evaluation thinking instead of restarting from BLEU-only translation research.

## 4. Surviving healthcare-specific capability

### Bilingual Visit Passport / 의료통역 안전기록

This is **not a new translation product**. It is a healthcare-domain application of existing B39 meaning-preservation and human-verification capability, connected to My Health Story.

### Before the visit

```text
foreign-language source document
→ source-preserving translation
→ critical facts / terms highlighted
→ ambiguous segment flagged
→ clinician-readable Korean intake packet
```

### During the visit

```text
patient speech ↔ clinician speech
→ speaker-attributed bilingual transcript
→ B39-style critical-slot / uncertainty checks
→ healthcare-specific slot checks
→ repair prompt / human interpreter escalation
→ human-confirmed wording
```

Healthcare-specific checks may add:

```text
number / date / time
left / right / body site
negation
symptom duration / frequency
allergy / medication name strings
dose / unit strings when present
follow-up date / instruction
```

### After the visit

```text
human-confirmed visit facts
+ source documents
+ bilingual transcript
→ bilingual My Health Story
→ source-linked follow-up / questions
→ portable patient/caregiver/next-provider handoff packet
```

## 5. What is genuinely new enough to test

The technical novelty question is no longer:

> Can PADIEM translate a medical conversation?

That is too generic and overlaps B39 plus current market products.

The useful R&D question is:

> Does the existing B39 human-verification / critical-slot architecture transfer to clinical conversation in a way that reduces medically important meaning-loss and creates a trustworthy bilingual visit memory when joined with My Health Story?

This is a **domain-transfer validation**, not a new product build.

## 6. First validation design

Reuse the existing 112 interpretation evaluation structure wherever possible, but add medical-domain error classes.

Potential synthetic language pairs:

```text
Korean ↔ English
Korean ↔ Chinese
```

Primary checks:

```text
critical-slot accuracy
number/date/time preservation
body-side/site preservation
negation preservation
symptom duration/frequency preservation
medication/allergy/dose-string preservation where present
speaker attribution
semantic omission/addition
uncertainty detection recall
human correction rate
latency
```

Do not treat generic BLEU as the decision metric.

Use synthetic or clearly licensed cases first. No real patient audio is necessary for the first domain-transfer gate.

## 7. Portfolio disposition

```text
BIO_012_STANDALONE_FOREIGN_PATIENT_PLATFORM = KILL_GENERIC
BIO_012_NEW_TRANSLATION_ENGINE = DUPLICATE_B39
B39_MEANING_PRESERVATION_CAPABILITY = REUSE
BILINGUAL_VISIT_PASSPORT = ABSORB_INTO_BIO_003 / PLAT_001
MEDICAL_DOMAIN_TRANSFER_R&D = WORTH_TESTING
NEW_BUSINESS_NUMBER = NO
```

If medical-domain evaluation shows a material benefit, the result should first become:

- a bilingual mode inside My Health Story;
- a multilingual layer inside Event Story Engine;
- or a hospital-facing capability using B39/B63 trust controls.

Only a later, clearly distinct buyer/workflow could justify a standalone Business.

## 8. Legal / operational boundary

Do not assume PADIEM may operate as an unregistered foreign-patient attraction broker.

Initial positioning should remain software/workflow support for appropriately registered healthcare institutions or facilitators, subject to legal review. Clinical responsibility stays with licensed professionals, and human interpreter escalation must remain available where required.
