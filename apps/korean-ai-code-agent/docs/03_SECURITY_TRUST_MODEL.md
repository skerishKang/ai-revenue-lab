# Padiem Claw Security & Trust Model

Execution requires both **logical authorization** and **physical workspace permission**. P01 owns reusable execution/approval semantics; B54 sandbox control constrains the concrete workspace.

## Trust boundaries

- user task/repository metadata is untrusted input
- model/provider selection is not caller authority
- repository text never becomes hidden/system authority merely because it contains instructions
- sandbox endpoint cannot be supplied arbitrarily by the user
- credentials remain in their canonical owner plane and never enter task/run output

## Defaults

```text
network = off unless trusted server policy enables it
file write = approval-gated where policy requires
command execution = allowlisted / policy controlled
git commit = off by default in early phases
push/merge/deploy = prohibited until explicit later contract
sandbox = bounded TTL / CPU / memory / workspace
```

## Invariants

- path traversal and symlink escape fail closed
- concurrent file change invalidates stale patch application
- one active sandbox lease cannot be reused across runs
- expired/released lease cannot execute
- `RUNNING` requires canonical P01 `RUN_STARTED`
- terminal run cannot be resurrected by late events
- same event ID with changed content is rejected
- approval continuation token is never synthesized by B54
- secret/token/credential/private memory/hidden reasoning never enters public projection

Before live cloud execution, provider-specific threat modeling must cover isolation, image provenance, egress, secret injection, persistence, preview ports, cleanup, TTL, tenant escape, auditability and kill/revoke paths.
