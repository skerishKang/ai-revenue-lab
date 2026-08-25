# AI Revenue Lab Idea Ledger

- Status: persistent idea-preservation ledger
- Updated: 2026-08-26
- Authority: idea capture only; does not assign a canonical Business number
- Canonical numbering authority: `docs/portfolio/BUSINESS_REGISTRY.md`
- Related legacy backlog: `docs/portfolio/BUSINESS_CANDIDATE_BACKLOG.md`

## Purpose

This ledger exists so ideas are not re-invented every session and so rejected, paused, duplicate, absorbed, historical and promoted ideas remain reusable portfolio knowledge.

New ideas are captured before development. Existing prototypes and owner-originated ideas must be recovered before a new candidate is invented.

## Status vocabulary

- `IDEA` — captured but not screened.
- `SCREENING` — duplicate / portfolio overlap / feasibility screening in progress.
- `RESEARCHING` — market, technical, FTO, grant or buyer research in progress.
- `VALIDATING` — a bounded synthetic/public evidence gate is implemented or running.
- `DEMO` — bounded prototype or technical demo exists / is in progress.
- `PAUSED` — worth preserving but blocked by evidence, partner, data or timing.
- `DUPLICATE` — materially overlaps an existing product/project; preserve the record and do not re-propose it as new.
- `ABSORB` — useful capability, but should be reused inside an existing product/platform rather than promoted as a new Business.
- `DEPRIORITIZED` — plausible or historically real, but not a current exploration priority.
- `KILL` — researched and rejected; preserve the reason.
- `PROMOTED` — promoted into a numbered/proposed Business workflow; canonical status still depends on the Business Registry.

## Capture rule

```text
recover existing ideas/prototypes first
→ IDEA_LEDGER entry
→ existing Business / GitHub / Drive / prior-session duplicate check
→ current market / regulation / support-program research
→ smallest truthful validation
→ GO | NARROW | PAUSE | KILL | DUPLICATE | ABSORB
→ only surviving standalone product boundaries enter Business-number promotion
```

Do not delete negative or absorbed findings. They prevent repeated rediscovery and preserve decision history.

## Current Bio / Healthcare ledger

| ID | Idea / product title | Status | Current disposition |
|---|---|---|---|
| BIO-001 | NIR Vein Intelligence / 정맥주사 실습 보조 | DEPRIORITIZED | Historical 2015–2017 PADIEM asset only. Issue #769 and PR #770 closed unmerged after owner reprioritization. |
| BIO-002 | Clinical AI Egress Control Plane | PROMOTED / PAUSED | Proposed B63. Concept demo complete; real hospital/HIS validation still required. |
| BIO-003 | My Health Story / 병원 스토리북 | DEMO / VALIDATING | ASTERIVE prototype exists. Issue #772 + Draft PR #774 validate source-grounded story vs summary/timeline using synthetic cases. |
| BIO-004 | Patient Communication AI | SCREENING / ABSORB-CANDIDATE | More likely a My Health Story / discharge / bilingual-visit capability than a standalone product. |
| BIO-005 | Health-check Trend AI | SCREENING / ABSORB-CANDIDATE | Prefer as a longitudinal My Health Story/CareGraph module unless a distinct buyer/workflow emerges. |
| BIO-006 | Ambient Medical AI / Scribe | DEPRIORITIZED | Crowded clinician-workflow category; weak current PADIEM wedge. |
| BIO-007 | Rehab / Pose AI | DEPRIORITIZED / ABSORB | Generic movement coaching overlaps B38 and mature digital-PT products. |
| BIO-008 | AI Drug Discovery | DEPRIORITIZED | Too broad and domain-capital intensive for current entry. |
| BIO-009 | Radiology Diagnosis AI | DEPRIORITIZED | Crowded/high-regulatory; weak current differentiation. |
| BIO-010 | Genomics AI | DEPRIORITIZED | Specialized domain/data capability not established. |
| BIO-011 | Medical Record Intelligence Workspace | SCREENING / ABSORB-CANDIDATE | Likely overlaps ASTERIVE/My Health Story; standalone boundary must be proven. |
| BIO-012 | Foreign Patient Medical Coordination | NARROW / ABSORB | Generic platform/translator killed; new translation engine duplicates B39. |
| BIO-012A | Bilingual Visit Passport / 의료통역 안전기록 | ABSORB / DOMAIN-TRANSFER R&D | Reuse B39 112 interpretation + existing dissertation/HITL evaluation; add medical-specific critical slots and connect to BIO-003. |
| BIO-013 | Bio Evidence Graph | DEPRIORITIZED / SUPERSEDED | Broad evidence-graph idea is superseded by the narrower autonomous-lab decision-provenance question in BIO-017. |
| BIO-014 | Home Rehab Observer Coach | KILL GENERIC / DEPRIORITIZED | Generic camera rehab coach is crowded and overlaps B38. Do not build standalone. |
| BIO-014A | Recovery Story / Between-Visits Recovery Layer | ABSORB INTO BIO-003 / PLAT-001 | Preserve between-visit attempts, changes, uncertainty and questions without autonomous rehab prescription. |
| BIO-015 | Clinical AI Shadow Lab / AI Native HIS Agent Sandbox | KILL GENERIC / ABSORB | Generic medical-agent sandbox is already occupied by current research/products. Surviving `Korean HIS Agent Site Acceptance & Replay` should be a healthcare verification profile using B42+B48+B63, not a new Business now. |
| BIO-016 | AI Change Impact & Revalidation Compiler / MFDS AI Change Delta | VALIDATING / NARROW | Strongest current support-program-derived standalone hypothesis. Given an exact medical-AI change, identify potentially stale evidence and candidate revalidation/document work with source-linked rationale and mandatory RA/QA review. Issue #782 + Draft PR #783 implement a 20-change synthetic benchmark. |
| BIO-017 | Closed-Loop Decision Provenance Verifier for Autonomous Bio Labs | PARTNER-LED R&D / NARROW | Generic ELN/LIMS/lineage platform killed. Surviving question verifies the AI decision → protocol → instrument execution → raw data → analysis → next-decision chain. Needs real lab/automation partner before serious product build. |
| BIO-018 | Clinical AI Incident Replay / Near-Miss Story | ABSORB INTO BIO-015 | Replay/forensics is a function of the healthcare agent acceptance profile, not a separate Business. |
| BIO-019 | Health Data Product Validation Workbench | LOWER-PRIORITY SCREEN | HIRA data-commercialization signal is real, but analytics/data-lab overlap risk remains high. |
| BIO-020 | Medical AI Export & Regulatory Readiness Passport | ABSORB / VERTICALIZE | Treat as BIO-016 + GEN-001 output/vertical, not a separate Business. |

## Cross-domain / general ideas retained

| ID | Idea | Status | Note |
|---|---|---|---|
| PLAT-001 | Event Story Engine / 사건·병원 여정 스토리 엔진 | SCREENING | Shared chronology/source/WHY-NEXT capability across My Health Story, Recovery Story, Bilingual Visit Passport and 사실로. |
| GEN-001 | AI Global Certification Passport | IDEA | General export/compliance candidate. Medical-AI vertical should be screened through BIO-016/BIO-020, not duplicated. |
| GEN-002 | Support Program AI Matching | DUPLICATE | Existing `400-ai-finder` / `cwtree` work. Do not repropose as a new Business. |

## Current Bio / Healthcare priority

Read together:

- `docs/portfolio/BIO_HEALTHCARE_IDEA_QUEUE.md`
- `docs/portfolio/research/BIO_SUPPORT_PROGRAM_RADAR_THROUGH_2026-09.md`
- `docs/portfolio/research/BIO_015_CLINICAL_AI_AGENT_SANDBOX_SCREEN_2026-08-26.md`
- `docs/portfolio/research/BIO_016_MEDICAL_AI_CHANGE_REVALIDATION_SCREEN_2026-08-26.md`
- `docs/portfolio/research/BIO_017_AUTONOMOUS_BIO_LAB_EVIDENCE_SCREEN_2026-08-26.md`

```text
P1 = BIO-003 My Health Story — patient-facing validation already underway
P2 = BIO-016 AI Change Impact & Revalidation Compiler — strongest new standalone validation candidate
P3 = BIO-015 Korean HIS Agent Site Acceptance & Replay — absorbed healthcare verification profile; partner-dependent
P4 = BIO-017 Closed-Loop Decision Provenance Verifier — partner-led autonomous-lab R&D
P5 = BIO-012A Bilingual Visit Passport — B39 domain transfer / absorb
P6 = BIO-014A Recovery Story + PLAT-001 Event Story Engine
P7 = BIO-019 Health Data Product Validation Workbench — low-priority screen
```

## September support-program rule

Through 2026-09-30, use support programmes in two ways:

```text
APPLY / PARTNER NOW = actual eligibility + deadline/consortium check
IDEA SIGNAL = open or closed RFPs used to infer current public/industry demand
```

A grant-aligned idea is promoted only if the product remains compelling without the grant.

## Business-number caution

No BIO-015~020 entry receives a Business number from this ledger. BIO-016 remains a numbered-free research candidate until synthetic validation plus qualified Korean medical-device RA/QA review support a product decision.

## Session handoff rule

Every future BI / Bio R&D session must read this ledger, the Bio/Healthcare queue, support-program radar and canonical Business Registry before generating a fresh idea. Record new status, duplicate/absorption finding, prototype evidence, support-program signal or rejection reason before moving to another candidate.
