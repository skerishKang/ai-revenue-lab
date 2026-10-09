# BIO-015 Clinical AI Shadow Lab / AI Native HIS Agent Sandbox — Deep Screen

- Date: 2026-08-26
- Status: `KILL_GENERIC / ABSORB_AS_HEALTHCARE_VERIFICATION_PROFILE`
- Business number: NONE
- Deployment: none

## Original thesis

Before a hospital or HIS vendor lets an AI agent act inside a live workflow, replay synthetic/de-identified events in shadow mode and inspect data access, tool calls, proposed actions, policy violations, evidence and human override.

## Internal overlap

PADIEM already has most generic governance primitives:

- B42 AI Development Control Tower — exact source/work-order/role/gate authority;
- B48 AI Verification Engine — exact artifact, claims, checks, evidence, exceptions and human approval;
- B63 Clinical AI Egress — healthcare-specific data egress/policy/audit;
- Event Story Engine — chronological evidence/replay grammar.

Therefore `medical version of B42/B48` is not enough to justify a new Business.

## 2026 external prior art / competition

The generic sandbox thesis is already directly occupied:

- Astral (AMIA 2026) proposes a secure sandbox for medical AI agents, with MCP orchestration, RBAC/OAuth identity, auditable agent actions and controlled simulations.
- H-AdminSim (CHIL 2026) provides a FHIR-integrated multi-agent simulator for realistic hospital administrative workflows and rubric-based evaluation.
- AgentClinic and other clinical-agent benchmarks already simulate tool-using clinical workflows.
- healthcare digital-twin/testbed work is explicitly targeting agent interaction with sensitive healthcare workflows.
- Pacific AI Gatekeeper is positioned as a pre-release healthcare AI testing gate, with clinical, bias, adversarial and regulatory test suites.

Sources reviewed include:

- https://pmc.ncbi.nlm.nih.gov/articles/PMC13274365/
- https://proceedings.mlr.press/v333/lee26a.html
- https://github.com/ljm565/H-AdminSim
- https://pacific.ai/gatekeeper/
- https://docs.pacific.ai/

## Policy / support signal

The opportunity signal is still real:

- KHIDI's 2026 `AI 지능형 병원정보시스템(AI Native HIS) 기획` shows that AI-native hospital workflows are now a Korean policy/design topic.
- healthcare governance literature increasingly treats action-level constraints, escalation, pause/redirect/suspend and traceable control points as necessary for agentic AI.

The signal validates the problem, not a generic sandbox product.

## Verdict

```text
GENERIC_CLINICAL_AI_AGENT_SANDBOX = KILL_AS_NEW_STANDALONE_THESIS
GENERIC_LLM_EVAL = KILL
NEW_BUSINESS_NUMBER = NO
PADIEM_REUSE_VALUE = HIGH
KOREAN_HIS_DOMAIN_PROFILE = WORTH_RESEARCH
```

## Surviving wedge — Korean HIS Agent Site Acceptance & Replay

Treat this as a healthcare-specific verification profile built from B48 + B42 + B63 rather than a new general platform.

Possible acceptance object:

```text
site-specific synthetic/de-identified FHIR/HIS workflow
→ agent observes / proposes action
→ action not executed
→ compare with expected human/policy path
→ data-access trace
→ tool-call trace
→ authorization / reversibility check
→ evidence/source check
→ human override / escalation check
→ replayable incident
→ site acceptance report
```

The distinctive object is not `model score`; it is **site-specific workflow/action acceptance evidence**.

## BIO-018 disposition

`Clinical AI Incident Replay / Near-Miss Story` should be a function inside this healthcare verification profile:

```text
source state
→ agent context
→ tool/action proposal
→ policy/gate state
→ human response
→ downstream effect
→ corrective control
```

Do not create BIO-018 as a separate Business.

## First technical validation if revisited

Build only after BIO-016 and BIO-003 higher-priority gates unless a HIS/hospital partner appears.

Synthetic validation could contain 10–20 FHIR-like workflows with deliberately injected failures:

- unauthorized data access;
- wrong patient/context object;
- missing human approval;
- irreversible tool call attempted;
- unsupported recommendation;
- stale policy/version;
- unsafe escalation omission;
- correct abstention.

Metrics:

```text
unsafe_action_detection_recall
policy_violation_recall
false_block_rate
missing_evidence_detection
human_override_detection
trace_completeness
replay_reconstruction_accuracy
```

## Buyer / partner

Potential buyers/partners:

- hospital digital-transformation / IT team;
- HIS vendor;
- medical-AI vendor integrating agents;
- AI Native HIS R&D consortium.

A real standalone purchase owner is not yet proven.

## Final disposition

```text
BIO_015 = ABSORB / RESEARCH_PROFILE
BIO_018 = ABSORB_INTO_BIO_015_PROFILE
FULL_PRODUCT_BUILD = NO
HOSPITAL_PARTNER = NEEDED_BEFORE_SERIOUS_BUILD
```
