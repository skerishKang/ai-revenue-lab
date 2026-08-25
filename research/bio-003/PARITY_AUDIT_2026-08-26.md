# BIO-003 Information-Parity Audit — 2026-08-26

Status: **CLOSED AT SYNTHETIC MECHANICS LEVEL**

Issue: #772  
Draft PR: #774

## Why this audit was required

The experiment claims to compare presentation formats using information-equivalent underlying facts:

```text
summary
vs timeline
vs source-grounded story
```

A review found that this claim was not fully true in the original fixture. In Case B, the timeline omitted at least two canonical facts that were present in summary/story:

- discomfort when gripping/twisting;
- the plan to review the prior X-ray result together with the symptom log at follow-up.

That defect could confound any later human result: a story condition might appear better because it contained more information, not because its structure/provenance grammar helped memory or source attribution.

## Correction

Case B timeline was updated to restore the missing facts.

The repair was then generalized into a persistent parity contract rather than relying on manual review.

Added:

- `fact_coverage.json`
  - canonical fact IDs for every case;
  - per-condition anchor text for every fact;
- `question_fact_map.json`
  - minimum canonical facts required to answer every validation question;
- stronger `tests/test_score.py` contracts.

## Mechanical checks now required

For every synthetic case:

```text
canonical facts in cases.json
=
canonical facts in fact_coverage.json
```

For every condition:

```text
summary / timeline / story
must each expose every canonical fact
and each declared fact anchor must exist in the actual rendering text
```

For every question:

```text
question
→ minimum required canonical facts
→ facts must belong to that case
→ every condition must contain those facts
```

The experiment intentionally does **not** require identical wording or identical provenance presentation. Explicit provenance labels are part of the My Health Story treatment being tested. The parity requirement is factual availability, not presentation identity.

## Independent mechanics check

After the repair, an independent execution of the parity/scoring mechanics confirmed:

```text
CASES = 3
CANONICAL_FACTS_PER_CASE = 8
TOTAL_CANONICAL_FACTS = 24
QUESTION_FACT_MAP_ENTRIES = 18
ALL_FACT_ANCHORS_PRESENT_IN_SUMMARY = YES
ALL_FACT_ANCHORS_PRESENT_IN_TIMELINE = YES
ALL_FACT_ANCHORS_PRESENT_IN_STORY = YES
ALL_QUESTION_FACT_DEPENDENCIES_PRESENT_IN_EVERY_CONDITION = YES
SCORER_PRIMITIVES = PASS
COUNTERBALANCING = PASS
```

This is an independent software/fixture mechanics check, not exact-head GitHub Actions CI and not evidence that My Health Story improves human outcomes.

At the checked head, GitHub returned no pull-request workflow runs for this research branch.

```text
EXACT_HEAD_GITHUB_ACTIONS = NOT_CONFIGURED / 0 RUNS
HUMAN_PARTICIPANT_RESULT = NONE
PRODUCT_BENEFIT_CLAIM = NOT ESTABLISHED
```

## Gate status

The original information-parity blocker is closed.

Next valid step:

```text
bounded synthetic participant pilot
→ immediate recall/source-attribution
→ delayed recall/follow-up memory
→ condition-level descriptive comparison
→ GO / NARROW / ABSORB / KILL
```

No real patient data, medical records, diagnosis generation or treatment recommendation is authorized by this audit.
