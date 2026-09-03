# B54 OpenBot Selective Reuse Matrix v1

Status: repository-side implementation slice  
Issue: #1653  
B54 base: `bf9d020e641cf90e110433339c9403fdf690f34e`  
OpenBot source of record: `skerishKang/OpenBot@257c1280d684089be9adb0b35cce262efc7064bf`  
License: MIT

## Decision

OpenBot is not adopted as the Padiem Claw product/runtime authority.

```text
P01           = canonical Tool / Skill / Approval / Evidence authority
B14           = model / provider / routing / model-credential authority
Control Plane = identity / entitlement / trusted secret and connector-account authority
B54           = Padiem Claw product + physical connector/computer execution adapters
```

This slice ports implementation behavior only where it fits those boundaries.

## Reuse matrix

| OpenBot source | Padiem target | Disposition | Notes |
| --- | --- | --- | --- |
| `server/src/plugins/transport.ts` | `connector_platform.py` | PORT / ADAPT | One transport contract; protocol details stay below grant/policy. |
| `server/src/plugins/catalogue.ts` | `connector_platform.py` | PORT / HARDEN | Pinned first-party source contracts and auth ownership. Padiem strengthens unknown-tool classification to `write`. |
| `server/src/plugins/mcp.ts` | `ConnectorTransport` contract | SHAPE REUSE | No MCP SDK dependency added in B54 M0. A future trusted MCP adapter plugs into the same contract. |
| `server/src/plugins/store.ts` | `ConnectorRuntime` | PORT / ADAPT | Grant check and policy check remain separate. No new approval authority is created. |
| `server/src/plugins/tools.ts` | `ConnectorRuntime`, `ConnectorSkill` | PORT / ADAPT | Skill declarations narrow tools but never grant a capability. |
| `server/src/plugins/oauth.ts` | Control Plane / connector authority | DO NOT PORT INTO B54 | OAuth state, refresh token and client-secret custody belong outside B54 task/model state. |
| `server/src/plugins/google-drive-rest.ts` | `google_drive_connector.py` | PORT / ADAPT | Tool names, query escaping, page bound, MIME allowlist, native export and explicit empty-result behavior ported. Credential resolution replaced by trusted `AuthorizedGoogleDriveHttpPort`. |
| `server/src/plugins/catalogue.ts` Notion entry | `NOTION_ENTRY` | PORT / HARDEN | Official hosted MCP endpoint retained as a reviewed source contract. Unknown live tools are material until explicitly classified. |
| `agent-computer/src/control.ts` | `agent_human_control.py` | PORT / HARDEN | Help/take/release, no agent action during takeover, secret reference metadata. Padiem additionally binds takeover to opaque `control_session_ref`. |
| `server/src/computer/gateway.ts` / policy | existing P01+B54 boundaries | CONCEPT REUSE | Existing B54 contracts are stronger and stay canonical; do not create a second policy state machine. |
| `server/src/computer/provider.ts` / `supervisor/*` | existing `agent_computer.py`, sandbox-provider contracts | CONCEPT REUSE | Docker-socket-specific supervisor code is not vendored into Cloud M1. Server-owned lifecycle and isolation semantics are already represented provider-neutrally. |
| `server/src/channels/*` | P01 orchestration | DO NOT PORT | Would duplicate canonical thread/run/orchestration authority. |
| OpenBot model/provider runtime | B14 | DO NOT PORT | B14 remains the only model/provider/router authority. |
| OpenBot credential tables | Control Plane/B14 trusted secrets | DO NOT PORT | B54 keeps opaque refs only. |
| OpenBot identity/entitlement | Control Plane | DO NOT PORT | No duplicate identity/billing authority. |

## Connector behavior adopted

### Transport contract

Every physical connector must fit:

```text
ConnectorConnection (opaque binding + actor ref)
  -> ConnectorTransport.list_tools()
  -> ConnectorTransport.call_tool()
```

MCP, REST and future built-in connectors can differ underneath without changing
grant, policy, audit or model-facing tool semantics.

### Grant and policy are separate

```text
tool exists
  -> agent has exact tool grant
  -> current trusted policy permits the exact call
  -> physical transport call
```

A grant is not a policy waiver. A skill is not a grant.

### Unknown tools fail closed

OpenBot documents a dangerous asymmetry for catalogue entries whose live server
advertises a new tool missing from the reviewed write list. B54 v1 removes that
ambiguity:

```text
explicit reviewed read -> read
anything else          -> write/material
```

This is intentionally stricter than the upstream default.

## Google Drive port

The read transport keeps the four upstream-compatible tool names:

```text
search_files
list_recent_files
get_file_metadata
read_file_content
```

Ported behavior:

- pinned GA REST base `https://www.googleapis.com/drive/v3`;
- page size 25;
- query escaping for backslash and apostrophe;
- result file id + metadata + web link;
- Google Docs -> `text/plain`;
- Google Sheets -> `text/csv`;
- Google Slides -> `text/plain`;
- positive textual MIME allowlist;
- binary/unknown content is refused instead of decoded as garbage;
- empty search explicitly says nothing was found;
- model-facing result is bounded to 20,000 characters.

Changed for Padiem:

- no bearer/access/refresh token exists in B54 connection objects;
- `AuthorizedGoogleDriveHttpPort` receives only opaque binding and actor refs;
- trusted connector authority resolves/refreshes the credential outside B54;
- live external calls remain unconfigured in this repository-only slice;
- writes remain unsupported until a separately reviewed P01 approval/evidence path exists.

## Human control port

Ported lifecycle:

```text
AGENT
  -> help requested
  -> HUMAN control taken
  -> agent actions refused (never queued)
  -> HUMAN releases
  -> AGENT
```

Padiem hardening:

- takeover is correlated to an opaque trusted `control_session_ref`;
- release must present the exact same ref;
- pending secret stores only label + field/snapshot refs;
- secret value is never stored in this state machine;
- expired unanswered help requests clear after 10 minutes;
- an active human takeover is never timed out from under the person.

## Reuse not performed in this slice

### OAuth implementation

OpenBot's sealed state + PKCE implementation is useful reference code, but moving
its verifier/token/client-secret custody into B54 would violate the current
authority split. #1632 should expose an opaque trusted OAuth/binding port rather
than make Claw a second token vault.

### Docker supervisor source

The OpenBot supervisor deliberately owns a Docker socket and controls per-Bot
containers. B54 Cloud M1 already requires provider-neutral sandbox conformance,
no runtime socket in the workload, explicit teardown and stronger provider
evidence. The lifecycle pattern is reused; Docker-specific authority is not.

### Historical removed connectors

Current OpenBot catalogue comments record that Atlassian, Box, Slack,
Salesforce and ServiceNow entries existed previously and were deliberately
removed because the deployment did not stand behind untried connectors. Do not
restore them blindly. Each #1631 child connector must recover and review its
historical entry, vendor endpoint, auth model and current official API/MCP
surface before adoption.

## Test coverage in #1653

Deterministic tests cover:

- pinned catalogue and secret-free projections;
- unknown/custom tool fail-closed classification;
- bounded/explicit connector results;
- skill declarations cannot self-grant tools;
- grant and policy both required;
- Drive tool compatibility, query escaping, page bound, native export and MIME safety;
- no raw credential field crossing the Drive HTTP seam;
- takeover TTL, exact control-session correlation and agent refusal during human control;
- secret reference metadata without secret value persistence.

## Production status

```text
REAL_CONNECTOR_OAUTH_CONFIGURED = NO
REAL_GOOGLE_DRIVE_CONNECTOR_CONFIGURED = NO
REAL_MCP_TRANSPORT_CONFIGURED = NO
PRODUCTION_MUTATION = NO
PRODUCTION_READY_CLAIM = NO
REPOSITORY_READY_FOR_TRUSTED_CONNECTOR_INTEGRATION = YES
```
