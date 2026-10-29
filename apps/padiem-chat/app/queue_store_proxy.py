"""#5881 follow-on — the Chat Worker asks the 컴2 queue for the PC-lane state.

Why this exists: the claim lane runs on the Cloudflare Python runtime, and that runtime
is where the measured failures are (9 `NoGilError` and 3 CPU-limit kills in one
180-second window, all on the executor poll). The rules are NOT re-implemented here - the
queue answers with the same store code - so this module is transport and nothing else:
one method name, its keyword arguments, one answer.

Three shapes are exposed:
  * `QueueBackedPairingStore` / `QueueBackedPresenceStore` replace the D1 objects whole.
  * `QueueForwardingHistoryStore` keeps every conversation method on D1 and forwards
    ONLY the dispatch names, so no call site has to change and the split cannot drift.
  * `queue_backend` is fail-closed: anything but `com2` keeps today's D1 path.
"""
from __future__ import annotations

from typing import Any, Callable

from . import httpx_compat as httpx

INTERNAL_STORE_PATH = "/internal/store"
QUEUE_SERVICE_SECRET_HEADER = "X-Padiem-Queue-Secret"
QUEUE_BACKEND_D1 = "d1"
QUEUE_BACKEND_COM2 = "com2"
MAX_SECRET_CHARS = 256
QUEUE_TIMEOUT_SECONDS = 8.0

#: The `oracle_mesh_dispatch` methods the queue owns. The result *content* is absent on
#: purpose: the over-budget original lives in private R2 and the delivered answer in the
#: conversation, and both stay with this Worker.
QUEUE_DISPATCH_METHODS = frozenset({
    "claim_oracle_mesh_dispatch",
    "cancel_oracle_mesh_dispatches_for_run",
    "consume_oracle_mesh_dispatch",
    "create_oracle_mesh_dispatch",
    "finish_oracle_mesh_dispatch",
    "get_oracle_mesh_dispatch_for_owner",
    "mark_oracle_mesh_store_failed",
    "oldest_pending_oracle_mesh_dispatch",
    "oracle_mesh_dispatch_cancellation",
    "oracle_mesh_node_live_claims",
    "record_oracle_mesh_first_result",
    "renew_oracle_mesh_claim",
})

QUEUE_PAIRING_METHODS = frozenset({
    "adopt_link",
    "approve_root",
    "claim",
    "complete_claim_from_observation",
    "consume",
    "device_scope",
    "drive_roots_for_node",
    "issue_code",
    "link_for",
    "list_codes",
    "list_links",
    "links_for_owner",
    "pause_link",
    "peek_pairing_code",
    "redeem_code",
    "resolve_account_ref",
    "resume_link",
    "revoke_link",
    "revoke_root",
    "set_link_label",
})

QUEUE_PRESENCE_METHODS = frozenset({"upsert", "load"})

__all__ = [
    "INTERNAL_STORE_PATH", "build_queue_client", "QUEUE_BACKEND_COM2", "QUEUE_BACKEND_D1",
    "QUEUE_DISPATCH_METHODS", "QUEUE_PAIRING_METHODS", "QUEUE_PRESENCE_METHODS",
    "QUEUE_SERVICE_SECRET_HEADER", "QueueForwardingHistoryStore", "QueueStoreClient",
    "QueueUnavailable", "queue_backend",
]


class QueueUnavailable(RuntimeError):
    """The queue could not answer. Never carries an argument or a response body."""


def queue_backend(value: Any) -> str:
    """The switch. Anything that is not exactly `com2` keeps the D1 path it runs on."""

    text = value.strip().lower() if isinstance(value, str) else ""
    return QUEUE_BACKEND_COM2 if text == QUEUE_BACKEND_COM2 else QUEUE_BACKEND_D1


def _https_root_origin(value: Any) -> str:
    """A bare https origin: no path, no credentials, no second scheme."""

    origin = (value or "").strip() if isinstance(value, str) else ""
    if not origin.startswith("https://"):
        raise QueueUnavailable("the queue origin must be a bare https origin")
    remainder = origin[len("https://"):].rstrip("/")
    if (not remainder or "://" in remainder or "@" in remainder or "/" in remainder
            or len(origin) > 200):
        raise QueueUnavailable("the queue origin must be a bare https origin")
    return origin[:len("https://")] + remainder


class QueueStoreClient:
    """One call shape: a declared name, its keyword arguments, its answer."""

    def __init__(self, *, origin: Any, service_secret: Any,
                 client_factory: Callable[..., Any] | None = None,
                 timeout_seconds: float = QUEUE_TIMEOUT_SECONDS):
        self._origin = _https_root_origin(origin)
        secret = service_secret if isinstance(service_secret, str) else ""
        if not 16 <= len(secret) <= MAX_SECRET_CHARS or any(
                ord(ch) < 33 or ord(ch) > 126 for ch in secret):
            raise QueueUnavailable("the queue service secret is required")
        self._secret = secret
        # Injected in tests, defaulted in production: the client object is the only
        # thing here that touches the network, so the whole module stays testable
        # without an httpx transport implementation.
        self._client_factory = client_factory
        self._timeout = timeout_seconds

    async def call(self, method: str, **arguments: Any) -> Any:
        if not isinstance(method, str) or not method.isidentifier():
            raise QueueUnavailable("the queue method name is invalid")
        payload = {"method": method, "arguments": dict(arguments)}
        client_options: dict[str, Any] = {
            "timeout": httpx.Timeout(self._timeout, connect=3.0),
            "follow_redirects": False,
        }
        factory = self._client_factory or httpx.AsyncClient
        try:
            async with factory(**client_options) as client:
                response = await client.post(
                    self._origin + INTERNAL_STORE_PATH, json=payload,
                    headers={QUEUE_SERVICE_SECRET_HEADER: self._secret,
                             "Accept": "application/json",
                             "Content-Type": "application/json",
                             "Cache-Control": "no-store"},
                )
                if response.status_code != 200:
                    raise QueueUnavailable("the queue refused the call")
                body = response.json()
        except QueueUnavailable:
            raise
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise QueueUnavailable("the queue could not be reached") from exc
        if not isinstance(body, dict) or body.get("ok") is not True or "result" not in body:
            raise QueueUnavailable("the queue answer was not usable")
        return body["result"]


def build_queue_client(env: Any) -> QueueStoreClient | None:
    """The client when this deployment is switched to the queue, else None.

    Reading the switch and the material together means an unset origin or a missing
    secret cannot half-switch a deployment: the caller keeps the D1 path it has.
    """

    if queue_backend(getattr(env, "PC_QUEUE_BACKEND", None)) != QUEUE_BACKEND_COM2:
        return None
    return QueueStoreClient(origin=getattr(env, "PC_QUEUE_ORIGIN", None),
                            service_secret=getattr(env, "PC_QUEUE_SERVICE_SECRET", None))


class QueueBackedPairingStore:
    """The pairing directory as seen by the browser routes, served by the queue."""

    def __init__(self, client: QueueStoreClient):
        self._client = client

    def __getattr__(self, name: str) -> Callable[..., Any]:
        if name.startswith("_"):
            raise AttributeError(name)
        if name not in QUEUE_PAIRING_METHODS:
            raise AttributeError(name)
        return lambda **arguments: self._client.call(name, **arguments)


class QueueBackedPresenceStore:
    """The presence receipts, served by the queue."""

    def __init__(self, client: QueueStoreClient):
        self._client = client

    async def upsert(self, **arguments: Any) -> Any:
        return await self._client.call("upsert", **arguments)

    async def load(self, **arguments: Any) -> Any:
        return await self._client.call("load", **arguments)


class QueueForwardingHistoryStore:
    """The Chat store surface, with the dispatch names answered by the queue.

    Every other attribute goes to the D1 store underneath, so the conversation rows, the
    projects and the R2 originals keep their exact home and no call site has to be
    rewritten to move the PC-lane state.
    """

    def __init__(self, inner: Any, client: QueueStoreClient):
        if inner is None:
            raise QueueUnavailable("a D1 store is required underneath the queue")
        self._inner = inner
        self._client = client

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        if name in QUEUE_DISPATCH_METHODS:
            return lambda **arguments: self._client.call(name, **arguments)
        return getattr(self._inner, name)
