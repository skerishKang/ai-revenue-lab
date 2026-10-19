# B54 Claw Connect — B62 authenticated multi-PC read API

Date: 2026-10-12 KST · GitHub #4139 · Verified Windows Alpha #3099

## Implemented scope

Authenticated GET `/api/claw/local-access/devices`, read-only.
This is the B62 boundary between **merged** Broker `device_directory` (#4418)
and the pending Web '내 컴퓨터' panel (#4419).

1. Cookie authenticated owner is resolved with existing `auth_ready` and
   `current_user_id`; workspace is resolved via canonical
   `claw_memory_routes._resolve_memory_workspace` (no input scope arguments).
   Missing canonical CP/shadow identity is 503, NOT an owner-only cross-tenant
   list. The legacy owner namespace is allowed only under the existing
   both-canonical-components-absent compatibility rule.
2. One trusted `LOCAL_AGENT_BROKER_AUTHORITY_SERVICE` binding only, and only its
   existing `device_directory({account_ref,workspace_ref})` RPC.
   Missing binding or method returns honest `available:false`.
3. Each Broker row is checked against the *exact* session owner and workspace;
   device ID must be well-formed and unique, max 24, count consistent. Any bad
   record refuses the **whole** directory.
4. The ONLY ONLINE classifier is pre-existing
   `CanonicalClawLocalAccessTruthSource._canonical_state` invoking canonical
   `kagent.local_agent_server_projection`. A fabricated `online` field,
   stale/no heartbeat, revoked or expired session cannot grant `CONNECTED`.
5. Raw Broker facts (session IDs, binding refs, credential generations, account
   or workspace references, tokens, command logs) are never serialized to Web.
   Only `deviceId, deviceName, platform, state, usable, revoked, expired`.
6. Owner-verified empty list returns `available:true, ownerScoped:true,
   devices:[]`. An absent/unhealthy service returns `available:false`; an
   unauthenticated request is HTTP 401. Query parameters (especially identity
   or device hints) are rejected with 400. All responses use `no-store`.

## Real integration path

```text
authenticated B62 web owner + canonical workspace
                  │
     GET /api/claw/local-access/devices
                  │
 trusted LOCAL_AGENT_BROKER_AUTHORITY_SERVICE
                  │
    read-only Broker device_directory RPC (#4418)
                  │
       binding + session + heartbeat facts
                  │
 pre-existing canonical ONLINE projection (#3094)
                  │
          minimal safe Web devices list
                  │
   Claw '내 컴퓨터' visual selector PR #4419
```

**NOT implemented or authorized** by this route: device registration, pairing,
credential creation, P01 decision, execution tickets, file/command READ or
WRITE, webhook, Telegram or Discord SEND. Even a selected ONLINE device is a
visual candidate, not an execution grant; any future work ticket must revalidate
owner, workspace, device ID, fresh ONLINE state and P01 approval atomically.

## Acceptance evidence

`apps/padiem-chat/tests/test_4139_claw_device_directory_route.py` plus
existing #3094 local access tests cover canonical bound source, valid empty vs
unconfigured, session and workspace isolation, malformed/duplicate/overflow,
revoked/expired, stale heartbeat, true connected receipt, query/owner spoof,
no credential leakage and no mutation. CI exact-head pending independent run.

Web UI PR #4419 must be rebased on the merged API after acceptance and its
device-list 390/873/1280 browser suite rerun before any production rollout.
Hermes/Telegram/Discord remain separate adapter and P01 approval tasks.
