# #4139 — PADIEM and B66 Quote customer-brand separation

**Decision date:** 2026-10-13 KST  
**Applies to:** canonical Identity/Broker, My Devices, Claw/Chat/Engine, B66 Quote  
**Status:** Architecture policy and source-level fail-closed guard; no public UI or route deployed.

## Owner direction

**PADIEM and B66 Quote are distinct products in the customer's experience.**
A shared AI infrastructure provider, Broker, Windows Connector implementation or
central administrator does **not** mean the customers perceive, authenticate to,
subscribe to, or control both products from one visible portal.

The old wording “PADIEM 통합 계정 → 내 컴퓨터” as a single customer-facing
entry for *both* PADIEM and B66 Quote is superseded by this decision.
Product branding and product membership are separate, unless there is a
future **explicit, reviewed, user-approved account linking** feature.

| Boundary | PADIEM Claw / Chat / Engine | B66 Quote |
| --- | --- | --- |
| Customer-facing website/login/navigation | PADIEM-branded account and My PCs | Quote-branded account and Connected PCs |
| Cross-link/menu naming the other brand | **No by default** | **No by default** |
| Customer profile, product tier, purchase/quote records | Own product permissions | Own product permissions |
| Default device visibility | Own authorized product scope | Own authorized product scope |
| Connector binary, Broker/Identity implementation | Can reuse same internal infrastructure | Can reuse same internal infrastructure |
| Registration/linking to another product | Not automatic | Not automatic |
| Files/PC tasks | Explicit product entitlement + P01 per-action approval | Explicit product entitlement + P01 per-action approval |

**Important:** One physical Connector install can be a *future internal transport
capability*, but this does **not** mean a B66 login knows about Claw, that the
same email implies a linked canonical owner/tenant, or that a PC registered in
one brand appears in the other. Separate product login identity, reviewed
cross-product subject/tenant linkage and the user's explicit per-product consent
would be required before any cross-brand device reuse. Until that authorization
exists, show **no shared device and no cross-brand account hint**.

## Canonical technical boundary

- **Identity Durable Object:** authenticates a specific product session and
  tenant ownership; never match accounts by an unverified email string.
- **Broker Durable Object:** canonical device identity/revoke/session authority
  shared behind the services, not a customer-visible unified brand.
- **ProductPcAccessPolicy:** explicit default-OFF access to `device.list` for
  each separately authenticated product and workspace; no P01 READ/WRITE
  follows from owning a PC.
- **PadiemPcAccountDeviceService / product_device_view_for_owner:** before
  exposing any product device list, the verified canonical login's
  `session.product_id` MUST exactly equal the requested `product_id`.
  The private server MUST reject a mismatch **before Broker lookup**. A
  Claw session plus a Quote grant is insufficient. B66's own current-session
  bridge is **not yet approved**; this policy does not silently enable it.
- **Backoffice administrator:** may govern product-specific access/routing,
  but must not acquire automatic customer PC file access, credentials,
  cross-product browsing history or silent cross-brand account linking.

## Separate future UI surfaces

**PADIEM:** `계정 → 내 컴퓨터` (PADIEM branding).
Includes PC registration, current connection facts, per-PADIEM-capability
controls and approved task records only when its own security gates are
wired. Does not offer a B66 sign-in, show a Quote subscription, or add a
"Switch to B66" menu by default.

**B66 Quote:** `견적 계정 → 연결된 컴퓨터` (B66 branding).
Only B66-connected approved devices and quote-file task permissions.
No PADIEM/Claw list, membership badge, shortcuts or global account panel.
Until independent B66 identity bridging and explicit product-PC grants are
proven, this page must show **not connected** or remain hidden; never
invent a shared link or imply the PC is online.

**Central operations:** One *internal* policy/Broker fleet infrastructure
may operate both, with enforced product/tenant partitioning, audited
role-specific actions and no support-operator credential exposure.

The physical PC may eventually be reusable across products *without a
second client installation*, but only when separate product authorization
and explicit linking are implemented. That is not an activated promise
from the present PC enrollment draft.

## Source verification / release gates

The central Draft #4476 adds fail-closed checks:
1. Product-facing PC directory rejects `session.product_id != product_id`.
2. The private account/device service rejects the mismatch **before** calling
   the Broker directory.
3. Tests assert Claw login + Quote product grant cannot list Quote devices.
4. The canonical owner-registration admission remains B54-only pending
   independently approved B66/Chat/Engine login bridges.
5. No UI, product endpoint or cross-brand account-linking is enabled.

```makefile
INTERNAL_PADIEM_CONNECTOR_IMPLEMENTATION=SHARED
CUSTOMER_FACING_PADIEM_AND_B66_BRANDS=SEPARATE
PADIEM_QUOTE_SSO_LINK=NOT_APPROVED
QUOTE_ACCOUNT_AUTOMATICALLY_SEES_PADIEM_DEVICE=NO
PADIEM_ACCOUNT_AUTOMATICALLY_SEES_QUOTE_DEVICE=NO
CLIENT_PRODUCT_ID_TRUSTED_AS_AUTHORITY=NO
CROSS_PRODUCT_AUTO_GRANT=NO
B66_CANONICAL_LOGIN_BRIDGE=NOT_APPROVED
PUBLIC_PC_MANAGEMENT_UI=NOT_MOUNTED
WINDOWS_LIVE_E2E=NOT_PROVEN
READY=NO
MERGED=NO
PRODUCTION=OFF
```
