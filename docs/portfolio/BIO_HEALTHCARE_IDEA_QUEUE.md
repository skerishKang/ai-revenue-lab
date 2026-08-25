# Bio / Healthcare AI R&D Idea Queue

- Updated: 2026-08-26
- Parent ledger: `docs/portfolio/IDEA_LEDGER.md`
- Support-program radar: `docs/portfolio/research/BIO_SUPPORT_PROGRAM_RADAR_THROUGH_2026-09.md`
- Recovery note: `docs/portfolio/research/BIO_HEALTHCARE_IDEA_RECOVERY_AND_PRIORITY_2026-08-26.md`
- Business-number authority: `docs/portfolio/BUSINESS_REGISTRY.md`

## Operating principle

This track uses three evidence sources together:

```text
owner-originated problems / existing prototypes
+ PADIEM reusable technology
+ current government / hospital / industry programme signals
→ duplicate / market / regulatory screen
→ smallest truthful validation
→ GO / NARROW / PAUSE / KILL / ABSORB
```

A support programme is a demand signal, not a reason to distort a product.

## Current priority queue

### P1 — BIO-003 My Health Story / 병원 스토리북 — `DEMO → VALIDATION`

A real ASTERIVE sample-only prototype already exists.

Narrowed product promise:

> Reconstruct each hospital visit as a source-grounded episodic memory so a patient/guardian can distinguish what they said, what the clinician/document said, what AI only organized, what they personally noted, and what must happen next.

Current execution:

- Issue #772 — validation contract;
- Draft PR #774 — synthetic summary-vs-timeline-vs-story validation pack.

No real PHI, diagnosis or treatment recommendation in the first gate.

### P2 — BIO-015 Clinical AI Shadow Lab / AI Native HIS Agent Sandbox — `RESEARCHING`

2026 signal:

- KHIDI posted `AI 지능형 병원정보시스템(AI Native HIS) 기획(1차)` on 2026-08-21;
- IRIS has active AI-application rapid-commercialization support through early September.

Hypothesis:

> Before an AI agent is allowed to act in a real hospital/HIS workflow, replay synthetic/de-identified workflows in shadow mode and audit proposed actions, data access, tool calls, evidence, policy violations and human overrides.

Potential chain:

```text
synthetic/de-identified HIS events
→ AI agent proposal
→ no real action
→ expected human/policy comparison
→ tool/data-access trace
→ unsafe/missing-evidence flags
→ human override
→ replayable acceptance / incident evidence
```

Internal reuse candidates:

- B42 AI Development Control Tower;
- B48 Verification Engine;
- B49/B50 connector concepts;
- B63 clinical egress controls;
- PLAT-001 Event Story Engine.

Next gate: competitor/internal-overlap scan, then synthetic demo only if a distinct hospital workflow wedge survives.

### P3 — BIO-016 Medical AI Lifecycle Evidence Passport — `RESEARCHING`

2026 signal:

- smart-electronic-drug commercialization support explicitly covers medical AI, cybersecurity and software validation;
- K-Biohealth programmes repeatedly support testing, certification and regulatory readiness.

Hypothesis:

> Track every model/prompt/provider/software change and automatically show what must be revalidated, which evidence exists, what cybersecurity/software-validation gaps remain and who approved the release.

```text
AI/software change
→ impact classification
→ required validation
→ evidence ingestion
→ completeness / unresolved risk
→ human approval
→ regulator / partner handoff package
```

Do not become a generic QMS/RA document manager. The wedge must be **AI-change-aware lifecycle evidence**.

BIO-020 Medical AI Export/Regulatory Readiness Passport is a possible vertical/output of this lane, not a separate Business yet.

### P4 — BIO-017 Autonomous Bio Lab Evidence Chain Guard — `SCREENING`

2026 signal:

- MSIT/NRF ran the `AI-네이티브 첨단바이오 자율실험실` new-project programme;
- IRIS Bio/Medical Technology Development includes an `인공지능바이오` area.

Hypothesis:

> Independently verify that an AI-driven experimental loop remains traceable from hypothesis and approved protocol through instrument execution, sample/batch identity, raw data, analysis and the next experiment recommendation.

```text
AI experiment proposal
→ approved protocol version
→ instrument command/log
→ sample/batch identity
→ raw-data fingerprint
→ analysis code/model
→ result/evidence
→ next experiment proposal
→ human override/approval
```

Technical demo can be synthetic; meaningful validation needs a lab / biotech / automation partner.

### P5 — BIO-012A Bilingual Visit Passport — `DOMAIN-TRANSFER / ABSORB`

Do not build a new medical translation engine.

Reuse:

- proposed B39 `112 Real-Time Interpretation`;
- existing 112 dissertation/HITL evaluation assets;
- BIO-003 source-grounded visit memory.

Medical-domain checks may extend B39 with body side/site, symptom duration/frequency, medication/allergy/dose strings and follow-up instructions.

If useful, absorb into BIO-003/B39/B63/PLAT-001.

### P6 — BIO-014A Recovery Story + PLAT-001 Event Story Engine — `PLATFORM SCREENING`

Generic camera rehab coaching was screened out because of B38 overlap and mature digital-PT competition.

Surviving question:

> Can the time between clinical visits be reconstructed well enough that patient and clinician know what was attempted, what changed, what was uncertain and what must be discussed next?

This is a continuity/story layer, not autonomous rehabilitation prescription.

### P7 — BIO-019 Health Data Product Validation Workbench — `LOWER-PRIORITY SCREEN`

2026 signal:

- HIRA Health/Medical Big Data Startup Incubating Lab runs through 2026-12-31.

Hypothesis:

> Convert a digital-health product hypothesis into a reproducible cohort/pathway/data-feasibility plan for approved/public health-data environments.

High overlap risk with existing analytics/data-lab tools. Keep low priority unless a concrete HIRA/partner workflow gap appears.

## Existing / paused

### BIO-002 / proposed B63 Clinical AI Egress Control Plane — `PAUSED`

Concept demo complete. Next evidence requires real hospital/HIS validation.

## Screened / absorbed / deprioritized

- `BIO-001 NIR / vein finder` — historical, deprioritized.
- `BIO-004 Patient Communication AI` — likely module of My Health Story / bilingual workflow.
- `BIO-005 Health-check Trend AI` — likely longitudinal module.
- `BIO-006 Ambient Scribe` — crowded / deprioritized.
- `BIO-007 generic Rehab/Pose` — B38 overlap / absorb only where useful.
- `BIO-008 AI Drug Discovery` — broad/domain-capital intensive.
- `BIO-009 Radiology Diagnosis AI` — crowded/high-regulatory.
- `BIO-010 Genomics AI` — specialist-data gap.
- `BIO-011 Medical Record Intelligence Workspace` — likely overlaps ASTERIVE/My Health Story.
- `BIO-012 generic Foreign Patient platform/translator` — generic thesis killed; B39 reuse.
- `BIO-013 Bio Evidence Graph` — superseded for now by narrower autonomous-lab evidence-chain hypothesis.
- `BIO-014 generic Home Rehab Observer Coach` — generic standalone killed.
- `BIO-018 Clinical AI Incident Replay` — likely BIO-015 module.
- `BIO-020 Medical AI Export/Regulatory Readiness Passport` — screen as BIO-016 + GEN-001 vertical.

## September support-program operating rule

Through 2026-09-30 maintain two views:

### APPLY / PARTNER NOW

Check actual eligibility, region, age/stage, consortium requirements, deadlines and required matching funds before any application decision.

### IDEA SIGNAL

Keep even closed calls when they reveal precise public/industry demand such as:

```text
AI Native HIS
medical AI software validation / cybersecurity
clinical real-world validation
health-data commercialization
autonomous bio labs / self-driving labs
bio testing / certification / export
AI application rapid commercialization
```

## Screening dimensions

Every standalone candidate must be checked on:

1. current market / prior art;
2. internal portfolio overlap;
3. PADIEM-specific wedge;
4. reusable asset fit;
5. data accessibility;
6. regulatory/safety boundary;
7. buyer / R&D partner;
8. government R&D / demonstration fit;
9. truthful synthetic/public first validation.

## Next-candidate rule

When the owner says `다음`:

1. continue the highest-priority unfinished candidate;
2. read this queue + support-program radar first;
3. search GitHub/Drive/prior sessions before creating a new idea;
4. research current market and programme signals;
5. record `GO / NARROW / PAUSE / KILL / DUPLICATE / ABSORB` before moving to the next candidate.
