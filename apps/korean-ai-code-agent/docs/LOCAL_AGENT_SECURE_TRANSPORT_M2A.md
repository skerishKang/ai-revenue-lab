# B54 Local Agent Secure Transport M2a

Issue: #1755  
Parent: #1634  
Related: #1633 #1635 #1651 #1569

Status: repository-side secure-storage + pinned outbound transport boundary. No real Padiem broker is configured.

## Purpose

M2a closes the local trust gap between the existing Local Agent pairing/session contracts and a future real outbound broker.

```text
Trusted browser/account pairing
  -> DeviceBinding
  -> opaque device credential
  -> Windows current-user DPAPI protected local store
  -> pinned outbound broker authority
  -> existing DeviceSession / DeviceCommandEnvelope
  -> physical outbound transport adapter
```

This slice does **not** create a remote-control service, inbound listener, generic remote shell, or Production broker.

## Credential-at-rest boundary

The canonical local credential store persists only a DPAPI-protected payload plus bounded binding metadata.

Binding context includes:

```text
binding_ref
device_id
account_ref
workspace_ref
credential_generation
SHA-256 fingerprint of credential_ref
credential_expires_at
```

The raw `credential_ref` and raw device credential are not stored in the safe projection.

The protected-data entropy is derived from the exact binding context. Therefore a different account, workspace, device, credential generation, credential ref or expiry context cannot silently reuse a stored credential.

### Windows DPAPI mode

`WindowsDpapiProtectedDataPort` uses Windows `CryptProtectData` / `CryptUnprotectData` with:

```text
CURRENT_USER_SCOPE = YES
CRYPTPROTECT_UI_FORBIDDEN = YES
CRYPTPROTECT_LOCAL_MACHINE = NO
```

`CRYPTPROTECT_LOCAL_MACHINE` is intentionally not passed. The Local Agent credential belongs to the paired user's Windows context rather than every account on the machine.

CI does not perform a real DPAPI protect/unprotect operation. Cross-platform deterministic tests use a reversible fake protected-data port whose output is explicitly not cryptography and never counts as live evidence.

## Protected file lifecycle

`ProtectedFileDeviceCredentialStore`:

1. validates the current binding is usable;
2. protects credential bytes before any persistent write;
3. writes a bounded JSON record to a temporary file inside the configured absolute credential directory;
4. flushes/fsyncs;
5. atomically replaces the binding's hashed credential record;
6. loads only after exact current binding-context comparison;
7. decrypts only after metadata and protected-payload validation.

Rotation changes the credential generation/ref fingerprint, so the previous record fails closed until a new protected credential is saved.

Revoked, unpaired, credential-expired or time-expired bindings cannot load or save credential material.

## Outbound endpoint contract

M2a accepts only a trusted TLS endpoint:

```text
HTTPS long poll -> https://...:443/...
WebSocket       -> wss://...:443/...
```

Rejected:

```text
http://
ws://
non-443 port
URL username/password
query-string authority
fragment authority
.. path traversal
public inbound port
```

The endpoint projection contains no bearer/device credential.

## Caller endpoint override is structurally removed

`OutboundLocalAgentTransportPort` is the low-level physical adapter contract and receives the trusted config internally.

Product/caller code should use `PinnedOutboundLocalAgentChannel`:

```text
PinnedOutboundBrokerBinding
  = exact DeviceBinding identity/generation
  + exact trusted OutboundTransportConfig
  + config fingerprint

PinnedOutboundLocalAgentChannel.poll(...)
PinnedOutboundLocalAgentChannel.acknowledge(...)
```

The caller-facing methods have **no `config`, `endpoint`, or `url` parameter**.

Before every call, the channel verifies:

- exact binding ref;
- exact device/account/workspace;
- exact credential generation;
- exact credential-ref fingerprint;
- binding not revoked/expired;
- session still current;
- session identity exactly matches the pinned authority.

Credential rotation requires creating a new pinned authority. A stale channel cannot continue after rotation.

## Replay and command semantics

This slice does not create another replay/command model.

The existing #1634 contracts remain canonical:

```text
DeviceSession
DeviceCommandEnvelope
pairing single-use/expiry
credential rotation/revocation
monotonic sequence
command expiry
reconnect replay protection
```

M2a only establishes secure local credential custody and a pinned outbound physical transport boundary around those contracts.

## Test gate

Deterministic contract tests cover:

- protected payload differs from plaintext;
- plaintext credential absent from persisted record;
- raw credential ref absent from persisted/safe projection;
- rotation invalidates stale stored context;
- account/workspace/device/credential mismatch fails closed;
- revoked/expired binding fails closed;
- HTTPS/WSS canonical TLS endpoints;
- downgrade/userinfo/query/fragment/non-443/path-escape rejection;
- TLS cannot be disabled;
- public inbound port cannot be enabled;
- caller-facing channel signature contains no endpoint/config argument;
- low-level adapter receives only the pinned config;
- stale credential generation cannot use the pinned channel;
- wrong session identity fails closed;
- unconfigured real transport fails closed.

## Live implementation gate

Before #1634 can be considered live-ready:

1. choose and deploy the canonical Padiem Local Agent broker/control endpoint;
2. bind its hostname/path as trusted configuration, not model/client input;
3. implement the physical HTTPS long-poll or WSS adapter;
4. integrate real trusted pairing/device credential issuance;
5. perform a Windows DPAPI install/store/restart/load/rotation/revoke acceptance on a disposable test device;
6. verify OS-user isolation expectations;
7. verify proxy/firewall disconnect and reconnect behavior;
8. verify heartbeat/last-seen truth;
9. prove completed/expired commands are not replayed after reconnect;
10. connect execution only through the existing P01-authorized Local Agent runtime/permission boundary;
11. capture bounded audit/evidence without secret material;
12. obtain explicit live/Production approval before any real remote execution claim.

## Non-claims

```text
WINDOWS_DPAPI_IMPLEMENTATION_PRESENT = YES
WINDOWS_DPAPI_LIVE_ACCEPTANCE = NO
PLAINTEXT_CREDENTIAL_PERSISTED = NO
LOCAL_MACHINE_DPAPI_SCOPE = NO
OUTBOUND_TLS_ONLY = YES
CALLER_ENDPOINT_OVERRIDE = NO
PUBLIC_INBOUND_PORT = NO
REAL_LOCAL_AGENT_BROKER_CONFIGURED = NO
REAL_REMOTE_CONTROL_CONFIGURED = NO
REAL_USER_PC_EXECUTION_OVER_NETWORK = NO
PRODUCTION_MUTATION = NO
PRODUCTION_READY = NO
```
