# Padiem Claw System Architecture

```text
Padiem Chat / CLI / future Web
        │ ClawTaskIntent
        ▼
B54 Padiem Claw
Task · Run · Repo · Sandbox · Diff · Test · Draft PR · UX
        │
        ▼
P01 Padiem AI Core
Agent · Tool · Skill · Approval · Recovery · Evidence · Orchestration
        │
        ▼
B14 Korean AI Platform
Model/Provider registry · credentials · routing · fallback · execution
        │
        ▼
Providers
```

Cross-runtime consumers may use Padiem AI Engine as the service boundary over Core. Shared Control Plane supplies identity/session, entitlement, usage, credits/subscription and audit; it is not the sandbox scheduler.

## Ownership matrix

| Plane | Owns | Must not own |
|---|---|---|
| B54 Claw | Task/Run/Repo/Sandbox/GitHub workflow/UX | provider routing, generic Agent semantics |
| P01 Core | Agent/Tool/Skill/approval/recovery/evidence/orchestration | Claw persistence, sandbox VM scheduler |
| AI Engine | cross-runtime execute/stream/resume/cancel | provider policy, product DB |
| B14 | models/providers/keys/routing/fallback/model execution | task/run/chat/sandbox state |
| B62 Chat | discovery/handoff/status/result presentation | shell/GitHub mutations, Agent loop |
| Control Plane | identity/entitlement/usage/credits/audit | diff/PR/sandbox scheduling |

B54 consumes canonical P01 request/event/result contracts rather than inventing a second Agent API.

## Extraction rule

Do not create speculative shared sandbox/agent packages. Keep Claw-specific infrastructure inside B54 until a second real product proves reuse.
