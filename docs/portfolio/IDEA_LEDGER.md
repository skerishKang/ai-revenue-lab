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
- `DEMO` — bounded prototype or technical demo exists / is in progress.
- `PAUSED` — worth preserving but blocked by evidence, partner, data or timing.
- `LEGACY_ASSET_REVALIDATION` — based on a real prior PADIEM technology/IP asset that needs current validation.
- `DUPLICATE` — materially overlaps an existing product/project; preserve the record and do not re-propose it as new.
- `DEPRIORITIZED` — plausible or historically real, but not a current exploration priority.
- `KILL` — researched and rejected; preserve the reason.
- `PROMOTED` — promoted into a numbered/proposed Business workflow; canonical status still depends on the Business Registry.

## Capture rule

```text
recover existing ideas/prototypes first
→ IDEA_LEDGER entry
→ existing Business / GitHub / Drive / prior-session duplicate check
→ research / prototype as warranted
→ GO | NARROW | PAUSE | KILL | DUPLICATE | ABSORB
→ only surviving standalone product boundaries enter Business-number promotion
```

Do not delete `KILL`, `DUPLICATE`, `PAUSED`, or `DEPRIORITIZED` entries. They prevent repeated rediscovery and preserve decision history.

## Current idea ledger

| ID | Domain | Idea / product title | Status | One-line product promise | Relationship / note |
|---|---|---|---|---|---|
| BIO-001 | Historical Bio / medical device | NIR Vein Intelligence / 정맥주사 실습 보조 | DEPRIORITIZED | Preserve PADIEM's 2015–2017 NIR/vein-assistance technical lineage for future reuse only if new evidence materially changes the opportunity. | Owner priority reset 2026-08-26: roughly decade-old idea; Issue #769 and PR #770 closed unmerged. Do not make this the center of current Bio discovery. |
| BIO-002 | Healthcare AI governance | Clinical AI Egress Control Plane | PROMOTED / PAUSED | Govern what Korean clinical data may leave hospital workflows for external/internal GenAI while preserving clinical utility and audit evidence. | Proposed as B63 in Issue #731; concept demo completed; hospital/HIS validation still required. |
| BIO-003 | Patient experience / longitudinal health | My Health Story / 병원 스토리북 | DEMO / VALIDATING | Turn one hospital visit into a source-grounded story: why I went, what I said, what the doctor said, tests, medication, what to remember and what happens next. | ASTERIVE sample-only prototype and QA evidence exist. Issue #772 + Draft PR #774 define the summary-vs-timeline-vs-story validation pack. |
| BIO-004 | Patient communication | Patient Communication AI | SCREENING | Translate complex clinical information into patient-appropriate language/channel while preserving exact source boundaries. | Likely module inside My Health Story, discharge/follow-up or foreign-patient workflows unless a distinct buyer/product boundary is proven. |
| BIO-005 | Preventive / longitudinal health | Health-check Trend AI | SCREENING | Track repeated checkup/test results and explain what changed over time with source-linked context. | Likely longitudinal module of My Health Story/CareGraph first; do not create a new Business by default. |
| BIO-006 | Clinical workflow | Ambient Medical AI / Scribe | DEPRIORITIZED | Capture and structure clinician-patient encounters into reviewable documentation. | Crowded category and weak first-fit relative to current PADIEM differentiation. |
| BIO-007 | Rehab / movement | Rehab / Pose AI | DEPRIORITIZED / ABSORB | Preserve movement-analysis capability only where it supports a differentiated patient-recovery workflow. | Generic camera pose/exercise coaching overlaps B38 and mature digital-PT products. Do not create standalone rehab coach from generic pose tracking. |
| BIO-008 | Biotech | AI Drug Discovery | DEPRIORITIZED | Apply AI to candidate discovery / ranking in drug R&D. | Too broad and domain-capital intensive for current first entry. |
| BIO-009 | Medical imaging | Radiology Diagnosis AI | DEPRIORITIZED | Apply multimodal AI to radiology image interpretation or diagnostic support. | Crowded and high-regulatory; no current differentiated PADIEM evidence recorded. |
| BIO-010 | Genomics | Genomics AI | DEPRIORITIZED | Apply AI to genomic interpretation and research workflows. | Requires specialized data/domain capability not yet established in current PADIEM evidence. |
| BIO-011 | Clinical documents | Medical Record Intelligence Workspace | SCREENING | Organize clinical documents, evidence, provenance, versions and review states into one grounded workspace. | Much of this is already represented by ASTERIVE search/source/relationship functions and My Health Story. Likely absorbed unless a new workflow/buyer is proven. |
| BIO-012 | Global healthcare | Foreign Patient Medical Coordination | NARROW / ABSORB | Preserve multilingual clinical meaning and hand off a source-grounded bilingual visit record rather than build another medical-tourism or translation platform. | Generic platform killed; new translation engine duplicates B39. Reuse proposed B39 112 Real-Time Interpretation + existing 112 dissertation evaluation, then add medical-domain slot checks and connect to My Health Story/Event Story Engine. No new Business. |
| BIO-012A | Multilingual visit memory | Bilingual Visit Passport / 의료통역 안전기록 | ABSORB INTO BIO-003 / B39 / PLAT-001 | Apply B39-style critical-term, uncertainty and human-correction grammar to medical encounters and leave a bilingual source-grounded visit memory. | Worth domain-transfer R&D; not a standalone translation engine. Candidate medical checks: number/date/time, body side/site, negation, symptom duration/frequency, medication/allergy/dose strings, speaker attribution and follow-up. |
| BIO-013 | Biotech R&D operations | Bio Evidence Graph / R&D Reproducibility Copilot | DEPRIORITIZED | Trace a research claim back through experiment, sample, protocol, raw data, analysis and report while flagging evidence breaks. | Preserve as later candidate; it should not displace owner-originated 2026 healthcare ideas. |
| BIO-014 | Home rehabilitation | Home Rehab Observer Coach / 혼자 재활할 때 보는 AI 코치 | DEPRIORITIZED / KILL GENERIC | Original concept: observe home rehabilitation, detect movement problems and provide correction/adaptation. | 2026 screen: generic thesis is crowded by Sword/Hinge/Kaia/Kemtai and Korean Dr.Answer 3.0 postoperative rehab; B38 already owns general movement coaching. Do not build as a new standalone product. |
| BIO-014A | Recovery continuity | Recovery Story / Between-Visits Recovery Layer | ABSORB INTO BIO-003 / PLAT-001 | Make the period between clinic visits observable and memorable: prescribed plan → attempted sessions → movement evidence → user uncertainty → adherence/change → questions for next visit. | Surviving angle from BIO-014. Prefer source-grounded continuity and clinician handoff over competing on generic live pose correction. No autonomous clinical-plan changes. |
| PLAT-001 | Cross-domain story infrastructure | Event Story Engine / 사건·병원 여정 스토리 엔진 | SCREENING | Convert recordings, documents and evidence into source-grounded event chapters, causal transitions, current state and next actions. | Common grammar across My Health Story and 사실로; Recovery Story and Bilingual Visit Passport are possible vertical layers. Treat as reusable platform capability before considering a standalone Business. |
| GEN-001 | Export / compliance | AI Global Certification Passport | IDEA | Show a Korean company's product-specific overseas certification/regulatory gaps, missing evidence and next actions by target country. | General portfolio candidate, not part of Bio R&D; no Business number reserved. |
| GEN-002 | Funding discovery | Support Program AI Matching / 지원사업 AI 매칭 | DUPLICATE | Match an organization to public support programs and explain eligibility, gaps and preparation tasks. | Duplicate / repackaging risk confirmed against existing `400-ai-finder` and `cwtree` support-program work. |

## Current Bio / Healthcare priority

See:

- `docs/portfolio/research/BIO_HEALTHCARE_IDEA_RECOVERY_AND_PRIORITY_2026-08-26.md`
- `docs/portfolio/research/BIO_014_HOME_REHAB_OBSERVER_COACH_SCREEN_2026-08-26.md`
- `docs/portfolio/research/BIO_012_FOREIGN_PATIENT_COORDINATION_SCREEN_2026-08-26.md`

```text
P1 = BIO-003 My Health Story validation
P2 = BIO-012A medical domain-transfer test using B39 + existing 112 research, only if it materially helps BIO-003
P3 = PLAT-001 Event Story Engine + BIO-014A Recovery Story reuse model
B63 = paused pending hospital/HIS evidence
BIO-014 generic home rehab coach = screened/deprioritized
BIO-012 generic foreign-patient platform/translator = screened/absorbed
BIO-001 NIR = historical/deprioritized
```

## Recent Business-number caution

Recent product-decision issues and implementation work may run ahead of the current canonical `BUSINESS_REGISTRY.md`. An Issue or prototype may propose B59–B63 identities without making them canonical. Always read the current registry and current Issues before assigning the next number.

## Source / evidence notes

- `07_BioR&D_설계팀장_임명및1차통합작업지시서_v1.md` requires PADIEM Bio R&D to proceed from research problem → technical hypothesis → validation → PoC → productization candidate rather than inventing medical products arbitrarily.
- `04_아스테리브_마이헬스스토리_병원스토리북_v1` proves the health-story direction already advanced beyond ideation into a bounded sample-data visual prototype.
- Proposed Business 38 explicitly excludes physical therapy/rehabilitation even though it owns general movement observation, session planning and form cues; generic home-rehab computer vision is also externally crowded.
- Proposed Business 39 already owns bilingual meaning-preservation, critical-term/negation/number risk, clarification, human correction and verified bilingual-record grammar. Existing 112 dissertation/presentation evidence in Drive provides an evaluation base; healthcare work should reuse it rather than create a duplicate translator.
- B63 evidence supports concept-demo completion and a narrowed healthcare-specific semantic/quasi-identifier safety layer, but not a production hospital product.
- PADIEM historical NIR technology remains valid portfolio history but is not a current priority merely because it has old patent evidence.

## Session handoff rule

Every future BI / Bio R&D session must first read this ledger, the Bio/Healthcare queue and the canonical Business Registry. Recover recent owner-originated ideas and prototypes before generating a fresh candidate. At session end, capture any new idea, status change, duplicate/absorption finding, prototype evidence or rejection reason here.
