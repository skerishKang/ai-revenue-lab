# BIO-016 — Korean Medical-Device RA/QA Review Packet v0.1

Status: **READY FOR QUALIFIED HUMAN REVIEW / RESEARCH ONLY**

Issue: #782  
Draft PR: #783

## 1. Purpose

Validate whether BIO-016's narrow output is useful to a qualified Korean medical-device RA/QA practitioner:

```text
exact AI/software change
+ versioned evidence inventory
→ candidate impacted evidence
→ stale/scope-mismatch candidates
→ candidate revalidation/document work
→ human RA/QA decision
```

This packet does **not** ask the reviewer to approve a product, determine legal compliance, or provide a regulatory filing opinion for a real device.

All product/change/evidence records are fictional synthetic research fixtures.

## 2. Reviewer profile

Preferred:

- Korean medical-device RA and/or QA experience;
- familiarity with software/digital medical devices, SaMD, AI medical devices or software validation;
- current or recent hands-on responsibility for change management, technical documentation, QMS, validation, cybersecurity or regulatory submissions.

Record only broad experience metadata needed to interpret the review:

```text
reviewer_code
RA_years_band
QA_years_band
software_medical_device_experience = YES/NO
AI_medical_device_experience = YES/NO
MFDS_change_management_experience = YES/NO
```

Do not collect employer-confidential information.

## 3. Research baseline

Use:

- `product_baseline.json`
- exact synthetic evidence inventory and its scope tokens;
- `source_manifest.json` only as public-source context.

The baseline is fictional `MEDDELTA-SYNTH` version 1.0.0.

## 4. Five-case blinded first pass

The reviewer should assess each case **before seeing BIO-016 predictions**.

### Case C01 — Model update

```text
classifier-1.0 → classifier-1.1
architecture unchanged
weights updated
```

Ask:

1. Which existing evidence records would you inspect first?
2. Which evidence might no longer cover the changed version/scope?
3. What revalidation/document work would you consider?
4. What additional context is required before deciding?
5. Which evidence should clearly *not* be reopened based only on this information?

### Case C05 — Intended-use expansion

```text
review-support-v1
→ recommendation-draft-v2
```

Same five questions.

### Case C06 — LLM provider/model swap

```text
provider-A / llm-A-1
→ provider-B / llm-B-2
```

Same five questions.

### Case C09 — Cybersecurity patch

```text
sec-lib-4.1
→ sec-lib-4.1.2
for a disclosed vulnerability
```

Same five questions.

This is intentionally a case where the current synthetic evidence inventory does not contain the exact security-component token. The reviewer should distinguish:

```text
class/work-area review needed
vs
specific existing evidence proven stale
```

### Case C20 — Internal-document typo only

```text
note-1.0
→ note-1.0.1
non-substantive spelling correction
```

Same five questions.

This is a hard-negative case. The benchmark should not turn every change into a broad revalidation event.

## 5. Stage 1 — Blind human baseline

For each case capture:

```text
reviewer_impacted_evidence_classes
reviewer_specific_evidence_ids_to_reopen
reviewer_specific_evidence_ids_still_current
reviewer_additional_information_needed
reviewer_candidate_work
reviewer_clear_non_impacts
reviewer_reasoning_short
review_time_seconds
confidence_1_5
```

Do not compare with `gold.json` during Stage 1.

## 6. Stage 2 — System-assisted review

After the blind response is locked, reveal the BIO-016 compiler output for that case.

For every suggested class/evidence relation ask the reviewer to mark:

```text
ACCEPT
REJECT
NEEDS_MORE_CONTEXT
```

Then ask:

- What did BIO-016 miss?
- What did it reopen unnecessarily?
- Did the exact evidence scope/version explanation make review easier?
- Would this output save meaningful time in a real change-impact workflow?
- What input fields would be mandatory in a real tool?
- Which outputs would be unsafe or misleading if shown without expert review?

Record second-pass time separately.

## 7. Research oracle boundary

`gold.json` is **not regulatory truth**. It is only the current software-mechanics oracle.

The qualified reviewer may disagree with it. Those disagreements are valuable evidence and should update the benchmark rather than be scored as reviewer error.

Current research-only prediction summary for later Stage 2 reveal is maintained in `RA_QA_REVIEW_KEY_RESEARCH_ONLY.md`.

## 8. Primary validation measures

Directional measures:

### A. Expert correction rate

```text
system suggestions rejected by expert
+
expert-required items missing from system
```

### B. Unnecessary reopen rate

How often BIO-016 labels an existing evidence record stale/reopen-worthy when the reviewer says it should remain current based on available context.

### C. Evidence recall

How much of the qualified reviewer's evidence set is surfaced by the system.

### D. Time usefulness

Compare:

```text
blind review time
vs
system-assisted correction/review time
```

Do not over-interpret a tiny N. Use time only as directional evidence.

### E. Context-deficiency rate

How often the correct expert response is:

```text
NEEDS_MORE_CONTEXT
```

A good product should make missing context visible rather than hallucinating a regulatory conclusion.

## 9. Decision gate

### GO_TO_PRODUCT_PROTOTYPE

Only if reviewers indicate that:

- exact evidence/version/scope mapping is materially useful;
- missing evidence is not systematically severe;
- unnecessary reopen noise is tolerable;
- the output reduces cognitive search/manual comparison effort;
- a real repeated workflow and buyer/user can be named;
- human authority boundaries remain clear.

### NARROW

Use if value is concentrated in one class of changes, such as:

- model/data changes;
- LLM/provider/prompt changes;
- post-market drift triggers;
- software/cybersecurity changes.

### ABSORB_INTO_B48_PROFILE

Use if the logic is useful but not a distinct medical-AI product/workflow.

### KILL_AS_STANDALONE

Use if expert review shows the mapping is too context-dependent, too noisy, or already trivial inside existing QMS/RA processes.

## 10. Forbidden conclusions

BIO-016 must not produce or imply:

```text
APPROVED
EXEMPT
NO_SUBMISSION_REQUIRED
MFDS_ACCEPTED
REGULATORY_COMPLIANT
```

Final interpretation belongs to qualified humans and relevant authorities.
