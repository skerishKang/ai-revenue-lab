# Oracle <-> COM2 MeshCentral execution failover / failback

**Scope:** which of the two hosts is allowed to claim a remote-execution
dispatch, and how that decision is proven.
**Status (2026-10-21):** the controller is merged and deployed on Oracle.
The device-transport leg is **not** yet redundant; see "Known blocker".

---

## 1. Why a second MeshCentral server is not enough

Two MeshCentral servers exist and both are healthy, but that alone does
not make the lane redundant. A remote-execution request can only be
served by the server the **target PC's agent is currently connected to**.
Measured on 2026-10-21:

| Host | MeshCentral | Target device | Agent connection |
|---|---|---|---|
| COM2 (`K_lipvoice`, 192.168.0.101) | 1.2.5 on `127.0.0.1:4443`, systemd `padiem-meshcentral.service` | registered, same node id | **connected** (`conn=1`) |
| Oracle (`instance-20251021-0112`, 168.138.200.12) | 1.2.5 on `127.0.0.1:4443`, no unit, no autostart | registered, **same node id, same group, same account** | **not connected** (`conn=0`) |

Both servers share the **same five certificate fingerprints** (agentserver
`47:A1:09:FF:…:22:01`), so the target's agent identity is valid on both.
The registration is therefore not the blocker; the **connection** is.

The target PC's agent is configured with a single server URL:

```
MeshServer=wss://127.0.0.1:4443/agent.ashx
```

which is COM1's loopback, forwarded to COM2 by the COM1 -> COM2 SSH
tunnel. So today the agent reaches COM2 *through COM1*.

## 2. What the controller owns

`apps/korean-ai-code-agent/src/kagent/local_agent_mesh_failover.py`

The controller answers exactly one question: **which host may claim a
dispatch right now?** It does not own the queue, the credential, the
result, or the device.

* The Chat channel hands the oldest claimable dispatch to exactly one
  poller with a fresh single-use nonce, so the server owns the claim.
* Liveness is "the target device is connected to MY MeshCentral", never
  "the server answered HTTP 200". A server that answers while owning no
  device cannot execute, and treating it as usable is exactly how a
  dispatch was lost before.
* Every switch bumps a monotonic **epoch**. A consumer may claim only
  while it holds the current epoch, so a slow or restarted consumer that
  still believes it is active is fenced out instead of racing the new
  one. The executor honours the gate through `claim_gate`.
* A held result is **not** gated. Bytes the PC already produced still
  have to reach the server exactly once, so a failover resends and never
  re-runs.
* Failover is confirmed faster than failback, so a flapping COM2 does not
  oscillate the active target.

### Event vocabulary

| Event | Meaning |
|---|---|
| `COM2_FAULT` | COM2 stopped being able to execute the dispatch |
| `ORACLE_ACTIVE` | Oracle now owns the claim |
| `COM2_RESTORED` | COM2 proved it can execute again |
| `FAILBACK_COMPLETE` | the claim went back to COM2 |

Events are emitted **only on a real transition**, and each transition
carries the two events that belong to it. Every event is appended to a
durable local log, so a host that cannot reach the operator's channel
still keeps the evidence.

## 3. The health signal travels COM2 -> Oracle

COM2 sits behind NAT and has no usable inbound path from Oracle (its
public ports accept TCP but do not serve HTTP, and there is no tunnel
process). Oracle therefore never reaches into COM2 to ask whether COM2
is usable. COM2 publishes that truth itself:

```json
{
  "schema": "padiem_mesh_heartbeat/v1",
  "target": "com2",
  "mesh_url": "wss://127.0.0.1:4443",
  "device_id": "<node id>",
  "device_connected": true,
  "executor_alive": true
}
```

A heartbeat that is missing, stale, or that does not claim the device is
**not** a proof of execution. The supervisor on Oracle reads it, and the
controller decides.

## 4. Deployment

### Oracle — the always-on control plane

Oracle had a MeshCentral server but **no executor, no systemd unit and no
autostart**, so it could never take over even when the device was
connected. The deployment adds:

| Unit | Role |
|---|---|
| `padiem-mesh-failover.service` / `.timer` | one supervisor pass per minute: read the heartbeat, evaluate, write the decision, emit events |
| `padiem-oracle-mesh-executor.service` | the executor, started only while Oracle is the active target |

The supervisor writes `failover-state.json`; the executor reads it
through `decision_file_claim_gate`. The executor's own pending/outbox
contract is unchanged: a restart resends the bytes it holds and never
re-runs the command.

### COM2 — the primary

COM2 keeps its current units (`padiem-meshcentral.service`,
`padiem-oracle-mesh-executor.service`, `padiem-mesh-health.timer`) and
gains the heartbeat publisher, so the heartbeat states the **device
connection** truth and not only "I am alive".

## 5. Known blocker — the device transport is still COM1-bound

**Current state:** the target's agent reaches COM2 through COM1's SSH
tunnel. If COM1 is down, or the tunnel task is retired, the agent has no
server to reach, and Oracle's MeshCentral will keep showing `conn=0` no
matter what the controller decides.

Measured constraints:

* A MeshCentral agent connects to **one** server. Upstream is explicit
  that a second server is reached by DNS/load balancing in front of both
  servers, not by a second URL in the agent.
* MeshCentral 1.2.5 does not relay commands to a device that is
  connected to a peer server, so server peering alone does not make
  Oracle able to execute.
* COM2 has no inbound path from Oracle that can carry the agent
  connection.

Therefore the transport leg needs one of these, and **none of them is
applied yet**:

1. a public ingress for COM2 that can carry the agent connection, or
2. an agent URL that resolves to whichever server is active, or
3. a local forwarder on the target PC whose backend target follows the
   controller's decision.

Until one of them is in place and verified against a real COM2 outage,
the failover is proven for the **claim** (the controller, the gate, the
exactly-once fencing) and **not** for the **device transport**.

## 6. COM1 Mesh-only scheduled work — inventory and retirement order

Retirement is deliberately **not** done yet, because the transport leg
above is not redundant. The inventory is captured so the retirement is a
reviewed, reversible step.

| Task | Trigger | Scripts | Decision |
|---|---|---|---|
| `PADIEM-COM2-Mesh-Health` | boot + every 5 min | `background-health.vbs` -> `com2-mesh-health.ps1` -> `com2-mesh-recovery.ps1` | retire after Oracle's supervisor is the authority |
| `PADIEM-Mesh-Tunnel` | boot + every 5 min | `background-tunnel.vbs` -> `padiem-tunnel-wrapper.cmd` -> `padiem-tunnel.cmd` | retire only when the agent reaches a server without this tunnel |
| `PADIEM-Grafana-Logs-COM1-Backup` | every 5 min | `background-grafana.vbs` | **not** Mesh work — keep |
| `Hermes_Gateway` | gateway service | `Hermes_Gateway.vbs` | **not** Mesh work — keep (it is the operator notification path) |

Existing task definitions and recovery copies are already on disk under
`C:\Users\limone\Padiem\` (`task-backup-health-20261021.xml`,
`task-backup-tunnel-20261021.xml`, `padiem-mesh-tunnel.backup.xml`), so
the task definitions survive the retirement.

Retirement order, once the transport leg is verified:

1. prove the agent reaches a server with no COM1 tunnel;
2. prove Oracle takes the claim and executes on the device;
3. prove COM2 takes the claim back;
4. disable `PADIEM-COM2-Mesh-Health` and `PADIEM-Mesh-Tunnel`;
5. re-verify the normal path end to end;
6. remove the tasks only after a clean operating period.

## 7. Verification performed

| Scenario | How | Result |
|---|---|---|
| A normal | COM2 usable | active target stays `com2`, no event, epoch unchanged |
| B fault | COM2 not usable | active target moves to `oracle`, `COM2_FAULT` + `ORACLE_ACTIVE`, epoch increases |
| C recover | COM2 usable again | after the restore window, active target moves back, `COM2_RESTORED` + `FAILBACK_COMPLETE` |
| D exactly once | a stale consumer presents the old epoch | the claim is refused; the epoch never goes back |

The controller core performs no I/O, so the four scenarios are covered
by unit tests that need no MeshCentral, no network and no clock. The
executor-side fence is covered by a test that proves the channel is
never polled while the gate is closed.

The real COM2 outage is **not** rehearsed in this document: the task
requires it to be done in an isolated scope that does not disturb other
LOCALs' work or the live connection, and the transport leg in section 5
has to be solved first.
