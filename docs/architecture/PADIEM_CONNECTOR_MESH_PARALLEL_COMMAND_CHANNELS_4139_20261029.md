# #4139 Connector — can MeshCentral carry PC commands in parallel? (2026-10-29 KST)

**Status:** RESEARCH MEMO · no code in this document is authorised by it · the fix that shipped is `fix/pc-line-blockage-selfheal-261029` (detection and clearing on the serial lane), NOT a parallel channel. Implementation of anything below is a separate PR with its own work contract.

**Primary artifact examined:** official MeshCentral, repository `Ylianst/MeshCentral`, and the published npm package `meshcentral@1.3.1` (tarball unpacked, read directly). Line numbers are from that package. Anything not seen in that source is marked **INFERENCE** or **UNVERIFIED**.

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

`domain.limits.maxagentsessions` (`agents/meshagent.js:726`), `maxusersessions` / `maxsingleusersessions` (`src/meshuser.js:390`), consent flags (`domain.userconsentflags`, `src/meshcentral.js:1609`; `domain.consentmessages.autoacceptifterminalnouser`, `src/meshrelay.js:926`) gate consent and session counts. None makes `runcommand` concurrent.

Trap for any retry or heartbeat loop on this lane: `agents/meshagent.js:1289` closes the agent connection after 30 identical console messages (anti-DoS). A polling-style probe that repeats one payload is therefore not safe at high frequency.

## 6. Clearing a wedged console without touching the agent service

`processConsoleCommand` (`agents/meshcore.js:4784`) implements agent console verbs including `ps`, `kill [pid]` (`meshcore.js:5895`, plain `process.kill`) and `tunnels` (`meshcore.js:6192`). These arrive as `{action:'msg', type:'console', value: ...}` (`meshcore.js:1359`), are routed by `src/meshuser.js:1021`, and require rights `& 8` and `& 16` = AgentConsole (`meshctrl.js:2641`). Because that path never touches `mesh.cmdchild`, ending the stuck `powershell.exe` fires its `exit` handler → `delete mesh.cmdchild` → `runcommand` recovers, with **no service restart**. This matches what was done by hand on 2026-10-28 and 2026-10-29.

The shipped fix reaches the same outcome through `meshctrl shell`, which is CLI-reachable and measured. The narrower follow-up worth one spike: whether an authorised client can send the `console` message directly (it is a server↔agent message type, and `meshctrl.js` exposes no subcommand for it in 1.3.1). If it can, detection and clearing become one small message instead of a bounded pty session. `eval "delete mesh.cmdchild"` (`meshcore.js:5923`) would clear the handle even faster but is **INFERENCE** — an unverified way to poke agent internals on a customer machine, and not adopted.

`agentupdate` / `agentupdateex` (`meshcore.js:5135`) swap meshcore without stopping the Windows service; relevant if an agent-side change ever becomes necessary.

## 7. Recommendation ordering for the next slice

1. Keep the shipped serial-lane healing (detection, bounded clearing, one retry, counters). It addresses the measured failure with the channels we already trust.
2. Spike **per-dispatch terminal sessions** (section 3). It is the only option that is both parallel and first-party, and it removes the class of defect instead of recovering from it. Price the framing, session-leak and exit-code consequences first.
3. Spike the direct `console` message path (section 6) as a cheaper clearing primitive.
4. Treat the ScriptTask plugin (section 4) as an adoption decision requiring `TECHNOLOGY_ADOPTION_POLICY` review, not as a quick win.

## Sources

- https://github.com/Ylianst/MeshCentral — `agents/meshcore.js`, `agents/meshagent.js`, `src/meshuser.js`, `src/meshrelay.js`, `src/taskmanager.js`, `src/pluginHandler.js`, `meshctrl.js` (npm `meshcentral@1.3.1` tarball, shasum `ce04bd2...405fb`)
- https://docs.meshcentral.com/
- https://github.com/ryanblenis/MeshCentral-ScriptTask — `modules_meshcore/scripttask.js`
- https://registry.npmjs.org/meshcentral/latest
