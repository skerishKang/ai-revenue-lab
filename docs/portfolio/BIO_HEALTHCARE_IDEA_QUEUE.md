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

Support programmes are demand signals, not reasons to manufacture products. A candidate does not receive a Business number merely because a synthetic benchmark works.

# Current priority queue

## P1 — BIO-003 My Health Story — `READY_FOR_BOUNDED_PARTICIPANT_PILOT`

Patient/guardian-facing source-grounded episodic visit memory.

Execution:

- Issue #772;
- Draft PR #774;
- scope `research/bio-003/**`;
- ASTERIVE product prototype already exists;
- 3 fully synthetic visit cases;
- summary vs timeline vs source-grounded story comparison.

A manual audit found a real experimental confound: the original Case B timeline omitted facts present in summary/story. That defect is now closed rather than hidden.

Current parity contract:

```text
3 cases
× 8 canonical facts
× summary / timeline / story
→ every fact physically present in every condition
→ 18 questions mapped to minimum fact dependencies
```

Independent mechanics after repair:

```text
TOTAL_CANONICAL_FACTS = 24
QUESTION_FACT_MAP_ENTRIES = 18
ALL_CONDITION_FACT_ANCHORS_PRESENT = YES
ALL_QUESTION_FACT_DEPENDENCIES_PRESENT = YES
SCORER_PRIMITIVES = PASS
COUNTERBALANCING = PASS
DELAYED_RECALL_SET = 9 BALANCED ITEMS
```

`PILOT_PROTOCOL_v0.1.md` defines the next gate:

```text
suggested N = 12
G1/G2/G3 = 4 each
immediate objective recall
10–15 minute neutral filler
delayed source/follow-up/retrieval recall
```

Primary evidence:

- source-attribution accuracy;
- follow-up memory;
- false recall as hard counter-signal.

Preference alone cannot justify GO.

**Current blocker:** real participants. Internal fixture preparation is sufficiently closed for the bounded pilot.

## P2 — BIO-016 AI Change Impact & Revalidation Compiler — `READY_FOR_QUALIFIED_RA_QA_REVIEW`

Strongest current support-program-derived standalone B2B hypothesis.

Surviving question:

> Given an exact medical-AI/software change and a versioned evidence inventory, can the system identify potentially stale evidence and candidate revalidation/document work with source-linked rationale, while leaving final interpretation to qualified RA/QA?

Execution:

- Issue #782;
- Draft PR #783;
- scope `research/bio-016/**`;
- fictional `MedDelta-SYNTH` baseline;
- 20 controlled change events;
- exact evidence record/version/scope assessment;
- research oracle includes exact stale evidence IDs but is explicitly **not regulatory truth**.

Compiler relationship vocabulary:

```text
STALE_OR_SCOPE_MISMATCH
COVERED_BY_CURRENT_SCOPE
CLASS_IMPACT_ONLY_REVIEW
RA_QA_DECISION_REQUIRED
```

Independent synthetic mechanics match the 20-case research oracle. Exact-head GitHub Actions are not configured, so do not call this CI GREEN.

Human review preparation is now complete:

- `RA_QA_REVIEW_PACKET_v0.1.md`;
- `RA_QA_REVIEW_KEY_RESEARCH_ONLY.md`;
- `ra_qa_review_template.csv`.

First blinded expert set:

```text
C01 model update
C05 intended-use expansion
C06 LLM provider/model swap
C09 cybersecurity patch
C20 document typo only
```

Stage 1 = expert assesses without system output.  
Stage 2 = reveal system suggestions and capture `ACCEPT / REJECT / NEEDS_MORE_CONTEXT`, omissions, unnecessary reopen noise, time and usefulness.

**Current blocker:** qualified Korean medical-device RA/QA practitioner. More synthetic rules are not the priority.

Post-market RWE/drift (BIO-021) remains absorbed here as a trigger into change/revalidation analysis.

Hard boundary: no autonomous `APPROVED`, `EXEMPT`, `NO_SUBMISSION_REQUIRED`, `MFDS_ACCEPTED`, or compliance conclusion.

## P3 — BIO-022 Health Model Egress Privacy Auditor — `READY_FOR_WORKFLOW_BUYER_DISCOVERY`

Issue #790 / Draft PR #792. Scope `research/bio-022/**`.

Problem boundary:

```text
controlled health source data stays inside
→ trained model / algorithm / artifact may be proposed for export
→ artifact itself may expose training-record information
→ reviewer needs reproducible privacy-risk evidence
→ HUMAN_EXPORT_REVIEW_REQUIRED
```

The wedge is **not** a new membership-inference attack. Generic privacy-attack tooling already exists. The candidate survives only if model/artifact release from controlled health-data environments is a distinct repeated governance/evidence workflow.

### v0.1 defect found and closed

The first benchmark compared a 300-record RandomForest with a 1,400-record LogisticRegression, so model family and training size confounded the observed membership signal.

v0.2 now uses:

```text
same 600 training records
same RandomForest family
same n_estimators / random state
capacity / regularization only differs
```

It also separates:

```text
exchangeable all-nonmember null control
vs
all-nonmember covariate-shift false-positive control
```

and exposes record-level score distributions, bootstrap uncertainty and low-FPR attack behavior.

Local v0.2 mechanics:

```text
overfit membership ROC-AUC      ≈ 0.8822
regularized membership ROC-AUC ≈ 0.5886
exchangeable null ROC-AUC      ≈ 0.4552
covariate-shift control AUC    ≈ 0.6537
local pytest                    = 8 passed
```

These are fixture behaviors, not privacy-safety thresholds. Exact-head GitHub Actions remain unconfigured.

Buyer/workflow discovery is now prepared:

- `BUYER_WORKFLOW_INTERVIEW_PACKET_v0.1.md`;
- `buyer_workflow_interview_template.csv`;
- HIRA/KHIDI workflow signals added to `source_manifest.json`.

Target cohorts:

1. controlled-data environment operator / export reviewer;
2. medical-AI company model developer/privacy-security lead;
3. medical-data-centered hospital/data collaboration team;
4. privacy/security assessor as technical reality check.

Standalone promotion minimum:

```text
3+ independent organizations
2+ operator/applicant perspectives
1+ repeated model/artifact release workflow confirmed
1+ plausible budget owner confirmed
clear current-process pain
clear reason generic privacy tooling is insufficient
```

**Current blocker:** external workflow/buyer evidence. If the workflow is not distinct, resolve to B63 model-artifact egress profile, B48 security-verification profile, or KILL.

## P4 — BIO-015 Korean HIS Agent Site Acceptance & Replay — `ABSORB / PARTNER_DEPENDENT`

Generic medical-agent sandbox is killed as a standalone thesis. Preserve only site-specific synthetic/de-identified HIS acceptance/replay as a healthcare verification profile using B42+B48+B63. BIO-018 incident replay is absorbed here.

**Blocker:** hospital/HIS/AI Native HIS partner.

## P5 — BIO-017 Closed-Loop Decision Provenance Verifier — `PARTNER_LED_R&D / NARROW`

Generic ELN/LIMS/SDMS/data-lineage product is killed. Preserve only:

```text
AI next-experiment proposal
→ rationale / constraints
→ approved protocol
→ sample / batch
→ instrument command / actual execution
→ raw-data fingerprint
→ analysis code/model version
→ result
→ next recommendation
→ human override
```

**Blocker:** university/biotech/lab-automation partner. Strong consortium/R&D fit; weak standalone justification without real lab evidence.

## P6 — BIO-012A Bilingual Visit Passport — `ABSORB / DOMAIN_TRANSFER`

Reuse B39 112 real-time interpretation and existing HITL evaluation. Do not build another translation engine. Medical critical-slot checks may feed BIO-003/B39/B63/PLAT-001.

## P7 — BIO-014A Recovery Story + PLAT-001 Event Story Engine — `PLATFORM_SCREENING`

Generic camera rehab coach is killed. Preserve the between-visits continuity problem: attempts, changes, uncertainty and questions for next visit. No autonomous rehabilitation prescription.

## P8 — BIO-019 Health Data Product Validation Workbench — `LOWER_PRIORITY_SCREEN`

HIRA data-commercialization signal is real, but analytics/data-lab overlap remains high. Keep until a concrete workflow gap appears.

# Existing / paused

- BIO-002 / proposed B63 Clinical AI Egress Control Plane — concept demo complete; hospital/HIS validation pending.

# Screened / absorbed / deprioritized

- BIO-001 NIR / vein finder — historical; deprioritized.
- BIO-004 Patient Communication AI — likely BIO-003/discharge/bilingual module.
- BIO-005 Health-check Trend AI — likely longitudinal BIO-003/CareGraph module.
- BIO-006 Ambient Scribe — crowded.
- BIO-007 generic Rehab/Pose — B38 overlap.
- BIO-008 AI Drug Discovery — broad/domain-capital intensive.
- BIO-009 Radiology Diagnosis AI — crowded/high-regulatory.
- BIO-010 Genomics AI — specialist-data gap.
- BIO-011 Medical Record Intelligence Workspace — likely ASTERIVE/BIO-003 overlap.
- BIO-012 generic Foreign Patient platform/translator — killed/absorbed into B39 transfer.
- BIO-013 Bio Evidence Graph — superseded by BIO-017.
- BIO-014 generic Home Rehab Observer Coach — killed.
- BIO-018 Clinical AI Incident Replay — absorbed into BIO-015.
- BIO-020 Medical AI Export/Regulatory Readiness Passport — verticalize BIO-016 + GEN-001 if warranted.
- BIO-021 Clinical AI Post-Market Evidence & Drift Trace — absorbed into BIO-016.
- BIO-023 Bio Manufacturing Deviation/CAPA Copilot — generic category crowded; KILL standalone, possible B48 partner profile only.

# Top-three external evidence gates

```text
BIO-003
→ 12-person synthetic product/UX pilot

BIO-016
→ qualified Korean medical-device RA/QA review

BIO-022
→ 3+ organization model-export workflow/buyer discovery
```

This is the current handoff. When these gates are pending, continue September support-program discovery and new-candidate screening rather than inventing more internal evidence to simulate external validation.

# September operating rule

Through 2026-09-30 maintain:

```text
APPLY / PARTNER NOW
= actual eligibility, deadline, consortium, matching-fund and partner checks

IDEA SIGNAL
= open/closed RFPs used to infer what hospitals, regulators, data centers and bio labs are preparing to buy or validate
```

Monitor 기업마당, K-Startup, IRIS, KHIDI/HIRA and Gwangju/regional programmes.

# Next-candidate rule

When the owner says `다음` or `계속`:

1. check whether any top-three external evidence has arrived;
2. if not, update the September support-program radar;
3. recover internal GitHub/Drive history before generating a new candidate;
4. screen current competition/regulation/partner reality;
5. persist `GO / NARROW / PAUSE / KILL / DUPLICATE / ABSORB` before moving on.
