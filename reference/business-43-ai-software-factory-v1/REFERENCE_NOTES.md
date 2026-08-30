# Reference notes

Research date: 2026-07-29

## 1. GitHub pull requests and status checks

- Sources:
  - https://docs.github.com/en/pull-requests/reference/pull-requests
  - https://docs.github.com/en/pull-requests/reference/status-checks
- Adopted: Draft is visibly distinct from merged; reviewers need changed files, checks, blockers and latest-head context in one proposal package.
- Rejected: GitHub navigation, merge box, tabs, logos, colors, iconography and proprietary page geometry.
- Decision: represent the proposal as a physical delivery crate and exact-head tag, not as a GitHub clone.

## 2. CircleCI Test Insights

- Source: https://circleci.com/docs/guides/insights/insights-tests/
- Adopted: failed tests, reruns, flaky/uncertain behavior and test counts remain inspectable rather than being flattened into one green status.
- Rejected: analytics dashboard, charts, product chrome and success-rate KPI theatre.
- Decision: use a test-rig board plus a separate failed-check slip and rerun result.

## 3. GitLab deployment approvals

- Source: https://docs.gitlab.com/ci/environments/deployment_approvals/
- Adopted: deployment readiness and deployment execution are separate; approval can block execution and approval does not itself perform deployment.
- Rejected: protected-environment UI, role screens, GitLab badges and pipeline layout.
- Decision: the delivery package states `DEPLOYMENT READINESS — NOT DEPLOYED` and preserves `HUMAN REVIEW REQUIRED`.

## 4. SLSA provenance

- Source: https://slsa.dev/spec/v1.2/provenance
- Adopted: artifact evidence should trace back to its exact source and process; consumers verify provenance against expectations.
- Rejected: claiming SLSA compliance, cryptographic attestation, signed provenance or a real build system in this synthetic Phase 1 reference.
- Decision: exact-head identity and evidence scope are shown as synthetic manufacturing tags, with no live attestation claim.

## 5. NIST SSDF verification guidance

- Source: https://www.nist.gov/itl/executive-order-14028-improving-nations-cybersecurity/software-supply-chain-security-guidance-2
- Adopted: review and testing are separate activities; discovered issues and remediations should be documented rather than hidden.
- Rejected: security certification claims, compliance scoring and autonomous approval.
- Decision: implementation self-check, independent validation, failed-check history and unresolved condition remain visibly separate.

## Final visual decisions

- Precision manufacturing ledger rather than IDE, terminal, agent chat, kanban or green-check dashboard.
- Warm specification paper, graphite machinery, process blue, inspection red and muted brass.
- Each state uses a different production artifact: specification sheet, patch reel, test rig, inspection sheet and delivery crate.
- Synthetic project and no-live-connection labels remain persistent.

## Product distinction

### Business 42 · AI Development Control Tower

Business 42 governs roles, exact-source authority, phase gates and the next authorized action across a workstream. Business 43 shows the bounded production line that turns one requirement into one delivery package. This reference does not become a governance console.

### Business 44 · Portfolio Operations Console

Business 44 manages many products, priorities, deployments and portfolio status. Business 43 is one requirement-to-delivery package and has no portfolio-wide metrics or prioritization.

### Business 48 · AI Verification Engine

Business 48 is a reusable validation and approval component. Business 43 contains independent validation as one station among requirement, patch, tests, packaging and release constraints. Validation does not dominate the whole product.
