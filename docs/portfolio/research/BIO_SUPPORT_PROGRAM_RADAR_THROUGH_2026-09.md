# Bio / Healthcare Support-Program Radar through 2026-09

- Updated: 2026-08-26
- Purpose: use active/upcoming Korean startup, company-support and R&D programmes as **problem-demand signals** for Bio/Healthcare idea discovery.
- Scope: Enterprise Support Portal (기업마당), K-Startup, IRIS, KHIDI/HIRA and selected Gwangju/regional programmes.
- Rule: a support programme is not itself a product idea. Extract the underlying problem, buyer, evidence requirement and implementation barrier, then map that signal to PADIEM capabilities.

## 1. Active / near-term opportunities and signals

### A. AI Application Rapid Commercialization Support — IRIS / MOTIR / KEIT

- 2026 second call.
- Application window: 2026-08-11 to 2026-09-03.
- Signal: the government is explicitly funding rapid commercialization of AI-applied products, not only foundational-model research.
- Relevance to Bio/Healthcare: a bounded AI healthcare workflow with clear validation/evidence can fit the broader commercialization direction if the call's detailed item/RFP requirements match.

### B. Bio/Medical Package Support — K-Startup / Dongguk BMC incubation center

- K-Startup current listing shows application through 2026-09-30.
- Signal: bio/medical startups need packaging around commercialization, productization, advisory, testing and market entry rather than model research alone.

### C. HIRA Health/Medical Big Data Startup Incubating Lab

- Rolling: 2026-04-06 to 2026-12-31.
- Target: prospective founders, existing founders, university/graduate students, startups and prior competition teams.
- Offers education / consulting around digital-health businesses using health/medical big data.
- Signal: public health-data access and commercialization remain an explicit startup pathway.

### D. K-Startup BioLink Startup Hub

- Current K-Startup listing remains open/active.
- Signal: bio collaboration, technology matching and access to external technology/partners are persistent bottlenecks.
- Product implication: do not create another grant/partner-matching portal; look instead at technical evidence exchange, reproducibility, due diligence and cross-organization workflow boundaries.

### E. 2026 TIPS support plan — K-Startup

- Current K-Startup listing remains active.
- Signal: a sufficiently differentiated Bio/Healthcare deep-tech product can be financed through the general startup R&D/commercialization pathway even when there is no narrow 'medical AI' grant.

### F. Smart Electronic Drug Commercialization Center — regulatory support

- Rolling in 2026.
- Target: Korean smart-electronic-drug technology companies.
- Support includes H/W + S/W regulatory guidance, medical-AI guidance, cybersecurity and software validation.
- Signal: medical AI commercialization increasingly requires **software validation, cybersecurity, regulatory evidence and lifecycle traceability**, not just model accuracy.

### G. K-Biohealth Regional/Strategic Center support

- 2026 programmes include shared infrastructure, testing/inspection, prototype development, regulatory/certification and exhibition support.
- A current joint-pavilion programme is listed through September / first-come in the Enterprise Support Portal.
- Signal: startups repeatedly need to assemble evidence from different labs, certification bodies, prototype facilities and programmes.

### H. Biohealth Global Export Auxiliary-Cost Support — MOHW/KHIDI

- 2026-06-22 to 2026-10-30.
- Supports logistics/export-related costs for biohealth companies.
- Signal: export readiness remains a major commercialization layer after product validation; regulatory/evidence portability across markets matters.

### I. AI Native HIS planning — KHIDI

- KHIDI posted `AI 지능형 병원정보시스템(AI Native HIS) 기획(1차)` on 2026-08-21.
- Bid date: 2026-09-03.
- This is procurement, not a startup grant, but it is a high-value policy signal.
- Signal: Korea is actively planning hospital information systems designed around AI-native workflows rather than merely bolting isolated AI models onto legacy HIS.

### J. AI-native Advanced Bio Autonomous Laboratory — IRIS / MSIT / NRF

- 2026 new-project call was announced in January (closed for this cycle).
- Signal: autonomous experimentation / self-driving lab is now an explicit national advanced-bio R&D direction.
- Important distinction: the opportunity is not only robotics; autonomous labs create new needs for provenance, experiment-plan validation, instrument execution trace, dataset lineage and human-override evidence.

### K. Bio/Medical Technology Development — `인공지능바이오` — IRIS

- 2026 third new-project call included `인공지능바이오` as an internal programme area.
- Signal: AI-bio is not limited to medical imaging or drug discovery; toolchain/infrastructure hypotheses should also be examined.

### L. Gwangju Dong-gu AI Healthcare Startup programme — regional signal

- 2026 programme (closed for the current round) supported joint R&D planning, product/service demonstration and exhibition for local AI-healthcare startups; new-industry eligibility included AI, big data, bio and medical devices.
- Signal: Gwangju has a concrete regional AI-healthcare commercialization / demonstration policy lane.
- Do not assume another round will open; retain it as a local ecosystem and partner signal.

## 2. What these programmes say the market/government is buying

The recurring demand is not simply `medical AI model`.

Across startup, company-support and R&D programmes, the repeated bottlenecks are:

```text
AI product commercialization
clinical / real-world validation
public-health-data utilization
software validation
cybersecurity
regulatory evidence
hospital AI integration
cross-organization collaboration
prototype/testing infrastructure
export readiness
AI-native experimentation
traceability / reproducibility
```

This changes the PADIEM Bio strategy.

PADIEM does not need to compete first in:

```text
drug molecule discovery
radiology diagnosis
foundation model training
medical-device hardware
commodity medical translation
commodity pose-based rehabilitation
```

A better portfolio search space is the **control / evidence / memory / workflow layer around AI-assisted healthcare and bio R&D**.

## 3. Support-program-derived idea expansion

### BIO-015 — Clinical AI Shadow Lab / AI Native HIS Agent Sandbox

Status: `RESEARCH CANDIDATE`

Problem signal:

- AI Native HIS is being formally planned;
- AI applications are moving into rapid commercialization;
- hospitals need evidence before allowing AI agents to act inside real workflows.

Product hypothesis:

> Let a hospital or HIS vendor replay synthetic/de-identified clinical workflows and run an AI agent in shadow mode before enabling real actions.

Core functions:

```text
synthetic/de-identified HIS event stream
→ AI agent observes / proposes action
→ no real action executed
→ expected human action / policy comparison
→ tool-call and data-access trace
→ source/evidence capture
→ unsafe action / missing evidence / policy violation
→ replayable incident record
→ acceptance report
```

PADIEM asset fit:

- B42 AI Development Control Tower;
- B48 AI Verification Engine;
- B49/B50 connector concepts;
- B63 clinical data egress controls;
- Event Story Engine / evidence replay grammar.

Key differentiation test:

This must be more than generic LLM evaluation. It should evaluate **workflow actions, data access, tool use, provenance and human override** in a Korean hospital/HIS context.

Potential buyer:

- hospital IT / digital transformation team;
- HIS vendor;
- medical-AI vendor integrating agentic workflows.

### BIO-016 — Medical AI Lifecycle Evidence Passport

Status: `RESEARCH CANDIDATE`

Problem signal:

- smart-electronic-drug support explicitly includes medical AI, cybersecurity and software validation;
- medical AI is regulated as software/lifecycle evidence, not merely a benchmark score;
- export/regulatory programmes create repeated evidence-packaging work.

Product hypothesis:

> Automatically maintain a version-linked evidence passport for a medical-AI product: model/prompt/provider/data changes → required revalidation → test evidence → cybersecurity/software-validation artifacts → approval/review state.

Core functions:

```text
model / prompt / provider / software version change
→ impact classification
→ required tests and documents
→ evidence ingestion
→ validation completeness
→ unresolved risk
→ human approval
→ regulator / partner export package
```

PADIEM asset fit:

- B48 Verification Engine;
- B63 privacy / governed egress;
- general certification-passport candidate;
- source-grounding / audit / workflow capabilities.

Differentiation test:

Avoid becoming a generic QMS/RA document manager. The wedge should be **AI-change-aware evidence requirements and automatic revalidation traceability**.

### BIO-017 — Autonomous Bio Lab Evidence Chain Guard

Status: `RESEARCH CANDIDATE`

Problem signal:

- 2026 `AI-네이티브 첨단바이오 자율실험실` national R&D programme;
- increasing AI/robotics integration in experimental loops;
- collaboration programmes require trusted exchange between labs/companies.

Product hypothesis:

> Independently verify that every AI-generated experimental decision remains traceable through protocol, instrument execution, raw data, analysis and next-experiment recommendation.

Core chain:

```text
AI hypothesis / next-experiment proposal
→ approved protocol version
→ instrument command / execution log
→ sample / batch identity
→ raw data fingerprint
→ analysis code/model version
→ result / statistical evidence
→ next-experiment recommendation
→ human override / approval
```

Primary value:

- reproducibility;
- evidence integrity;
- experiment-chain audit;
- AI autonomous-lab safety / accountability.

PADIEM asset fit:

- B48 verification;
- Research Memory;
- provenance / evidence graph concepts;
- agent workflow audit.

Critical blocker:

Requires a university / biotech / lab-automation partner for meaningful domain validation. Synthetic event-chain demo is feasible before that.

### BIO-018 — Clinical AI Incident Replay / Near-Miss Story

Status: `SCREEN WITH BIO-015`

Problem signal:

As AI becomes embedded in HIS and clinical workflow, organizations will need to investigate not only model output but **the complete sequence that produced an unsafe or questionable recommendation/action**.

Product hypothesis:

> Convert one AI-related clinical near miss into a replayable evidence story: source data → model/context → tool call → recommendation → human response → downstream effect → corrective action.

This is likely a module of BIO-015, not a standalone Business.

PADIEM-specific advantage:

- Event Story Engine already uses source-grounded chronology / WHY-NEXT grammar;
- B63 can contribute egress/policy events;
- B48 can contribute verification assertions.

### BIO-019 — Health Data Product Validation Workbench

Status: `LOWER-PRIORITY SCREEN`

Problem signal:

- HIRA explicitly supports digital-health startups using health/medical big data;
- startups need to validate whether a problem/cohort/pathway exists before product build.

Possible product hypothesis:

> Let a startup or research team express a healthcare product hypothesis and generate a reproducible cohort/pathway analysis plan against approved/public health-data environments.

Potential outputs:

```text
product hypothesis
→ target cohort definition
→ data fields / coding map
→ feasibility gaps
→ reproducible query plan
→ aggregate evidence report
→ privacy / non-identification constraints
```

Risk:

High overlap with existing data-lab/analytics tooling; keep lower priority unless a strong HIRA/partner workflow gap appears.

### BIO-020 — Medical AI Export / Regulatory Readiness Passport

Status: `ABSORB / VERTICALIZE GEN-001`

Problem signal:

- K-Biohealth certification/testing support;
- smart-electronic-drug regulatory support;
- biohealth global export support;
- repeated global-market entry programmes.

Product hypothesis:

Not a new Business yet. Verticalize the existing Global Certification Passport candidate for medical AI/SaMD:

```text
product architecture
+ target market
+ software/model characteristics
+ existing test/cert evidence
→ likely regulatory route
→ missing evidence
→ cybersecurity / software validation gaps
→ export readiness
→ expert/lab handoff
```

This should be screened together with BIO-016 rather than creating another separate product.

## 4. Updated priority from grant signals

The programmes do **not** make every candidate good. They change which candidates deserve deeper research.

Recommended order:

```text
P1  BIO-003 My Health Story — validation already underway
P2  BIO-015 Clinical AI Shadow Lab / AI Native HIS Agent Sandbox
P3  BIO-016 Medical AI Lifecycle Evidence Passport
P4  BIO-017 Autonomous Bio Lab Evidence Chain Guard
P5  BIO-012A Bilingual Visit Passport — reuse B39; domain-transfer only
P6  BIO-014A Recovery Story — absorb into My Health Story/Event Story Engine
P7  BIO-019 Health Data Product Validation Workbench — low-priority screen
```

Why BIO-015 moves high:

- policy timing is extremely current (AI Native HIS planning posted 2026-08-21);
- it reuses multiple PADIEM assets;
- a synthetic demo is possible without hospital PHI;
- hospital validation can be deferred until after a visible technical prototype;
- it is not another commodity diagnosis/translation/pose model.

Why BIO-016 also moves high:

- medical-AI software validation/cybersecurity/regulatory evidence is explicitly funded/supported;
- PADIEM already has verification, audit and governance primitives;
- product can start with synthetic version/evidence records;
- Korea-first regulatory workflow may offer a narrower wedge than global generic compliance software.

Why BIO-017 remains behind them:

- national R&D signal is strong;
- technical/product story is strong;
- but domain validation requires access to actual experimental/lab automation workflows.

## 5. September operating method

Through 2026-09-30, maintain two parallel lists:

### `APPLY / PARTNER NOW`

Programmes for which current PADIEM/new-company eligibility and deadline are worth checking immediately.

### `IDEA SIGNAL`

Programmes that may already be closed or not directly eligible but reveal what government/hospitals/labs are actively buying, validating or preparing to buy.

Do not discard closed calls. For idea discovery, a closed RFP can be more valuable than an open generic subsidy because it exposes precise national problem definitions.

## 6. Sources to monitor through September

Primary:

```text
기업마당 (bizinfo.go.kr)
K-Startup (k-startup.go.kr)
IRIS (iris.go.kr)
KHIDI / 의료기기산업 종합정보시스템
HIRA 보건의료빅데이터개방시스템
```

Secondary / regional:

```text
광주테크노파크
광주창조경제혁신센터
인공지능산업융합사업단
지역 K-바이오헬스 센터
서울바이오허브 / 오픈이노베이션 programmes
```

Search dimensions:

```text
바이오 / 헬스케어 / 디지털헬스 / 의료AI / 의료기기
AI Native HIS / 병원정보시스템 / 의료데이터
인공지능바이오 / 자율실험실 / SDL
실증 / PoC / 사업화 / 기술검증
인허가 / SW validation / cybersecurity / 인증
수출 / 글로벌 / 오픈이노베이션 / TIPS
```

## 7. Decision rule

A grant-aligned idea is promoted only if all are true:

```text
REAL_PROBLEM_SIGNAL = YES
PADIEM_ASSET_FIT = HIGH_OR_MEDIUM_HIGH
EXTERNAL_DUPLICATE_GAP = PLAUSIBLE
SYNTHETIC_OR_PUBLIC_FIRST_VALIDATION = POSSIBLE
BUYER_OR_R&D_PARTNER = IDENTIFIABLE
GRANT_FIT_DOES_NOT_DISTORT_PRODUCT = YES
```

Government funding is evidence of demand, not proof of product-market fit.
