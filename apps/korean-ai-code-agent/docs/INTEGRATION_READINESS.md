# Padiem Claw — Integration Readiness Boundary

Status: pre-production integration contract. This document does **not** authorize merge, deployment, provider selection, external writes, billing, or Production.

## Why this boundary exists

B54 now has deterministic product/cloud contracts for onboarding, task/run lifecycle, P01 orchestration, approval pause/resume, sandbox conformance, repository materialization, Agent Computer, private preview, human takeover, background dispatch, persistence/reconciliation, verification, artifact export, verified diff, Draft PR planning/outbox, teardown, metering, public-safe failure projection, business intake/RFQ/quote/PO, communications, inbound quarantine, attachment scan receipts, retention/deletion, customer quotations, customer acceptance, receivables, delivery, pilot metrics and evidence.

Those contracts are not equivalent to a live service. A live capability is configured only when every required external adapter is represented by a current trusted CONNECTED probe.

## Adapter authority map

| Adapter kind | Owning authority | B54 role |
|---|---|---|
| `control_plane_identity` | Control Plane | consume trusted session/workspace identity projection |
| `control_plane_entitlement` | Control Plane | consume entitlement/quota reference |
| `b14_model_execution` | B14 | invoke model execution through P01/B14 boundary |
| `sandbox_provider` | selected provider behind B54 port | isolated execution backend after conformance review |
| `github_repository_read` | GitHub adapter | acquire approved repository/revision |
| `github_draft_write` | GitHub adapter | create Draft PR only through approval/outbox contract |
| `communication_outbound` | business communication adapter | approved outbound only |
| `communication_inbound` | business communication adapter | authenticated webhook/event ingestion into quarantine only |
| `attachment_scanner` | malware/content scanning adapter | produce trusted exact-hash scan receipts before attachment review release |
| `retention_storage` | product storage adapter | enforce server-owned retention/legal-hold/deletion policy and deletion receipts |
| `accounting_read` | accounting connector | read/projection input only in current scope |

B54 does not own provider credentials, identity, membership, billing, credit debit, canonical P01 approval semantics, scanner security certification, or accounting write authority.

## Live capability gates

### Managed Cloud Run

Required:

- Control Plane identity
- Control Plane entitlement
- B14 model execution
- sandbox provider
- GitHub repository read

Not sufficient by itself for Draft PR creation or business messaging.

### Draft PR Output

Requires the complete Managed Cloud Run set plus:

- GitHub Draft write

Still Draft-only. Auto-merge, force-push and deployment are outside authority.

### Business Messaging — Outbound

Required:

- Control Plane identity
- Control Plane entitlement
- communication outbound adapter

Business-message construction and approval contracts remain separate. A connected adapter does not waive approval.

### Business Inbound Review

Required:

- Control Plane identity
- Control Plane entitlement
- communication inbound adapter
- attachment scanner
- retention storage

Inbound text remains untrusted even after release for review. Attachments require both MIME/size/count policy and an exact CLEAN scan receipt. A connected scanner probe is only adapter-readiness evidence; it is not a scanner security certification.

### Live Data Retention

Required before importing real design-partner/customer operational data:

- Control Plane identity
- Control Plane entitlement
- retention storage

The repository policy defines TTL/legal-hold/deletion contracts. Live configuration additionally requires a storage adapter capable of enforcing those decisions and returning bounded deletion evidence.

### Finance Projection — Live Read

Required:

- Control Plane identity
- Control Plane entitlement
- accounting read adapter

This does not grant accounting write, journal, tax, invoice, settlement, or payment authority.

## Probe states

- `UNCONFIGURED`: cannot satisfy a live gate.
- `DETERMINISTIC_FAKE`: tests only; cannot satisfy a live gate.
- `CONNECTED`: may satisfy a gate only while the trusted probe is active (`issued_at <= now < expires_at`).

Stale, future, duplicate, missing, fake or unconfigured probes fail closed.

## Production blockers intentionally remaining

The repository-side contracts are intentionally provider-neutral and external-write-neutral. The following require real external decisions, accounts or credentials and therefore are not completed by deterministic repository code alone:

1. merge/rebase of the reviewed Draft PR stack into the canonical branch;
2. Control Plane identity/entitlement adapter wiring;
3. live B14/P01 model execution wiring for the product environment;
4. sandbox provider selection after evidence/conformance review;
5. real GitHub repository-read and Draft-write adapter authorization;
6. real outbound email/business-messaging account authorization;
7. real inbound webhook/event adapter authorization;
8. real attachment malware/content scanner adapter and policy authority;
9. live storage implementation enforcing retention/legal-hold/deletion decisions;
10. optional accounting read connector authorization;
11. secret-vault/KMS references for BYOK or organization-managed credentials;
12. environment-specific deployment configuration and release approval;
13. preview/Production smoke and recovery validation.

None of those blockers should be bypassed by marking a deterministic fake as connected.

## Explicit non-claims

```text
PRODUCTION_READY = NO
PRODUCTION_DEPLOYED = NO
MERGE_AUTHORIZED = NO
PROVIDER_SELECTED = NO
REAL_SANDBOX_CALL = NO
REAL_GITHUB_PRODUCT_WRITE = NO
REAL_BUSINESS_MESSAGE_SEND = NO
REAL_INBOUND_WEBHOOK = NO
REAL_ATTACHMENT_SCANNER = NO
REAL_RETENTION_STORAGE_DELETE = NO
REAL_ACCOUNTING_CALL = NO
SECURITY_CERTIFICATION = NO
DEPLOYMENT_APPROVAL = NO
```

The next implementation phase is external-adapter integration after explicit merge/integration authorization and provision of the relevant real accounts/credentials through their owning secure systems.
