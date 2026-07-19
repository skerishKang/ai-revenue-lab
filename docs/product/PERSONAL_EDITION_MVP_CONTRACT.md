# Personal Edition MVP Product Contract

## 1. Purpose

This contract defines what the first Personal Edition product must accept, produce, remember, and change. Implementation is conforming only when the complete two-edition loop satisfies this contract.

The contract is intentionally stricter than a generic writing prompt. It exists to make free-model output measurable, reviewable, and replaceable across providers.

## 2. Product promise

> Material intentionally supplied by a reader is transformed into a polished personal publication. The next edition visibly responds to the reader's feedback without inventing personal facts.

The product is not:

- a raw chat transcript;
- generic advice;
- meeting minutes;
- a psychological profile;
- an automated biography;
- a factual claim generator beyond supplied material.

## 3. Edition sequence

Each participant owns one ordered edition sequence.

Rules:

- edition numbers begin at 1;
- each edition is based on one or more approved input records;
- edition 2 and later may reference one prior published edition and its feedback;
- unpublished or rejected drafts do not advance the public edition number;
- feedback always identifies the edition to which it responds;
- deleted participant data is not reused.

## 4. Input contract

### 4.1 EditionInput

Conceptual schema:

```json
{
  "participant_id": "internal-id",
  "input_id": "internal-id",
  "language": "ko",
  "raw_text": "user supplied material",
  "submitted_at": "ISO-8601 timestamp",
  "consent_confirmed": true,
  "preferences": {
    "tone": "calm_editorial",
    "length": "standard",
    "practicality": 0.5,
    "reflection": 0.5,
    "excluded_topics": []
  },
  "prior_edition": null,
  "feedback": null
}
```

### 4.2 Input rules

- input must be intentionally supplied by the participant;
- supported pilot languages are Korean and English;
- empty or whitespace-only input is rejected;
- default minimum length is 500 words unless an administrator explicitly approves a shorter sample;
- default maximum length is 5,000 words per generation request;
- raw input is normalized without changing meaning;
- secrets, credentials, and unnecessary third-party private details should be removed before generation;
- consent confirmation is required for every first input and retained for the pilot.

### 4.3 Segmenting

Normalized input is divided into stable segments before model use.

Example:

```json
[
  {
    "segment_id": "s001",
    "text": "...",
    "start_offset": 0,
    "end_offset": 248
  },
  {
    "segment_id": "s002",
    "text": "...",
    "start_offset": 249,
    "end_offset": 511
  }
]
```

Generated plans and claims reference these identifiers. Segment identifiers are audit metadata and are not normally shown to the reader.

## 5. Feedback contract

### 5.1 FeedbackInput

```json
{
  "edition_id": "internal-id",
  "direction": ["more_reflective", "deeper_on_section"],
  "selected_section_id": "section-2",
  "free_text": "Tomorrow focus more on why the idea changed.",
  "tone_override": null,
  "length_override": null,
  "submitted_at": "ISO-8601 timestamp"
}
```

### 5.2 Allowed direction values

- `continue_direction`;
- `more_practical`;
- `more_reflective`;
- `deeper_on_section`;
- `reduce_topic`;
- `exclude_topic`;
- `shorter`;
- `longer`;
- `change_tone`.

The application may add values later only through an explicit contract revision.

### 5.3 Material application requirement

Edition 2 and later must contain an `applied_feedback` record.

```json
{
  "feedback_id": "internal-id",
  "action": "Expanded the explanation of how the business idea changed from speed to personalization.",
  "affected_section_ids": ["section-1", "section-3"],
  "evidence": "The selected sections contain new analysis not present in the prior edition while remaining grounded in the new input and feedback."
}
```

A claim that feedback was applied is invalid when the visible edition remains materially unchanged.

## 6. Editorial plan contract

### 6.1 EditorialPlan

```json
{
  "plan_version": "personal-edition-v1",
  "language": "ko",
  "central_theme": "string",
  "reader_value": "string",
  "opening_intent": "string",
  "sections": [
    {
      "section_id": "section-1",
      "working_title": "string",
      "purpose": "string",
      "source_segment_ids": ["s001", "s003"],
      "allowed_interpretations": ["string"],
      "prohibited_inferences": ["string"],
      "feedback_action": null
    }
  ],
  "continuity": {
    "prior_edition_references": [],
    "applied_feedback": null
  },
  "uncertain_or_excluded_material": [],
  "highlighted_insight": "string",
  "next_edition_prompt": "string"
}
```

### 6.2 Editorial plan requirements

- two to four planned sections;
- every section references at least one valid input segment;
- interpretations are separated from direct statements;
- uncertain material is excluded or clearly marked;
- no medical, legal, financial, diagnostic, or crisis guidance;
- no invented personal relationship, motivation, event, or memory;
- follow-up editions identify the feedback action;
- the plan has a coherent editorial angle rather than summarizing every input sentence.

## 7. Edition content contract

### 7.1 EditionContent

```json
{
  "content_version": "personal-edition-v1",
  "language": "ko",
  "publication_title": "string",
  "edition_title": "string",
  "deck": "string",
  "opening": "string",
  "sections": [
    {
      "section_id": "section-1",
      "title": "string",
      "paragraphs": ["string", "string"],
      "source_segment_ids": ["s001", "s003"],
      "contains_interpretation": true
    }
  ],
  "highlighted_insight": "string",
  "continuity_note": "string",
  "applied_feedback": null,
  "next_edition_prompt": {
    "question": "string",
    "choices": ["string", "string"]
  },
  "provenance_note": "This edition was created from material supplied by the reader."
}
```

### 7.2 Visible output requirements

The edition must include:

- publication identity;
- edition number and date supplied by the application;
- title and deck;
- opening paragraph;
- two to four sections;
- highlighted insight;
- continuity note for edition 2 and later;
- optional next-edition question;
- provenance note;
- feedback interface.

### 7.3 Length limits

Default Korean edition target:

- 700 to 1,400 Korean words or an equivalent configured character range;
- opening: one to three paragraphs;
- each section: one to four paragraphs;
- title: no more than 80 visible characters;
- deck: no more than 180 visible characters;
- next-edition question: no more than 200 visible characters.

The implementation may use language-specific character thresholds but must test them deterministically.

### 7.4 Style requirements

The edition should:

- read as an edited publication;
- use coherent paragraphs rather than excessive bullets;
- preserve the participant's intended meaning;
- explain development or significance where supported;
- avoid repetitive praise and generic motivational language;
- avoid pretending to know the participant beyond supplied material;
- avoid phrases that reveal internal prompts, models, or validation rules;
- avoid overusing the participant's name;
- maintain a consistent voice across one edition.

## 8. Grounding contract

### 8.1 Direct statement

A direct statement is information explicitly present in an input segment or approved prior edition.

### 8.2 Interpretation

An interpretation connects supplied information without adding an unsupported event or fact.

Example allowed interpretation:

> The conversation appears to move from speed as the main advantage toward personalization as the larger economic idea.

This is allowed only when the relevant input segments demonstrate that progression.

### 8.3 Prohibited invention

Critical failures include:

- inventing a place, date, amount, relationship, diagnosis, intention, or event;
- attributing a statement to the participant that they did not make;
- claiming emotional certainty not supported by the input;
- adding external factual claims without an approved source workflow;
- manufacturing continuity from a prior edition that does not exist.

One critical invention is sufficient to reject the draft.

## 9. Validation contract

A draft is rejected before human review when any of the following occurs:

- invalid JSON or schema mismatch;
- unknown input segment reference;
- missing required section;
- unsupported named entity, date, amount, or relationship;
- visible HTML, script, iframe, event handler, or unsafe URL;
- prohibited guidance category;
- length outside hard bounds;
- follow-up edition without an applied feedback record when feedback exists;
- provenance note omitted;
- provider response contains refusal or internal error text instead of edition content.

Warnings that do not automatically reject may include:

- repetitive language;
- weak distinction from a summary;
- excessive generic praise;
- low novelty from the prior edition;
- insufficient visible feedback adaptation;
- style drift.

Warnings remain visible to the human reviewer.

## 10. Human review contract

During the pilot, a reviewer can:

- approve unchanged;
- edit and approve;
- reject and regenerate;
- reject without regeneration.

The system records:

- reviewer action;
- correction duration;
- fields materially edited;
- critical or noncritical defect category;
- final publication timestamp.

Substantial rewriting means the reviewer changed the central angle, added or removed a section, corrected an invented fact, or rewrote more than a configured portion of visible text.

## 11. Quality rubric

Each edition is scored on 100 points.

### Grounding and personal-fact safety — 30

- no critical invention: mandatory;
- claims trace to supplied segments;
- interpretations are supportable;
- uncertainty is handled correctly.

### Personalization and continuity — 20

- reflects actual preferences;
- edition 2+ materially applies feedback;
- continuity is accurate;
- output is not interchangeable with another participant's edition.

### Editorial quality — 20

- clear angle;
- coherent structure;
- readable prose;
- strong title and opening;
- meaningful selection rather than exhaustive summary.

### Product distinction — 15

- feels like a publication rather than chat;
- provides a persistent, shareable reading object;
- has a deliberate ending and next-edition bridge.

### Schema and operational compliance — 10

- valid structured output;
- correct identifiers;
- required fields;
- length and formatting compliance.

### Safety and privacy language — 5

- no prohibited advice;
- no unnecessary sensitive repetition;
- correct provenance and interpretation boundaries.

Minimum pilot publication score: 80, with no critical grounding failure.

## 12. Test fixtures

Development fixtures must be synthetic or explicitly approved and redacted.

At least three fixture families are required:

### Founder conversation

A conversation in which a business idea develops over time, contains repeated thoughts, and requires editorial selection.

### Travel preference journal

A traveler initially asks for famous destinations, then reveals preferences for local food, quiet places, solo travel, or specific routines.

### Place and memory note

A person describes one ordinary place with different personal meanings across time, without inviting the system to invent missing memories.

Each family requires:

- first-edition input;
- expected allowed facts;
- prohibited inventions;
- feedback;
- second-edition input or instruction;
- expected material adaptation;
- quality rubric notes.

## 13. Acceptance scenarios

### Scenario A: first edition

Given a valid first input, when generation succeeds, then the application creates a validated draft with no prior-edition continuity claim.

### Scenario B: feedback-responsive second edition

Given a published first edition and feedback requesting a deeper explanation of one section, when the second edition is generated, then the plan and visible content identify and implement that request.

### Scenario C: unsupported personal fact

Given an input that never mentions a spouse, when a provider invents a spouse, then deterministic or review validation rejects the draft.

### Scenario D: provider invalid JSON

Given a provider response that is not valid structured output, then the run is recorded as failed and no draft is published.

### Scenario E: participant isolation

Given two participant access tokens, when one token requests the other's edition, then access is denied without revealing whether the edition exists.

### Scenario F: deletion

Given a deletion request confirmed by an administrator, when deletion completes, then raw input and private editions are removed or irreversibly anonymized according to the pilot policy.

## 14. Contract versioning

Prompt versions, plan schemas, and content schemas are versioned independently.

A published edition stores the versions used to create it. Contract changes that alter required fields or grounding behavior require:

- a document update;
- migration or backward-compatibility decision;
- fixture updates;
- tests demonstrating old-data handling;
- benchmark re-evaluation for approved providers.
