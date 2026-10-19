# PADIEM account-wide My Devices — CENTRAL #4139 / draft #4476

**Stage:** Source-only S1, unmounted. **Brand-separation correction:** PADIEM and B66 Quote remain distinct visible customer services; shared backend does not imply shared customer account or device visibility. `PADIEM_CONNECTOR_BRAND_SEPARATION_4139_20261013.md` supersedes any earlier wording suggesting one unified customer-facing portal. **Primary infrastructure objective:** one enrolled
Windows PC available from PADIEM Quote B66, Claw B54, Chat B62, Engine and future
products **only where independently authorized**. Registration is an account
capability; using a PC is a separate product+P01 capability.

## Implemented source boundary

| Existing component | Authoritative responsibility |
| --- | --- |
| Canonical Identity Durable Object | Signed active canonical session, tenant OWNER membership, reviewed login bridge and explicit consent |
| Reviewed canonical account/workspace scope | Product-neutral owner scope; legacy B62 context remains an unapproved candidate |
| Canonical Local Agent Broker Durable Object | One binding and device ID per PC, read-only scoped `device_directory`, revoke/session/heartbeat facts |
| Shared `local_agent_pc_access.py` (#4429) | Independent default-off product `device.list`, READ/WRITE guard and strict sanitized directory |
| New `padiem_pc_account_devices.py` | Read-only account My Devices projection + per-product directory gate over SAME Broker facts |
| New `padiem_pc_account_device_service.py` | Private-source Identity→Broker read composition; feature off by default; no route |
| Windows `kagent` / LOCAL2 #4490 | Existing outbound HTTPS transport, same Broker device, DPAPI store and protected install ACK |

The new owner view returns only `device_id`, `canonical_state`,
`has_session` and `heartbeat_present`, explicitly **not** ONLINE.
The canonical ONLINE rule remains `kagent.local_agent_server_projection`.
No `subject_id`, `tenant_id`, `account_ref`, `workspace_ref`,
`binding_ref`, `credential_generation`, credential or session secret crosses
the account read boundary.

The shared parser:
- rejects a swapped account/workspace binding, a mixed owner, unverified
  Broker attestation, duplicate device ID, wrong device count, invalid state,
  malformed session, unbounded or truncated list and any Broker error;
- does **not** return a partially filtered list when an owner-scope check fails;
- recognizes canonical `no_device_binding` as an honest empty view;
- allows an authenticated OWNER to see account devices **without** creating any
  permanent product entitlement;
- returns an empty list for B66, Claw, Chat or Engine unless the existing
  `ProductPcAccessPolicy` explicitly grants that product `device.list`
  for this workspace;
- never returns `dispatch_authorized`, an approval, P01 READ/WRITE or
  authenticated ONLINE simply because a PC appeared in a list.

## Closed staging boundary

This stage **does not** add an account-level public route. The private Identity
owner-context resolver is an **injected protocol**, not a new identity service
and not implemented in deployed `app_factory.py`. Any future adapter must
resolve the current product login through a verified canonical Identity DO
session, re-read live OWNER tenant membership, and resolve an approved
product-neutral scope before passing the context to this service.

The shipped flags are hard-false:

```makefile
PADIEM_PC_ACCOUNT_READ_ROUTE_MOUNTED=NO
PADIEM_PC_ACCOUNT_DEFAULT_READ_ENABLED=NO
PADIEM_PC_ACCOUNT_REVOKE_ROUTE_MOUNTED=NO
CANONICAL_SCOPE_SECURITY_APPROVAL=PENDING
INITIAL_REVIEWED_OWNER_LOGIN=B54_ONLY
B66_CHAT_ENGINE_LOGIN_BRIDGES=PENDING
B14_PC_ACCESS_AUTHORITY=NO
PRODUCT_PC_ACCESS_DEFAULT=OFF
DISPATCH_AUTHORIZED=NO
P01_READ_GRANTED=NO
P01_WRITE_GRANTED=NO
WINDOWS_LIVE_E2E=NOT_PROVEN
PRODUCTION=OFF
```

## Next implementation sequence

1. Review canonical account/tenant/workspace **scope**; the old `b62`
   `canonical_connector_context` row has not been certified for universal
   PC ownership. Do not solve this by inventing a per-product scope or
   guessing cross-product account equality from a shared email.
2. Implement the reviewed server-owned `resolve_current_owner_context`
   private adapter using the *existing* Identity DO and browser login. This
   must be bound to the original authenticated server session, not arbitrary
   `session_id` or `owner_id` from a client body. Keep the route off until
   signed login+CSRF+owner scope and read evidence are proven.
3. Integrate one account-wide **Connected computers / My Devices** UI and
   backend service; product views consume existing default-off
   `ProductPcAccessPolicy`. No second binding table or separate B66/Claw
   installation.
4. For **revoke**, an explicit owner action with current session/CSRF and
   exact canonical binding must call existing Broker revoke and verify its
   result; do not expose an unguarded device-id-to-revoke API and do not assume
   withdrawing consent alone disconnects the live PC.
5. Source and QA: same PC visible to account owner; not visible to ungranted
   product; cannot cross scope, reuse a product ticket, elevate READ to WRITE
   or fake ONLINE; exact-head Control Plane and B62 CI; authorized real Windows
   #3099 multi-product E2E. Activate only after all security gates.

**Ownership:** CENTRAL CTO controls Identity, Broker and account Devices API;
LOCAL2 controls Windows receiver; B66 chat work is separate. No automatic
merge, schema install, or production deployment from this source-only PR.
