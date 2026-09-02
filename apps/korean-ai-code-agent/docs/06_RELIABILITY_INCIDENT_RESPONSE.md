# Padiem Claw Reliability & Incident Response

## Initial SLIs

- task admission success
- queue wait time
- sandbox allocation success/latency
- P01 start latency
- run completion rate
- approval resume success
- test/evidence completion
- sandbox release success
- Draft PR creation success when enabled

Production SLO numbers remain TBD until real sandbox/provider telemetry establishes baselines.

## Severity

- SEV-0: suspected cross-tenant access, credential exposure, unauthorized production mutation
- SEV-1: widespread run corruption, security-impacting cleanup failure, approval bypass
- SEV-2: major feature outage or sustained queue/execution failure
- SEV-3: limited degradation with safe fallback

## First response

1. stop unsafe new execution if a security boundary is uncertain
2. preserve exact release/run/trace IDs
3. revoke/isolate affected sandbox/provider credentials through the owner plane
4. do not print secrets into tickets/logs
5. identify owning plane: B54, P01, Engine, B14, Control Plane, GitHub or provider
6. recover via reviewed rollback/retry authority
7. record root cause, containment, corrective PR and prevention test
