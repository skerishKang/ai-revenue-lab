# Padiem Claw Ops — Managed Cloud and Deployment Modes

Issue: #1413  
Related: #1405

## Default SMB experience

The design-partner discovery showed that a non-technical business owner should not need to purchase an expensive dedicated AI workstation or configure provider APIs simply to use automation.

Therefore the default Claw Ops pilot path is:

```text
Padiem login
→ company workspace
→ authorized data/connectors
→ Claw Ops workflow
```

## Product modes

### 1. Claw Cloud / Managed — default

Padiem operates the required application infrastructure and model access.

User responsibilities:
- sign in;
- configure company/business data;
- connect authorized business systems;
- review/approve business actions.

Provider keys are not user-visible and never enter Claw task payloads.

### 2. Claw Cloud / BYOK — advanced

User/org may supply its own model-provider account through a trusted credential/vault boundary.

The credential is referenced by trusted server policy; it is not copied into task text, sandbox state, logs or model-visible context.

### 3. Claw Local

Installed execution for users who want work to happen on their own machine. Local mode should retain explicit write/command permissions and should prefer an isolated local workspace/container where practical.

### 4. Claw Self-Hosted

Enterprise/government/private deployment option for organizations that require private infrastructure, private Git/data sources, internal models or stronger data-residency controls.

## Shared control path

```text
User / Organization
   ↓
Padiem Control Plane
   ├─ identity
   ├─ entitlement
   ├─ usage / credits
   └─ audit
   ↓
Padiem Claw Ops
   ↓
P01 orchestration / approval / tools
   ↓
B14 model execution
```

Where a sandbox is needed, its lifecycle remains separate from model/approval authority.

## Managed secret rule

```text
Claw task          -> no provider secret
P01 request         -> no provider secret value
sandbox             -> no inherited provider secret
B14 trusted runtime -> provider/model authority
```

Business-system connector credentials follow the same principle: product state keeps connector references, not raw credentials.

## Cloud sandbox rule

Cloud coding/shell workloads must pass #1405. Claw Ops may also contain workflows that do not require arbitrary code execution; those should use bounded server-side Tools/connectors rather than spinning up a general sandbox unnecessarily.

## Onboarding principles

- Managed Cloud first;
- no API key field on the normal first-run path;
- explain business outcomes, not model infrastructure;
- one company workspace with supplier/template setup;
- permissions/connectors requested only when needed;
- easy transition to BYOK/Local/Self-Hosted later without changing the user's business workflow concepts.
