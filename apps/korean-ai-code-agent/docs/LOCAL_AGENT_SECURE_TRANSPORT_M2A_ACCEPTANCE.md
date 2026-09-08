# Local Agent Secure Transport M2a Acceptance

Issue: #1755

Repository acceptance target:

```text
WINDOWS_DPAPI_CURRENT_USER = YES
LOCAL_MACHINE_DPAPI_SCOPE = NO
PLAINTEXT_CREDENTIAL_PERSISTED = NO
ATOMIC_CREDENTIAL_REPLACEMENT = YES
BINDING_CONTEXT_EXACT = YES
ROTATION_STALE_CREDENTIAL_FAILS = YES
REVOKED_EXPIRED_FAILS = YES
OUTBOUND_TLS_ONLY = YES
PINNED_BROKER_AUTHORITY = YES
CALLER_FACING_CONFIG_ARGUMENT = NO
PUBLIC_INBOUND_PORT = NO
REAL_BROKER_CONFIGURED = NO
REAL_REMOTE_CONTROL = NO
PRODUCTION_READY = NO
```

Merge gate:

- exact-head KAgent Ubuntu success;
- exact-head KAgent Windows success;
- secret scan success;
- preview/checks success where automatically attached;
- main drift rechecked immediately before merge;
- PR head unchanged between gate and merge;
- no live broker/remote execution performed.
