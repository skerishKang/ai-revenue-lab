# BIO-016 AI Change Impact & Revalidation Compiler — Synthetic Benchmark

Issue: #782

Status: **research scaffold only**. This is not regulatory advice, not a QMS, not a submission tool, and not an MFDS/FDA approval decision engine.

## Research question

Given an exact change to a fictional medical-AI software product and a versioned evidence inventory, can a deterministic compiler:

1. identify evidence classes plausibly affected by the change;
2. detect evidence that is stale or scope-mismatched against the new version;
3. identify candidate revalidation/document-review work;
4. preserve source/rationale references;
5. route regulatory judgment to a qualified RA/QA human rather than inventing approval authority?

## Important limitation

The benchmark `gold.json` is a **research oracle authored for testing the software mechanics**. It is not an official regulatory interpretation. A later qualified Korean medical-device RA/QA reviewer must correct it before any GO decision.

## Synthetic fixture

`MedDelta-SYNTH` is a wholly fictional AI-enabled digital medical-device software fixture. It does not represent a real product, patient, manufacturer, hospital, indication, clearance, approval or submission.

The benchmark contains 20 controlled change events including model, threshold, data, LLM/provider, prompt, cybersecurity, runtime, UI, hardware interface, intended-use, population and integration changes.

## Output vocabulary

The compiler may emit only support-oriented labels:

```text
REVIEW_REQUIRED
REVALIDATION_CANDIDATE
DOCUMENT_UPDATE_CANDIDATE
EVIDENCE_STALE_OR_SCOPE_MISMATCH
NO_ADDITIONAL_ACTION_IDENTIFIED_BY_RULESET
RA_QA_DECISION_REQUIRED
```

It must never emit `APPROVED`, `EXEMPT`, `NO_SUBMISSION_REQUIRED`, or an equivalent regulatory conclusion.

## Files

- `product_baseline.json` — fictional product/version/evidence inventory.
- `changes.json` — 20 synthetic change deltas without expected outputs.
- `gold.json` — research-only expected affected evidence classes and support labels.
- `source_manifest.json` — authoritative public sources used to define only high-level lifecycle/change-control concepts.
- `compiler.py` — deterministic change-type/tag → candidate evidence-impact engine.
- `score.py` — compares compiler output with the research oracle.
- `tests/test_compiler.py` — boundary and deterministic-behavior tests.

## Run

```bash
python compiler.py --baseline product_baseline.json --changes changes.json --out predictions.json
python score.py --gold gold.json --predictions predictions.json
python -m pytest -q
```

No network call or model/API key is required.

## What this benchmark can prove

- the evidence/version object model is coherent;
- the compiler is deterministic;
- unsupported change classes fail safely to human review;
- stale-evidence and candidate-revalidation outputs can be scored reproducibly;
- no forbidden regulatory-authority label is emitted.

## What it cannot prove

- that the research oracle is legally/regulatorily correct;
- that a particular change requires or does not require a submission;
- that an MFDS/FDA reviewer would accept the output;
- clinical safety/effectiveness;
- commercial value.

## Human gate

Before product promotion:

```text
QUALIFIED_KOREAN_RA_QA_REVIEW = REQUIRED
BUSINESS_NUMBER = NONE
PRODUCTION = NO
DEPLOYMENT = NONE
ISSUE_778_PORTAL_MUTATION = NO
```
