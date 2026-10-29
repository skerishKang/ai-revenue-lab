# #4139 Connector — can MeshCentral carry PC commands in parallel? (2026-10-29 KST)

**Status:** RESEARCH MEMO + the record of what shipped on this lane · no code in this document is authorised by it · the fix that shipped first is `fix/pc-line-blockage-selfheal-261029` (#6106, detection and clearing on the serial lane), and the follow-up closes its cross-host hole (§0). Implementation of anything below §1 is a separate PR with its own work contract.

**Primary artifact examined:** official MeshCentral, repository `Ylianst/MeshCentral`, and the published npm package `meshcentral@1.3.1` (tarball unpacked, read directly). Line numbers are from that package. Anything not seen in that source is marked **INFERENCE** or **UNVERIFIED**.

## 0. What shipped, and the hole its follow-up closed

#6106 heals the serial lane: a pre-flight look at the PC's console over the terminal
tunnel, a 120-second bound on the wait for an ANSWER (never on the work), one retry
after clearing, and counts in the journal. Its own active-dispatch map says which PC
this connector is busy with.

That map is the limit of what one host can see. Two executor hosts exist (#5462) and
during a handover both can hold a claim on one PC, so the first host's 120-second
silence can be the second host's running command - and a sweep that ended it would
break standard rule 1. The follow-up therefore gates the clearing on the server's own
claim state:

* a read-only `POST /api/claw/connector/mesh-reads/busy` on the Chat side takes the
  node reference and the asker's own dispatch id, and answers from the lease columns
  the lane already writes - `state='pending' AND expires_at>now AND nonce_sha256 IS
  NOT NULL AND claimed_until>now`, minus the asker's own row. One boolean, nothing
  claimed, nothing written, the same channel proof as poll.
* the held sweep runs only when that answer says nothing is claimed. A live claim, a
  refused channel, a non-200, an unreadable body, a port composed with no guard at
  all - all of them mean **clear nothing**. The safe default here is deliberately the
  opposite of the owner-stop probe's, because what this answer unlocks is ending a
  process on a customer machine.
* the pre-flight (abandoned-marker) scope is not gated: it already reaches only a
  marker this very host wrote, so it cannot be wrong about a partner's work, and
  gating it would spend a channel round trip on every command for no safety.

### 0.1 The stop must prove the PC ran it (live measurement, 2026-10-29 KST)

Qoder measured the terminal channel on COM1 (older agent), COM2 and a freshly installed
CGI-1 agent: a line typed into `meshctrl shell` comes back as a mirror of itself —
the probe line answered 71 bytes, `+"\n"` 73 bytes, `+"; Exit"` 77 bytes, printable
characters 1.00 — with no prompt, no banner and no error. Input is not executed, and the
behaviour is independent of agent generation. That is a defect of this transport, not of
the agent version, so the console probe ships off (#6183) and the per-dispatch session
lane (#6163) stays off until the transport answers.

What it does not excuse: the owner's stop rode the same session and reported
`cancel_kill` as though it had worked. An opened session is not evidence. The stop script
now ends with `Write-Output ('__PADIEM_' + 'KILL__')` — built from two literals, so the
terminal's echo of the typed line can never contain the joined token — and
`kill_command_process` raises `MeshCentralStopUnconfirmed` unless that token comes back.
`_stop_on_pc` then logs `cancel_kill_unverified`, distinct from `cancel_kill_refused`:
the stop was delivered and is unproven, which is the honest state of this lane today.
Diffing #6106 against #6059 found no channel regression — the stop's argv, stdin
bootstrap, pty payload and 15-second bound are byte-identical; #6106 only extracted
`_run_shell_session`. So the stop was never verified through this path recently, and it
now cannot claim otherwise.

## 1. Why the lane is serial, and what a stuck command actually does to the next one

`runcommand` has no server-side queue. `src/meshuser.js:3216-3325` (`case 'runcommands'`) only forwards the request to the agent with `agent.send()`. The lock is entirely agent-side, in `agents/meshcore.js:1975`:

```js
if (mesh.cmdchild != null) { sendConsoleText("Run commands can't execute, already busy."); break; }
```

`mesh.cmdchild` is one agent-global handle and is cleared only in the child's own `exit` handler (`delete mesh.cmdchild`, `agents/meshcore.js:2003 / 2018 / 2034`).

Two consequences that change how the incident reads:

* A second command while the agent is busy is **dropped, not queued**. The agent prints a console line and never sends a reply for the request. That is exactly our `no_reply` with an unobserved exit code — it is not "waiting behind" the orphan, and no amount of waiting clears it.
* Therefore a wedged `mesh.cmdchild` is a permanent state until that child exits or the handle is cleared. A retry is only meaningful after the holder is gone, which is what the shipped fix does (one retry after the sweep). The word "queue" in the older code comments describes the intent, not the mechanism.

`responseid` / `sessionid` (`src/meshuser.js:3297`) disambiguate the reply stream; they do not create a second command lane.

## 2. `meshctrl.js` subcommand inventory (what a CLI caller can actually ask for)

`meshctrl.js:50` (`possibleCommands`) contains `runcommand`, `shell`, `upload`, `download`, `devicepower`, `deviceinfo`, `listusersessions`, `devicesharing`, `webrelay`, `report`, `agentdownload`, `indexagenterrorlog`.

**`sessionAdd`, `sessionGroups`, `nodeTasks`, `command` do not exist** in this version (they belong to MeshCommander-era material). Only `shell` opens an independent session: `meshctrl.js:2217-2225` requests an auth cookie and then sends `{action:'msg', type:'tunnel', value:'*/meshrelay.ashx?p=<1|6>&nodeid=...&id=<rand>&rauth=...'}`, and `meshctrl.js:2867+` binds the CLI's stdin/stdout to that relay websocket.

This is the source-level reason the out-of-band lane works: the terminal is a *tunnel*, and tunnels never touch `mesh.cmdchild`.

## 3. Terminal sessions are already parallel per node — the real candidate

`agents/meshcore.js:3564` (protocol table): 1 = terminal (admin), 6 = PowerShell (admin), 8/9 = user variants, 7 = plugin. The agent keeps a `tunnels[]` array indexed by `nextTunnelIndex++` (`meshcore.js:937, 1426`), counts each session in `tunnelUserCount.terminal++` (`meshcore.js:2869`) and reports `{action:'sessions', type:'terminal'}` (`agents/meshagent.js:1562`). Each terminal tunnel spawns **its own** pty (`win-terminal` / `win-virtual-terminal` → `StartPowerShell`, `meshcore.js:2920-2970`). A tunnel closes only on an explicit `endtunnel` (`meshcore.js:1437-1455`).

* No per-node terminal cap was found in the agent. **N concurrent PowerShell terminals per PC are supported by the agent today**, each with its own byte stream, addressed by the relay token (`p`, `nodeid`, random `id`, `rauth`/`auth`).
* `src/meshrelay.js:1046` gates which protocols a given cookie may open — the permission boundary lives there, not in the agent.
* `meshprojects`, `CoreTerminal`, `terminal_server.js`: **not found** in MeshCentral source. Do not design against them.

Design shape this permits (not implemented): one terminal session per dispatch, keyed by our own `dispatch_id`, with the transcript read off that session's stream instead of a `--reply` console transcript. That removes the serial lane entirely rather than healing it.

Tradeoffs to price before choosing it: a terminal is interactive by protocol, so output framing becomes our job (the envelope/sentinel work already in `local_agent_meshcentral_command_port.py` carries over); a leaked session is a live pty on a customer PC until `endtunnel`, so the same "no orphan may survive" rule we just built is required for sessions too; per-dispatch sessions change exit-code semantics and the desktop/read lanes that share the agent.

## 4. "Agent Tasks" is a stub; genuine parallel commands come from a plugin

`src/taskmanager.js` is 19 lines and returns an empty object. It is switched on by `config.json` `Settings.taskmanager` (`src/meshcentral.js:1779`). Its only agent-side hook is `agents/meshagent.js:1848` `case 'script-task'` → `taskManager.agentAction()`, and nothing in `meshcore.js` emits `script-task`. Core MeshCentral therefore has **no working per-task command runner**.

The feature people mean by that name is the third-party plugin `ryanblenis/MeshCentral-ScriptTask`. Its agent module `modules_meshcore/scripttask.js` spawns **its own child per `jobId`** (`runScript` / `jobIsRunning` / `finalizeJob`, returning `{action:'plugin', plugin:'scripttask', pluginaction:'jobComplete', jobId, retVal, errVal}`), bypassing `mesh.cmdchild` — genuinely parallel, with its own result channel.

Costs: `Settings.plugins.enabled` plus meshcore module injection (`pluginHandler.js:155 addMeshCoreModules`); a 1-minute dispatch timer (`scripttask.js:34`); no implemented concurrency cap (the source carries a `//@TODO ... taskLimiter`, line 67); 200-event / 90-day job history; no offline queuing. It is also an Apache-licensed third-party dependency injected into the agent on customer machines — a `TECHNOLOGY_ADOPTION_POLICY` decision, not an internal change.

## 5. Knobs that do NOT help, and one trap to respect

`domain.limits.maxagentsessions` (`src/meshagent.js:726`), `maxusersessions` / `maxsingleusersessions` (`src/meshuser.js:390`), consent flags (`domain.userconsentflags`, `src/meshcentral.js:1609`; `domain.consentmessages.autoacceptifterminalnouser`, `src/meshrelay.js:926`) gate consent and session counts. None makes `runcommand` concurrent.

Trap for any retry or heartbeat loop on this lane: `src/meshagent.js:1287-1295` closes the agent connection once `consoleKickCount > 30` consecutive **identical** agent console output strings arrive (anti-DoS). That drops the agent offline, so a probe that repeats one payload — or a `kill` retried verbatim 31 times — is not safe at high frequency.

## 6. Clearing a wedged console without touching the agent service — SPIKE VERDICT

**Verdict: reachable, but not with `meshctrl.js`. It needs a new small WebSocket client, and it is not cheaper than what shipped. Recommendation: do not build it now; keep the terminal-session sweep and re-open this only as part of the dispatch-session design (§3).**

What the source says:

* `processConsoleCommand` (`agents/meshcore.js:4784`) does implement `ps`, `kill [pid]` (`meshcore.js:5895`, plain `process.kill`) and `tunnels` (`meshcore.js:6192`), fed by `{action:'msg', type:'console', value: ...}` (`meshcore.js:1358-1364`) and gated by rights `& 8` and `& 16` = AgentConsole. That path never touches `mesh.cmdchild`, so ending the stuck `powershell.exe` fires its `exit` handler → `delete mesh.cmdchild` → `runcommand` recovers with **no service restart**. Nothing is blocked about the mechanism.
* `meshctrl.js` cannot send it. The literal `'console'` appears zero times as a message type in `meshctrl.js` (master, 3,356 lines, and npm `latest` = 1.3.1), `possibleCommands` (`meshctrl.js:50`) has no such subcommand, and the reply handler folds `case 'msg'` (`meshctrl.js:2305`) into a `responseid`-gated block (`meshctrl.js:2333-2340`) that would not surface console output even if it arrived.
* Typing `kill 123` inside a `meshctrl shell` session is **not** that path. `processConsoleCommand` has only two feeders: the `msg`/`console` handler above and a local registered-app IPC path that requires `debugConsole` (`meshcore.js:641-644`). A terminal tunnel spawns a real pty (`win-terminal` / `win-virtual-terminal`, `meshcore.js:2920, 2962, 2970`), so `kill` there resolves to PowerShell's `Stop-Process` alias — which is the same class of action our sweep already performs with `taskkill /T /F`. The shipped fix therefore already reaches the outcome by the CLI-reachable route.
* The minimal new client is: connect `wss://<host>/control.ashx` (`meshctrl.js:1368-1376`), then send `{action:'runcommands', nodeids:['node/<domain>/<id>'], type: 4, cmds: 'kill <pid>', responseid: '<x>'}`. `type: 4` is first-party and labelled "agent console command" in `src/meshuser.js:3246-3268`, which checks `(rights & 24) != 24` and builds the `{action:'msg', type:'console', ...}` message. Auth is the `x-meshauth` header (`meshctrl.js:1389-1395`), or a passwordless `?auth=` via `--loginkey` / `--loginkeyfile` (`meshctrl.js:1398-1425`), or a token from `meshctrl LoginTokens --add` (`meshctrl.js:1472-1480`). No REST route exists (`runcommands` is absent from `webserver.js`), and `meshcmd` is agent-local only (`agents/meshcmd.js:186-196`).
* What it would buy, and what it would not: the ACK is `result:'OK'` alone, and real output returns as `{action:'msg', type:'console', value, nodeid}` events on the caller's own session (`src/webserver.js:10489-10502`; agent side `meshcore.js:6840, 6844`) with **no sentinel framing of ours**. So `kill` could replace one half of a sweep session while the detection half — which needs the marker, the parent chain and the protected set read back as a parseable verdict — would still need the pty session and its Base64 frame. Reaching that only by console events also loses the tree kill (`/T`) that a `taskkill` of the marker pid gives us today.
* Consent: no customer-visible prompt. The console branch never reads `data.consent` (`meshcore.js:1358-1364`); consent exists only on tunnel paths (`meshcore.js:1392-1417`, `2773+`).
* `eval` (`meshcore.js:5923`, help listed at `meshcore.js:4789`) is guarded only by the same `& 8 && & 16` check, and its own source comment reads "can only be run by trusted administrator" (`meshcore.js:5929`). It runs arbitrary JavaScript as SYSTEM on the customer's machine. Not adopted, for any purpose, including `delete mesh.cmdchild`.

`agentupdate` / `agentupdateex` (`meshcore.js:5135`) swap meshcore without stopping the Windows service; relevant only if an agent-side change ever becomes necessary.

_Correction to the first draft of this memo: it cited `agents/meshagent.js` for the session limits and the anti-DoS kick. The package ships that file at `src/meshagent.js`; the line numbers were right, the directory was not._

## 7. What the pre-flight probe costs (test environment, 2026-10-29 KST)

Requested measurement, stated with its boundary: these numbers are **this development PC and the test doubles**, so they cover PADIEM's own work and the floor of launching a child. They do **not** cover a real agent round trip. The live per-command number is Qoder's to take on 컴1, and it is the one that matters for the lane's latency budget.

Environment: Windows 11 (10.0.22631), CPython 3.13.7, Node v26.3.0, code at `main` after #6106. Timed with `time.perf_counter`.

| What | min | median | max | n |
|---|---|---|---|---|
| `sweep_script(...)` build (one held-scope script, 2,494 bytes) | 0.0029 ms | 0.0037 ms | 0.0677 ms | 3,000 |
| `parse_sweep_reply(...)` on a noisy terminal buffer (echo + frame) | 0.0019 ms | 0.0022 ms | 0.0200 ms | 3,000 |
| Bare `node -e 0` child launch on this PC (the floor of any meshctrl session) | 32.4 ms | 35.3 ms | 40.0 ms | 15 |

What that does and does not say:

* The Python the probe adds is **microseconds per command** and is not the cost. Anything measured above is process launch and network.
* One sweep is one `meshctrl shell` session — the same shape, same credential path and same 15-second bound (#6059) already ships as the owner's stop. So the added latency per command is approximately **one stop session per command**, and its floor on this PC is ~35 ms of node startup; the real total is node startup + tunnel connect + agent terminal + one PowerShell + the CIM queries.
* The session exits **as soon as its answer frame parses** (`_TerminalHandoff.wait_for` breaks on the predicate), so a healthy PC does not pay the 15-second bound. The polling granularity is 0.2 s (`select` timeout), so the answer is noticed within 200 ms of arriving.
* Worst case is bounded by `LINE_SWEEP_WAIT_SECONDS = 15` for the sweep, and the sweep's failure is reported (`line_probe_refused` / `line_probe_unobserved`) rather than retried into a loop.
* Two consequences worth deciding on deliberately, because they are choices and not facts: (1) a live claim on that PC now gates the held sweep, so the probe's channel round trip still happens at pre-flight while the clearing itself is skipped; (2) if the round trip measures materially against interactive read latency, the pre-flight scope can be narrowed to once per node per window, or made to run only after a non-clean previous outcome, with the 120-second path left as the recovery.

## 8. Recommendation ordering for the next slice

1. Keep the shipped serial-lane healing (detection, bounded clearing, one retry, counters) with the server-claim gate of §0. It addresses the measured failure with the channels that are already reachable and already proven on a real PC.
2. Spike **per-dispatch terminal sessions** (section 3). It is the only option that is both parallel and first-party, and it removes the class of defect instead of recovering from it. Price the framing, session-leak and exit-code consequences first. The `{action:'msg', type:'console'}` lane of section 6 belongs to this decision, not to a separate one: it only makes sense as the result channel of sessions we already own.
3. Do not build the console-`kill` client on its own (section 6 verdict): it cannot carry detection, it drops the tree kill, and it adds a second authenticated transport for one half of one command.
4. Treat the ScriptTask plugin (section 4) as an adoption decision requiring `TECHNOLOGY_ADOPTION_POLICY` review, not as a quick win.

## Sources

- https://github.com/Ylianst/MeshCentral — `agents/meshcore.js`, `agents/meshcmd.js`, `src/meshagent.js`, `src/meshuser.js`, `src/meshrelay.js`, `src/webserver.js`, `src/taskmanager.js`, `src/pluginHandler.js`, `meshctrl.js` (npm `meshcentral@1.3.1` tarball, shasum `ce04bd2...405fb`; master `meshctrl.js` re-fetched for the §6 verdict, 3,356 lines)
- https://docs.meshcentral.com/
- https://github.com/ryanblenis/MeshCentral-ScriptTask — `modules_meshcore/scripttask.js`
- https://registry.npmjs.org/meshcentral/latest
