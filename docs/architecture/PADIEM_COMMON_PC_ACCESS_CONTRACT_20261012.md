# PADIEM common PC connection contract — product-common device & capability access (2026-10-12)

Issue: [#4139](https://github.com/skerishKang/ai-revenue-lab/issues/4139);
Windows Alpha proof: [#3099](https://github.com/skerishKang/ai-revenue-lab/issues/3099).

## Purpose

Every PADIEM product that consumes B14 — Padiem Claw, B66 Padiem Quote,
Padiem Chat, Padiem Engine — must be able to use **one** Windows Connect
installation and **one** PC registration/approval chain, without any of them
gaining PC access merely by being a B14 consumer.

This slice adds the missing *product-scoped* contract on top of the existing
canonical authorities. It creates no new authority of any kind.

## Authority separation (unchanged)

```text
B14                        = AI model execution only (provider/model registry,
                             model invocation, per-model policy, usage/cost).
                             NOT a PC access authority. No PC endpoint is added.
PADIEM Control Plane       = account/workspace identity, product identity links,
                             canonical product ids (allowed_product_ids).
Canonical Local Agent      = device binding / session / heartbeat / command
Broker (existing)            metadata + admission evidence. The only device and
                             ONLINE fact source.
P01 approval (existing)    = execution approval. Never duplicated, never minted
                             here.
PADIEM Connect (Windows)   = LOCAL2. Resident execution only.
```

New in this slice: a **product → PC access operation** grant table that the
Control Plane evaluates server-side, and a sanitized product-device view that
product routes (B66/Chat/Engine) can consume.

## Source

- `packages/padiem-control-plane/padiem_control_plane/local_agent_pc_access.py`
  — `PcAccessOperation`, `ProductPcAccessGrant`, `ProductPcAccessPolicy`,
  `evaluate_pc_access`, `build_product_device_view`,
  `device_eligible_for_pc_access`, `evaluate_pc_preflight`,
  `PcPreflightDecision`, `pc_dispatch_requirements`.
- Exported from `padiem_control_plane.__init__` as a shared declaration.

## Product identifiers

The product identifier is a **routing/permission** input only:

```text
PRODUCT_ID_IS_AUTHENTICATION        = False
PRODUCT_ID_IS_ROUTING_PERMISSION_INPUT = True
```

It never authenticates a user and never establishes a workspace. The account
and workspace always come from the server session, and the product must be one
of the canonical product ids already accepted by the existing identity
authority (`allowed_product_ids`, e.g. `b54-padiem-claw`, `b62`). This slice
does **not** declare a second product registry: grants are supplied as
configuration, exactly like `allowed_product_ids`.

## Operations and the canonical capability vocabulary

```text
device.list   -> canonical Broker device_directory / device_truth read
task.status   -> canonical Broker poll
task.result   -> canonical Broker terminal_command_result
file.list     -> kagent.local_agent_permissions.LocalCapability.FILESYSTEM_READ
file.read     -> kagent.local_agent_permissions.LocalCapability.FILESYSTEM_READ
file.write    -> kagent.local_agent_permissions.LocalCapability.FILESYSTEM_WRITE
```

The local file capabilities are **referenced** by their exact canonical token
strings (`CANONICAL_LOCAL_CAPABILITY_FOR_OPERATION`), never re-declared, so this
contract cannot drift into a second capability vocabulary. A parity test asserts
those tokens still exist in the canonical source
(`apps/korean-ai-code-agent/src/kagent/local_agent_permissions.py`).

## Contract rules

- `PRODUCT_PC_ACCESS_DEFAULT = OFF`. The shipped policy is
  `ProductPcAccessPolicy.default_off()` — an empty grant table. A product with
  no explicit grant is refused every operation (`product_not_enabled`).
- Unknown/malformed product or operation fails closed
  (`invalid_pc_access_request`).
- A workspace-scoped grant is refused from any other workspace
  (`product_workspace_not_granted`).
- `file.write` needs its **own** grant and requires the product to also hold
  `file.read` (`write_requires_read_grant`); a READ grant never implies WRITE.
- A work ticket/approval minted for one product can never be replayed by another
  (`cross_product_ticket_reuse_denied`), in either direction.
- `requires_p01_approval` is a **floor**, not a grant: `allowed: true` is never
  permission to run anything, and the guard can only *require* the existing P01
  approval, never lower it. A product UI must not treat it as approval.

## P2 — preflight eligibility only (never a dispatch authorization)

`evaluate_pc_preflight` is the **preflight** contract a product must satisfy
before the existing Local Runner may even consider executing anything. It
checks, in order, and refuses on the first failure:

1. the product holds the capability (`evaluate_pc_access`);
2. the existing work ticket was minted for this same product
   (`cross_product_ticket_reuse_denied`);
3. the canonical device binding belongs to this authenticated account and
   workspace (`device_scope_mismatch`) — the device id is read out of the
   canonical row, never supplied by the caller;
4. the device is non-terminal with a bound session (`device_not_actionable`);
5. a PC-touching operation presents an approval the *existing* path already
   verified, minted for this same product (`p01_approval_required` /
   `cross_product_approval_reuse_denied`);
6. a READ approval can never authorize WRITE (`read_approval_cannot_write`);
7. a replayed request is refused (`replay_denied`).

### This contract releases nothing

```text
preflight_eligible         = "every precondition this contract can check passed"
dispatch_authorized        = False   (property, hard-wired — not a field)
preflight_only             = True
fresh_online_proven_here   = False
dispatch_gate_wired        = False
```

`dispatch_authorized` is a **property that always returns `False`**, not a
dataclass field, so a `True` dispatch authorization cannot even be constructed.
There is deliberately **no** `fresh_online_verified` parameter: this module
cannot obtain a trustworthy fresh ONLINE fact, and it will not stand up a second
heartbeat/presence authority to invent one. `PcPreflightDecision.safe_dict()`
exposes no `allowed` key at all — only `preflight_eligible` — precisely so a
product route or UI cannot mistake it for a run permission.

`p01_verified_by_existing_path` / `p01_product_id` are **caller-supplied inputs**
produced by the existing B54 approval path. They are never proof, and setting
them true changes no dispatch fact. This contract never verifies and never mints
an approval.

`pc_dispatch_requirements()` is the contract-level hand-off: it *declares* the
closed set of trusted facts a future dispatch gate must obtain, and grants
nothing (`dispatch_authorized: False`, `new_authority_created: False`):

```text
canonical_broker_fresh_online_attestation
canonical_device_session_and_heartbeat_recheck
existing_p01_approval_verification
work_ticket_scope_expiry_and_replay_check
```

Until such a gate exists, no execution path may key off this contract.
`PC_EXECUTION_PATH_NEWLY_WIRED = False`: this slice provides the contract, not
a newly-wired execution path. Where the existing P01 execution path is not yet
connected, that is reported as not connected rather than claimed.

## Product-neutral device view

`build_product_device_view` consumes the canonical `device_directory` result
unchanged and returns only:

```text
device_id, canonical_state, has_session, heartbeat_present, actionable,
online_decided_here=False
```

### Only an attested envelope may carry a device fact

Device facts are emitted **only** from the envelope the canonical Broker marks
`owner_scoped: true` **and** `available: true`. Both are required by identity,
so a missing attestation, a false attestation, a non-boolean value, or an
`available: false` envelope that still carries a device list refuses the whole
view. The empty-but-attested list is itself treated as a contradiction (the
Broker returns `available: false` when nothing is bound), so an empty directory
is never presented as a normal, connected-looking state.

The canonical `no_device_binding` read stays a **distinct, verified** state
(`owner_scoped: true`, `directory_verified: true`, `devices: []`). Any other
untested `available: false` text is *not* trusted: it is reported with this
contract's own bounded code and its text is never echoed.

### Integrity invariants are re-checked, never weakened

| condition | result |
| --- | --- |
| duplicated `device_id` | whole view refused (`device_directory_malformed`) |
| more than `MAX_PRODUCT_VIEW_DEVICES` (24) devices | whole view refused |
| declared `device_count` missing, non-int or != the list length | whole view refused |
| `max_devices` present but not the canonical 24 | whole view refused |
| malformed `canonical_state` type or unknown state value | whole view refused |
| malformed binding, or a session that does not speak for that same id/scope | whole view refused |
| non-text `heartbeat_last_seen_at` | whole view refused |

The canonical Broker already guards duplication and the device bound; the
shared projection must not silently weaken those invariants, so it re-checks
them and a parity test asserts `MAX_PRODUCT_VIEW_DEVICES` still equals
`local_agent_broker_durable_runtime.MAX_DEVICE_DIRECTORY_DEVICES`. A malformed
record is never skipped while the rest of the computers are shown as if the list
were complete — refusal is whole-list, fail-closed. One bounded reason
vocabulary is used and the Broker's own `reason` / `error.code` /
`error.message` text is never echoed.

### Other properties

- It requires `device.list`; a product without it gets
  `available:false`, `devices:[]` — never a guessed or partial device set.
- It never decides ONLINE: the existing
  `kagent.local_agent_server_projection` rule remains the only ONLINE
  authority. `actionable` only rules out the states the Broker itself declares
  terminal (`revoked`, `credential_expired`), any unrecognised state, and a
  device with no bound session.
- It strips every owner/workspace/binding/session/credential field, so a
  product route can never forward Broker internals to a browser.
- Device ids are preserved exactly, so Claw and B66 resolve the same physical PC
  to the same device id (shared device identity).
- The view itself carries `dispatch_authorized: false` and `preflight_only:
  true`, and it is an availability projection, not permission to run anything.

## Guarantees

```text
PRODUCT_PC_ACCESS_CONTRACT_VERSION   = padiem.common-pc-access.v1
PRODUCT_PC_ACCESS_DEFAULT            = off
B14_IS_PC_ACCESS_AUTHORITY           = False
NEW_ENGINE_CREATED                   = False
NEW_BROKER_CREATED                   = False
NEW_DEVICE_AUTHORITY_CREATED         = False
NEW_DEVICE_TABLE_CREATED             = False
NEW_P01_APPROVAL_SERVER_CREATED      = False
ONLINE_DECIDED_IN_CONTRACT           = False
SECOND_ONLINE_AUTHORITY              = False
SECOND_DEVICE_AUTHORITY              = False
SECOND_CAPABILITY_VOCABULARY         = False
CLIENT_DEVICE_ID_TRUSTED             = False
SELF_ASSERTED_ACCOUNT_WORKSPACE_AUTHORITY = False
READ_GRANT_IMPLIES_WRITE             = False
WRITE_REQUIRES_SEPARATE_GRANT        = True
WRITE_REQUIRES_P01_APPROVAL          = True
CROSS_PRODUCT_TICKET_REUSE_ALLOWED   = False
PRODUCT_VIEW_EXPOSES_BROKER_INTERNALS = False
P01_VERIFIED_IS_AN_INPUT             = True
READ_APPROVAL_CAN_AUTHORIZE_WRITE    = False
PC_EXECUTION_PATH_NEWLY_WIRED        = False
PC_EXECUTION_REQUIRES_DEVICE_SESSION = True
PC_EXECUTION_REPLAY_ALLOWED          = False
DEVICE_VIEW_REQUIRES_OWNER_SCOPE_ATTESTATION = True
DEVICE_VIEW_REQUIRES_AVAILABLE_ATTESTATION   = True
DEVICE_VIEW_FAILS_CLOSED_ON_UNVERIFIED_ENVELOPE = True
DEVICE_VIEW_FAILS_CLOSED_ON_MALFORMED_ROW    = True
DEVICE_VIEW_REPORTS_EMPTY_ATTESTED_DIRECTORY = False
DEVICE_VIEW_ENFORCES_MAX_DEVICES             = True
DEVICE_VIEW_ENFORCES_DUPLICATE_DEVICE_ID     = True
DEVICE_VIEW_ENFORCES_DECLARED_DEVICE_COUNT   = True
DEVICE_VIEW_ECHOES_BROKER_ERROR_TEXT         = False
PREFLIGHT_ONLY_NO_DISPATCH_GRANT             = True
DISPATCH_AUTHORIZED_BY_THIS_CONTRACT         = False
DISPATCH_GATE_WIRED                          = False
P01_VERIFIED_IS_A_CALLER_SUPPLIED_INPUT      = True
FRESH_ONLINE_PROVEN_IN_CONTRACT              = False
TRUSTED_FRESH_ONLINE_FACT_AVAILABLE          = False
ONLINE_TRUTH_AUTHORITY  = canonical_broker_fresh_online_projection
```

## Responsibility boundary

LOCAL1 owns this common contract, the canonical-Broker-facing projection code
and its tests. **Product API/UI wiring is CENTRAL**: wiring B66, the Claw web
selector or Chat routes to `build_product_device_view` / `evaluate_pc_access`
is out of scope here. This slice adds no Worker schema, route, secret, device
enrollment, browser permission, remote execution or production deploy change,
and does not change the merged Claw `device_directory` / P01 behaviour.

Wiring the three merged/adjacent surfaces (`device_directory` #4418, read API
#4424, Web device manager #4419) to this product guard is the CENTRAL item; this
PR only provides the product-neutral contract they consume.

## S1 — PADIEM Connector enrollment (one account sign-in → one registered PC)

Slice S1 of #4139 answers the next question: after the PADIEM Connector is
installed on a Windows computer, **signing in with the same PADIEM account**
must be enough for that PC to be registered in the existing Canonical Broker.

### Investigation: what already existed and is reused as-is

| need | existing owner (reused, not re-implemented) |
| --- | --- |
| canonical user/account identity | `padiem_control_plane.auth_sessions.AuthSessionSnapshot` via the existing `resolve_current_auth_session` resolvers (B54 bridge / identity authority) |
| server-owned account/workspace refs | an injected Control Plane owner resolver (`CanonicalEnrollmentScopePort`) |
| reviewed product ids | `identity_authority.allowed_product_ids` (the contract declares no second registry) |
| device enrollment + one-time code + proof | `local_agent_broker_pairing.InMemoryBrokerPairingAuthority` (`/v1/broker/pairings/challenge`, `/redeem`) |
| binding, credential generation, rotation, revocation | `local_agent_broker.InMemoryLocalAgentBrokerAuthority` |
| device lifecycle vocabulary, ONLINE truth | `kagent.local_agent_pairing`, `kagent.local_agent_server_projection` |
| READ/WRITE execution approval + P01 | the existing P01 approval path |
| product → PC capability grants | `local_agent_pc_access` (this slice does not change it) |

Because every one of those already existed, S1 adds **no** login system, **no**
device DB/registry, **no** second pairing/credential/rotation/revocation
authority and **no** new authentication method.

### Source

- `packages/padiem-control-plane/padiem_control_plane/padiem_connector_enrollment.py`
  — `ConnectorEnrollmentScope`, `CanonicalEnrollmentScopePort`,
  `ConnectorEnrollmentConsent`, `evaluate_connector_enrollment`,
  `issue_connector_enrollment_challenge`, `redeem_connector_enrollment`,
  `connector_enrollment_dependencies`, `connector_enrollment_boundary`.
- Exported from `padiem_control_plane.__init__`.

### The enrollment chain (fail-closed, in order)

```text
Connector signs in            -> existing canonical PADIEM auth session (verified server-side)
evaluate_connector_enrollment -> session ACTIVE, USER subject, canonical tenant,
                                 reviewed product id, server-owned product-neutral scope,
                                 active enrollment consent scoped to that exact scope
issue_connector_enrollment_   -> canonical pairing challenge for the SERVER-derived
  challenge                      (account, workspace) — never a caller-supplied one
Connector redeems             -> canonical one-time code proof (device ownership)
redeem_connector_enrollment   -> re-verify session + consent, delegate to the canonical
                                 pairing authority, confirm the binding scope
registered PC                 -> canonical Broker binding, same device id for every product
```

The Connector, a browser or a product route can supply **none** of the identity,
scope, tenant or product facts, and the device id is never trusted as a
self-asserted claim — it is proven by possession of the one-time enrollment code
(the canonical HMAC-SHA256 pairing proof).

### Enrollment consent is not execution approval

```text
ENROLLMENT_CONSENT_REQUIRED                = True
ENROLLMENT_CONSENT_IS_EXECUTION_APPROVAL   = False
ENROLLMENT_CONSENT_GRANTS_READ             = False
ENROLLMENT_CONSENT_GRANTS_WRITE            = False
ENROLLMENT_CONSENT_GRANTS_DISPATCH         = False
EXECUTION_APPROVAL_OWNER                   = existing P01 approval path
EXECUTION_APPROVAL_MINTED_HERE             = False
```

Registering a computer and approving a READ/WRITE execution stay two separate
decisions owned by two separate authorities. Consenting to enroll never grants a
file read, a file write or a command run, and this contract mints no approval.

### One PC id, shared by every product

Enrollment is **owner-scoped and product-neutral**, so one physical computer has
exactly one canonical binding. A second product attempting to enroll the same PC
is refused by the canonical Broker (`duplicate_device_binding`), not given a
second registration:

```text
PRODUCT_SCOPED_ENROLLMENT                 = False
SHARED_DEVICE_IDENTITY_ACROSS_PRODUCTS    = True
DEVICE_REENROLLMENT_WITHOUT_REVOKE_ALLOWED = False
```

### Refusals (all bounded, upstream text never echoed)

| situation | bounded reason |
| --- | --- |
| no verified canonical session | `canonical_session_required` |
| revoked/expired session (account change, expired sign-in) | `canonical_session_inactive` |
| non-USER subject | `canonical_subject_not_user` |
| session without a canonical tenant | `canonical_tenant_required` |
| session from an unreviewed product | `canonical_session_product_not_reviewed` |
| resolver down/unconfigured | `enrollment_scope_unavailable` |
| resolver returned a non-scope | `enrollment_scope_unverified` |
| scope belongs to another user | `enrollment_scope_owner_mismatch` |
| resolver returned a product-scoped scope | `enrollment_scope_product_scoped_denied` |
| no / malformed consent | `enrollment_consent_required` |
| consent withdrawn | `enrollment_consent_withdrawn` |
| consent for another user/account/workspace | `enrollment_consent_scope_mismatch` |
| unknown / expired challenge | `enrollment_challenge_not_found` / `enrollment_challenge_expired` |
| challenge consumed twice | `enrollment_duplicate_redeem_denied` |
| bad/forged device proof | `enrollment_proof_invalid` |
| same PC enrolled a second time | `enrollment_duplicate_device_denied` |
| revoked binding, expired/rejected credential | `enrollment_binding_revoked_denied`, `enrollment_credential_expired_denied` |
| canonical issuance rate bound | `enrollment_rate_limited` |
| any other canonical refusal | `enrollment_dependency_refused` |
| dependency unavailable | `enrollment_dependency_unavailable` |

`ENROLLMENT_REFUSAL_BY_CANONICAL_CODE` is a closed table and a parity test
asserts every canonical code it names still exists in the canonical pairing /
Broker sources.

### Unsupported Connector authentication methods (dependencies, not inventions)

Recorded by `connector_enrollment_dependencies()` and required to stay
unimplemented (`NEW_AUTH_METHOD_INVENTED = False`): OIDC device authorization
grant (RFC 8628), mTLS client-certificate identity, SAML/SSO federation, and any
Connector-local password store. The Connector must present an existing canonical
PADIEM session; where the server has no such capability, that is reported as a
dependency instead of being invented.

### Guarantees

```text
CONNECTOR_ENROLLMENT_CONTRACT_VERSION = padiem.connector-enrollment.v1
SECOND_LOGIN_SYSTEM                   = False
SECOND_DEVICE_DB                      = False
SECOND_PAIRING_AUTHORITY              = False
SECOND_DEVICE_AUTHORITY               = False
SECOND_CREDENTIAL_STORE               = False
SECOND_ROTATION_AUTHORITY             = False
SECOND_REVOCATION_AUTHORITY           = False
NEW_AUTHORITY_CREATED                 = False
NEW_AUTH_METHOD_INVENTED              = False
SELF_ASSERTED_ACCOUNT_WORKSPACE_AUTHORITY = False
SELF_ASSERTED_DEVICE_OWNERSHIP        = False
DEVICE_POSSESSION_PROOF_REQUIRED      = True
PRODUCT_PC_ACCESS_DEFAULT_UNCHANGED   = True
DISPATCH_AUTHORIZED_BY_THIS_CONTRACT  = False
PC_EXECUTION_PATH_NEWLY_WIRED         = False
PRODUCTION_ACTIVATION                 = False
PRODUCTION_READY                      = False
```

### Evidence / limits (S1)

- Tests: `packages/padiem-control-plane/tests/test_padiem_connector_enrollment.py`
  (S1-01 … S1-31) exercise the real canonical pairing authority and the real
  canonical Broker binding authority: a verified session enrolls a PC whose
  credential then authenticates against the canonical Broker; cross-user,
  cross-workspace, revoked/expired-session, withdrawn-consent, wrong-proof,
  replayed-challenge and duplicate-PC attempts all refuse with a bounded reason;
  the one-time code and the device credential never appear in a `safe_dict`.
- **Not** proven: a live Windows 2-PC end-to-end run (`WINDOWS_LIVE_E2E`).
  `PRODUCTION_ACTIVATION=OFF`; no product route is wired to this contract, and
  the Connector client (`apps/claw-connect/**`, LOCAL2) is untouched.

## Evidence / limits

- New tests:
  `packages/padiem-control-plane/tests/test_local_agent_pc_access.py`
  (92 cases: default OFF, per-product grants, READ/WRITE isolation, workspace
  narrowing, cross-product ticket/approval replay denial, sanitized product
  view, shared device identity, revoked/expired/session-less/unknown-state
  refusal, P2 preflight preconditions (account/workspace scope, no implicit
  approval, READ approval cannot write, replay), canonical vocabulary parity,
  no-new-authority constants; plus the review-hardening cases G01–G05: owner
  scope/availability attestation required, `available:false` + device facts
  refused, empty attested directory refused, canonical `no_device_binding`
  kept distinct, duplicated device id / over-bound list / `device_count`
  mismatch / malformed state and session / bad `max_devices` all refused,
  Broker error text never echoed, preflight never authorized dispatch, and the
  view boundary parity with the canonical Broker constant).
- Full Control Plane suite: `1089 passed`.
- `WINDOWS_LIVE_E2E` is **not** proven by this slice and is not claimed.
  `PRODUCTION_ACTIVATION=OFF`; no product route is enabled.
