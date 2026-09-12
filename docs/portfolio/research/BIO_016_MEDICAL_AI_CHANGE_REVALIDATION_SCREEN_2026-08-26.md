# BIO-016 Medical AI Lifecycle Evidence Passport — Deep Screen

- Date: 2026-08-26
- Status: `NARROW / STRONGEST NEW STANDALONE VALIDATION CANDIDATE`
- Business number: NONE
- Deployment: none

## Original thesis

Maintain version-linked lifecycle evidence for a medical-AI product as models, prompts, providers, datasets, software and cybersecurity controls change.

Generic flow:

```text
change
→ impact classification
→ required validation / documents
→ evidence linkage
→ unresolved risk
→ human approval
```

## Internal overlap

B48 AI Verification Engine already owns generic exact-version claims/checks/evidence/exceptions/human approval. B63 owns clinical data egress, not device change control. GEN-001 Global Certification Passport may later contribute export/certification mapping.

Therefore a generic `medical B48` or generic evidence folder is duplicate/weak.

The healthcare-specific value must come from **regulatory change semantics**: knowing which AI/software change invalidates which evidence and what must be revalidated.

## Fresh Korean regulatory timing

MFDS published `디지털의료기기 변경관리 계획서 허가 심사 가이드라인` on 2026-06-26 specifically for digital medical devices using AI technology.

MFDS also published an LLM-based digital-medical-device permit/review guideline on 2026-06-30 and held a 2026 digital-medical-device permit/review briefing covering the change-management plan guideline.

Primary official sources:

- https://www.mfds.go.kr/law/board/boardDetail.do?brdId=data0011&menuKey=29&seq=15874
- https://www.mfds.go.kr/brd/m_1060/list.do?board_id=data0011&data_stts_gubun=C1004&multi_itm_seq=0&srchTp=0
- https://www.mfds.go.kr/brd/m_220/view.do?seq=32927

This is a highly current Korean workflow signal, not merely a generic international compliance trend.

## International direction

FDA's AI-enabled device Predetermined Change Control Plan (PCCP) framework similarly makes planned modification, modification protocol, validation and impact assessment a lifecycle concern. IMDRF's 2026 AI lifecycle-management work reinforces the same direction.

## External competition

A broad medical-device QMS/evidence platform is crowded:

- Greenlight Guru covers medical-device QMS, design controls, change impact and traceability, and now markets AI-assisted change-impact workflows.
- Pacific AI covers healthcare AI system registry, governance, pre-release testing and continuous monitoring.
- other healthcare AI governance products increasingly track risk, validation evidence and lifecycle state.

Therefore:

```text
GENERIC_MEDICAL_AI_QMS = KILL
GENERIC_EVIDENCE_PASSPORT = TOO_BROAD
GENERIC_HEALTHCARE_AI_GOVERNANCE = HIGH_COMPETITION
```

## Surviving wedge — AI Change Impact & Revalidation Compiler

Working Korean description:

> **의료 AI 변경 델타를 읽고, 기존 증거 중 무엇이 더 이상 유효하지 않으며 어떤 재검증·문서·검토가 필요한지를 근거와 함께 컴파일하는 계층.**

Possible working name:

`MFDS AI Change Delta / Medical AI Revalidation Compiler`

Input is not an entire QMS. Input is an exact product delta:

```text
before version
+ after version
+ changed model/prompt/provider/data/software/config/intended-use elements
+ current evidence inventory
+ approved change-management plan / policy profile
```

Output:

```text
change classification
→ potentially impacted safety/performance claims
→ stale / invalidated evidence
→ required revalidation tests
→ required document updates
→ regulatory-review-required flags
→ unresolved rationale
→ human RA/QA approval
→ exact version-linked change dossier
```

## Example change classes to test

The first synthetic corpus should include at least:

1. algorithm/model version update;
2. threshold change;
3. retraining / dataset refresh;
4. LLM/provider/model swap inside a generative component;
5. system prompt / instruction change;
6. cybersecurity patch;
7. library/runtime dependency change;
8. UI copy-only change;
9. new input device / hardware interface;
10. intended-use expansion;
11. target population expansion;
12. workflow/integration change without model change.

The point is to distinguish `everything must be revalidated` from defensible, evidence-linked impact analysis.

## Why this can be more than B48

B48 asks:

> Did the exact submitted artifact satisfy its verification plan?

BIO-016 narrow wedge asks:

> Given this regulated medical-AI change, **what verification plan is now required, which old evidence is stale, and why?**

B48 can be the verification engine underneath; BIO-016 provides the medical-AI regulatory change graph/compiler above it.

## Technical validation design

### Synthetic fixture

Create 8–12 fictional medical-AI products or one product with 20–40 controlled change events. No patient data needed.

Each event has:

```text
baseline version
change delta
intended use / user / population / input / output
model/software/config versions
evidence inventory and exact versions
expected impact classes
expected stale evidence
expected required tests/docs
source/rationale reference
```

### Gold labels

Start with a conservative deterministic manually authored gold set based on public MFDS/FDA guidance. Later require review/correction by a Korean medical-device RA/QA expert.

### Metrics

Primary:

```text
IMPACTED_EVIDENCE_RECALL
STALE_EVIDENCE_DETECTION_RECALL
REQUIRED_REVALIDATION_RECALL
```

Secondary:

```text
UNNECESSARY_REVALIDATION_RATE
RATIONALE_CITATION_COVERAGE
CHANGE_CLASSIFICATION_ACCURACY
REVIEWER_CORRECTION_COUNT
REVIEWER_TIME_TO_ACCEPTABLE_DOSSIER
```

A system that blocks everything is not successful.

## Commercial buyer hypothesis

Strongest initial buyer candidates:

- Korean medical-AI / SaMD startup RA/QA team;
- digital-therapeutics / smart-electronic-drug company;
- medical-device regulatory consulting firm;
- larger medtech software team managing frequent AI/software releases.

Hospital IT may be secondary; this is primarily manufacturer/vendor lifecycle work.

## Support-program fit

Potentially strong with support that funds:

- medical-AI software validation;
- cybersecurity;
- regulatory readiness;
- commercialization and certification;
- export readiness.

Do not distort the product for a specific grant. The workflow must remain useful without subsidy.

## Regulatory boundary

The product must never state that a change is legally approved or that submission is unnecessary. Outputs are decision support/evidence planning for qualified RA/QA human review.

```text
REGULATORY_APPROVAL_AUTHORITY = HUMAN / REGULATOR
AUTONOMOUS_LEGAL_CONCLUSION = NO
```

## Current verdict

```text
BIO_016_GENERIC_LIFECYCLE_PASSPORT = NARROW
SURVIVING_WEDGE = AI_CHANGE_IMPACT_AND_REVALIDATION_COMPILER
INTERNAL_REUSE = B48 + source/provenance primitives
CURRENT_STANDALONE_POTENTIAL = MEDIUM_HIGH
TECHNICAL_VALIDATION_WITH_SYNTHETIC_DATA = YES
RA_EXPERT_VALIDATION = REQUIRED_BEFORE_GO
BUSINESS_NUMBER = HOLD
NEXT_GATE = SYNTHETIC_CHANGE_DELTA_BENCHMARK
```

Of the support-program-derived BIO-015/016/017 set, this is currently the strongest near-term standalone product hypothesis.
