# BIO-012 Foreign Patient Medical Coordination — 2026 Screen

- Date: 2026-08-26
- Status: NARROW / R&D TEST WORTHY
- Business number: NONE

## 1. Original product direction

Use PADIEM multilingual speech/translation capability to help an international patient move through:

```text
pre-visit documents
→ appointment / intake
→ consultation
→ explanation
→ follow-up
→ cross-institution / cross-country handoff
```

The idea is attractive because it combines real PADIEM assets rather than requiring PADIEM to invent a new diagnostic model.

## 2. Market reality

### Korea demand is large

MOHW reported 1.17 million foreign patients visiting Korea in 2024, up 93.2% from 2023 and the largest annual result since the programme began.

Government policy has also emphasized:

- regional distribution of international-patient demand;
- ICT-based pre-consultation and post-care;
- stronger quality/accreditation systems;
- medical-tourism / global-healthcare industry development.

Medical Korea / KHIDI continues to operate registration, accreditation, market information and international-patient programmes in 2026.

### But generic coordination is already crowded

Current products/services include:

- **Imdr** — Korea-focused foreign-patient platform with search, booking, interpretation, treatment, payment and records across 7 languages, plus hospital operations tooling;
- **The Medical Korea** and other licensed facilitators — pre-arrival consultation, provider matching, managers and aftercare;
- **BT Medi / KoreaMedis** — multilingual medical-tourism cycle with booking, video consultation, AI-assisted interpretation and payment;
- **Cross Border Care / CareAI** — end-to-end international-patient orchestration including records, logistics, treatment and follow-up;
- **MaiMedic / MedDossier** — multilingual record translation and portable cross-border medical packets;
- **MedLingo / HearWise** — multilingual clinical interpretation/documentation, summaries and EMR-oriented workflows.

Therefore:

```text
GENERIC_MEDICAL_TOURISM_PLATFORM = KILL_AS_NEW_THESIS
GENERIC_AI_MEDICAL_TRANSLATOR = HIGH_COMPETITION
GENERIC_MULTILINGUAL_SCRIBE = HIGH_COMPETITION
```

## 3. PADIEM-specific surviving wedge

PADIEM should not compete on hotel/visa/booking/concierge breadth.

A narrower technical/product hypothesis fits PADIEM's prior emergency-interpretation research, source grounding, verification and My Health Story work:

# Bilingual Visit Passport / 의료통역 안전기록

> Preserve the exact clinical meaning of a multilingual encounter, make uncertainty visible, and leave both patient and clinician with a source-grounded bilingual record of what was actually said and what must happen next.

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
→ critical-slot preservation
→ numbers / dates / dosage-like strings / body side / negation checks
→ uncertainty / repair prompt
→ optional human-interpreter escalation
```

### After the visit

```text
clinician-approved source facts
+ visit transcript
+ documents
→ bilingual My Health Story / visit passport
→ instructions and follow-up kept source-linked
→ portable handoff packet for patient / caregiver / next provider
```

The AI does not invent diagnosis or treatment and does not replace a qualified medical interpreter where one is required.

## 4. Why this is closer to PADIEM

Reusable evidence/capability:

- prior real-time multilingual emergency interpretation research and evaluation design;
- slot-level accuracy thinking for numbers, places and urgent facts;
- speech / STT / translation / TTS experience;
- source-grounding / evidence labels;
- B63 privacy/egress thinking;
- My Health Story episodic patient-memory format;
- human-review and uncertainty workflows.

This is a more credible PADIEM R&D wedge than building another foreign-patient booking marketplace.

## 5. Duplicate risk remains material

MedLingo and other multilingual clinical systems already combine real-time translation, clinical documentation, patient summaries and fact-checking. Cross-border record platforms also provide multilingual portable records.

Therefore the surviving wedge is **not yet a proven standalone product**.

```text
DUPLICATE_RISK = MEDIUM_HIGH
PADIEM_ASSET_FIT = HIGH
MARKET_DEMAND = HIGH
REGULATORY_SAFETY_BURDEN = HIGH
STANDALONE_PRODUCT = NOT_PROVEN
R&D_TEST_VALUE = HIGH
```

## 6. First technical validation question

> Can a Korean-first, source-grounded interpretation pipeline reduce critical-fact translation errors and expose uncertainty more reliably than a plain general-purpose translation workflow, without unacceptable latency?

Do not test generic BLEU alone.

### Synthetic benchmark dimensions

At minimum:

```text
critical-slot accuracy
number/date/time accuracy
left/right/body-site accuracy
negation preservation
medication/dose-string preservation where present
speaker attribution
semantic omission/addition
uncertainty detection recall
human correction rate
latency
```

Potential first language pairs:

```text
Korean ↔ English
Korean ↔ Chinese
```

Use synthetic or properly licensed medical-dialogue cases first. No real patient audio is required for the first gate.

## 7. Product decision after benchmark

### GO / NARROW

Only if PADIEM can demonstrate a measurable safety/verification advantage or a meaningfully lower human-review burden in Korean hospital workflows.

### ABSORB

If the useful result is mostly a capability, absorb it into:

- My Health Story bilingual mode;
- B63 controlled AI/PHI workflow;
- hospital international-patient integration;
- future Event Story Engine multilingual layer.

### KILL AS STANDALONE

If performance is comparable to commodity translation/medical-scribe systems and no Korean workflow advantage emerges.

## 8. Legal / operational boundary

PADIEM should not assume it can act as an unregistered foreign-patient attraction intermediary.

Initial positioning should be software / workflow support for appropriately registered healthcare institutions or facilitators, with legal review before any patient-attraction or brokerage activity.

Clinical responsibility remains with licensed clinicians, and interpretation-risk controls must be explicit.

## 9. Current disposition

```text
BIO_012 = NARROW
FOREIGN_PATIENT_CONCIERGE_OS = KILL_GENERIC
SURVIVING_WEDGE = BILINGUAL_VISIT_PASSPORT / CLINICAL_INTERPRETATION_SAFETY_LEDGER
NEXT_GATE = SYNTHETIC_CRITICAL_SLOT_TRANSLATION_BENCHMARK
BUSINESS_NUMBER = HOLD
```
