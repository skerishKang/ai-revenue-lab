# BIO-016 AI Change Impact & Revalidation Compiler — Synthetic Benchmark

Issue: #782

Status: **research scaffold only**. This is not regulatory advice, not a QMS, not a submission tool, and not an MFDS/FDA approval decision engine.

## Research question

Given an exact change to a fictional medical-AI software product and a versioned evidence inventory, can a deterministic compiler:

1. identify evidence classes plausibly affected by the change;
2. inspect exact evidence records and their version/scope tokens;
3. distinguish a directly stale/scope-mismatched evidence record from a class-level review candidate;
4. recognize a revert that returns to a scope already covered by current evidence;
5. identify candidate revalidation/document-review work;
6. preserve source/rationale references;
7. route regulatory judgment to a qualified RA/QA human rather than inventing approval authority?

## Important limitation

The benchmark `gold.json` is a **research oracle authored for testing the software mechanics**. It is not an official regulatory interpretation. A later qualified Korean medical-device RA/QA reviewer must correct it before any GO decision.

## Synthetic fixture

`MedDelta-SYNTH` is a wholly fictional AI-enabled digital medical-device software fixture. It does not represent a real product, patient, manufacturer, hospital, indication, clearance, approval or submission.

The benchmark contains 20 controlled change events including model, threshold, data, LLM/provider, prompt, cybersecurity, runtime, UI, hardware interface, intended-use, population and integration changes.

The baseline contains a versioned evidence inventory. Evidence records carry explicit scope tokens such as `classifier-1.0`, `threshold-0.65`, `provider-A`, `runtime-3.2`, `adults-18plus` and `device-adapter-1.0`.

## Evidence-level mechanics

The compiler first maps a synthetic change type to candidate evidence classes. It then checks each evidence record in those classes against exact before/after scope tokens.

Possible evidence relations are:

```text
STALE_OR_SCOPE_MISMATCH
COVERED_BY_CURRENT_SCOPE
CLASS_IMPACT_ONLY_REVIEW
```

A record is not marked stale merely because its class appears in an impact map. Direct staleness/scope mismatch requires the record to cover a before-token while failing to cover the corresponding after-token(s).

This distinction is important for cases such as:

- a model update where evidence explicitly scopes `classifier-1.0` but not `classifier-1.1`;
- a second input-device vendor where current evidence covers only the first adapter;
- a cybersecurity patch whose exact component is not represented in the current evidence scope, which therefore remains a class-level review rather than fake record-level staleness;
- a revert to `classifier-1.0`, where current evidence already covers the restored token.

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

- `product_baseline.json` — fictional product/version/evidence inventory with explicit evidence scopes.
- `changes.json` — 20 synthetic change deltas without expected outputs.
- `gold.json` — research-only expected affected evidence classes, exact stale evidence IDs and support labels.
- `source_manifest.json` — authoritative public sources used to define only high-level lifecycle/change-control concepts.
- `compiler.py` — deterministic change-type → class impact plus evidence-scope delta engine.
- `score.py` — compares class-level and exact stale-evidence-ID output with the research oracle.
- `tests/test_compiler.py` — boundary, evidence-scope and deterministic-behavior tests.

## Run

```bash
python compiler.py --baseline product_baseline.json --changes changes.json --out predictions.json
python score.py --gold gold.json --predictions predictions.json
python -m pytest -q
```

No network call or model/API key is required.

## What this benchmark can prove

- the evidence/version/scope object model is coherent;
- the compiler is deterministic;
- the compiler actually consumes the baseline evidence inventory rather than only memorizing a change-type lookup table;
- direct stale/scope mismatch can be separated from class-level review;
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
