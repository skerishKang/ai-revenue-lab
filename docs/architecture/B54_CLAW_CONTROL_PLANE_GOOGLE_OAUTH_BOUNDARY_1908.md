# B54 / Padiem Claw vs Control Plane Google OAuth Ownership Boundary

Date: 2026-09-07
Repository: skerishKang/ai-revenue-lab
Issue: #1908 — [B54][Boundary] Record Padiem Claw vs Control Plane Google OAuth ownership split
Base commit: `58e006f6e688ce30b1ca1b251b6a81db72412b15`

## 1. Purpose & Background

This document formally defines and locks the architecture and ownership boundary for Google OAuth between:
1. **Padiem Control Plane** (packages/padiem-control-plane/): The multi-tenant canonical identity, session, and credential authority.
2. **Padiem Claw / B54 Local Agent** (apps/korean-ai-code-agent/src/kagent/): The local execution environment, desktop/OS workspace agent, and connector runtime.

Historically, docs/architecture/B62_P01_B14_CONTROL_PLANE_OWNERSHIP_REVIEW_20260831.md established ownership across B62 (Padiem Chat), P01 (Core/Engine), B14 (Model Provider Router), and Control Plane, but did not authoritatively include B54 / Padiem Claw.

As a result, Google OAuth-related contracts and utilities exist in both:
- **Claw / B54**:
  - apps/korean-ai-code-agent/src/kagent/google_oauth_authority.py
  - apps/korean-ai-code-agent/src/kagent/google_oauth_provisioning.py
- **Control Plane**:
  - packages/padiem-control-plane/google_oauth_worker.py
  - packages/padiem-control-plane/google_oauth_edge_worker.py
  - packages/padiem-control-plane/identity_connector_ticket.py
  - packages/padiem-control-plane/identity_authority_worker.py

This document records the exact ownership split, detects potential drift or duplicate authority, and enforces invariants via conformance test .github/tests/test_b54_claw_control_plane_oauth_boundary_1908.py.

---

## 2. Canonical Ownership Lock

```text
GOOGLE_OAUTH_PROVIDER_CLIENT_CONFIG_OWNER = SPLIT
GOOGLE_TOKEN_REFRESH_AUTHORITY            = SPLIT
GOOGLE_CANONICAL_IDENTITY_AUTHORITY       = CONTROL_PLANE
CONNECT_TICKET_ISSUANCE                   = CONTROL_PLANE
DEVICE_CREDENTIAL_AND_PAIRING_AUTHORITY   = CONTROL_PLANE
GMAIL_DRIVE_API_CALL_EXECUTION            = CLAW_CONNECTOR_RUNTIME
WINDOWS_LOCAL_EXECUTION                   = CLAW
```

### Detailed Ownership Breakdown

| Capability / Responsibility | Owner | Rationale |
| :--- | :--- | :--- |
| **GOOGLE_OAUTH_PROVIDER_CLIENT_CONFIG_OWNER** | **SPLIT** | Control Plane owns production multi-tenant web application client credentials (used for web ingress & connect tickets). Claw may hold local Desktop App / loopback client configuration for local workstation development or offline desktop-isolated flows, but must never hold production web client secrets. |
| **GOOGLE_TOKEN_REFRESH_AUTHORITY** | **SPLIT** | Control Plane owns server-side / managed connector refresh token sealing and lifecycle. Claw owns local runtime token refresh using provisioned credentials only when executing connector operations locally on the workstation. |
| **GOOGLE_CANONICAL_IDENTITY_AUTHORITY** | **CONTROL_PLANE** | Canonical user subjects, account mappings, and global session IDs are exclusively minted and tracked in Control Plane (CanonicalIdentityDurableObject). Claw MUST NOT mint canonical identity. |
| **CONNECT_TICKET_ISSUANCE** | **CONTROL_PLANE** | Connect tickets are cryptographic capability grants signed exclusively by GoogleConnectTicketIssuer in Control Plane. Claw consumes authorized tickets and MUST NOT issue connect tickets. |
| **DEVICE_CREDENTIAL_AND_PAIRING_AUTHORITY** | **CONTROL_PLANE** | Pairing desktop/local agents to accounts/workspaces and issuing device tokens is exclusively owned by Control Plane. Claw MUST NOT declare or issue pairing authority. |
| **GMAIL_DRIVE_API_CALL_EXECUTION** | **CLAW_CONNECTOR_RUNTIME** | Claw executes Gmail and Google Drive API queries (GoogleReadonlyOAuthAuthority) locally on behalf of the user/task using bounded HTTPS calls once authorized. Control Plane acts as identity and ingress authority, not a batch document downloader. |
| **WINDOWS_LOCAL_EXECUTION** | **CLAW** | Local OS interaction (Windows subprocess, PowerShell, local filesystem, desktop automation) is strictly Claw-owned. Control Plane runs on serverless edge (Cloudflare Workers) and MUST NOT perform local Windows execution. |

---

## 3. Duplicate Authority Audit & Finding

Inspection of apps/korean-ai-code-agent/src/kagent/google_oauth_provisioning.py reveals:
1. GoogleOAuthProvisioner in Claw contains a full PKCE authorization-code flow and state store (SqliteSealedGoogleOAuthStore).
2. GoogleOAuthProvisioner.begin() generates state_ref and code_verifier, while complete_callback() exchanges the authorization code with Google for tokens and constructs a ConnectorBindingProjection.
3. In parallel, packages/padiem-control-plane/google_oauth_worker.py and identity_authority_worker.py contain GoogleOAuthIngressRuntime and ConnectorConnectTicketAuthority, which also handle connect flow, state verification, and credential sealing via Cloudflare Workers and Durable Objects.

### Finding:
- **DUPLICATE_AUTHORITY_DETECTED = YES**
- Both Claw (apps/korean-ai-code-agent/src/kagent/google_oauth_provisioning.py) and Control Plane (packages/padiem-control-plane/google_oauth_worker.py / google_oauth_edge_worker.py) implement authorization-code onboarding and credential sealing.
- **SEPARATE_CONSOLIDATION_ISSUE_NEEDED = YES**
  - Claw's google_oauth_provisioning.py represents a standalone / self-contained desktop onboarding prototype (GOOGLE_OAUTH_PRODUCTION_SEALER_CONFIGURED = False).
  - As production converges toward the Shared Control Plane, onboarding and credential sealing must be unified under the Control Plane, with Claw receiving sealed credentials or delegated session tokens via connect tickets.
  - Per the #1908 work contract, existing code is **NOT deleted or refactored** here. A separate consolidation issue must be scheduled to retire Claw's local onboarding authority and route all desktop provisioning through the Control Plane pairing flow.

---

## 4. Conformance Rules & Safety Invariants

The boundary is enforced by .github/tests/test_b54_claw_control_plane_oauth_boundary_1908.py with the following automated assertions:

1. **Claw must not mint canonical identity or sessions**:
   - apps/korean-ai-code-agent must not define canonical session minting or canonical subject factories (e.g. CanonicalSubjectRef, CanonicalIdentityDurableObject).
2. **Claw must not issue connect tickets**:
   - Claw must not implement GoogleConnectTicketIssuer or ticket signing logic (decode_connect_ticket_key).
3. **Claw must not claim device pairing authority**:
   - Claw must not act as the pairing root authority; pairing tokens and device authorization are issued by the Control Plane.
4. **Control Plane must not perform local execution**:
   - packages/padiem-control-plane must not invoke local Windows/OS process execution (subprocess, winreg, Windows-specific shell commands).
5. **Secret material hygiene**:
   - Neither Claw nor Control Plane source files may contain hardcoded secret literals (e.g., live client secrets, private keys). References must be via environment variables or secret store interfaces.
6. **Zero Provider / Zero Mutation Invariant**:
   - All boundary audits and tests execute with 0 network calls, 0 provider calls, 0 storage mutations, and 0 production mutations.
