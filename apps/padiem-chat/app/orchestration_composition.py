"""One orchestration-bridge composition for both Chat entries (#5115 step ②).

The Worker (``worker.py``) and the CPython host (``app.local_cpython``) reach the
same Engine-owned orchestration client over different transports: a Service
Binding on Cloudflare, a loopback HTTP transport on COM2. Everything else — the
activation switch, the run mode, the D1 state store, the canonical-subject
variant — is identical, so it is composed here exactly once and each entry
supplies only its own client factory.

Keeping the gate in one place is the point: a host that read a different switch,
or that skipped the store, would be a second orchestration authority wearing the
same name.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .canonical_orchestration_bridge import CanonicalSubjectB62EngineOrchestrationBridge
from .orchestration_bridge import B62EngineOrchestrationBridge, D1OrchestrationStateStore
from .worker_config import binding_value

#: The same server-owned switch the Worker reads from its bindings and the host
#: reads from its environment (``binding_value`` handles both views).
ORCHESTRATION_ENABLED_ENV = "PADIEM_CHAT_ORCHESTRATION_ENABLED"
#: The app identity Chat presents to the Engine. Not a caller parameter: the
#: Engine's caller registry allows this app id for this call.
CHAT_ENGINE_APP_ID = "padiem-chat"


def orchestration_enabled(env: Any) -> bool:
    value = binding_value(env, ORCHESTRATION_ENABLED_ENV)
    return (value.strip() if isinstance(value, str) else "").lower() == "true"


def compose_orchestration_bridge(
    *,
    env: Any,
    settings: Any,
    db_binding: Any,
    build_client: Callable[[], Any],
    canonical_subject_resolver: Any | None = None,
) -> B62EngineOrchestrationBridge | None:
    """The Engine orchestration bridge, or ``None`` when it is not activated.

    Gate order is the Worker's existing order: explicit switch, run mode, D1
    store, then the Engine client. A missing prerequisite leaves the bridge off
    (the routes keep their current answer) instead of a half-built one.
    """

    if not orchestration_enabled(env):
        return None
    if getattr(settings, "runtime_mode", "mock") != "b14":
        return None
    if db_binding is None:
        return None
    client = build_client()
    if client is None:
        return None
    store = D1OrchestrationStateStore(db_binding)
    if canonical_subject_resolver is not None:
        return CanonicalSubjectB62EngineOrchestrationBridge(
            client=client,
            store=store,
            canonical_subject_resolver=canonical_subject_resolver,
        )
    return B62EngineOrchestrationBridge(client=client, store=store)


__all__ = [
    "CHAT_ENGINE_APP_ID",
    "ORCHESTRATION_ENABLED_ENV",
    "compose_orchestration_bridge",
    "orchestration_enabled",
]
