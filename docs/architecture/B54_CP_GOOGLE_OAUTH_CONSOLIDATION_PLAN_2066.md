# B54 Claw vs Control Plane Google OAuth Consolidation Plan (#2066)

Date: 2026-09-07
Repository: skerishKang/ai-revenue-lab
Issue: #2066 — [B54/CP][OAuth] Consolidate Claw local Google OAuth onboarding under Control Plane ticket flow
Context & Predecessor: #1908 (PR #2065, docs/architecture/B54_CLAW_CONTROL_PLANE_GOOGLE_OAUTH_BOUNDARY_1908.md)
Base commit: 5b9438af066f5ce53ba4c04c3b88dc7c8677deb3

---

## 1. Executive Summary & Audit State

During the completion of issue #1908, the repository-wide Google OAuth boundary between **Padiem Claw / B54 Local Agent** and the **Shared Control Plane** was audited and locked. That audit confirmed:

```text
DUPLICATE_AUTHORITY_DETECTED = YES
SEPARATE_CONSOLIDATION_ISSUE_NEEDED = YES
```

Both Claw (apps/korean-ai-code-agent/src/kagent/google_oauth_provisioning.py) and Control Plane (packages/padiem-control-plane/google_oauth_worker.py / google_oauth_edge_worker.py) contain full authorization-code onboarding pipelines, PKCE state handling, and credential sealing.

### Scope of ACT-0
- **This document provides the source-grounded consolidation plan and identifies the smallest safe future implementation slice.**
- Consolidation is **NOT** performed in ACT-0.
- Existing code is **NOT** refactored or deleted in ACT-0.
- All boundary constraints remain frozen:
  ```text
  PROVIDER_CALLS = 0
  OAUTH_FLOW_EXECUTION = 0
  CREDENTIAL_READS = 0
  SECRET_WRITES = 0
  STORAGE_MUTATION = 0
  PRODUCTION_MUTATION = 0
  ```

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

---
## 3. Current Duplicated Authority Source Map

| Responsibility | Claw / B54 Implementation | Control Plane Implementation | Duplication Status |
| :--- | :--- | :--- | :--- |
| **OAuth Authorization Code Flow Initiation** | GoogleOAuthProvisioner.begin() in google_oauth_provisioning.py | GoogleOAuthDurableObject.begin_connect() / GoogleOAuthIngressRuntime.begin() in google_oauth_worker.py | **DUPLICATED** |
| **OAuth State & PKCE Session Storage** | SqliteSealedGoogleOAuthStore (google_oauth_sessions table) in google_oauth_provisioning.py | CloudflareDurableGoogleOAuthStore / GoogleOAuthDurableObject in google_oauth_worker.py | **DUPLICATED** |
| **Authorization Code Callback & Token Exchange** | GoogleOAuthProvisioner.complete_callback() in google_oauth_provisioning.py | GoogleOAuthDurableObject.complete_callback() / CloudflareGoogleOAuthTokenExchangePort in google_oauth_worker.py | **DUPLICATED** |
| **Credential Record Sealing & Ciphertext Storage** | SqliteSealedGoogleOAuthStore (google_oauth_credentials table) in google_oauth_provisioning.py | GoogleOAuthWebCryptoSealer & Durable Object Storage in google_oauth_worker.py | **DUPLICATED** |
| **Connector Binding Projection Construction** | ConnectorBindingProjection instantiation in google_oauth_provisioning.py:702 | CanonicalConnectorContextStore & Ingress Runtime in identity_connector_ticket.py | **DUPLICATED** |

---

## 4. What Must NOT Be Deleted Yet & What Must Be Gated First

### What Must NOT Be Deleted Yet
1. apps/korean-ai-code-agent/src/kagent/google_oauth_authority.py:
   - Contains GoogleReadonlyOAuthAuthority, StdlibGoogleProviderNetwork, and token refresh helpers required for Claw to perform bounded Gmail/Drive API execution on the local workstation.
2. apps/korean-ai-code-agent/src/kagent/google_oauth_provisioning.py:
   - Existing unit and contract tests in apps/korean-ai-code-agent/tests/ depend on GoogleOAuthProvisioner and SqliteSealedGoogleOAuthStore contracts.
   - Deleting this code prematurely would break B54 local test harnesses before the desktop pairing bridge exists.

### What Must Be Gated First
1. **Device Pairing Authority**: Control Plane must provide a verifiable device/workstation pairing protocol (so a local Claw workstation instance can exchange an authorized ticket for sealed credentials or delegated tokens).
2. **Connect Ticket Consumption Port in Claw**: Claw needs a dedicated adapter (ControlPlaneConnectTicketReceiver) that receives a signed ticket or sealed credential payload from the Control Plane without running its own authorization code exchange.
3. **Feature Flag / Deprecation Gate**: Claw's GoogleOAuthProvisioner should be gated behind a legacy/local-only flag before removal.

---

## 5. Safe Migration Sequence

```text
Phase 0 (ACT-0, Current):
  - Record consolidation plan and invariant tests (#2066).
  - Verify zero mutation, zero provider calls.

Phase 1 (ACT-1 Candidate):
  - Implement Control Plane Connect Ticket verification/ingestion adapter in Claw.
  - Add explicit deprecation notice on GoogleOAuthProvisioner.

Phase 2 (ACT-2):
  - Wire Claw to request authorization via Control Plane begin_connect redirect rather than minting local PKCE sessions.
  - Implement callback delegation from Control Plane to paired desktop instance.

Phase 3 (ACT-3):
  - Retire Claw local PKCE code exchange and SqliteSealedGoogleOAuthStore session table.
  - Retain local credential caching (google_oauth_credentials) strictly for offline execution of readonly queries.
```

---

## 6. Smallest ACT-1 Implementation Candidate

The minimal safe code step for **ACT-1** is:
- **Scope**: Contract-only consumption in Claw.
- **Action**: In apps/korean-ai-code-agent/src/kagent/, define ControlPlaneConnectorTicketPort (or adapter) that parses a verified connect ticket / receipt minted by packages/padiem-control-plane/identity_connector_ticket.py.
- **Safety**:
  - Does NOT touch live network or OAuth servers.
  - Does NOT delete google_oauth_provisioning.py.
  - Proves compatibility between Control Plane ticket structures and Claw's ConnectorBindingProjection.

---

## 7. Rollback & Recovery Path

If any migration phase encounters incompatibilities:
1. **Fallback to Local Onboarding**: B54 retains its standalone GoogleOAuthProvisioner until Phase 3 is fully validated.
2. **Deterministic Rollback**: Each Phase is encapsulated in a single isolated PR with strict conformance tests.
3. **No Distributed State Dependency**: Local execution requires only valid GoogleOAuthCredentialRecord instances; if Control Plane ingress fails, local dev bindings remain intact.

---

## 8. Test Strategy

1. **Architecture Conformance Tests**: .github/tests/test_b54_cp_google_oauth_consolidation_plan_2066.py and .github/tests/test_b54_claw_control_plane_oauth_boundary_1908.py.
2. **Zero Provider / Zero Network Enforcement**: All tests assert standard mocks and zero external HTTP calls.
3. **Static AST Analysis**: Ensure Control Plane files do not import local process modules and Claw does not import ticket-signing authorities.
