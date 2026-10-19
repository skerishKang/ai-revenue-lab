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

These are **presentation** states. `ONLINE` is reserved for the canonical
`server_projection` owned by #3080. Local runner supervision may report runner
health, but it cannot make the shell claim a paired, reachable device.

## Pairing deep-link seam

`padiem://pair?...` is parsed, bounded and turned into a **non-secret**
correlation reference. Values are never returned to the renderer, no credential
is stored, and no session is minted. #3080 owns the canonical contract.

## Workbench shell (#3598, first slice)

The renderer is a three-pane desktop workbench derived from the ZCode
information architecture. This is an IA adaptation, **not** a pixel copy and
**not** a ZCode authority import: Padiem identity, P01 approval, the Local
Runner, the Execution Broker, Drive/artifact authority, connector authority and
the existing account/workspace authority are unchanged.

```text
┌─ top shell ─ current task title · workspace/project context · Settings ─────┐
│ Navigation  │  Claw task workspace            │  Tools / status             │
│ New task    │  existing continuation          │  Connection                 │
│ Search      │  canonical conversation         │  Local Runner               │
│ Automations │  tool/run + result cards        │  Progress / Approvals       │
│ Plugins     │                                 │  Artifacts                  │
│ Projects    │                                 │  Git (placeholder)          │
│ Sessions    │                                 │                             │
├─────────────┴─────────────────────────────────┴─────────────────────────────┤
│ composer: task input · execution/computer-access status · run action        │
└─────────────────────────────────────────────────────────────────────────────┘
```

Rules this shell holds to:

- **No fabricated capability.** `New task`, `Automations`, the plugin
  marketplace, task submission and Git have no backend authority in this slice.
  They render as visibly non-executable controls (`disabled` +
  `aria-disabled` + `data-unsupported`) with an honest reason — never as
  working buttons, and never with invented changed files or progress.
- **Real state only.** Progress / Approvals / Artifacts are counts projected
  from the canonical run list the shell already holds. An unavailable canonical
  source is stated in words; it is never rendered as a zero.
- **No model/provider selector.** `SUCCESSOR_MODEL_SELECTED=NO`, so the composer
  shows provider-neutral execution facts (local execution, computer access)
  only. `MODEL_SELECTOR_ACTIVATION=0`.
- **Nothing is removed.** Workspace selection, connection/re-check,
  readiness/pause and Local Runner state are re-placed into the new IA, not
  deleted.
- **#3591 search is composed, not reimplemented.** The Search/Projects
  navigation opens the existing #3583 bounded search surface; the search and
  filesystem authority stay in the main process.
- **Responsive.** At narrow widths the navigation rail collapses to an icon
  strip and the tools rail stacks under the centre, so the centre workspace
  stays primary.

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
