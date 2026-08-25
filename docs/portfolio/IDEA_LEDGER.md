# AI Revenue Lab Idea Ledger

- Status: persistent idea-preservation ledger
- Updated: 2026-08-26
- Authority: idea capture only; does not assign a canonical Business number
- Canonical numbering authority: `docs/portfolio/BUSINESS_REGISTRY.md`
- Related legacy backlog: `docs/portfolio/BUSINESS_CANDIDATE_BACKLOG.md`

## Purpose

This ledger prevents ideas, negative findings, absorptions and validation states from being rediscovered from scratch in later sessions.

## Status vocabulary

- `IDEA` — captured but not screened.
- `SCREENING` — duplicate/portfolio/feasibility screen in progress.
- `RESEARCHING` — market, technical, FTO, grant or buyer research in progress.
- `VALIDATING` — bounded synthetic/public/human evidence gate is active.
- `DEMO` — bounded prototype exists.
- `PAUSED` — worth preserving but blocked by evidence, partner, data or timing.
- `DUPLICATE` — materially overlaps existing work.
- `ABSORB` — useful capability but not a standalone Business.
- `DEPRIORITIZED` — plausible/historical but not current priority.
- `KILL` — researched and rejected as a standalone thesis.
- `PROMOTED` — entered a proposed/numbered Business workflow; canonical status still depends on Business Registry.

## Capture rule

```text
recover existing ideas/prototypes first
→ ledger entry
→ existing Business / GitHub / Drive / prior-session duplicate check
→ current market / regulation / support-program research
→ smallest truthful validation
→ GO | NARROW | PAUSE | KILL | DUPLICATE | ABSORB
→ only surviving standalone boundary can enter Business-number promotion
```

Do not delete negative or absorbed findings.

# Current Bio / Healthcare ledger

| ID | Idea / product title | Status | Current disposition |
|---|---|---|---|
| BIO-001 | NIR Vein Intelligence / 정맥주사 실습 보조 | DEPRIORITIZED | Historical 2015–2017 PADIEM asset only. Do not prioritize merely because it is owned history. |
| BIO-002 | Clinical AI Egress Control Plane | PROMOTED / PAUSED | Proposed B63. Concept demo complete; real hospital/HIS validation required. |
| BIO-003 | My Health Story / 병원 스토리북 | DEMO / VALIDATING | Issue #772 + Draft PR #774. Information-parity defect found and repaired. 24 canonical facts / 18 question dependencies mechanically pass. `PILOT_PROTOCOL_v0.1.md` ready. **Blocker = 12-person synthetic participant pilot.** |
| BIO-004 | Patient Communication AI | ABSORB-CANDIDATE | More likely BIO-003/discharge/bilingual capability than standalone product. |
| BIO-005 | Health-check Trend AI | ABSORB-CANDIDATE | Prefer longitudinal BIO-003/CareGraph module unless distinct buyer emerges. |
| BIO-006 | Ambient Medical AI / Scribe | DEPRIORITIZED | Crowded clinician-workflow category. |
| BIO-007 | Rehab / Pose AI | DEPRIORITIZED / ABSORB | Generic movement coaching overlaps B38 and mature digital-PT market. |
| BIO-008 | AI Drug Discovery | DEPRIORITIZED | Too broad/domain-capital intensive for current entry. |
| BIO-009 | Radiology Diagnosis AI | DEPRIORITIZED | Crowded/high-regulatory with weak PADIEM wedge. |
| BIO-010 | Genomics AI | DEPRIORITIZED | Specialized domain/data capability not established. |
| BIO-011 | Medical Record Intelligence Workspace | ABSORB-CANDIDATE | Likely ASTERIVE/BIO-003 overlap. |
| BIO-012 | Foreign Patient Medical Coordination | NARROW / ABSORB | Generic platform/translator killed; new translation engine duplicates B39. |
| BIO-012A | Bilingual Visit Passport | ABSORB / DOMAIN-TRANSFER | Reuse B39 + existing HITL research; medical critical-slot layer only. |
| BIO-013 | Bio Evidence Graph | SUPERSEDED | Broad evidence graph superseded by BIO-017 closed-loop decision provenance. |
| BIO-014 | Home Rehab Observer Coach | KILL GENERIC | Generic camera rehab coach overlaps B38 and mature market. |
| BIO-014A | Recovery Story | ABSORB INTO BIO-003 / PLAT-001 | Preserve between-visit attempts/changes/uncertainty/questions, not rehab prescription. |
| BIO-015 | Clinical AI Shadow Lab / AI Native HIS Agent Sandbox | KILL GENERIC / ABSORB | Generic sandbox occupied. Preserve Korean HIS Site Acceptance & Replay as B42+B48+B63 profile. **Blocker = hospital/HIS partner.** |
| BIO-016 | AI Change Impact & Revalidation Compiler | VALIDATING / NARROW | Issue #782 + Draft PR #783. Exact evidence/version/scope synthetic mechanics complete; blinded 5-case `RA_QA_REVIEW_PACKET_v0.1.md` ready. **Blocker = qualified Korean medical-device RA/QA review.** |
| BIO-017 | Closed-Loop Decision Provenance Verifier for Autonomous Bio Labs | PARTNER-LED R&D / NARROW | Generic ELN/LIMS/lineage killed. Preserve AI decision→protocol→instrument→raw data→analysis→next decision chain. **Blocker = university/biotech/lab-automation partner.** |
| BIO-018 | Clinical AI Incident Replay | ABSORB INTO BIO-015 | Replay/forensics is a BIO-015 profile function. |
| BIO-019 | Health Data Product Validation Workbench | LOWER-PRIORITY SCREEN | HIRA signal real; analytics/data-lab overlap high. |
| BIO-020 | Medical AI Export & Regulatory Readiness Passport | ABSORB / VERTICALIZE | BIO-016 + GEN-001 output/vertical, not separate product now. |
| BIO-021 | Clinical AI Post-Market Evidence & Drift Trace | ABSORB INTO BIO-016 | Generic RWE/drift monitoring occupied; preserve drift/RWE event → stale-evidence/revalidation trigger. |
| BIO-022 | Health Model Egress Privacy Auditor | VALIDATING / NARROW | Issue #790 + Draft PR #792. v0.1 confound found and repaired in v0.2. Paired 600-record/same-RF benchmark, exchangeable null + covariate-shift control, record-level score distribution, local 8-test mechanics. Buyer interview packet ready. **Blocker = 3+ organization model-export workflow/buyer discovery.** |
| BIO-023 | Bio Manufacturing Deviation / CAPA Copilot | KILL GENERIC / ABSORB PROFILE | AI deviation/CAPA category already crowded. Possible B48 partner profile only. |

# Cross-domain / general ideas retained

| ID | Idea | Status | Note |
|---|---|---|---|
| PLAT-001 | Event Story Engine / 사건·병원 여정 스토리 엔진 | SCREENING | Shared chronology/source/WHY-NEXT capability across BIO-003, Recovery Story, Bilingual Visit Passport and 사실로. |
| GEN-001 | AI Global Certification Passport | IDEA | General export/compliance candidate; medical-AI vertical belongs with BIO-016/BIO-020. |
| GEN-002 | Support Program AI Matching | DUPLICATE | Existing `400-ai-finder` / `cwtree`. |

# Current Bio priority and external evidence gates

```text
P1 BIO-003 My Health Story
   INTERNAL = parity/scoring/pilot protocol ready
   NEXT = 12-person synthetic participant pilot

P2 BIO-016 AI Change Impact & Revalidation Compiler
   INTERNAL = 20-case evidence-scope mechanics + blinded review packet ready
   NEXT = qualified Korean medical-device RA/QA review

P3 BIO-022 Health Model Egress Privacy Auditor
   INTERNAL = v0.2 paired privacy benchmark + buyer interview packet ready
   NEXT = 3+ organization workflow/buyer discovery

P4 BIO-015 Korean HIS Agent Site Acceptance & Replay
   NEXT = hospital/HIS partner

P5 BIO-017 Closed-Loop Decision Provenance
   NEXT = lab/automation consortium partner

P6 BIO-012A Bilingual Visit Passport
P7 BIO-014A Recovery Story + PLAT-001
P8 BIO-019 Health Data Product Validation Workbench
```

The top three have reached a meaningful internal-preparation closure point. Do not fabricate additional synthetic evidence to substitute for the external gates above.

# Read together

- `docs/portfolio/BIO_HEALTHCARE_IDEA_QUEUE.md`
- `docs/portfolio/research/BIO_SUPPORT_PROGRAM_RADAR_THROUGH_2026-09.md`
- BIO-003: Issue #772 / PR #774
- BIO-016: Issue #782 / PR #783
- BIO-022: Issue #790 / PR #792

# September support-program rule

Through 2026-09-30:

```text
APPLY / PARTNER NOW = actual eligibility + deadline/consortium check
IDEA SIGNAL = open/closed RFPs used to infer current public/industry demand
```

A grant-aligned idea is promoted only if it remains compelling without the grant.

# Business-number caution

No BIO-015~023 entry receives a Business number from this ledger. BIO-016 and BIO-022 remain number-free research candidates until relevant human/domain evidence supports a product decision.

# Session handoff rule

Every future BI/Bio R&D session must read this ledger, Bio queue, support-program radar and Business Registry before creating a fresh idea. If top-three external evidence has not arrived, continue September support-program discovery and screen new domains rather than repeatedly rebuilding the same internal benchmarks.
