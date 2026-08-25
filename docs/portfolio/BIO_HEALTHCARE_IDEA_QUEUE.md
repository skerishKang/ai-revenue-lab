# Bio / Healthcare AI R&D Idea Queue

- Updated: 2026-08-26
- Parent ledger: `docs/portfolio/IDEA_LEDGER.md`
- Support-program radar: `docs/portfolio/research/BIO_SUPPORT_PROGRAM_RADAR_THROUGH_2026-09.md`
- Business-number authority: `docs/portfolio/BUSINESS_REGISTRY.md`

## Operating principle

```text
owner-originated problems / existing prototypes
+ PADIEM reusable technology
+ current government / hospital / industry signals
→ internal duplicate check
→ current market / regulatory screen
→ smallest truthful validation
→ GO / NARROW / PAUSE / KILL / DUPLICATE / ABSORB
```

Support programmes are demand signals, not reasons to manufacture products.

## Current priority queue

### P1 — BIO-003 My Health Story — `DEMO → VALIDATION`

Patient/guardian-facing source-grounded episodic visit memory. Existing ASTERIVE prototype; Issue #772 and Draft PR #774 implement the synthetic summary-vs-timeline-vs-story gate.

### P2 — BIO-016 AI Change Impact & Revalidation Compiler — `VALIDATING`

This is currently the strongest support-program-derived standalone product hypothesis.

The broad `Medical AI Lifecycle Evidence Passport` was narrowed after current MFDS/FDA/IMDRF and competitor research.

Surviving question:

> Given an exact medical-AI/software change and a versioned evidence inventory, can the system identify potentially stale evidence and candidate revalidation/document work, explain why with source-linked rationale, and hand the final decision to qualified RA/QA?

Internal boundary:

- reuse B48 for generic exact-version verification;
- reuse B63 where privacy/egress applies;
- do not build a generic QMS or regulatory document repository.

Current execution:

- Issue #782 — validation contract;
- Draft PR #783 — `research/bio-016/**` only;
- fictional `MedDelta-SYNTH` product/evidence baseline;
- 20 controlled change events;
- deterministic compiler/scorer/tests;
- official public guidance source manifest;
- implementation-level self-check 7/7 assertions PASS;
- exact-head pytest and qualified Korean RA/QA review remain pending.

Hard boundary: no `APPROVED`, `EXEMPT`, `NO_SUBMISSION_REQUIRED`, or autonomous regulatory conclusion.

### P3 — BIO-015 Korean HIS Agent Site Acceptance & Replay — `ABSORB / PARTNER-DEPENDENT RESEARCH PROFILE`

Generic `Clinical AI Agent Sandbox` is **not** a strong new standalone thesis. Current research/products already cover medical-agent sandboxes, FHIR workflow simulators and pre-release healthcare AI gates.

Surviving PADIEM-specific role:

```text
site-specific synthetic/de-identified HIS workflow
→ agent proposal in shadow mode
→ expected human/policy comparison
→ data/tool authorization + reversibility
→ source/evidence + B63 egress checks
→ human override/escalation
→ replayable site acceptance evidence
```

Build from B42 + B48 + B63 rather than assign another Business number. Serious build waits for a hospital/HIS/AI Native HIS partner.

BIO-018 Clinical AI Incident Replay is absorbed here as a replay/forensics function.

### P4 — BIO-017 Closed-Loop Decision Provenance Verifier — `PARTNER-LED R&D / NARROW`

Generic ELN/LIMS/SDMS/data-lineage platform is killed as a new thesis because Benchling, TetraScience, Dotmatics and others already occupy the space.

Surviving autonomous-lab R&D question:

```text
AI next-experiment proposal
→ rationale / constraints
→ approved protocol
→ sample / batch
→ instrument command
→ actual execution log
→ raw-data fingerprint
→ analysis code/model version
→ result/evidence
→ next recommendation
→ human override
```

Validate broken-chain detection synthetically if useful, but real product evidence requires a university/biotech/lab-automation partner. High consortium/R&D fit; low justification for standalone build without partner.

### P5 — BIO-012A Bilingual Visit Passport — `DOMAIN-TRANSFER / ABSORB`

Reuse B39 `112 Real-Time Interpretation` and existing dissertation/HITL evaluation. Do not build another translation engine. Medical-domain checks can extend to body side/site, symptom duration/frequency, medication/allergy/dose strings and follow-up. Absorb into BIO-003/B39/B63/PLAT-001 if useful.

### P6 — BIO-014A Recovery Story + PLAT-001 Event Story Engine — `PLATFORM SCREENING`

Generic camera rehab coach was killed. Preserve the between-visits continuity question: what was attempted, what changed, what was uncertain, and what should be discussed next. No autonomous rehab prescription.

### P7 — BIO-019 Health Data Product Validation Workbench — `LOWER-PRIORITY SCREEN`

HIRA data-commercialization signal is real, but overlap with analytics/data-lab tooling is high. Keep low priority until a concrete partner workflow gap appears.

## Existing / paused

- BIO-002 / proposed B63 Clinical AI Egress Control Plane — concept demo complete; hospital/HIS validation pending.

## Screened / absorbed / deprioritized

- BIO-001 NIR / vein finder — historical, deprioritized.
- BIO-004 Patient Communication AI — likely module.
- BIO-005 Health-check Trend AI — likely longitudinal module.
- BIO-006 Ambient Scribe — crowded.
- BIO-007 generic Rehab/Pose — B38 overlap.
- BIO-008 AI Drug Discovery — broad/domain-capital intensive.
- BIO-009 Radiology Diagnosis AI — crowded/high-regulatory.
- BIO-010 Genomics AI — specialist-data gap.
- BIO-011 Medical Record Intelligence Workspace — likely ASTERIVE/My Health Story overlap.
- BIO-012 generic Foreign Patient platform/translator — killed/absorbed into B39-based domain transfer.
- BIO-013 Bio Evidence Graph — superseded by narrower BIO-017 decision-provenance question.
- BIO-014 generic Home Rehab Observer Coach — killed as standalone.
- BIO-018 Clinical AI Incident Replay — absorbed into BIO-015 profile.
- BIO-020 Medical AI Export/Regulatory Readiness Passport — verticalize BIO-016 + GEN-001 if warranted.

## September operating rule

Through 2026-09-30 maintain:

```text
APPLY / PARTNER NOW
= actual eligibility, deadline, consortium, matching-fund and partner checks

IDEA SIGNAL
= open/closed RFPs used to infer what hospitals, regulators and bio labs are preparing to buy or validate
```

Monitor 기업마당, K-Startup, IRIS, KHIDI/HIRA and Gwangju/regional programmes. Closed calls remain useful as problem-definition evidence.

## Next-candidate rule

When the owner says `다음` or `계속`:

1. continue the highest-priority unfinished validation;
2. update support-program radar with materially new September signals;
3. search internal GitHub/Drive history before creating a new idea;
4. screen current competition/regulation/partner reality;
5. persist `GO / NARROW / PAUSE / KILL / DUPLICATE / ABSORB` before moving on.
