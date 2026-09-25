# Padiem Desktop Shell — M1 (CLAW4 #3083)

Electron + React **Windows desktop shell** that supervises a **separate Padiem
headless runner process**.

This is the first source-only shell foundation for Padiem Claw Desktop. It is a
**presentation and lifecycle** slice, not an execution slice.

## Authority boundaries (non-negotiable)

| Boundary | Status |
| --- | --- |
| Electron renderer is not the execution authority | yes |
| Electron main is not a P01 replacement | yes |
| Desktop shell is not the broker authority | yes |
| Second execution authority | 0 |
| Second pairing authority | 0 |

Canonical device/session truth belongs to **#3080** (broker + pairing).
Windows process-tree kill (Job Object) belongs to **#3081**.
The runner does not implement P01 approval; that stays in the existing
KAgent/B54/P01 stack and is wired in a later slice.

## Architecture

```text
React renderer  (no node, no fs, no child_process, no network)
    |  window.padiemShell  -> 6 allowlisted methods only
    |  contextBridge, contextIsolation=true, sandbox=true, nodeIntegration=false
Electron main   (owns the device projection, the IPC allowlist, the supervisor)
    |  typed RunnerSupervisor
Padiem headless runner  (separate OS process, no inbound listener)
```

## IPC surface (the whole surface)

```text
padiem:shell:get-status
padiem:shell:runner-start
padiem:shell:runner-stop
padiem:shell:runner-health
padiem:shell:pairing-deeplink-submit
padiem:shell:get-bounded-log
```

There is deliberately **no** `invoke(command, args)`, no channel passthrough and
no raw shell terminal. `tests/preload-and-main-security.test.ts` reads the actual
preload/main/renderer sources and fails if any of those come back.

## Device presentation states

```text
NOT_PAIRED  PAIRING  OFFLINE  ONLINE  ACTION_REQUIRED
```

These are **presentation** states. `ONLINE` can only be reached from a
`supervision` or `server_projection` fact, so neither the renderer nor a locally
running process can talk the shell into claiming a paired, reachable device.

## Pairing deep-link seam

`padiem://pair?...` is parsed, bounded and turned into a **non-secret**
correlation reference. Values are never returned to the renderer, no credential
is stored, and no session is minted. #3080 owns the canonical contract.

## Commands

```bash
npm ci                 # ELECTRON_SKIP_BINARY_DOWNLOAD=1 is set in .npmrc
npm run typecheck
npm run build          # tsc + esbuild renderer bundle
npm test               # build + node --test
npm run package:win    # source-ready packaging config; NOT signed, NOT published
```

## Not in this slice

```text
Production signing                     NO
Auto-update rollout                    NO
Production installer publish           NO
Broker transport                       NO   (#3080)
Pairing/session minting                NO   (#3080)
Runner execution semantics             NO   (P01/KAgent/B54 stack)
Windows Job Object process-tree kill   NO   (#3081)
Desktop run persistence / recovery     NO
```
