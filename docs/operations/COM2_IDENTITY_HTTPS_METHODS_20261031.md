# COM2 identity HTTPS ingress: source call sites

Base: main 19c76ccad. This is a source inventory, not evidence that a gated
feature is active in a deployed environment. Existing nine methods are
unchanged. The table identifies 12 of the 14 additional methods as called by
Chat source. P01 source uses the existing resolve_auth_session and
resolve_connector_workspace methods; no calls to the 14 were found in its app.
No calls to the 14 were found in apps/padiem-broker. The 8802 relay and
private network endpoint must be separately configured; this change deploys
nothing and never creates secrets.

| Additional method | Call location |
|---|---|
| issue_google_connect_ticket | apps/padiem-chat/app/connector_ticket_routes.py:122 |
| create_tenant | apps/padiem-chat/app/control_plane_identity.py:213 |
| assign_tenant_membership | apps/padiem-chat/app/control_plane_identity.py:217; connector_owner_role_bootstrap.py:78 |
| resolve_active_memberships | apps/padiem-chat/app/control_plane_identity.py:204; connector_owner_role_bootstrap.py:71 |
| resolve_active_tenant_membership | apps/padiem-chat/app/claw_automation_mutation_authority.py:144 |
| install_connector_enrollment_schema | apps/padiem-chat/app/connector_enrollment_schema_install.py:60 |
| resolve_connector_owner_scope | apps/padiem-chat/app/chat_pc_drive.py:467; connector_pending_pc_owner_rpc.py:92 |
| grant_connector_enrollment_consent | apps/padiem-chat/app/claw_connector_enrollment_routes.py:314 |
| revoke_connector_enrollment_consent | apps/padiem-chat/app/claw_connector_enrollment_routes.py:337 |
| resolve_connector_enrollment_consent_for_device | apps/padiem-chat/app/canonical_connector_enrollment_async_host.py:101 |
| bind_connector_enrollment_challenge | apps/padiem-chat/app/canonical_connector_enrollment_async_host.py:144 |
| authorize_connector_enrollment_redeem | apps/padiem-chat/app/canonical_connector_enrollment_async_host.py:214 |

`get_tenant` and `revoke_tenant_membership` were not found as calls in these
source directories and remain closed over HTTPS. The ingress retains the
existing service HMAC verification and default-off secret. Existing method-level
enrollment/schema gates still apply; exposing these methods broadens the
shared-secret caller's authority and requires CTO security review before any
separate deployment.
