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
