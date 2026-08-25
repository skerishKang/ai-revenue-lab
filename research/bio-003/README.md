# BIO-003 My Health Story Validation Pack

Status: **synthetic / dataset-free / non-clinical product-validation scaffold**.

Issue: #772

## Product question

Does a source-grounded episodic visit story improve **source attribution** and **follow-up memory** compared with an information-equivalent conventional after-visit summary or chronological timeline?

This pack does not test diagnosis, treatment, medication decisions, emergency classification, clinical efficacy, or hospital integration.

## Conditions

Each synthetic case uses the same atomic facts in three representations:

- `summary` — conventional patient-facing after-visit summary;
- `timeline` — chronological event cards;
- `story` — My Health Story chapters with explicit provenance labels.

The first test deliberately minimizes cinematic/physical-book effects. It tests information architecture and trust/memory, not visual preference.

## Files

- `cases.json` — three fictional source bundles plus information-equivalent A/B/C renderings;
- `questions.json` — deterministic task/question bank and answer keys;
- `counterbalancing.json` — three-group case/condition rotation;
- `responses.schema.csv` — question-response capture schema;
- `case_ratings.schema.csv` — cognitive-load/usefulness capture schema;
- `score.py` — deterministic item scorer;
- `analyze.py` — condition-level descriptive analysis;
- `tests/test_score.py` — synthetic-only contract tests.

## Synthetic cases

- `A`: conversation-heavy sleep/stress consultation;
- `B`: test/instruction-heavy hand-pain visit;
- `C`: document/numeric-heavy routine checkup.

Every person, institution, number and event is fictional. Do not replace these fixtures with real patient records in this repository.

## Response encoding

`response_json` must contain valid JSON.

Examples:

```text
single choice: "CLINICIAN_SAID"
multi-select: ["action A","action B"]
sequence: ["event 1","event 2","event 3"]
```

## Run

```bash
python -m pip install -r requirements.txt
python -m pytest -q
python score.py --questions questions.json --responses responses.csv --out scored.csv
python analyze.py --scored scored.csv --ratings case_ratings.csv
```

## Pilot decision vocabulary

```text
GO_TO_PRODUCT_PROTOTYPE
NARROW
ABSORB_AS_CAPABILITY
KILL_AS_STANDALONE
```

Preference alone is never a GO criterion. The primary signals are source-attribution accuracy and follow-up-action recall, with factual errors/false recall treated as a hard counter-signal.

## Safety

```text
REAL_PATIENT_DATA = NO
REAL_CONSULTATION_AUDIO = NO
REAL_PRESCRIPTION = NO
REAL_MEDICAL_BILL = NO
DIAGNOSIS_GENERATION = NO
TREATMENT_RECOMMENDATION = NO
BUSINESS_NUMBER = NONE
PRODUCTION = NO
```
