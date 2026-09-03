# BIO-016 Korea Pilot Partner & Competition Map — 2026-08-26

- Candidate: `AI Change Impact & Revalidation Compiler / MFDS AI Change Delta`
- Status: validation planning
- Business number: none
- Purpose: identify who can falsify/correct the synthetic rules and whether a Korea-first direct competitor is already obvious.

## 1. Public-market competition finding

Current Korean public search shows a strong and rapidly developing **regulatory/support framework** for AI digital medical devices, but no obvious public product was found whose narrow primary job is:

> ingest exact AI/software product deltas → identify version-scoped stale evidence → propose candidate revalidation/document review → preserve source rationale → require RA/QA decision.

This is **not an FTO or patent-clearance conclusion**. It is only a directional public-market screen.

Generic adjacent competition is strong:

- medical-device eQMS / change management;
- AI governance / model registry / pre-release healthcare AI testing;
- regulatory consulting / technical-file support;
- software validation tools and services.

The candidate survives only if it stays narrower than those categories.

## 2. Why a pilot user exists

2026 public job postings from Korean medical-AI/medical-device companies explicitly ask RA/QA staff to handle combinations of:

- MFDS / CE MDR / FDA authorization work;
- AI SaMD / digital-medical-device QMS;
- ISO 13485 / GMP;
- post-market / maintenance processes;
- cybersecurity documentation;
- post-approval change management.

This indicates that change/evidence review is an actual operating role rather than an invented workflow.

Potential user archetype:

```text
medical-AI manufacturer
→ RA/QA manager or specialist
→ receives software/model/product change request
→ determines impact
→ identifies evidence/documents to revisit
→ coordinates verification/validation
→ records rationale and human approval
```

## 3. Strong validation/support institutions

### KTL — 의료AI개발지원센터

Public KTL staff/service information lists responsibilities including:

- medical-device software validation;
- cybersecurity technical support;
- AI/software validation research/testing;
- medical-AI algorithm development/testing;
- medical-device company authorization/technical support.

Why relevant:

KTL can challenge whether the proposed evidence classes and validation outputs correspond to real software-validation work rather than a purely documentary abstraction.

### 한국AI의료헬스케어연구원 + 범부처통합헬스케어협회 + 충북테크노파크

2026 `AI융합 의료기기 신뢰성 강화 및 성능 평가·실증 통합지원` supports AI SaMD/SiMD companies with:

- reliability/performance evaluation;
- clinical design / risk management;
- clinical demonstration / security;
- IEC 62304-based software validation;
- reports/certificates usable in technical documentation.

Why relevant:

The programme provides an external reality check for which outputs from BIO-016 would actually save work versus merely create another internal checklist.

### 원주의료기기테크노밸리 / RA ecosystem

Current RA education/support infrastructure confirms that product development, domestic/international authorization, manufacturing and quality management are treated as lifecycle regulatory work.

Use as a broader expert-network path rather than a first technical pilot unless a direct contact emerges.

## 4. Potential manufacturer pilot profiles

Do not treat job postings as partnership commitments. They only reveal active role demand.

Useful profiles include:

### AI SaMD company with active RA/QA team

Examples in 2026 public recruitment include companies asking for:

- digital medical-device GMP / ISO 13485;
- AI software QMS;
- MFDS / CE MDR;
- FDA 510(k);
- cybersecurity documentation;
- post-market and change-management work.

These are good pilot profiles because they can compare the compiler output with their real review process.

### Gwangju / regional medical-device manufacturer

A 2026 Gwangju medical-device RA recruitment posting explicitly included:

- domestic/international authorization;
- GMP / CE MDR;
- authorization maintenance;
- post-approval change management;
- regulatory-agency response.

This supports searching Gwangju/Jeonnam first for a relationship-accessible RA/QA reviewer, even if the company is not an AI SaMD maker.

## 5. Suggested validation sequence

Do not ask an expert to validate an entire product concept first.

### Step A — 30-minute rule correction

Show 5 deliberately different synthetic deltas:

1. model update;
2. intended-use expansion;
3. LLM/provider swap;
4. cybersecurity patch;
5. document typo only.

Ask the reviewer to mark:

```text
which evidence classes would you inspect?
which prior evidence might no longer cover the changed version/scope?
which validation/document work would you consider?
what is over-conservative?
what is dangerously missing?
what cannot be decided without more context?
```

### Step B — Blind comparison

Give 10 unseen synthetic deltas to:

```text
human-only review
vs
compiler-assisted review
```

Measure:

- missing impacted evidence;
- unnecessary review/revalidation items;
- corrections to machine suggestion;
- review time;
- confidence / explanation quality.

### Step C — Real but sanitized change log

Only if A/B are useful, ask one manufacturer to provide a de-identified/sanitized historical change example with no patient or confidential model data. Compare the tool's output with the actual resolved RA/QA process.

## 6. Pilot success criteria

Do not use `the expert liked it` as the primary gate.

Useful evidence would be:

```text
RA_QA_CORRECTION_RATE decreases after rule refinement
HIGH_RISK_MISS_RATE is acceptably low
UNNECESSARY_REVIEW_RATE is materially below an all-blocking baseline
TIME_TO_FIRST_REVIEWABLE_IMPACT_MAP decreases
SOURCE_RATIONALE is understandable and auditable
```

The system must remain decision support. Qualified RA/QA retains authority.

## 7. Current partner shortlist by role

```text
TIER_1_TECHNICAL_VALIDATION
- KTL 의료AI개발지원센터
- 한국AI의료헬스케어연구원 / related AI medical-device reliability programme

TIER_1_USER_VALIDATION
- Korean AI SaMD manufacturer RA/QA specialist/manager
- digital-medical-device startup with frequent software/model releases

TIER_2_LOCAL_ACCESS
- Gwangju/Jeonnam medical-device RA/QA practitioner
- regional medtech support/testing organization

TIER_2_REGULATORY_NETWORK
- medical-device RA expert / consultant
- RA education/support organizations
```

No contact or partnership is claimed by this document.

## 8. Current verdict

```text
DIRECT_KOREA_PUBLIC_PRODUCT_DUPLICATE = NOT_OBVIOUS_FROM_PUBLIC_SCREEN
FTO_CLEARANCE = NOT_DONE
REAL_RA_QA_WORKFLOW_DEMAND = SUPPORTED
TECHNICAL_SUPPORT_PARTNER_PATH = PLAUSIBLE
FIRST_HUMAN_GATE = 5-CASE_RULE_CORRECTION
BUSINESS_PROMOTION = HOLD
```
