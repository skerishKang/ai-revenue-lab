# B54 Claw Connect — multi-PC Web device selection contract (2026-10-12)

Issue: [#4139](https://github.com/skerishKang/ai-revenue-lab/issues/4139); controlled Windows Alpha proof: [#3099](https://github.com/skerishKang/ai-revenue-lab/issues/3099).

## Decision

Use the existing canonical PADIEM Local Agent Broker, account/workspace identity,
P01 approvals and single Local Runner. **Never create a second device authority,
a Web-issued pairing token or an always-on public PC inbound port.**

The initial independently reviewable Web slice is
`static/claw-local-handoff.js::deriveDeviceDirectory`. It is a pure,
side-effect-free read-only projection and **does not turn on remote access**.

### Typed boundary for a future *authenticated* device directory

The following is the shape consumed by the pure Web view-model; it is **not
a new enabled production HTTP endpoint**:

```json
{
  "available": true,
  "ownerScoped": true,
  "devices": [
    {"deviceId":"office-pc","deviceName":"사무실 PC","platform":"Windows",
     "state":"CONNECTED","usable":true},
    {"deviceId":"home-pc","deviceName":"집 PC","platform":"Windows",
     "state":"OFFLINE","usable":false}
  ]
}
```

`ownerScoped` is only an envelope expectation, **not proof of authentication**.
A future same-origin endpoint must derive authenticated account and workspace
from the server session, query only that owner's canonical Broker authority,
and send sanitized facts with `Cache-Control: no-store`. Neither HTTP query
parameters nor a Telegram/Discord user ID may independently establish scope.
Missing/untrusted directory → no devices / no targeting, never a guessed online
status. The client must not turn a local status or its own `ownerScoped` flag
into an execution grant.

### Web projection invariants (implemented + tested)

- At most 24 bounded devices; duplicates or malformed device identity reject
  the *entire* directory (no silently choosing the first occurrence).
- Device identifiers are exact ASCII tokens; never infer by visible name.
- No implicit target even when exactly one connected PC exists.
- A selected device must exist in the **current** owner-scoped snapshot and have
  canonical `CONNECTED`, explicit `usable:true`, and no expiry/revocation.
- Unrecognised state, offline, revoked, expired and pairing state are not
  actionable. Online appearance cannot be inferred from recent local activity.
- List/order and human-readable names are presentation only; never copy raw
  credentials, owner/workspace IDs, pairing tokens or stdout to the UI.
- Recheck the *exact* account/workspace/device_id on the server for each work
  ticket; a client-selected ID is a hint, **not authority**. Bind target to
  conversation/run and P01 approval before execution.

### Connection routes and messaging

```text
Claw Web ────────┐
Telegram (Hermes)├─ authenticated PADIEM identity + conversation
Discord (Hermes) ┘      │
                         ├─ server-authoritative Broker directory & P01 approval
                         └─ exact work ticket(owner,workspace,device,run)
                                        │
                         outbound-only selected Windows Resident
                                        │
                         bounded/redacted result to initiating conversation
```

Hermes messenger adapters are **not implemented by this Web slice**. Messenger
user and chat/channel identifiers require explicit PADIEM account linkage and
a permission policy, not blanket trust of any incoming bot command. Denied,
offline, stale approval, channel/owner mismatch and revoked connections execute
**zero** local actions. PC auto-start is an explicit opt-in after Windows user
login; it does not change command authorization.

### Next implementation contract (LOCAL1 separate worktree)

1. Finish tray-only Claw Connect and optional Windows login auto-start. Expose
   canonical heartbeat and device identity through the existing Resident.
2. Add owner/workspace-scoped **read-only multi-device directory** to the
   canonical Broker, never a parallel table of online status. Pairing remains
   the existing server-authoritative flow with explicit user approval.
3. Wire the Web directory projection to an accessible device selector with
   explicit device choice and fresh server-side revalidation. Keep unconfigured
   production surface disabled; **do not** fabricate devices for screenshots.
4. Prove at least two physically separate Windows PCs, one offline/revoked
   negative case, approval denial, and results returned to the originating
   conversation. Log controlled Alpha acceptance once in #3099.
5. Introduce the optional `npx` launcher and Telegram/Discord adapter later,
   reusing the *same* Runner and Broker device identity. Full Desktop must not
   start a second Runner when Connect is already installed.

## Evidence / limits

- New tests: `apps/padiem-chat/tests/test_4139_claw_device_directory_projection.py`.
- Existing #3084 projection/IME test remains unchanged and runs alongside.
- This PR contains **no** Worker, schema, secret, device enrollment, browser
  permission, remote execution or production deploy change.
- `deriveDeviceDirectory` returning `canTarget:true` means **only a currently
  online, explicitly selected device may be displayed as a possible target**;
  it does not authorize running a command and must not be treated as P01.

## LOCAL1 server slice — canonical Broker `device_directory` RPC (2026-10-12)

The server half of item 2 ("owner/workspace-scoped read-only multi-device
directory to the canonical Broker") is implemented in the existing Canonical
Local Agent Broker. No new DB, device table, endpoint or authority is created.

**Source**

- `packages/padiem-control-plane/local_agent_broker_durable_runtime.py`
  — `LocalAgentBrokerDurableRuntime.device_directory` plus the shared
  `_device_facts` projection and `select_current_bindings_by_device`.
- `packages/padiem-control-plane/local_agent_broker_worker.py` — thin
  passthrough on `LocalAgentBrokerDurableObject` and the `Default` gateway.

**RPC contract**

- Request key set is closed and identical to `device_truth`:
  `{account_ref, workspace_ref?}`. A caller can narrow by workspace but can
  never name a device, so a device id is an output, never an input.
- Response: `{ok, available, owner_scoped, device_count, max_devices, devices[]}`
  where each device row is the exact `device_truth` fact set
  (`canonical_state` + `binding` + `session` + `heartbeat_last_seen_at`).
- `canonical_state` reuses the `device_truth` vocabulary only —
  `revoked` / `credential_expired` / `paired_offline`. The broker **never**
  reports ONLINE; each row carries the binding + session + heartbeat facts the
  existing `kagent.local_agent_server_projection` rule needs to decide ONLINE
  downstream. A second ONLINE authority is not created.
- Empty owner scope returns `{ok:true, available:false, reason:"no_device_binding"}`.
  Malformed requests, a duplicated/forged device identity (two ACTIVE bindings
  for one device id) and more than 24 devices each fail the **whole** directory
  closed with a bounded error code; the list is never truncated.

**Guarantees**

```text
DEVICE_DIRECTORY_VOCABULARY_HAS_ONLINE=False
DEVICE_DIRECTORY_SECOND_ONLINE_AUTHORITY=False
DEVICE_DIRECTORY_SECOND_DEVICE_AUTHORITY=False
DEVICE_DIRECTORY_OWNER_SCOPED=True
DEVICE_DIRECTORY_MUTATION=False
DEVICE_DIRECTORY_MAX_DEVICES=24
DEVICE_DIRECTORY_TRUNCATES=False
DEVICE_DIRECTORY_STABLE_ORDER=device_id_ascending
```

**Evidence / limits**

- New tests:
  `packages/padiem-control-plane/tests/test_local_agent_broker_device_directory.py`
  (owner/workspace scoping, 3-PC/1-PC/offline/revoked/expired/missing-heartbeat
  states, re-pairing collapse, duplicate + >24 fail-closed, read-only, no
  secret leakage, single-PC `device_truth` regression).
- Integration test:
  `apps/padiem-chat/tests/test_4139_claw_connect_multi_device_directory.py`
  drives the real broker entrypoint and feeds each directory row through the
  real B62 consumer seam and the existing ONLINE rule, proving CONNECTED/usable
  is produced only by that rule.
- This slice adds no Worker schema, secret, device enrollment, browser
  permission, remote execution or production deploy change, and **no** Web
  surface change: wiring the Web selector to this RPC remains item 3 (CENTRAL).

