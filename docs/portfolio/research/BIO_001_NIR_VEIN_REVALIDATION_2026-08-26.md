# BIO-001 NIR Vein Intelligence Revalidation

- Date: 2026-08-26
- Portfolio ID: BIO-001
- Parent queue: `docs/portfolio/BIO_HEALTHCARE_IDEA_QUEUE.md`
- Decision: `NARROW`
- Current state: `RESEARCHING`
- Full clinical product build: `HOLD`
- Next authorized work: software-only benchmark / training-assessment prototype using public data

## 1. Executive decision

Do **not** rebuild a generic near-infrared vein finder / projector as the product thesis.

That category is already mature, commercially occupied and protected by substantial prior art. PADIEM's historical asset remains valuable, but the defensible 2026 direction is narrower:

> **AI-assisted venipuncture training and objective assessment, using NIR vein maps as one sensing layer rather than treating vein visualization itself as the innovation.**

Working R&D wedge:

```text
NIR / forearm image
→ vein segmentation and visibility-quality analysis
→ candidate puncture-zone / anatomy guidance
→ learner action capture
→ objective skill scoring and feedback
→ evidence-linked training record
```

The first prototype should be education/research-only. It must not make diagnosis, treatment, vascular-access success, or medical-device performance claims.

## 2. Verified PADIEM asset

Drive company-technology and IP records verify that PADIEM has real historical Bio/medical-device lineage rather than a newly invented story.

### Patent / technical history

PADIEM records identify:

- patent registration `10-1725148`;
- application `10-2015-0122164`;
- filing date `2015-08-28`;
- registration date `2017-04-04` in the internal IP ledger;
- title recorded in current company records as `주사기용 혈관감지 장치 및 방법` / historical materials also describe a vein-detection injection-practice assistance device;
- technology area: optical / imaging / sensor-assisted blood-vessel location for injection assistance.

The current company technology genealogy also records 2015–2017 work on:

- near-infrared vein visualization / transillumination;
- bracelet-form vein-transillumination and injection-practice support prototypes;
- sensor, optics, mechanical and circuit prototyping;
- youth-startup-academy and university-industry R&D/productization activity.

This is useful evidence of prior hardware/optical product-development capability, but it does **not** prove present-day efficacy, present patent enforceability, regulatory clearance, or market advantage.

### Patent-status caveat

The current web search confirms that `KR101725148B1` exists in the patent citation landscape as `Blood vessel detection apparatus and method for syringe`, but a reliable current KIPRIS maintenance/legal-status read was not recovered in this review. Do not rely on the historical registration as an active moat until official current legal status, assignee and maintenance-fee status are rechecked.

## 3. 2026 market reality

### Global category is mature

AccuVein launched the `AV600` in March 2026 as its fourth-generation NIR vein-visualization device. FDA device listings currently show AccuVein products and VeinViewer products under:

```text
Classification: Device, vein location, liquid crystal
Product code: KZA
Device class: 1
Regulation: 21 CFR 880.6970
```

This means that basic non-invasive vein location / visualization is not an open greenfield category.

### Strong Korean competitor exists now

`iiSM Inc.` operates the `VeinProbe` line in Korea and abroad. Current evidence shows:

- NIR/spectroscopic real-time vascular visualization;
- desk and compact / clinical models;
- blood draw / IV and aesthetic / varicose-vein use positioning;
- deployment in hospitals and nursing-school practice environments;
- product listings claiming ISO 13485, CE and FDA;
- product specs advertising up to 8 mm effective depth, zoom, image save, multiple real-time modes and mobile mounting options;
- active 2026 exhibition / commercialization activity, including KHF, KOADMEX and the 2026 Jeonnam-Gwangju Future Industry Expo.

Therefore a Korean `better vein finder` pitch would collide directly with an established domestic company whose optical-medical-device specialization is stronger than PADIEM's current active hardware organization.

## 4. Clinical evidence is use-case dependent, not universally positive

The evidence does **not** support a claim that NIR vein visualization is universally superior to standard palpation for all patients.

### Evidence against broad routine-use claim

A 2026 systematic review/meta-analysis of adult RCTs (J Adv Nurs; PMID 40302136) reported no statistically significant improvement in first-attempt success, overall success, attempts, cannulation time or pain for routine adult PIVC, with substantial heterogeneity.

A 2025 randomized oncology study (Support Care Cancer; PMID 41276617) reported first-attempt success of:

```text
NIR: 90%
transilluminator: 70%
standard control: 96.2%
```

with no significant pain/fear advantage for NIR.

### Evidence supporting selected populations / education

A 2026 geriatric systematic review/meta-analysis (BMC Geriatrics; PMID 41507782; 8 studies, n=1,022) found higher first-attempt success for NIR in older patients (OR 2.36, 95% CI 1.73–3.21), shorter procedure time and fewer complications.

Nursing-education evidence is also promising:

- 2024 Journal of Infusion Nursing study (PMID 38968587): NIR improved vein visibility/direction and 69% of participants reported greater confidence after use.
- 2025 BMC Medical Education RCT (PMID 40405183): the NIR education group had the strongest first-attempt acquisition outcome among compared training techniques.
- crossover simulation evidence in novice operators found similar success versus ultrasound but substantially shorter first-attempt procedure time with NIR.

### Interpretation

This evidence supports a **targeted training / difficult-access / selected-population research thesis**, not a blanket claim that every clinician should use NIR for every IV.

## 5. AI / technical prior art has advanced significantly

Modern research already covers deep-learning-based vein segmentation and mobile implementation.

Examples include:

- 2024 real-time upper/lower-extremity venous segmentation using CNN/U-Net approaches (PMID 38651783);
- 2025 TAU-Net / multi-stage NIR vascular enhancement and segmentation;
- 2025 lightweight deep-learning vein visualization deployed to a smartphone;
- 2024–2026 work on transformer-enhanced segmentation, 3D reconstruction, mixed reality and mobile NIR systems.

Patent prior art is also broad. Recent patent publications describe:

- handheld infrared detection plus visible projection;
- projected vein depth / diameter / confidence information;
- mobile-device NIR camera systems with CGAN / deep learning and 2D/3D vein mapping;
- projection-alignment methods for vein masks;
- optical / NIR vascular localization systems dating well before PADIEM's 2015 filing.

Therefore `AI + NIR + vein segmentation` alone is **not** a sufficient 2026 novelty claim.

## 6. The surviving product wedge

### Rejected thesis

```text
PADIEM builds a new clinical NIR vein finder
```

Decision: `KILL AS PRIMARY THESIS`

Reasons:

- mature global category;
- strong domestic direct competitor;
- commodity low-cost products also exist;
- mixed broad clinical evidence;
- heavy optical / projection / mobile-AI prior art;
- hardware, ISO 13485, medical-device QMS and distribution would be expensive to rebuild before proving differentiation.

### Narrowed thesis

Working name:

**NIR Venipuncture Training & Assessment System**

Korean working name:

**AI 정맥주사 실습·평가 시스템**

Core job:

> Help nursing/medical learners practice vein assessment and puncture planning on diverse difficult-vein cases, and receive objective, repeatable feedback instead of only instructor observation.

NIR is an input modality and educational visualization layer. The differentiation must come from **measurement, scoring, feedback, difficult-case coverage and training evidence**, not from merely rendering veins.

### Why this fits PADIEM better

The narrowed direction can combine three real PADIEM capability lineages:

1. **Historical Bio hardware/IP** — NIR vein/injection-assistance prototype and patent lineage.
2. **Computer vision / AI** — later PADIEM posture/action-analysis and multimodal AI capability.
3. **Verification / evidence workflow** — current systems for structured evidence, scoring, audit and human review.

That combination is more credible than restarting as a pure optical-device company.

## 7. Public-data feasibility: strong

A software benchmark can begin without patient recruitment or hospital PHI.

### CUBITAL public forearm dataset

A public research repository currently exposes a strong first benchmark candidate:

- 2,016 NIR images;
- 1,008 subjects with low-visible veins;
- arm/vein masks;
- antecubital-fossa coordinates;
- arm angle;
- demographic fields including complexion;
- validation subset where three certified nurses marked preferred venipuncture locations;
- reported U-Net agreement of 83% with nurse-selected regions.

This is unusually well aligned with the proposed training use case.

Other open NIR forearm / hand-vein datasets and code also exist, including smaller manually annotated forearm sets and U-DAVIS-style forearm segmentation data.

### Important limitation

Public datasets are sufficient for algorithmic benchmarking, but **not** sufficient to claim clinical puncture success or safety. Human-skill and patient outcomes require separate ethically approved validation later.

## 8. Phase A benchmark — recommended next work

Do not build hardware first.

Build a reproducible software benchmark with this comparison:

```text
INPUT
public NIR forearm images + masks + nurse-selected access regions

BASELINE A
CLAHE / classical vessel enhancement + threshold / filtering

BASELINE B
standard U-Net or equivalent published segmentation baseline

PADIEM CANDIDATE
lightweight segmentation + quality/confidence + access-zone ranking

OUTPUT
1. vein mask
2. candidate vein segments / access regions
3. confidence / visibility quality
4. difficult-case flags
5. nurse-reference agreement
6. subgroup performance summary where metadata supports it
```

### Required metrics

At minimum:

- Dice / F1 for vein segmentation;
- IoU;
- precision / recall;
- inference latency;
- nurse-selected-region agreement where available;
- failure-rate / abstention rate;
- performance by available complexion / demographic metadata, without overclaiming fairness from a single dataset.

### Research question

The first technical question should **not** be:

> Can AI find veins?

That is already proven widely.

It should be:

> Can a low-cost, education-focused model reliably identify usable vein regions and explain/score difficult cases well enough to support repeatable venipuncture training across varied visibility conditions?

## 9. Phase B training prototype — only after benchmark survives

If the software benchmark is credible, the next prototype can add simulated learner actions.

Candidate architecture:

```text
NIR / synthetic arm case
+ learner camera view
+ mock needle / marker tracking
+ target vein / puncture zone
+ procedural checklist

→ insertion-site selection
→ approach angle / hand position / sequence evidence
→ attempt count / correction history
→ AI feedback + instructor review
```

A 2024 haptic-simulator paper demonstrates that real-needle attitude and depth can be tracked with embedded vision + IMU at high precision, and a University of Florida 2025–2026 project demonstrates 3D hand tracking, needle tracking and step recognition for peripheral-IV coaching. This proves technical feasibility but also confirms that objective procedural coaching is an active research field; PADIEM must benchmark rather than assume novelty.

## 10. FTO / IP decision

Current decision:

```text
BROAD_VEIN_FINDER_FTO = HIGH_RISK / CROWDED
PADIEM_2015_PATENT_AS_MOAT = NOT_PROVEN
TRAINING_ASSESSMENT_WORKFLOW_FTO = REQUIRES_NARROW_CLAIM_CHART
```

Before any new patent filing or clinical device build:

1. verify official current status and ownership of KR 10-1725148 in KIPRIS;
2. retrieve full claims and prosecution history;
3. claim-chart against major vein-visualization / projection / mobile-AI families;
4. separately search objective venipuncture training / skill-scoring claims;
5. patent only a narrow surviving technical method, not `AI vein finder` broadly.

## 11. Regulatory boundary

### First prototype

Keep the first prototype explicitly:

```text
education / research tool
synthetic or public data
no patient-use recommendation
no clinical diagnosis
no treatment guidance
no claim of improved real-patient cannulation success
```

### If later promoted to patient-use clinical guidance

Regulatory scope changes materially. The US category includes FDA-listed Class I vein-location devices, while an AI layer that actively recommends puncture targets or predicts outcomes may require a different regulatory assessment depending on intended use and claims. Korean MFDS classification must be confirmed from the exact intended-use statement rather than inferred from foreign classification.

## 12. Government / R&D fit

Fit is **credible but not an immediate reason to distort the product**.

2026 policy/program evidence shows active support for:

- 범부처 첨단 의료기기 연구개발사업;
- AI 응용제품 신속상용화 보건/디지털의료기기 support;
- AI융합 의료기기 신뢰성·성능평가·실증 support;
- broader digital-health / medical-device R&D programs.

However, many 2026 application windows already closed earlier in the year. The correct use of this evidence is:

> prepare a validated benchmark and education-focused PoC now, then map the surviving prototype to the next suitable medical-device / digital-health / simulation-education funding cycle.

## 13. Commercial hypothesis

Best early buyers to test are not general hospitals first.

Suggested order:

1. nursing colleges / medical simulation centers;
2. hospital education / training departments;
3. venipuncture / IV training programs;
4. only later, clinical departments if a separate patient-use hypothesis survives.

Why:

- training buyers tolerate research-stage software more readily;
- objective assessment is a clearer pain point than replacing mature clinical vein finders;
- public/synthetic benchmark can create evidence before patient access;
- PADIEM's historical `주사실습보조` lineage is directly relevant.

## 14. Final disposition

```text
BIO_001 = NARROW
GENERIC_NIR_VEIN_FINDER = KILL_AS_PRIMARY_PRODUCT
HISTORICAL_PADIEM_ASSET = VALID / RELEVANT
CURRENT_PATENT_MOAT = UNVERIFIED
SURVIVING_WEDGE = AI_VENIPUNCTURE_TRAINING_AND_ASSESSMENT
PUBLIC_DATA_BENCHMARK = FEASIBLE
HARDWARE_BUILD_NOW = NO
CLINICAL_PATIENT_USE_NOW = NO
NEXT_PHASE = SOFTWARE_BENCHMARK
FULL_BUSINESS_PROMOTION = HOLD
```

## 15. Evidence references

### PADIEM internal / Drive

- `02_제품_기술_R&D_목록.md` — PADIEM technology genealogy and 2015–2017 vein/injection-assistance lineage.
- `04_특허_상표_인증.md` — patent register including 10-1725148 / 10-2015-0122164.

### Current market / regulation

- AccuVein, `AV600` launch, 2026-03-18.
- US FDA device listing: AccuVein products, product code KZA, Class I, 21 CFR 880.6970.
- US FDA device listing: VeinViewer Flex/Vision/Vision2, product code KZA, Class I.
- iiSM / VeinProbe current company and 2026 exhibition materials.
- BuyKorea VeinProbe VPism-D+ product listing and certifications/specifications.

### Clinical / educational evidence

- PMID 40302136 — adult IR/NIR systematic review/meta-analysis, 2026.
- PMID 41507782 — geriatric NIR systematic review/meta-analysis, 2026.
- PMID 41276617 — adult oncology RCT, 2025.
- PMID 38968587 — NIR visualization and learner/nurse skills, 2024.
- PMID 40405183 — nursing student PVC RCT, 2025.
- crossover simulation study comparing NIR and ultrasound for novice difficult access.

### AI / public-data / training evidence

- PMID 38651783 — CNN-based real-time extremity vein segmentation.
- CUBITAL public forearm NIR dataset/repository — 2,016 images / 1,008 subjects / masks / nurse validation.
- U-DAVIS arm venous segmentation dataset/research.
- 2024 real-needle motion-sensor / optical-flow simulator study.
- University of Florida Peripheral IV mixed-reality hand/needle-tracking coaching project, updated 2026.
