# Model Change Owner Approval Policy

- Status: **CANONICAL REPOSITORY OPERATING POLICY**
- Effective: 2026-10-06
- Last reconciled: 2026-10-08 (#3554, #3523)
- Owner authority: Product Owner
- Tracking issue: #3571

## 0. Scope clarification — per-execution user choice is not a model decision

Additive clarification. It **narrows an ambiguity** in sections 1-3 and **weakens no**
owner gate. Sections 5, 8 and 10 are unchanged and remain fully in force.

An end user selecting, per execution, one model that is **already registered and allowed in the
B14 catalog** is product runtime input, not an agent/owner model decision. The agent, Web CTO,
worker, validator and reviewer do not choose, rank, benchmark or pre-approve that choice, and no
repository development step is gated on it.

    PER_EXECUTION_USER_MODEL_CHOICE=NOT_A_MODEL_POLICY_CHANGE
    MODEL_DECISION_REQUIRED_FOR_PER_EXECUTION_USER_CHOICE=NO
    STOP_AND_ASK_OWNER_FOR_PER_EXECUTION_USER_CHOICE=NO
    REPEATED_OWNER_APPROVAL_FOR_REGISTERED_MODEL_USE=NOT_REQUIRED
    SINGLE_PRIMARY_REQUIRED=NO
    SUCCESSOR_SELECTION_REQUIRED_BEFORE_MVP=NO
    GLOBAL_REPRESENTATIVE_MODEL_REQUIRED=NO
    BENCHMARK_REQUIRED_BEFORE_OWNER_USE=NO
    MODEL_COMPARISON=OPTIONAL
    EXACT_MODEL_ID_AND_EXECUTION_PERMISSION_VERIFIED_BY=B14

The following remain `OWNER_ONLY` and are unchanged by this section:

- registering or activating a **new** model/provider, or changing the active route set;
- credential/secret/binding mutation;
- automatic routing and fallback policy changes;
- Production mutation and live canary activation.

Any choice that is unregistered, disallowed, ambiguous, or automatically substituted **fails
closed**. No silent fallback is permitted on any path:

    UNREGISTERED_OR_DISALLOWED_MODEL=FAIL_CLOSED
    NO_MODEL_SELECTED=FAIL_CLOSED
    SILENT_FALLBACK=PROHIBITED

Historical single-primary, Agnes, and Space Bunny records are provenance only and create no
current requirement:

    HISTORICAL_MODEL_DECISIONS=PROVENANCE_ONLY
    NO_SUCCESSOR_SELECTION_AS_PRECONDITION=YES

If a model-dependent canary needs a model, the OWNER supplies the choice at that time. Absence of
an OWNER choice blocks only that canary; it is not a repository or source-development blocker.
Per AGENTS.md, `AGENTS.md` and `AI_DEVELOPMENT_OPERATING_POLICY.md` already point here, so this
section is the single canonical statement and is not duplicated into those documents.

## 1. Rule

Provider/model selection is an **owner-only decision boundary**.

No AI agent, Web CTO, local implementation worker, validator, automation, or reviewer may independently choose, benchmark, rank, replace, route, activate, merge, deploy, or otherwise alter a model/provider decision unless the Product Owner explicitly authorizes that model work for the current task.

This rule applies even when a model/provider problem blocks another product task.

    MODEL_DECISION_AUTHORITY=OWNER_ONLY
    DEFAULT_AGENT_ACTION=STOP_AND_ASK_OWNER
    IMPLICIT_MODEL_APPROVAL=NO
    PRIOR_MODEL_APPROVAL_CARRY_FORWARD=NO

## 2. What counts as model-related work

This policy applies to any change or investigation whose purpose is to decide or alter:

- model/provider identity;
- primary, secondary, fallback, failover, or retry ordering;
- provider routing;
- model capability claims used for routing;
- free/paid status when used to select or activate a route;
- model context/output limits when used to select or activate a route;
- model-specific credentials, bindings, or provider endpoints;
- model benchmark/evaluation results used to select a route;
- live candidate smoke or comparison calls;
- product-tier model assignment;
- B14 registry/routing changes that affect active or candidate model selection;
- B62/B66/B67/Engine/Core/Control Plane model selection or fallback policy.

Merely encountering a model-related defect does **not** authorize model work.

Per-execution selection of an already registered/allowed model by an end user is outside this
list; see section 0.

## 3. Required behavior when model work becomes relevant

When an agent discovers that progress may depend on a model/provider decision, it must stop model work and report:

    MODEL_DECISION_REQUIRED=YES
    CURRENT_STATE=<current configured state, read-only>
    DECISION_NEEDED=<specific owner decision>
    PRODUCT_BLOCKED=YES|NO
    NON_MODEL_WORK_CAN_CONTINUE=YES|NO
    PROPOSED_OPTIONS=<optional concise choices, only if already known>
    MODEL_MUTATION_PERFORMED=NO
    LIVE_MODEL_COMPARISON_PERFORMED=NO

Then ask the Product Owner what to do.

Do **not** report `MODEL_DECISION_REQUIRED=YES` for a per-execution user choice of an already
registered/allowed model (section 0). That reporting duty is reserved for an actual agent, worker,
validator or reviewer model decision.

The agent may continue unrelated or model-independent product work.

## 4. Allowed without fresh owner approval

The following are allowed when needed to explain a blocker:

- read the currently configured model/provider route;
- state that the current route is unavailable or unresolved when that fact is already evidenced;
- identify the exact owner decision needed;
- preserve or restore fail-closed behavior;
- continue UI, data, renderer, PDF, XLSX, auth, workflow, or other product work that does not require choosing a model;
- create an issue documenting the unresolved model decision.

The agent must not expand these actions into candidate discovery or model selection.

## 5. Prohibited without fresh owner approval

Without explicit current owner instruction, do **not**:

- search for replacement models;
- benchmark models;
- run live candidate/model/provider calls for comparison;
- create a ranked model shortlist;
- change active model IDs;
- change fallback order;
- enable or disable fallback to select a model;
- change provider/model registry metadata for activation purposes;
- mutate model credentials/bindings/endpoints;
- change product-tier model assignments;
- merge a model-routing PR;
- deploy model-routing changes;
- infer authorization from a casual model mention, an old conversation, a stale issue, a prior approval, or a worker recommendation.

## 6. What counts as explicit owner authorization

Examples of sufficient authorization:

    "이 모델로 바꿔"
    "이 후보들을 테스트해"
    "fallback 순서를 A → B → C로 해"
    "모델 작업 진행해"
    "이 모델 PR merge해"

Authorization is bounded to the named decision and scope.

A new model/provider decision requires a new owner instruction.

## 7. Product-work precedence

A model question must not hijack a product task.

If the current product can proceed without a model decision:

    CONTINUE_NON_MODEL_PRODUCT_WORK=YES
    DEFER_MODEL_WORK=YES

For example, B66 UI, template selection, QuoteCore rendering, CGI preview/PDF parity, XLSX export, login/session behavior, and navigation may proceed independently of model selection.

## 8. Existing unmerged model work

Model experiments or route changes created before this policy do not gain approval merely because source exists or tests pass.

    UNMERGED_MODEL_WORK=HOLD
    MERGE_AUTHORITY=OWNER_ONLY
    DEPLOY_AUTHORITY=OWNER_ONLY

Before resuming any such branch, ask the owner whether to abandon it, keep it as evidence only, revise it, merge it, or deploy it.

## 9. Reporting rule

Do not report a model decision as complete unless the owner explicitly chose it and the authorized scope was executed.

Preferred unresolved status:

    MODEL_DECISION=PENDING_OWNER
    MODEL_WORK=STOPPED
    NON_MODEL_WORK=<ACTIVE|COMPLETE|BLOCKED>

## 10. Repository-wide scope

This policy is repository-wide and includes at minimum:

- B14 Korean AI Platform;
- B62 Padiem Chat;
- B66 Padiem Quote;
- B67 Padiem Legal;
- Padiem AI Engine;
- Padiem Core;
- Padiem Control Plane;
- Padiem Claw;
- candidate evaluation/smoke workflows;
- provider registries and model-primary/fallback declarations.

A more specific product document may add stricter restrictions but may not weaken this owner gate.
