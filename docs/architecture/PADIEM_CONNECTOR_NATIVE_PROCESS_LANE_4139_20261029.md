# #4139 Connector — stop typing into a shell: the agent's native process lane (2026-10-29 KST)

**Status:** source investigation + the design it authorises · nothing in this document is
deployed by it · the code that follows is a separate PR with its own work contract ·
no merge until the CTO says so, and the executor picks it up only after the queue-cutover
observation window.

**Primary artifact examined:** `meshcentral@1.3.1` (npm tarball unpacked, read directly:
`agents/meshcore.js`, `meshuser.js`, `meshweb/webserver.js`, `meshctrl.js`,
`views/default.handlebars`). Line numbers are from that package. Anything not seen there is
marked **UNVERIFIED**.

## 0. Why the typing route is dropped

Qoder's live measurement after #6207: on CGI-1 (installed today) and on the older COM1
agent alike, a terminal session answered **371 bytes in 75 seconds**, the prompt `>` was
visible, the input was mirrored, nothing executed; the sweep stayed `unobserved` and the
stop channel returned **0 bytes in 20 seconds**. Same on both agent generations.

#6207 fixed a real defect on this host (the pty echoed our own bytes and the client's answer
stream was discarded) — it was **necessary, not sufficient**. The remaining suspect is
exactly what that commit message said it did not prove: the Windows console at the far end
does not accept the submission we send. Rather than keep guessing at encodings on a channel
that (a) is not needed for anything else and (b) can only be tested by holding a customer
PC's console, this lane moves to a path MeshCentral itself already uses for this job.

## 1. The web UI "Processes" tab is a structured agent command, not a typed console

That tab's Stop button sends one frame
(`views/default.handlebars:11040`):

```js
meshserver.send({ action: 'msg', type: 'pskill', nodeid: currentNode._id, value: tag })
// tag = pid + '|' + name                                    (default.handlebars:11039)
```

and the list it renders comes from `{action:'msg', type:'ps'}`. The agent side is one
switch, inside `case 'msg'` (`agents/meshcore.js:1357`):

| verb | agent line | needs | agent action | reply |
|---|---|---|---|---|
| `ps` | `:1498-1504` | `data.sessionid` | `processManager.getProcesses(cb)` | `{action:'msg', type:'ps', value: JSON.stringify(plist), sessionid}` |
| `psinfo` | `:1505-1539` | `data.pid` | `getProcessInfo(pid)` | `{action:'msg', type:'psinfo', pid, sessionid, value:{…}}` |
| `pskill` | `:1542-1550` | `data.value` | `process.kill(parseInt(pid))` + `MeshServerLogEx(19,…)` | none; a console text on failure (`pskill: <error>`) |

Three properties make it the better lane:

* **It never touches `mesh.cmdchild`.** `runcommand` is refused-and-dropped while one agent
  command child lives (`agents/meshcore.js`, the serialisation this memo series documented at
  §1); a terminal tunnel is a separate session; `ps`/`pskill` are a third, already-used
  path. A held console cannot block it.
* **The answer is a real field, not text.** The reply's `value` is JSON keyed by pid, each
  record carrying at least `cmd` and `user` — proven by the first-party parser
  (`views/default.handlebars:10842-10848`), which reads `processes[pid].cmd` and
  `.user` and passes `pid + '|' + cmd` to `pskill`. Owner standard 4 (verdicts from state,
  never from a string match) is satisfiable here in a way it never was on a terminal.
* **Rights are the ones this deployment already has.** The agent gates only the *text*
  console: `agents/meshcore.js:1360` requires `rights & 8` **and** `rights & 16`
  (Remote Control and Console). `ps`/`psinfo`/`pskill` carry no such check — the server's own
  routing requires `rights & MESHRIGHT_REMOTECONTROL (8) || MESHRIGHT_REMOTEVIEWONLY (256)`
  (`meshuser.js:288`), injects `command.sessionid = ws.sessionId` (`:292`) and adds the
  caller's rights to the frame (`:293`). Desktop control already works on these PCs, so the
  authority exists; no new privilege is asked for.

### What the official clients do and do not expose

* `meshctrl.js` has **no** `ps`/`pskill` subcommand (absent from `possibleCommands`, and
  nowhere in the file), and its `runcommand` sends only
  `type: ((args.powershell) ? 2 : 0)` (`meshctrl.js:1814`) — it cannot reach the agent
  console type either.
* No HTTP/REST route relays `msg`: `webserver.js` has no `case 'msg'` handler; the API
  surface is separate from this socket. The agent's reply is delivered by
  `obj.routeAgentCommand` (`webserver.js:10479-10495`), which finds the caller's session by
  the `sessionid` the server itself stamped, **stamps `command.nodeid` from the source agent**
  and strips the sessionid before sending — so what arrives on our socket is
  `{action:'msg', type:'ps', value:'<json>', nodeid:'node/…'}`, attributable to the device
  that answered rather than to the request we happened to have in flight.
* The frame is reachable from the same authenticated socket the official CLI already uses:
  `meshctrl.js:1368-1377` builds `wss://…/control.ashx` (+`?key=` login key), and
  `meshuser.js` treats that session as any other user session — which is where `ps`/`pskill`
  are routed. **So the implementation is one small first-party client over the existing
  transport, not a new privilege, not a new port, and not a plugin.**

### What it costs: the tree kill

Today's stop is `taskkill /T /F /PID <pid>` — the whole subtree. `pskill` is
`process.kill(pid)`: **one pid**. Losing `/T` on a customer machine is not a detail, so the
switch must keep the property explicitly: enumerate the subtree from `ps` and `pskill` each
pid in it, deepest-first. Whether `ps` records carry a parent field is **UNVERIFIED** — the
first-party parser only reads `cmd` and `user`, while `psinfo` (`agents/meshcore.js:1505`)
returns a per-pid detail object whose field set is built by the agent's `process-manager`
module (bundled, not readable in this package). One read-only `ps` + one `psinfo` capture on
CGI-1 settles it; nothing hangs, nothing is killed by that observation.

## 2. The PR this authorises (design, then code)

`kill_command_process` becomes four steps, every one judged on a field:

1. `ps` → the pid set whose record identifies this dispatch (see below), plus, if the field
   exists, their descendants from the same table.
2. `pskill` each pid, deepest first.
3. `ps` again.
4. **Verdict = the target pids are gone.** Any other outcome raises
   `MeshCentralStopUnconfirmed`, the discipline #6204 introduced: an open channel, a sent
   frame or a returned `result:'OK'` is not evidence. The server's own log line
   (`MeshServerLogEx(19, …, "Killing process <pid>")`, `agents/meshcore.js:1547`) is a second
   witness the operator can read, not the verdict.

Identifying the dispatch's own process: the wrapped script travels as plain UTF-8 JSON
(`_wrap`, and the marker path carries the dispatch id verbatim —
`padiem-dispatch-<id>.pid`), so a `cmd` that contains that marker name is our process. If
`ps` reports only the image name and not the command line, the match yields nothing and the
stop is reported **unverified** — never as done. Which of the two it is, the same read-only
capture answers.

The sweep (#6106) keeps its gate exactly as #6113 built it (the server's live claims answer
first, and nothing is cleared on a refusal), and only its *primitive* changes: from typing a
script that reads marker files to reading `ps` here and `pskill`ing there. That also removes
the sweep's dependency on the terminal's 4096-byte input queue
(`#6207`'s `TERMINAL_PREQUEUE_LIMIT_BYTES`).

## 3. Judgement asked for: do the probe and the session lane need a shell at all?

**No, and that is the finding.** The console probe (#6106) exists to answer one question —
"is something of ours holding this PC's console?" `ps` answers it directly and better, from
a state field, without typing anything. So:

* `PADIEM_MESH_LINE_PROBE` (#6183) stays **off** and becomes unnecessary once the sweep rides
  the process lane; keeping it off is not a temporary compromise.
* The per-dispatch session lane (#6163) was built to give each command its own terminal
  because the *queue* lane is serial. Its transport is the same shell we are leaving, so it
  stays **off**; the serial-queue problem it was designed around is a MeshCentral agent
  property (§1 of the channels memo) and does not go away by typing harder into a terminal.
* The shell submission defect itself is **recorded and de-prioritised** (a separate task),
  with the measurement plan in §4. Nothing in this lane waits on it.

## 4. Shell submission, if anyone picks it up later: measurement plan only

Constraints: short commands that **terminate by themselves**; nothing that can hold a
console; one PC (CGI-1) with the operator's leave; every variant bounded by a communication
timeout, and the run recorded whether it produced a sentinel or only a mirror.

Variables to cross:

1. submission byte: `\r` alone · `\n` alone · `\r\n` · `\n\r`
2. preamble: none · after a `{ctrlChannel:'102938',type:'options',cols,rows}` size frame
   (`meshctrl.js:2882-2884` sends exactly that before piping) · after a `termsize` frame
   (`meshctrl.js:2895-2898`)
3. mode: what the client leaves the pty in after `process.stdin.setRawMode(true)`
   (`meshctrl.js:2888`) versus a real interactive terminal, and whether the agent's
   `win-terminal`/`win-virtual-terminal` spawner (`agents/meshcore.js` §3 of the channels
   memo) expects console *key events* rather than text at all — that is the hypothesis the
   numbers cannot rule out, and the reason this stays a measurement task and not a guess.

Report = a table of (variant → bytes back, sentinel seen Y/N, wall time), nothing else; the
decision whether the shell lane is ever worth reviving comes after that table, not before.

## 5. Open items, and the single observation that closes each

| unknown | closes with | blocks |
|---|---|---|
| does `ps.value` carry the command line (not just the image name)? | one read-only `ps` on CGI-1 | the dispatch→pid match in §2 |
| does `ps`/`psinfo` carry a parent pid? | one `ps` + `psinfo` capture | the subtree kill in §2 |
| does `control.ashx` accept `{action:'msg',type:'ps'}` from an operator login with no browser session? | one read-only call | the whole lane (the source says the socket is the same one `meshctrl` uses; the consent flags in `meshuser.js:295-307` must be checked for a non-desktop caller) |
| is a `pskill` of an SYSTEM-owned process permitted to this operator account? | one `pskill` of a process we started ourselves | the stop path (never a PC process we do not own) |

**UNVERIFIED** in this memo, in one line each: the `process-manager` field set (bundled
module); whether `pskill` on a service-owned pid fails silently or returns the console text
`pskill: <error>`; the consent behaviour for a non-browser session on these node groups.

## 6. The probe: what to run on the host, and what the answer means

`scripts/ops/mesh_process_lane_probe.js` is the read-only observation. It sends exactly two
frames — `{action:'msg',type:'ps'}` and one `{action:'msg',type:'psinfo',pid}` — and has no
code path that sends `pskill`. It prints counts and **field names only**: a customer's
command lines and user names are the two fields a PC has most of, and they never leave the
terminal.

On 컴2, with the same operator credential file the executor already uses (the password
travels on stdin, never as an argument — `meshctrl.js:1395` builds the header from it and
this script does the same):

```bash
# $CRED is the mode-0600 file the service itself reads. The repository does not record
# its path: `systemctl show -p EnvironmentFiles padiem-oracle-mesh-executor.service`
# names the env file, and ORACLE_MESH_PASSWORD_FILE inside it names the credential.
node scripts/ops/mesh_process_lane_probe.js \
      --id '<the CGI-1 nodeRef>' \
      --url wss://127.0.0.1:4443 \
      --loginuser '<the operator account the service names>' \
      --ws-module /opt/meshcentral/node_modules/ws \
      < "$CRED"
```

Read the file the way the service reads it (mode-0600, one line); do not put the value on a
command line, in a shell variable in history, or in the issue. `--dry-run` prints the two
frames and sends nothing, so the operator can read exactly what will go out first.
A non-loopback `--url` is refused unless `--allow-remote-unverified` is passed, because this
was written for the server on this host, whose own certificate is why verification is off
(`meshctrl.js:1381` does the same for this socket).

Expected output is one line:

```
PROBE_RESULT {"ps_reply":true,"ps_count":214,"ps_fields":["cmd","user","mem","cpu"],
 "ps_parent_like":[],"ps_pid_key_is_numeric":true,"nodeid_echoed":true,
 "psinfo_reply":true,"psinfo_fields":["processName","workingSet"],"psinfo_parent_like":[],
 "routed_error":false,"notes":[]}
```

| reading | means | what the port PR does |
|---|---|---|
| `ps_reply:false`, `routed_error:true` (`unable_to_route`) | the nodeRef form is wrong for this frame | fix the id form in `ps_frame`; nothing on the PC changed |
| `ps_reply:false`, no error | the socket is not accepted for this login, or the agent did not answer | the lane is not reachable from a socket client; §1's last unknown is the answer, and the memo is corrected |
| `ps_parent_like` non-empty | a parent link exists | the subtree kill is computable, deepest first |
| `ps_parent_like:[]` and `psinfo_parent_like:[]` | no parent link | the stop addresses **the matched root pid only** and the report says `tree:false`; start times and name patterns are not used |
| `ps_fields` without `cmd`, or `ps_count` fine but a test dispatch not matched | `cmd` is not a command line | the target cannot be identified: the stop answers `no_target` and nothing is killed |
| exit code 3 | nothing was confirmed within the bound | report it; do not run it again in a loop |

Run it **once per question**, not as a monitor. One `ps` of a busy PC is a few tens of
kilobytes on a loopback socket; nothing about it is repeated, so the agent's anti-DoS kick
(`src/meshagent.js:1287-1295`, 31 identical console outputs) is not in play.

## 7. What the companion PR implements, and what it does not

Implemented there, with the flag off by default: `local_agent_meshcentral_process_port.py` —
the three frames in their first-party shape, the table reader that follows the web UI's own
parser, the marker-name match as the only target rule, the subtree ordering with an
explicit `tree=False` when no parent link exists, and `stop()` as
`ps → kill → ps` where **only the second read can confirm**.
`MeshCentralCliCommandPort.kill_command_process` uses it when a deployment injects a lane
and `PADIEM_MESH_PROCESS_LANE` says yes; otherwise the terminal stop runs unchanged, with
#6204's evidence token.

Not implemented, on purpose: the socket. `ws` is not a Python dependency of this package,
and the two §5 unknowns decide what that layer has to do (one shot per call versus a held
session, and whether a `responseid` is honoured at all). Writing it before the probe runs
would be a second transport built on a guess. The wiring follows the observation, and the
flag stays off until it.

## Sources

- `meshcentral@1.3.1`: `agents/meshcore.js:1357-1560`, `meshuser.js:277-307,1021-1056`,
  `meshctrl.js:1368-1377,1814,2867-2900`, `views/default.handlebars:10837-10860,11039-11040`,
  `webserver.js:10479-10495` (`routeAgentCommand`) and the absence of any `case 'msg'`
  REST handler in that file.
- This lane: `docs/architecture/PADIEM_CONNECTOR_MESH_PARALLEL_COMMAND_CHANNELS_4139_20261029.md`
  (§0.1 the stop's evidence rule, §0.2 the host-pty cause, §1 why the queue lane is serial),
  `apps/korean-ai-code-agent/src/kagent/local_agent_meshcentral_command_port.py`
  (`cancel_kill_command`, `kill_command_process`, `sweep_agent_children`),
  #6204, #6207, #6183, #6163, #6106.
