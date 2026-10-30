"""#5881 follow-on — the result lane under com2, against the real door.

The 19:09 retest showed the second half of the same split: the queue answers dispatch
questions now, but the conversation side still asked D1 about `oracle_mesh_dispatch`.
`store_oracle_mesh_original` refused with 403 and the browser's read-back answered 503 on a
run that had executed correctly. These tests run the lane with the dispatch rows living ONLY
in the queue — the D1 underneath has no such table, so any re-read fails loudly — and they
use the real door (the queue's own handler) behind the real forwarder, not a stubbed echo.

Both lanes are pinned: the read lane and the command lane. The refusals that must survive
also are: a forged digest, another owner's dispatch, and a plain dict passed off as proof.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import pathlib
import sqlite3
import sys
from types import SimpleNamespace

QUEUE = pathlib.Path(__file__).resolve().parents[1]
CHAT = QUEUE.parents[1] / "apps" / "padiem-chat"
sys.path.insert(0, str(CHAT))
sys.path.insert(0, str(QUEUE))

import schema  # noqa: E402
import service as queue_service  # noqa: E402
from app.d1_sqlite import SqliteD1, connect  # noqa: E402
from app.oracle_mesh_read_return_routes import (  # noqa: E402
    _COMMAND_FILE_SENTINEL, _COMMAND_PATH_RELATIVE, _COMMAND_ROOT_REF)
from app.history import (  # noqa: E402
    D1HistoryStore, HistoryError, HistoryForbidden, VerifiedDispatch)
from app.queue_store_proxy import QueueForwardingHistoryStore, QueueStoreClient  # noqa: E402
from internal_store import INTERNAL_STORE_PATH, QUEUE_SERVICE_SECRET_HEADER  # noqa: E402

SERVICE_SECRET = "queue-service-secret-value-261030"
CHANNEL = "c" * 32
USER = "usr_" + "b" * 32
OTHER = "usr_" + "c" * 32
RUN = "run_" + "d" * 32
BODY = ("PC 읽기 결과 본문입니다. " * 900)  # over one message, so the original is stored
SHA = hashlib.sha256(BODY.encode("utf-8")).hexdigest()
SIZE = len(BODY.encode("utf-8"))


class _Bucket:
    """The R2 surface the original store uses: put(key, bytes, httpMetadata=...)."""

    def __init__(self):
        self.stored = {}

    def put(self, key, data, **_meta):
        self.stored[key] = data
        return key


class _Headers(dict):
    def get(self, key, default=None):
        return super().get(str(key).lower(), default)


class _Request:
    def __init__(self, state, wire):
        self.app = SimpleNamespace(state=state)
        body = json.dumps(wire).encode("utf-8")
        self.headers = _Headers({"content-type": "application/json",
                                "content-length": str(len(body)),
                                QUEUE_SERVICE_SECRET_HEADER.lower(): SERVICE_SECRET})
        self._body = body

    async def body(self):
        return self._body


class _StreamedResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def aiter_bytes(self):
        yield self._payload


def _lane(tmp_path):
    """A queue database with the rows, and a D1 that has no dispatch table at all."""

    queue_connection = connect(str(tmp_path / "queue.sqlite3"))
    schema.apply(queue_connection)
    app = queue_service.create_app(connection=queue_connection, channel_secret=CHANNEL,
                                   service_secret=SERVICE_SECRET, legacy_map_lane=False,
                                   request_log="off")
    handler = [route for route in app.routes
               if getattr(route, "path", None) == INTERNAL_STORE_PATH][0].endpoint

    d1_connection = sqlite3.connect(":memory:", isolation_level=None)
    d1_connection.row_factory = sqlite3.Row
    d1_connection.execute("CREATE TABLE claw_run_history (id INTEGER PRIMARY KEY,"
                          " run_id TEXT, user_id TEXT, workspace_id TEXT, conversation_id TEXT)")
    inner = D1HistoryStore(SqliteD1(d1_connection), full_context_bucket=_Bucket())

    async def build():
        state = app.state

        class _Factory:
            def __init__(self):
                self.loop = asyncio.get_event_loop()

            def __call__(self, **_options):
                outer = self

                class _Client:
                    async def __aenter__(self):
                        return self

                    async def __aexit__(self, *exc_info):
                        return False

                    def stream(self, method, url, *, json=None, headers=None, **_rest):
                        outer = self

                        class _Call:
                            async def __aenter__(self_inner):
                                response = await handler(_Request(state, json))
                                self_inner.payload = (response.status_code, response.body)
                                return _StreamedResponse(*self_inner.payload)

                            async def __aexit__(self_inner, *exc_info):
                                return False

                        return _Call()

                return _Client()

        client = QueueStoreClient(origin="https://queue.invalid", service_secret=SERVICE_SECRET,
                                  client_factory=_Factory())
        return QueueForwardingHistoryStore(inner, client), queue_connection, d1_connection

    store, queue_db, d1_db = asyncio.run(build())
    return store, queue_db, d1_db


def _staged(store, run_id=RUN, kind_body=BODY, sha=None, size=None):
    """create → claim → consume, the way the poll and the first submission do it."""

    sha = sha or hashlib.sha256(kind_body.encode("utf-8")).hexdigest()
    size = size if size is not None else len(kind_body.encode("utf-8"))
    created = asyncio.run(store.create_oracle_mesh_dispatch(
        user_id=USER, run_id=run_id, command_id="cmd_" + "1" * 32,
        tool_request_ref="treq_" + "2" * 32, request_id="oreq_" + "3" * 32,
        revision_ref="rev_" + "4" * 32, evidence_ref=None, request_fingerprint="5" * 64,
        account_ref="acct_1", workspace_ref="ws_" + "6" * 32, device_id="dev_" + "7" * 24,
        binding_ref=None, node_ref="node_1", root_ref="C:", path_relative="Windows/win.ini",
        file_path="C:/Windows/win.ini",
        expires_at="2099-01-01T00:00:00.000Z"))
    dispatch_id = created["dispatch_id"]
    nonce = "n" * 32
    assert asyncio.run(store.claim_oracle_mesh_dispatch(
        dispatch_id=dispatch_id, nonce_sha256=hashlib.sha256(nonce.encode()).hexdigest())) is True
    consumed = asyncio.run(store.consume_oracle_mesh_dispatch(dispatch_id=dispatch_id, nonce=nonce))
    assert isinstance(consumed, VerifiedDispatch) and consumed["claim"] == "first"
    return dispatch_id, sha, size


def test_the_read_lane_stores_its_original_with_no_dispatch_rows_in_d1(tmp_path):
    store, queue_db, d1_db = _lane(tmp_path)
    dispatch_id, sha, size = _staged(store)

    assert asyncio.run(store.record_oracle_mesh_first_result(
        dispatch_id=dispatch_id, content_sha256=sha, content_bytes=size,
        termination="exited", exit_code=0)) is True
    key = asyncio.run(store.store_oracle_mesh_original(
        user_id=USER, dispatch_id=dispatch_id, conversation_id="chat_" + "a" * 32,
        message_id="msg_" + "1" * 32, raw=BODY, expected_sha256=sha, expected_bytes=size))
    assert isinstance(key, str) and key
    rows = list(queue_db.execute("select state, result_sha256 from oracle_mesh_dispatch"))
    assert str(rows[0]["state"]) == "received" and str(rows[0]["result_sha256"]) == sha

    # The read-back the browser makes: the terminal receipt is found in the queue, and the
    # D1 underneath never gets asked for a table it does not have.
    assert asyncio.run(store.finish_oracle_mesh_dispatch(dispatch_id=dispatch_id, outcome="done")) is True
    correlation = asyncio.run(store.get_oracle_mesh_run_correlation(user_id=USER, run_id=RUN))
    assert isinstance(correlation, VerifiedDispatch)
    assert str(correlation["command_id"]).startswith("cmd_")
    pin = asyncio.run(store.get_oracle_mesh_dispatch_pin(user_id=USER, dispatch_id=dispatch_id))
    assert str(pin["result_sha256"]) == sha and int(pin["result_bytes"]) == size


def test_the_command_lane_stores_its_result_with_no_dispatch_rows_in_d1(tmp_path):
    store, queue_db, _d1 = _lane(tmp_path)
    output = ("Volume in drive C has no label. " * 900)
    out_sha = hashlib.sha256(output.encode("utf-8")).hexdigest()
    created = asyncio.run(store.create_oracle_mesh_dispatch(
        user_id=USER, run_id="run_" + "e" * 32, command_id="cmd_" + "1" * 32,
        tool_request_ref="treq_" + "2" * 32, request_id="oreq_" + "3" * 32,
        revision_ref="rev_" + "4" * 32, evidence_ref=None, request_fingerprint="5" * 64,
        account_ref="acct_1", workspace_ref="ws_" + "6" * 32, device_id="dev_" + "7" * 24,
        binding_ref=None, node_ref="node_1", root_ref=_COMMAND_ROOT_REF,
        path_relative=_COMMAND_PATH_RELATIVE, file_path=_COMMAND_FILE_SENTINEL,
        kind="command", command_text="fsutil behavior query disablelastboot",
        expires_at="2099-01-01T00:00:00.000Z"))
    dispatch_id = created["dispatch_id"]
    nonce = "m" * 32
    assert asyncio.run(store.claim_oracle_mesh_dispatch(
        dispatch_id=dispatch_id,
        nonce_sha256=hashlib.sha256(nonce.encode()).hexdigest())) is True
    consumed = asyncio.run(store.consume_oracle_mesh_dispatch(dispatch_id=dispatch_id, nonce=nonce))
    assert consumed is not None and str(consumed["kind"]) == "command"
    asyncio.run(store.record_oracle_mesh_first_result(
        dispatch_id=dispatch_id, content_sha256=out_sha,
        content_bytes=len(output.encode("utf-8")), termination="exited", exit_code=0))
    key = asyncio.run(store.store_oracle_mesh_command_result(
        user_id=USER, dispatch_id=dispatch_id, conversation_id="chat_" + "a" * 32,
        message_id="msg_" + "1" * 32, raw=output, expected_sha256=out_sha,
        expected_bytes=len(output.encode("utf-8"))))
    assert isinstance(key, str) and key


def test_a_forged_digest_and_another_owner_are_still_refused(tmp_path):
    store, _queue_db, _d1 = _lane(tmp_path)
    dispatch_id, sha, size = _staged(store)
    asyncio.run(store.record_oracle_mesh_first_result(
        dispatch_id=dispatch_id, content_sha256=sha, content_bytes=size,
        termination="exited", exit_code=0))

    try:
        asyncio.run(store.store_oracle_mesh_original(
            user_id=USER, dispatch_id=dispatch_id, conversation_id="chat_" + "a" * 32,
            message_id="msg_" + "1" * 32, raw="다른 내용", expected_sha256="0" * 64, expected_bytes=3))
    except HistoryError as exc:
        assert "pinned result" in str(exc)
    else:
        raise AssertionError("a forged digest must not be stored")

    try:
        asyncio.run(store.store_oracle_mesh_original(
            user_id=OTHER, dispatch_id=dispatch_id, conversation_id="chat_" + "a" * 32,
            message_id="msg_" + "1" * 32, raw=BODY, expected_sha256=sha, expected_bytes=size))
    except HistoryForbidden:
        pass
    else:
        raise AssertionError("another owner's dispatch must be refused")


def test_a_plain_dict_is_never_taken_as_proof(tmp_path):
    """A handle must come from an owner-scoped read; a hand-made dict falls back and loses."""

    store, _queue_db, _d1 = _lane(tmp_path)
    dispatch_id, sha, size = _staged(store)
    asyncio.run(store.record_oracle_mesh_first_result(
        dispatch_id=dispatch_id, content_sha256=sha, content_bytes=size,
        termination="exited", exit_code=0))
    forged = VerifiedDispatch({"user_id": USER, "result_sha256": sha, "result_bytes": size,
                              "kind": "read", "root_ref": "C:"})
    forged["verified_for_user"] = USER  # the tag, but not from a read this store made

    # The fallback is the authoritative queue read, so the real pin is still enforced:
    # a dict that claims a digest the row does not carry is refused.
    try:
        asyncio.run(store.store_oracle_mesh_original(
            user_id=USER, dispatch_id=dispatch_id, conversation_id="chat_" + "a" * 32,
            message_id="msg_" + "1" * 32, raw=BODY, expected_sha256="9" * 64, expected_bytes=size,
            verified=forged))
    except HistoryError as exc:
        assert "pinned result" in str(exc)
    else:
        raise AssertionError("an unverified handle must not decide the pin")


def test_the_d1_path_still_answers_from_its_own_table(tmp_path):
    """Nothing here changes d1 mode: the same store reads its own dispatch rows."""

    connection = connect(str(tmp_path / "d1.sqlite3"))
    schema.apply(connection)
    connection.execute("CREATE TABLE claw_run_history (id INTEGER PRIMARY KEY,"
                       " run_id TEXT, user_id TEXT, workspace_id TEXT, conversation_id TEXT)")
    store = D1HistoryStore(SqliteD1(connection), full_context_bucket=_Bucket())
    connection.execute("INSERT INTO claw_run_history (run_id, user_id, workspace_id,"
                       " conversation_id) VALUES (?, ?, ?, ?)",
                       (RUN, USER, "ws_" + "6" * 32, "chat_" + "a" * 32))
    dispatch_id, sha, size = _staged(store)
    asyncio.run(store.record_oracle_mesh_first_result(
        dispatch_id=dispatch_id, content_sha256=sha, content_bytes=size,
        termination="exited", exit_code=0))
    key = asyncio.run(store.store_oracle_mesh_original(
        user_id=USER, dispatch_id=dispatch_id, conversation_id="chat_" + "a" * 32,
        message_id="msg_" + "1" * 32, raw=BODY, expected_sha256=sha, expected_bytes=size))
    assert isinstance(key, str)
    found = asyncio.run(store.get_oracle_mesh_run_correlation(user_id=USER, run_id=RUN))
    assert found is None  # 'done' state not reached yet; the read is served, not refused
