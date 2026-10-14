### Corrigendum to the comment above (line-number precision)

Two line references in my #4546 preliminary-phase comment were off; the evidence and conclusions are unchanged.

| Cited | Correct |
|---|---|
| `identity_authority_worker.py:108` (*"Private canonical identity/session and connector-ticket authority"*) | **L110** |
| `identity_authority_worker.py:131-136` (`RuntimeError` when the env product set does not match the reviewed set) | **L126** |

All other cited paths and line numbers were re-verified exactly:

```text
identity_authority_worker.py:23        _ALLOWED_PRODUCTS = {"b62", "b54-padiem-claw"}
identity_authority_worker.py:24/25/31/36  closed RPC key sets
identity_authority_worker.py:339/347   resolve_active_memberships / resolve_active_tenant_membership
engine_admission_authority_worker.py:57   "Canonical entitlement + usage authority. No public HTTP route exists."
engine_admission_authority_worker.py:22-24,71-75  product boundary + RuntimeError on mismatch
b54_identity_bridge.py:51, 98-99, 115  B54_PRODUCT_ID, resolve_current_auth_session(product_id=…), cross-product guard
control_plane_identity.py:27, 75-110, 136, 278  PADIEM_CHAT_PRODUCT_ID="b62", Protocol, bridge, require_active_canonical_session
entitlements.py:131-133                allows() default-deny
auth_routes.py:83-128, 108-111         auth_status payload + "never used as access authority"
product-capabilities.js:66-68          hardcoded display-only tier list
worker_config.py:38 / worker.py:129    IDENTITY_AUTHORITY_SERVICE binding name + resolution
```

No re-verification of the underlying claims was needed — only the two line numbers.
