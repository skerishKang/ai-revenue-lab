# Reference notes

Research date: 2026-07-29

This reference uses primary or official guidance only as conceptual input. It does not reproduce an agency interface, logo, dispatch code, proprietary protocol, record or operating screen.

## 1. National 911 Program — Calling 911 / FAQ

Source: National 911 Program, `911.gov/calling-911/` and FAQ.

Adopted:
- Separate location, nature of incident and details into explicit information fields.
- Keep questions visible as information-gathering prompts rather than as evidence that an event is verified.
- Preserve the distinction between caller/source statements and agency-confirmed facts.

Rejected:
- Live-call simulation, operator instructions, active-call timer, emergency number branding and any implication that this visual reference can obtain help.

## 2. FEMA / U.S. Fire Administration — NIMS Command and Coordination

Source: FEMA/USFA, “National Incident Management System: Command and Coordination.”

Adopted:
- Explicit separation between information gathering, analysis, policy guidance and operational authority.
- Human authority and formal handoff boundaries remain visible at every state.
- Common operating information should preserve limits and exceptions rather than collapse them.

Rejected:
- Incident-command hierarchy replication, resource ordering, tactical action controls, command transfer UI or operational forms.

## 3. CISA — National Emergency Communications Plan

Source: Cybersecurity and Infrastructure Security Agency, National Emergency Communications Plan.

Adopted:
- Clear provenance, consistent information structure and cross-role readability.
- Critical information should reach the right human role while preserving governance and accountability.

Rejected:
- Communications-system connectivity, dispatch interoperability, alerts, radio/network controls and real-time information exchange.

## 4. W3C — PROV-O / PROV family

Source: W3C Recommendation, PROV-O and PROV Overview.

Adopted:
- Show origin, transformation, responsibility and derivation of a source statement.
- Treat provenance as first-class review data, not hidden metadata.
- Keep a visible correction/derivation trail from source wording to human-reviewed wording.

Rejected:
- Exposing ontology syntax, RDF identifiers or technical provenance graphs to the review user.

## 5. NIST AI RMF 1.0 and FDA human-factors guidance

Sources: NIST AI RMF 1.0; FDA, Applying Human Factors and Usability Engineering to Medical Devices.

Adopted:
- Human-in-the-loop authority, visible uncertainty, testable boundaries and explicit non-actions.
- Design high-consequence review controls to reduce use error, false precision and automation bias.
- Confirmation occurs through a human correction record rather than an opaque model decision.

Rejected:
- Medical-device framing, clinical claims, diagnosis, treatment advice, AI model execution or claims that the interface is safe/effective for real emergencies.

## Adopted visual patterns

- incident-review folio and source-provenance strip;
- observable indicator cards separated from interpretation;
- conflict split and uncertainty ledger;
- clarification slips that never instruct delay;
- provisional rationale with escalation/downgrade review boundaries;
- human-correction tape and human-only authority seal;
- dispatch-authority hold card;
- persistent uncertainty after completion.

## Rejected patterns

- red alert scoreboard, countdown, threat heatmap, hospital monitor or dispatch map;
- single urgency/risk score, confidence presented as certainty or missing data treated as safety evidence;
- demographic, neighborhood, language, disability, occupation or other proxy inference;
- live microphone, GPS, call, sensor, health-data or provider-model UI;
- promises of response time, survival, correctness or safety.

## Difference from Business 39

Business 39 preserves bilingual meaning and human correction during interpretation. Business 40 begins after meaning has been preserved and organizes urgency-related evidence and uncertainty. It does not translate, infer language quality or assign urgency from language.

## Difference from Business 41

Business 41 is a user-side preparation surface for structuring an emergency report before official-service handoff. Business 40 is a professional-side evidence review surface. It does not impersonate a caller, connect to services or prepare a user script.

## Difference from medical triage

This reference does not diagnose, predict prognosis, recommend treatment, process symptoms into a clinical category or replace qualified clinical assessment. The fixture states only that no injury is verified; it does not infer health status.

## Difference from dispatch systems

This reference does not connect calls, locate incidents, choose units, allocate resources, create alerts, issue dispatch codes or control any operational system. Final priority and all response authority remain with authorized humans outside this reference.
