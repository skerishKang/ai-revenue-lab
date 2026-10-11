# #4139 B54 Claw Connect — Web "내 컴퓨터" management UX (2026-10-12)

## Scope and release gate

This is a **read-only, fail-closed client UI** over PR #4414's existing
`PadiemClawLocalHandoff.deriveDeviceDirectory`. It does not register devices,
pair them, grant P01 approval, mint credentials, choose a default target, issue
commands or turn on remote access.

New assets:
- `apps/padiem-chat/static/claw-device-manager.js`
- `apps/padiem-chat/static/claw-device-manager.css`
- `apps/padiem-chat/tests/test_4139_claw_device_manager_browser.py`

The button appears only in the **actual Claw workspace**, not the ordinary
Chat conversation. Opening it performs exactly one same-origin GET.
No interval polling is allowed. Explicit refresh, visible-page return or account
change revalidates the snapshot. Closing/leaving Claw forgets the choice.

## LOCAL1 server integration handoff

**Proposed unimplemented B62 GET**: `/api/claw/local-access/devices`.

Only after LOCAL1's canonical Broker `device_directory` RPC is implemented and
reviewed should B62 expose this same-origin route. Its narrow browser-facing
success envelope:

```json
{
  "ok": true,
  "available": true,
  "ownerScoped": true,
  "devices": [
    {
      "deviceId": "office-pc",
      "deviceName": "사무실 PC",
      "platform": "Windows",
      "state": "CONNECTED",
      "usable": true,
      "revoked": false,
      "expired": false
    },
    {
      "deviceId": "laptop",
      "deviceName": "노트북",
      "platform": "Windows",
      "state": "OFFLINE",
      "usable": false
    }
  ]
}
```

- `available:true` and `ownerScoped:true` may be emitted **only after**
  server-side account/workspace authentication and a trusted Broker directory
  read. They are a UI envelope, not authentication proof in the client.
- Never accept account, workspace or identity hints from query parameters.
  Derive them from the current authenticated session; no public unauthenticated
  or cross-workspace directory. Prefer a 401 if logged out; cache-control
  `no-store` and `Vary: Cookie` (or appropriately scoped response headers).
- Use existing `kagent.local_agent_server_projection` for canonical ONLINE,
  with session and heartbeat checks. Broker should not claim ONLINE itself.
- `devices` max 24, stable sort, exact canonical device ID, duplicates and
  overflow fail closed. **No** tokens, session refs, binding refs, secrets,
  credentials, command output, arbitrary logs, owner/workspace identifiers.
- A legitimate empty directory is `available:true, ownerScoped:true,
  devices:[]`. Unconfigured server is `available:false` or 404/503, **not
  an empty successful directory**. The UI distinguishes these honestly.
- Only trusted server fields are shown via `textContent`; raw response extra
  fields are discarded from in-memory projection.
- **No server-side selection or execution endpoint is introduced here.** A
  browser-selected `deviceId` is a visual candidate ONLY. Future task
  execution must rederive owner+workspace+device, conversation/run/P01 decision,
  TTL and revocation atomically at the authoritative broker before work.
- Do not silently connect a sole online PC or persist selected device in
  localStorage, sessionStorage, cookies or a messenger bot.
- On account change, navigation away from Claw, offline/revoke or source failure,
  stale selections must be dropped. Visibility return is a GET to recheck
  rather than a connection claim.

## Work boundaries

- LOCAL1 owns **canonical Broker multi-device directory** only.
- LOCAL2 owns **Windows Claw Connect tray / resident / installer** only.
- CENTRAL owns this B62 Web UI and later authenticated B62 route wiring.
- Telegram/Discord/Hermes bridging requires separate identity mapping,
  channel policy, P01 approvals, and controlled acceptance in #3099.
- No production Worker/DB/Secrets/pairing/WRITE/SEND should be deployed from
  this UI PR.

## Evidence

Browser tests: three responsive viewport widths (390, 873, 1280), no implicit
selection, explicit online-only choice, denied offline/revoked, refresh revocation,
owner-change clearing, unavailable vs empty, malicious HTML/credential fields
filtered, Escape-to-close and no command requests. Legacy #3084/#4139 static
projection tests remain required.
