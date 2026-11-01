"""#5881 follow-on — the queue path and the D1 path must be one behaviour, not two.

Both sides run the SAME store code; what differs is who answers. So this is a differential
test over the rules the switch must not change: the atomic claim, the lease, the rotated
nonce, the renewal answer, the consumption gate, and - the one that fails quietly if the
ownership split is wrong - a PC paired by double-click showing up in its owner's list.

Random material (a pairing code, a link id, a claim nonce) is masked before comparing.
Everything derived from the moment handed in is compared exactly.
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import pathlib
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from json import loads as _json_loads
from types import SimpleNamespace

QUEUE = pathlib.Path(__file__).resolve().parents[1]
CHAT = QUEUE.parents[1] / "apps" / "padiem-chat"
sys.path.insert(0, str(CHAT))
sys.path.insert(0, str(QUEUE))

from app.d1_sqlite import SqliteD1  # noqa: E402
from app.history import D1HistoryStore  # noqa: E402
from app.pc_device_pairing_store import D1PcPairingStore  # noqa: E402
from app.queue_store_proxy import (  # noqa: E402
    QueueBackedPairingStore, QueueForwardingHistoryStore, QueueStoreClient,
)
from schema import apply  # noqa: E402

SECRET = "queue-channel-secret-value-261029"
SERVICE_SECRET = "queue-service-secret-value-261029"
OWNERSHIP = [{"account_ref": "acct-1", "device_id": "device-1", "node_ref": "node//NEWPC",
              "root_ref": "C:", "path_relative": "p.txt", "file_path": "C:/p.txt",
              "command_exec": True}]
USER = "usr_" + "a" * 32
NONCE = "a" * 32
NOW = datetime(2026, 10, 29, 3, 4, 5, 123000, tzinfo=timezone.utc)
#: Identifiers minted per call. Everything else - owner, node, label, state, the
#: timestamps derived from the moment handed in - is compared exactly.
MASKED = {"code", "code_sha256", "code_id", "pairing_code_id", "install_tag",
          "link_id", "nonce",
          "claimed_until", "pairing_tag"}


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


internal = _load("queue_internal_store_for_parity", QUEUE / "internal_store.py")
service = _load("queue_service_for_parity", QUEUE / "service.py")

DISPATCH_COLUMNS = (
    "dispatch_id", "user_id", "run_id", "command_id", "tool_request_ref", "request_id",
    "revision_ref", "evidence_ref", "request_fingerprint", "account_ref", "workspace_ref",
    "device_id", "binding_ref", "node_ref", "root_ref", "path_relative", "file_path",
    "kind", "state", "expires_at", "created_at",
)


class _Headers(dict):
    def get(self, key, default=None):
        return super().get(str(key).lower(), default)


class _FakeRequest:
    """The header/body surface the queue's internal handler reads."""

    def __init__(self, headers, payload):
        body = json.dumps(payload).encode("utf-8")
        merged = {str(key).lower(): value for key, value in (headers or {}).items()}
        merged.setdefault("content-type", "application/json")
        merged.setdefault("content-length", str(len(body)))
        self.headers = _Headers(merged)
        self._body = body
        self.app = SimpleNamespace(state=None)

    async def body(self):
        return self._body


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    async def aiter_bytes(self):
        yield json.dumps(self._payload).encode("utf-8")


def _db():
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    apply(connection)
    return SqliteD1(connection)


def _queue_app(database):
    return service.create_app(
        connection=database, channel_secret=SECRET, mode="mesh",
        ownership_map=json.dumps(OWNERSHIP), service_secret=SERVICE_SECRET)


def _client(queue_app):
    """A Chat-side client whose transport calls the queue's own handler in-process."""

    handler = next(route.endpoint for route in queue_app.routes
                   if route.path == internal.INTERNAL_STORE_PATH)

    class _Bridge:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def stream(self, method, url, json=None, headers=None):
            assert method == "POST"
            class Context:
                async def __aenter__(self):
                    response = await handler(_FakeRequest(headers, json))
                    return _FakeResponse(response.status_code, _json_loads(response.body))
                async def __aexit__(self, *exc):
                    return False
            return Context()

    return QueueStoreClient(origin="https://queue.padiem.net",
                            service_secret=SERVICE_SECRET,
                            client_factory=lambda **kwargs: _Bridge(**kwargs))


def _mask(value):
    if isinstance(value, dict):
        return {key: ("<masked>" if key in MASKED else _mask(item))
                for key, item in value.items()}
    if isinstance(value, list):
        return [_mask(item) for item in value]
    return value


def _run(coro):
    return asyncio.run(coro)


def _iso(moment):
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _stage(database, dispatch_id, *, when):
    # The claim compares `expires_at` against the STORE's own clock, so the staged
    # row's life must come from the real clock, not from the fixed `when` this file
    # uses for flows that take `now` explicitly. A frozen expiry is a time bomb: it
    # starts failing the moment wall-clock passes it, which is what happened to the
    # `NOW = 2026-10-29T03:04:05Z` fixture on 2026-10-29 (#82 triage).
    expires_at = _iso(datetime.now(timezone.utc) + timedelta(minutes=10))
    values = (dispatch_id, USER, "chat_pcq_" + "c" * 24, "cmd-" + dispatch_id[-6:],
              "tool-" + dispatch_id[-6:], "req-" + dispatch_id[-6:],
              "rev-" + dispatch_id[-6:], "evid-" + dispatch_id[-6:],
              "fp-" + dispatch_id[-6:], "acct-1", "ws-1", "device-1", "bind-1",
              "node//NEWPC", "C:", "p.txt", "C:/p.txt", "read", "pending",
              expires_at, _iso(when))
    database.connection.execute(
        "INSERT INTO oracle_mesh_dispatch (%s) VALUES (%s)"
        % (",".join(DISPATCH_COLUMNS), ",".join("?" * len(DISPATCH_COLUMNS))), values)


# --------------------------------------------------------------------------- pairing


def _pairing_flow(pairing, *, node_ref):
    issued = _run(pairing.issue_code(user_id=USER, issued_at=NOW))
    claim = _run(pairing.complete_claim_from_observation(
        agent_name="%s [C D] CGI-9" % issued["install_tag"],
        mesh_node_id=node_ref, now=NOW + timedelta(seconds=40)))
    links = _run(pairing.list_links(user_id=USER))
    codes = _run(pairing.list_codes(user_id=USER, now=NOW))
    return _mask({"issued_keys": sorted(issued), "claim": claim, "links": links,
                  "open_codes": codes})


def test_double_click_pairing_ends_in_the_owners_list_on_both_paths():
    d1_database = _db()
    queue_database = _db()
    left = _pairing_flow(D1PcPairingStore(d1_database), node_ref="node//NEWPC")
    right = _pairing_flow(QueueBackedPairingStore(_client(_queue_app(queue_database))),
                          node_ref="node//NEWPC")
    assert left == right
    # Not both-empty by accident: the list really did gain the machine, on both paths.
    assert len(left["links"]) == 1
    assert left["links"][0]["state"] == "active"
    assert left["links"][0]["mesh_node_id"] == "node//NEWPC"
    # The one-time code is spent by the claim, and what is left of it is the record
    # that says so - never a code that could be redeemed a second time.
    assert left["claim"] is not None
    assert [row["state"] for row in left["open_codes"]] == ["claimed"]


# -------------------------------------------------------------------------- dispatch


def _dispatch_flow(store, database, *, dispatch_id):
    _stage(database, dispatch_id, when=NOW)
    # The claim stores the digest of the nonce the executor was handed, so the test
    # claims with that digest and submits the nonce it came from.
    digest = hashlib.sha256(NONCE.encode("utf-8")).hexdigest()
    first = _run(store.claim_oracle_mesh_dispatch(dispatch_id=dispatch_id,
                                                  nonce_sha256=digest))
    again = _run(store.claim_oracle_mesh_dispatch(dispatch_id=dispatch_id,
                                                  nonce_sha256="b" * 64))
    renewed = _run(store.renew_oracle_mesh_claim(dispatch_id=dispatch_id,
                                                 nonce_sha256=digest))
    lost = _run(store.renew_oracle_mesh_claim(dispatch_id=dispatch_id,
                                              nonce_sha256="e" * 64))
    consumed = _run(store.consume_oracle_mesh_dispatch(dispatch_id=dispatch_id,
                                                       nonce=NONCE))
    second = _run(store.consume_oracle_mesh_dispatch(dispatch_id=dispatch_id,
                                                     nonce=NONCE))
    return _mask({
        "first_claim": first, "second_claim": again,
        "renew_ok": renewed is not None, "lost_renew": lost is None,
        "consumed_claim": consumed.get("claim") if consumed else None,
        "consumed_state": consumed.get("state") if consumed else None,
        "second_consume": second,
    })


def test_claim_lease_and_consumption_answer_the_same_on_both_paths():
    d1_database = _db()
    queue_database = _db()
    left = _dispatch_flow(D1HistoryStore(d1_database), d1_database,
                          dispatch_id="dsp_" + "1" * 32)
    right = _dispatch_flow(QueueForwardingHistoryStore(
        D1HistoryStore(queue_database), _client(_queue_app(queue_database))),
        queue_database, dispatch_id="dsp_" + "2" * 32)
    assert left == right
    assert left["first_claim"] is True and left["second_claim"] is False
    assert left["renew_ok"] is True and left["lost_renew"] is True
    assert left["consumed_claim"] == "first" and left["consumed_state"] == "received"
    assert left["second_consume"] is None


def test_a_name_the_queue_did_not_decline_is_never_answered():
    """The parity claim is only meaningful while both allowlists stay one list."""

    from app import queue_store_proxy as chat_side

    assert chat_side.QUEUE_DISPATCH_METHODS == internal.DISPATCH_METHODS
    assert chat_side.QUEUE_PAIRING_METHODS == internal.PAIRING_METHODS
    assert chat_side.QUEUE_PRESENCE_METHODS == internal.PRESENCE_METHODS
    assert chat_side.QUEUE_DRIVE_METHODS == internal.DRIVE_METHODS
