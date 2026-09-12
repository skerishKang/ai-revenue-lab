# BIO-017 Autonomous Bio Lab Evidence Chain Guard — Deep Screen

- Date: 2026-08-26
- Status: `KILL_GENERIC / NARROW_TO_PARTNER_LED_R&D`
- Business number: NONE
- Deployment: none

## Original thesis

Independently verify that every AI-generated experimental decision remains traceable through protocol, instrument execution, sample/batch, raw data, analysis and next-experiment recommendation.

## Internal overlap

PADIEM already has reusable generic components:

- B48 Verification Engine — exact-version claims/checks/evidence/exceptions;
- Business 33 Research Memory — claim/source/revision/unresolved research continuity;
- Bio Evidence Graph concept — experiment/sample/protocol/raw-data/analysis links;
- Event Story / agent-audit patterns.

A generic scientific provenance graph is therefore not enough internally either.

## 2026 policy and research signal

The problem is real and current:

- Korea's 2026 `AI-네이티브 첨단바이오 자율실험실` programme makes autonomous experimentation a national R&D direction.
- 2026 autonomous-science literature increasingly treats provenance-aware, verifiable policies as necessary for debugging, reproducibility and safe operation.
- recent work on `Instrument Traces` argues that active/autonomous experimentation creates an additional scientific record: the experimental trajectory. It proposes synchronized sample, instrument and decision traces.

Representative sources:

- 2026 IRIS AI-native advanced-bio autonomous-laboratory call;
- https://arxiv.org/abs/2608.23039
- https://arxiv.org/abs/2601.17920

## External competition / category maturity

Generic lineage/data-platform territory is already strong:

### Benchling

2026 Benchling Automation connects 200+ instruments to scientific records, runs analyses and feeds results into subsequent decisions. It explicitly preserves traceability from results to source samples and experiments.

Sources:
- https://www.benchling.com/blog/benchling-automation-closing-the-lab-in-a-loop
- https://www.benchling.com/automation

### TetraScience

Universal SDMS provides full scientific-data lineage, provenance, audit trails and chain of custody. AI Services adds workflow registration/versioning, production/evaluation controls and operational auditability.

Sources:
- https://www.tetrascience.com/platform/universal-sdms
- https://developers.tetrascience.com/docs/tetrascience-ai-services

### Dotmatics

Luma/Luma Agent already positions experiment lineage and audit-ready report generation as a core capability, with logged actions and explicit approval for writes.

Sources:
- https://www.dotmatics.com/
- https://www.dotmatics.com/luma/artificial-intelligence

Therefore:

```text
GENERIC_ELN_LIMS_SDMS = KILL
GENERIC_SCIENTIFIC_DATA_LINEAGE = KILL
GENERIC_EXPERIMENT_PROVENANCE_GRAPH = TOO_BROAD
```

## Surviving wedge — Closed-Loop Decision Provenance Verifier

The narrower question is not whether data lineage exists. It is whether the **AI decision that closes the loop** is justifiably and reproducibly linked to the physical experiment that occurred.

Verification chain:

```text
AI next-experiment proposal
→ decision rationale / uncertainty / constraints
→ approved protocol version
→ sample / batch identity
→ instrument command
→ actual execution log
→ raw-data fingerprint
→ processing / analysis code + model version
→ result/statistical evidence
→ next recommendation
→ human override / approval
```

Potential failures:

- recommendation references the wrong sample/batch;
- protocol version differs from executed protocol;
- instrument command differs from approved plan;
- raw data missing or fingerprint mismatch;
- analysis uses an unrecorded code/model version;
- next experiment has no traceable supporting result;
- safety/feasibility constraint is violated;
- human override occurred but was not recorded;
- failed/tuning runs disappear from the scientific record.

This is closer to **independent closed-loop evidence integrity** than another scientific data platform.

## Why standalone commercialization is not yet strong

Benchling, TetraScience and Dotmatics are rapidly moving from data management into AI-enabled closed-loop workflows. A standalone horizontal platform would face large integration and procurement barriers.

The narrower verifier still needs domain-specific semantics and real instrument/workflow access, which PADIEM does not currently possess.

Thus:

```text
STANDALONE_PRODUCT_NOW = NO
PARTNER_LED_R&D_VALUE = HIGH
GOVERNMENT_CONSORTIUM_FIT = HIGH
SYNTHETIC_DEMO_FEASIBLE = YES
REAL_VALIDATION_WITHOUT_LAB_PARTNER = NO
```

## First technical validation

Before any real integration, build a synthetic event-chain benchmark with intentionally broken provenance.

Example event classes:

```text
proposal
protocol_approval
sample_binding
instrument_command
instrument_execution
raw_data_created
analysis_started
analysis_output
recommendation_created
human_override
```

Inject failures:

- orphan proposal;
- sample mismatch;
- protocol mismatch;
- missing execution event;
- raw-data hash mismatch;
- wrong analysis version;
- unsupported recommendation;
- missing override;
- out-of-order impossible event;
- hidden failed run.

Metrics:

```text
BROKEN_CHAIN_RECALL
FALSE_ALARM_RATE
ROOT_CAUSE_LOCALIZATION
MISSING_EVENT_DETECTION
VERSION_MISMATCH_DETECTION
DECISION_SUPPORT_TRACE_COMPLETENESS
```

This only proves the evidence model, not scientific validity.

## Ideal partner

- university self-driving-lab group;
- biotech automation laboratory;
- lab-automation vendor;
- research institute participating in AI-native advanced-bio R&D;
- ELN/LIMS/SDMS integrator seeking an independent verification layer.

## Current verdict

```text
BIO_017_GENERIC_EVIDENCE_CHAIN_GUARD = NARROW
SURVIVING_WEDGE = CLOSED_LOOP_DECISION_PROVENANCE_VERIFIER
PRODUCT_MODE = PARTNER_LED_R&D_MODULE
NEW_BUSINESS_NUMBER = NO
NEXT_GATE = SYNTHETIC_BROKEN_CHAIN_BENCHMARK + LAB_PARTNER_DISCOVERY
PRIORITY_BELOW_BIO_016 = YES
```
