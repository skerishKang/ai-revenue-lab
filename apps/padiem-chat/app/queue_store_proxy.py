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

from datetime import date, datetime
import json
import logging
import re
import time
from typing import Any, Callable
from urllib.parse import urlsplit

from .history import VerifiedDispatch, _tagged
from . import httpx_compat as httpx
from .pc_correlation import RUN_HASH_HEADER, DISPATCH_ID_HEADER, run_hash, dispatch_id

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

INTERNAL_STORE_PATH = "/internal/store"
QUEUE_SERVICE_SECRET_HEADER = "X-Padiem-Queue-Secret"
QUEUE_BACKEND_D1 = "d1"
QUEUE_BACKEND_COM2 = "com2"
MAX_SECRET_CHARS = 256
QUEUE_TIMEOUT_SECONDS = 8.0
#: The Workers Python runtime stamps outbound fetches with `Python-urllib/3.12`,
#: and the Cloudflare edge bot rule answers that UA with 403 error 1010 before
#: the request reaches the queue. Every queue call names itself instead.
QUEUE_USER_AGENT = "PadiemChat-Queue/1.0"

#: The `oracle_mesh_dispatch` methods the queue owns. The result *content* is absent on
#: purpose: the over-budget original lives in private R2 and the delivered answer in the
#: conversation, and both stay with this Worker.
QUEUE_DISPATCH_METHODS = frozenset({
    "get_oracle_mesh_dispatch_pin",
    "get_oracle_mesh_run_correlation",
    "get_oracle_mesh_run_command",
    "get_oracle_mesh_run_open_state",
    "oracle_mesh_lane_status",
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
QUEUE_DRIVE_METHODS = frozenset({"upsert_drives", "load_drives"})

__all__ = [
    "INTERNAL_STORE_PATH", "build_queue_client", "QUEUE_BACKEND_COM2", "QUEUE_BACKEND_D1",
    "QUEUE_DISPATCH_METHODS", "QUEUE_DRIVE_METHODS", "QUEUE_PAIRING_METHODS", "QUEUE_PRESENCE_METHODS",
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


def _loopback_http_root_origin(value: Any) -> str:
    """A bare loopback http origin, only for the explicit staging opt-in.

    The queue normally sits behind https. A staging Chat on the same host may
    reach the 8830 queue over http, but only 127.0.0.1/localhost, only with an
    explicit port, and only when the deployment asks for it: no path, no
    userinfo, no query, no second scheme.
    """

    origin = (value or "").strip() if isinstance(value, str) else ""
    if not origin.startswith("http://") or len(origin) > 200:
        raise QueueUnavailable("the queue origin must be a bare loopback http origin")
    try:
        parsed = urlsplit(origin)
        port = parsed.port
    except ValueError as exc:
        raise QueueUnavailable(
            "the queue origin must be a bare loopback http origin"
        ) from exc
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}
            or port is None or parsed.username or parsed.password
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
        raise QueueUnavailable("the queue origin must be a bare loopback http origin")
    return f"http://{parsed.netloc}"


def _exception_diagnostic(exc: BaseException, stage: str) -> tuple[str, str]:
    """Return a bounded exception class and transport phase, never its text."""
    name = type(exc).__name__
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", name):
        name = "InvalidExceptionName"
    lower = name.lower()
    phase = next((item for item in ("connect", "read", "write", "pool")
                  if lower.startswith(item)), "unknown")
    if phase == "unknown" and stage == "body_read":
        phase = "read"
    return name, phase


class QueueStoreClient:
    """One call shape: a declared name, its keyword arguments, its answer."""

    def __init__(self, *, origin: Any, service_secret: Any,
                 client_factory: Callable[..., Any] | None = None,
                 timeout_seconds: float = QUEUE_TIMEOUT_SECONDS,
                 allow_loopback_http: bool = False):
        self._origin = (
            _loopback_http_root_origin(origin) if allow_loopback_http
            else _https_root_origin(origin)
        )
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
        try:
            payload = {"method": method,
                       "arguments": {key: _wire(value) for key, value in arguments.items()}}
            probe = json.dumps(payload)
        except (TypeError, ValueError):
            # A value that cannot cross the boundary is refused here, before anything is
            # sent: half a call is worse than no call.
            raise QueueUnavailable("the queue call cannot be encoded")
        del probe
        client_options: dict[str, Any] = {
            "timeout": httpx.Timeout(self._timeout, connect=3.0),
            "follow_redirects": False,
        }
        factory = self._client_factory or httpx.AsyncClient
        started = time.perf_counter()
        stage, status = "request", 0
        trace_run = run_hash(arguments.get("run_id"))
        trace_dispatch = dispatch_id(arguments.get("dispatch_id"))
        trace_headers = {}
        if trace_run:
            trace_headers[RUN_HASH_HEADER] = trace_run
        if trace_dispatch:
            trace_headers[DISPATCH_ID_HEADER] = trace_dispatch
        # Only declared operation names are observable. Never log arguments,
        # origins, headers, body bytes or exception messages/tracebacks.
        safe_method = method if method in (
            QUEUE_DISPATCH_METHODS | QUEUE_PAIRING_METHODS | QUEUE_PRESENCE_METHODS | QUEUE_DRIVE_METHODS
        ) else "other"

        def record(outcome, reason, exception="none", transport_phase="none"):
            log = logger.info if outcome == "ok" else logger.warning
            log("pc_queue_call method=%s stage=%s status=%s outcome=%s reason=%s elapsed_ms=%s exception=%s transport_phase=%s run_hash=%s dispatch_id=%s",
                safe_method, stage, status, outcome, reason,
                int((time.perf_counter() - started) * 1000), exception, transport_phase, trace_run or "none", trace_dispatch or "none")

        try:
            async with factory(**client_options) as client:
                # Workers compat exposes stream(), not post(); its Response
                # exposes aiter_bytes(), not json()/aread()/content. Real httpx
                # supports this same streaming interface and closes on exit.
                async with client.stream(
                    "POST", self._origin + INTERNAL_STORE_PATH, json=payload,
                    headers={QUEUE_SERVICE_SECRET_HEADER: self._secret,
                             "Accept": "application/json",
                             "Content-Type": "application/json",
                             "Cache-Control": "no-store",
                             "User-Agent": QUEUE_USER_AGENT, **trace_headers},
                ) as response:
                    stage, status = "status", response.status_code
                    if status != 200:
                        record("error", "http_status")
                        raise QueueUnavailable("the queue refused the call")
                    stage = "body_read"
                    raw = b"".join([chunk async for chunk in response.aiter_bytes()])
                    stage = "json_decode"
                    body = json.loads(raw)
        except QueueUnavailable:
            raise
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            reason = ("transport_error" if isinstance(exc, httpx.HTTPError)
                      else "invalid_json" if stage == "json_decode" else "invalid_response")
            kind, phase = _exception_diagnostic(exc, stage)
            record("error", reason, kind, phase)
            raise QueueUnavailable("the queue could not be reached") from None
        except Exception as exc:
            # Never include exception text: it can contain URLs or credentials.
            kind, phase = _exception_diagnostic(exc, stage)
            reason = "unexpected_AttributeError" if isinstance(exc, AttributeError) else "unexpected_other"
            record("error", reason, kind, phase)
            raise QueueUnavailable("the queue could not be reached") from None
        stage = "envelope"
        if not isinstance(body, dict) or body.get("ok") is not True or "result" not in body:
            record("error", "invalid_envelope")
            raise QueueUnavailable("the queue answer was not usable")
        stage = "complete"
        result = body["result"]
        if isinstance(result, dict):
            trace_dispatch = dispatch_id(result.get("dispatch_id")) or trace_dispatch
        record("ok", "ok")
        return body["result"]


def build_queue_client(env: Any) -> QueueStoreClient | None:
    """The client when this deployment is switched to the queue, else None.

    Reading the switch and the material together means an unset origin or a missing
    secret cannot half-switch a deployment: the caller keeps the D1 path it has.
    """

    if queue_backend(getattr(env, "PC_QUEUE_BACKEND", None)) != QUEUE_BACKEND_COM2:
        return None
    allow_loopback_http = str(
        getattr(env, "PADIEM_CHAT_QUEUE_ALLOW_LOOPBACK_HTTP", "") or ""
    ).strip().lower() in {"1", "true"}
    return QueueStoreClient(origin=getattr(env, "PC_QUEUE_ORIGIN", None),
                            service_secret=getattr(env, "PC_QUEUE_SERVICE_SECRET", None),
                            allow_loopback_http=allow_loopback_http)


def _wire(value: Any) -> Any:
    """An instant becomes the ISO text the queue parses back.

    The stores take real `datetime` objects and the transport carries JSON, so the
    boundary converts in exactly the format both sides already write their columns in.
    """

    if isinstance(value, datetime):
        return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    return value


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


class QueueBackedDriveStore:
    """The latest complete drive snapshots, served by the production queue."""

    def __init__(self, client: QueueStoreClient):
        self._client = client

    async def upsert_drives(self, **arguments: Any) -> Any:
        return await self._client.call("upsert_drives", **arguments)

    async def load_drives(self, **arguments: Any) -> Any:
        return await self._client.call("load_drives", **arguments)


#: Reads whose rows arrive already scoped to one owner, so they may carry the handle.
_OWNER_SCOPED_ROW_READS = frozenset({
    "consume_oracle_mesh_dispatch", "get_oracle_mesh_dispatch_for_owner",
    "get_oracle_mesh_dispatch_pin", "get_oracle_mesh_run_correlation",
    "get_oracle_mesh_run_command",
})


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
        # The dispatch rows are the queue's now, so anything the conversation side reads
        # from them must be asked there. Without this the browser's result read-back re-read
        # D1, found nothing, and answered 503 on a run that had completed fine.
        setter = getattr(inner, "set_dispatch_authority", None)
        if callable(setter):
            setter(self)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        if name in QUEUE_DISPATCH_METHODS:
            if name not in _OWNER_SCOPED_ROW_READS:
                return lambda **arguments: self._client.call(name, **arguments)

            async def read(**arguments):
                # The queue answered for one named owner; tag the row so the original
                # stores accept it as proof and never re-read a table they do not own.
                row = await self._client.call(name, **arguments)
                return _tagged(row) if isinstance(row, dict) else row

            return read
        return getattr(self._inner, name)
