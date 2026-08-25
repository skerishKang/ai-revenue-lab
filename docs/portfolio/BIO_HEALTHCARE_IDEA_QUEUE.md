# Bio / Healthcare AI R&D Idea Queue

- Updated: 2026-08-26
- Parent portfolio ledger: `docs/portfolio/IDEA_LEDGER.md`
- Project lineage: `07_BioR&D`
- Business-number authority: `docs/portfolio/BUSINESS_REGISTRY.md`

## Operating principle

Bio R&D is not a one-idea project. The goal is to preserve and test a continuing queue of research/product hypotheses while grounding each one in PADIEM's real technology, IP, R&D history and reusable software capability.

```text
PADIEM assets / prior R&D
→ research question
→ technical hypothesis
→ public/synthetic validation
→ competitive/FTO/grant screen
→ bounded demo or PoC
→ GO / NARROW / PAUSE / KILL
→ product promotion only when warranted
```

A new session must not skip directly to inventing a replacement idea merely because the prior candidate is paused.

## Current queue

### A. Active / evidence-bearing

1. **Clinical AI Egress Control Plane** — `PROMOTED / PAUSED`
   - Current proposed identity: B63 under Issue #731.
   - Concept demo complete.
   - Technical direction narrowed to strong generic PII + clinical-context/quasi-identifier layer + false-positive reduction.
   - Next evidence: real hospital/HIS buyer and deployment validation.

2. **NIR Vein Intelligence → AI Venipuncture Training & Assessment / AI 정맥주사 실습·평가** — `RESEARCHING / NARROW`
   - 2026 revalidation completed in `research/BIO_001_NIR_VEIN_REVALIDATION_2026-08-26.md`.
   - PADIEM's 2015–2017 NIR vein / injection-assistance asset and patent-registration history are verified in current company records.
   - Generic patient-use clinical vein finder is **killed as the primary product thesis** because AccuVein / VeinViewer / iiSM VeinProbe and broad patent prior art already occupy the category.
   - Surviving wedge: education/research-first NIR venipuncture training, difficult-case visualization and objective learner assessment.
   - Public-data benchmark is feasible now using CUBITAL-style annotated forearm NIR data and nurse-selected access regions.
   - Next work: software-only segmentation / access-zone / subgroup-performance benchmark. No hardware build and no clinical efficacy claim yet.

### B. Unscreened / screening candidates

3. **Longitudinal Patient CareGraph** — `IDEA`
4. **Patient Communication AI** — `IDEA`
5. **Health-check Trend AI** — `IDEA`
6. **Rehab / Pose AI** — `SCREENING`; check overlap with Business 38 AI Exercise Coach.
7. **Medical Record Intelligence Workspace** — `IDEA`; check overlap with Living Archive / Research Memory / B63.
8. **Foreign Patient Medical Coordination** — `IDEA`; investigate reuse of PADIEM multilingual speech/translation/dubbing assets.
9. **Bio Evidence Graph / R&D Reproducibility Copilot** — `IDEA`; investigate ELN/LIMS/scientific-data-management competition and evidence-traceability wedge.

### C. Preserved but currently deprioritized

10. **Ambient Medical AI / Scribe** — `DEPRIORITIZED`
11. **AI Drug Discovery** — `DEPRIORITIZED`
12. **Radiology Diagnosis AI** — `DEPRIORITIZED`
13. **Genomics AI** — `DEPRIORITIZED`

Deprioritized does not mean impossible. It means the queue should not repeatedly restart from these broad categories until a new PADIEM asset, partner, dataset, grant call, or distinct product wedge changes the evidence.

## BIO-001 next benchmark gate

The next technical slice for BIO-001 is deliberately software-only.

```text
PUBLIC NIR FOREARM DATA
→ preprocessing baseline
→ U-Net-style published baseline
→ lightweight PADIEM candidate
→ vein mask / access-zone ranking / confidence
→ nurse-reference agreement
→ subgroup performance where metadata supports it
```

Required evaluation dimensions:

- Dice / segmentation F1;
- IoU;
- precision / recall;
- inference latency;
- nurse-selected access-region agreement where the dataset provides it;
- abstention / low-confidence failure rate;
- available complexion / demographic subgroup results without overclaiming fairness.

Do not promote BIO-001 to a numbered Business merely because the benchmark can be built. Promotion requires a technical advantage or a commercially meaningful education/evaluation workflow that survives the benchmark and buyer screen.

## Screening dimensions

Every candidate should be scored or at least explicitly assessed on these dimensions before product build:

1. **Existing market / prior art** — Is the category already commoditized or dominated?
2. **PADIEM-specific wedge** — What can PADIEM do that is more than generic LLM/RAG packaging?
3. **Reusable asset fit** — Existing IP, multimodal AI, speech/translation, connectors, verification, source grounding, workflow, local/runtime assets.
4. **Data accessibility** — Can meaningful validation be done with public/synthetic data before asking a hospital/lab partner for private data?
5. **Regulatory / safety boundary** — Medical device, diagnosis/treatment, PHI/privacy, research-only or workflow-software boundaries.
6. **Commercial buyer** — Named buyer/owner and plausible budget or PoC route.
7. **Government R&D fit** — Credible fit to national/regional R&D, demonstration, commercialization or healthcare-AI programs without distorting the product.
8. **Demo feasibility** — Can a truthful, useful visual/technical demo be built without pretending unresolved clinical evidence exists?

## Next-candidate rule

When the owner asks for the next Bio/Healthcare idea:

1. Read this queue first.
2. Select an existing unscreened candidate unless there is a specific reason to generate a new one.
3. Check Business Registry, GitHub repositories/issues, Drive/File Library and prior-session evidence for duplicates.
4. Research the candidate deeply enough to reach `GO`, `NARROW`, `PAUSE`, `KILL`, or `DUPLICATE`.
5. Update this queue and `IDEA_LEDGER.md` before moving to another candidate.

This prevents session-by-session re-invention and makes negative findings reusable R&D assets.
