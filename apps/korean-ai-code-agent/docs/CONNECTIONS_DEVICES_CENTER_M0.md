# B54 Connections & Devices Center M0

Issue: #1742  
Parent: #1651  
Status: repository-side projection + static UI reference

## Purpose

Give Padiem Claw one visible trust-management surface for external connector accounts and Padiem Local Agent devices without creating a new authority system.

The Center composes existing authority-owned projections:

```text
Control Plane / trusted connector authority
  → ConnectorBindingProjection
  → ConnectorHealthProjection

Local Agent trusted management authority
  → LocalAgentManagementSnapshot
  → DeviceBinding / DevicePermissionProfile / activity summaries

P01
  → approval/evidence authority for material actions

Connections & Devices Center
  → safe read projection + management affordances only
```

The Center never turns a button, browser field, client boolean or model request into trusted authority.

## Connector account card

A connector card exposes only safe management state:

- service label;
- connector/account/binding refs;
- connected / expired / action-required / unavailable / revoked;
- granted scopes;
- granted capabilities;
- conservative access class: read-only / read-write / material-write;
- current health/freshness;
- last successful probe timestamp when known;
- last material action summary/evidence ref when known;
- private/shared/public exposure warning;
- reconnect/disconnect/revoke affordances appropriate to state.

Secret material is never a card field:

```text
ACCESS_TOKEN = NO
REFRESH_TOKEN = NO
CLIENT_SECRET = NO
API_KEY = NO
COOKIE = NO
```

Expired, degraded, stale-health and unavailable bindings remain visible as action-required states rather than being rendered as healthy.

## Local Agent device card

The Local Agent card reuses `LocalAgentManagementSnapshot` and therefore remains bounded by the existing device/workspace/root/capability model.

Visible state:

- device ID/name;
- paired account/workspace ref;
- platform + architecture;
- client version;
- lifecycle/online state;
- last seen;
- compatibility/current/update state;
- exact user-selected roots;
- per-root capability policy;
- device-global capability policy;
- last bounded local activity summary;
- disable/revoke/delete/update affordances.

Existing Local Agent protections remain authoritative:

```text
OUTBOUND_ONLY = YES
WHOLE_PC_GRANT = NO
ADMIN_ELEVATION_DEFAULT = NO
RAW_DEVICE_CREDENTIAL = NO
RAW_COMMAND_OUTPUT_IN_CENTER = NO
```

The static reference may display Windows root paths because the existing trusted `LocalAgentManagementSnapshot.safe_dict()` deliberately exposes the user-selected roots for management. This does not expand roots or authorize access outside them.

## Capability escalation

Scope/capability widening is explicit and reviewable.

Every escalation projection contains:

```text
current scope
requested scope
additions
removals
reason
sensitivity
approval required
trusted approval present / absent
```

A pending widening can be shown before approval, but it cannot authorize itself. `require_authorized_widening()` fails closed whenever additions exist and no trusted approval reference is present.

```text
DISPLAY_PENDING_REQUEST = ALLOWED
UI_APPROVES_ITSELF = NO
SILENT_WIDENING = NO
TRUSTED_APPROVAL_REQUIRED_TO_APPLY = YES
```

A pure narrowing does not require widening approval, but the actual mutation still uses the existing trusted management/connector mutation path.

## One-place revocation

The aggregate `ConnectionsDevicesCenterSnapshot` returns a `revocation_targets` projection containing both:

- connector disconnect/revoke targets;
- Local Agent disable/revoke/delete targets.

This is a discoverability feature, not an execution API.

## Static UI reference

`site/connections.html` is intentionally self-contained and labeled:

```text
SYNTHETIC STATIC REFERENCE
REAL_BACKEND_WIRED = false
UI_ACTION_AUTHORITY = false
SECRET_VALUE_VISIBLE = false
```

It demonstrates:

- healthy connector;
- action-required/shared connector;
- visible read/write classification;
- Local Agent roots/capabilities;
- last probe/action fields;
- capability escalation comparison;
- one-place revocation surface.

All buttons are disabled. There are no forms, external scripts, external stylesheets, token fields or live account/device calls.

## Backend/live gate

Before parent #1651 can be considered live-ready:

1. wire the Center to trusted Control Plane connector binding/health reads;
2. wire Local Agent device/session/management reads;
3. establish truthful last-successful-probe and last-material-action evidence sources;
4. bind reconnect/disconnect/revoke to trusted server-side operations;
5. bind Local Agent disable/revoke/delete/update to existing management authorities;
6. bind escalation approval to P01/trusted approval authority;
7. prove client-side mutation attempts cannot widen scopes or permissions;
8. prove secret/token/device-credential values never enter the Center payload or logs;
9. verify expired/revoked/unavailable states with real adapters;
10. perform accessible UI/browser acceptance against the live settings shell.

## Non-claims

```text
REAL_CONNECTIONS_CENTER_BACKEND_WIRED = NO
REAL_CONNECTOR_ACCOUNT_SHOWN = NO
REAL_LOCAL_DEVICE_ACTION_EXECUTED = NO
REAL_RECONNECT_DISCONNECT_REVOKE = NO
REAL_PERMISSION_WIDENING = NO
SECRET_VALUE_VISIBLE = NO
UI_ACTION_AUTHORITY = NO
PRODUCTION_MUTATION = NO
PRODUCTION_READY = NO
```
