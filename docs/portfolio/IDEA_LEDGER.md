# AI Revenue Lab Idea Ledger

- Status: persistent idea-preservation ledger
- Updated: 2026-08-26
- Authority: idea capture only; does not assign a canonical Business number
- Canonical numbering authority: `docs/portfolio/BUSINESS_REGISTRY.md`
- Related legacy backlog: `docs/portfolio/BUSINESS_CANDIDATE_BACKLOG.md`

## Purpose

This ledger exists so ideas are not re-invented every session and so rejected, paused, duplicate, and promoted ideas remain reusable portfolio knowledge.

New ideas are captured before development. A title and one-line product promise are enough to enter the ledger. Investigation may then add competitors, technical evidence, FTO, government/R&D fit, prototype evidence, or customer evidence.

## Status vocabulary

- `IDEA` — captured but not screened.
- `SCREENING` — duplicate / portfolio overlap / feasibility screening in progress.
- `RESEARCHING` — market, technical, FTO, grant or buyer research in progress.
- `DEMO` — bounded prototype or technical demo in progress.
- `PAUSED` — worth preserving but blocked by evidence, partner, data or timing.
- `LEGACY_ASSET_REVALIDATION` — based on a real prior PADIEM technology/IP asset that needs current validation.
- `DUPLICATE` — materially overlaps an existing product/project; preserve the record and do not re-propose it as new.
- `DEPRIORITIZED` — plausible domain idea but currently weak fit or too broad relative to PADIEM assets.
- `KILL` — researched and rejected; preserve the reason.
- `PROMOTED` — promoted into a numbered/proposed Business workflow; canonical status still depends on the Business Registry.

## Capture rule

```text
new idea
→ IDEA_LEDGER entry
→ existing Business / GitHub / Drive / prior-session duplicate check
→ research / prototype as warranted
→ GO | NARROW | PAUSE | KILL | DUPLICATE
→ only surviving product boundaries enter Business-number promotion
```

Do not delete `KILL`, `DUPLICATE`, `PAUSED`, or `DEPRIORITIZED` entries. They prevent repeated rediscovery and preserve decision history.

## Current idea ledger

| ID | Domain | Idea / product title | Status | One-line product promise | Relationship / note |
|---|---|---|---|---|---|
| BIO-001 | Bio / medical device | NIR Vein Intelligence / 근적외선 혈관 가시화·주사실습 보조 | LEGACY_ASSET_REVALIDATION | Re-evaluate PADIEM's historical near-infrared vein-visualization and injection-training technology with current sensing/AI capabilities. | Real 2015–2017 PADIEM technical/IP lineage; efficacy and present-day medical-device claims are not assumed. |
| BIO-002 | Healthcare AI governance | Clinical AI Egress Control Plane | PROMOTED / PAUSED | Govern what Korean clinical data may leave hospital workflows for external/internal GenAI while preserving clinical utility and audit evidence. | Proposed as B63 in Issue #731; concept demo completed; hospital/HIS validation still required. |
| BIO-003 | Clinical longitudinal intelligence | Longitudinal Patient CareGraph | IDEA | Connect fragmented longitudinal patient events, records and care transitions into an evidence-linked patient journey graph. | Conversation-captured candidate; requires duplicate and clinical-workflow screening before any build. |
| BIO-004 | Patient communication | Patient Communication AI | IDEA | Translate complex clinical information into patient-appropriate language, channel and comprehension level while preserving source boundaries. | Conversation-captured candidate; do not imply diagnosis/treatment authority. |
| BIO-005 | Preventive health | Health-check Trend AI | IDEA | Track repeated health-check results over time and explain meaningful changes, missing follow-up and evidence-linked trends. | Conversation-captured candidate; medical interpretation and regulated-claim boundary must be screened. |
| BIO-006 | Clinical workflow | Ambient Medical AI / Scribe | DEPRIORITIZED | Capture and structure clinician-patient encounters into reviewable documentation. | Crowded category and weak first-fit relative to current PADIEM differentiation; preserve for later reassessment. |
| BIO-007 | Rehab / movement | Rehab / Pose AI | SCREENING | Use pose/motion analysis for rehabilitation or guided movement workflows with measurable feedback. | Must be screened against existing PADIEM AI Exercise Coach / Business 38 lineage to avoid duplicate packaging. |
| BIO-008 | Biotech | AI Drug Discovery | DEPRIORITIZED | Apply AI to candidate discovery / ranking in drug R&D. | Too broad and domain-capital intensive for current first entry; preserved rather than repeatedly reproposed. |
| BIO-009 | Medical imaging | Radiology Diagnosis AI | DEPRIORITIZED | Apply multimodal AI to radiology image interpretation or diagnostic support. | Crowded and high-regulatory; no current differentiated PADIEM evidence recorded. |
| BIO-010 | Genomics | Genomics AI | DEPRIORITIZED | Apply AI to genomic interpretation and research workflows. | Requires specialized data/domain capability not yet established in current PADIEM evidence. |
| BIO-011 | Clinical documents | Medical Record Intelligence Workspace | IDEA | Organize clinical documents, evidence, provenance, versions and review states into one grounded workspace. | Conversation-captured candidate; screen against Living Archive, Research Memory and B63 boundaries. |
| BIO-012 | Global healthcare | Foreign Patient Medical Coordination | IDEA | Coordinate multilingual medical documents, appointments, explanations and workflow handoffs for international patients. | Strong possible reuse of PADIEM multilingual speech/translation assets; must not collapse into generic translation. |
| BIO-013 | Biotech R&D operations | Bio Evidence Graph / R&D Reproducibility Copilot | IDEA | Trace a research claim back through experiment, sample, protocol, raw data, analysis and report while flagging evidence breaks. | Current-session candidate; screen against ELN/LIMS/scientific-data-management products and Research Memory. |
| GEN-001 | Export / compliance | AI Global Certification Passport | IDEA | Show a Korean company's product-specific overseas certification/regulatory gaps, missing evidence and next actions by target country. | General portfolio candidate, not part of Bio R&D; no Business number reserved. |
| GEN-002 | Funding discovery | Support Program AI Matching / 지원사업 AI 매칭 | DUPLICATE | Match an organization to public support programs and explain eligibility, gaps and preparation tasks. | Duplicate / repackaging risk confirmed against existing `400-ai-finder` and `cwtree` support-program work. Do not propose as a new Business without a materially new boundary. |

## Recent Business-number caution

Recent product-decision issues and implementation work may run ahead of the current canonical `BUSINESS_REGISTRY.md`. An Issue or prototype may propose B59–B63 identities without making them canonical. Always read the current registry and current Issues before assigning the next number.

## Source / evidence notes

- `07_BioR&D_설계팀장_임명및1차통합작업지시서_v1.md` requires PADIEM Bio R&D to start from verified company technology/IP/R&D history and proceed through research problem → technical hypothesis → validation → PoC → productization candidate rather than inventing medical products arbitrarily.
- PADIEM historical evidence includes near-infrared vein visualization / injection-training assistance as a Bio asset requiring present-day revalidation.
- B63 evidence currently supports concept-demo completion and a narrowed healthcare-specific semantic/quasi-identifier safety layer, but not a production hospital product.

## Session handoff rule

Every future BI / Bio R&D session that generates a new product-scale idea should first read this ledger and the canonical Business Registry. At session end, capture any new idea, status change, duplicate finding, or rejection reason here (or in a reviewed successor ledger) before generating another candidate.
