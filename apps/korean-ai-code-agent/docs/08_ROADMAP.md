# Padiem Claw Roadmap

## Current

- Phase 1 local terminal vertical slice
- B54 identity/boundary audit
- task/run/sandbox refactor — Draft PR #1392
- P01 orchestration consumer adapter — #1396
- canonical docs/portal — #1399

## Order

1. land task/run/sandbox refactor
2. exact-head P01 adapter conformance + approval/resume
3. product run persistence port
4. durable background queue: checkpoint/cancel/resume/TTL
5. sandbox provider selection after threat model
6. exact repo SHA clone/worktree + bounded process execution
7. test/evidence artifact pipeline
8. GitHub branch + Draft PR adapter; no auto-merge
9. Padiem Chat handoff/status/result cards
10. first web Claw workspace
11. production reliability baseline/SLO
12. parallel agent fan-out
13. Linear/Sentry/Slack/MCP/connectors
14. managed credits and team/enterprise controls

Do not jump from fake sandbox to multi-agent cloud execution. Every milestone preserves authority boundaries, exact-head validation and rollback evidence.
