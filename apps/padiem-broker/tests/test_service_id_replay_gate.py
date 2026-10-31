"""The broker ingress consumes a signed request id and refuses a replay.

The broker is a CPython service, so its door composes the same policy and the
same reviewed request-id store the Workers use, over its own SQLite file. The
transitional policy keeps an id-less v1 request working for one release.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import time

import httpx
import pytest

import service as broker_service
from harness_support import SECRET, build_app, client_for, environ, rpc
from internal_rpc_ingress import SERVICE_ID_HEADER

METHOD = "get_enrollment_binding"
BODY = json.dumps({"challenge_id": "synthetic.challenge.1"}, separators=(",", ":")).encode()


def _v2_headers(path: str, service_id: str, *, at: int | None = None) -> dict[str, str]:
    at = int(time.time()) if at is None else at
    signed = b"\n".join(
        (b"v2", b"POST", path.encode(), str(at).encode(), service_id.encode(), BODY)
    )
    return {
        "content-type": "application/json",
        "x-padiem-service-at": str(at),
        SERVICE_ID_HEADER: service_id,
        "x-padiem-service-proof": "v2="
        + hmac.new(SECRET.encode(), signed, hashlib.sha256).hexdigest(),
    }


@pytest.mark.asyncio
async def test_a_replayed_request_id_is_refused_and_a_new_one_is_served(tmp_path):
    app = build_app(tmp_path)
    path = "/internal/rpc/" + METHOD
    async with client_for(app) as client:
        first = await client.post(
            path, content=BODY, headers=_v2_headers(path, "req-0000000000000001")
        )
        replay = await client.post(
            path, content=BODY, headers=_v2_headers(path, "req-0000000000000001")
        )
        fresh = await client.post(
            path, content=BODY, headers=_v2_headers(path, "req-0000000000000002")
        )
        # The transitional default still serves a v1 request with no id.
        legacy = await rpc(client, METHOD, {"challenge_id": "synthetic.challenge.1"})

    assert first.status_code == 200
    assert replay.status_code == 409
    assert replay.json()["error"]["code"] == "rpc_replay_detected"
    assert fresh.status_code == 200
    assert legacy.status_code == 200


@pytest.mark.asyncio
async def test_the_id_is_remembered_in_the_brokers_own_database(tmp_path):
    app = build_app(tmp_path)
    path = "/internal/rpc/" + METHOD
    async with client_for(app) as client:
        first = await client.post(
            path, content=BODY, headers=_v2_headers(path, "req-0000000000000003")
        )
    assert first.status_code == 200

    # A set in memory would forget the id on restart; the row must be in the
    # broker database itself.
    with sqlite3.connect(str(tmp_path / "broker.sqlite3")) as raw:
        rows = raw.execute(
            "SELECT service_id FROM service_request_ids WHERE service_id=?",
            ("req-0000000000000003",),
        ).fetchall()
    assert rows == [("req-0000000000000003",)]


@pytest.mark.asyncio
async def test_the_required_policy_refuses_an_idless_v1_request(tmp_path):
    env = environ(tmp_path)
    env["PADIEM_RPC_SERVICE_ID_POLICY"] = "required"
    app = broker_service.build_app(environ=env)

    async with client_for(app) as client:
        response = await rpc(client, METHOD, {"challenge_id": "synthetic.challenge.1"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "rpc_service_id_required"


@pytest.mark.asyncio
async def test_a_bad_id_is_refused_before_dispatch(tmp_path):
    app = build_app(tmp_path)
    path = "/internal/rpc/" + METHOD
    async with client_for(app) as client:
        response = await client.post(
            path, content=BODY, headers=_v2_headers(path, "bad id with spaces 000000")
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "rpc_service_id_invalid"
