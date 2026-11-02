"""#6011 follow-up — the Connector's self-reported version reaches the device facts.

The missing link after #6637: the Connector reports its product version in the
enrollment redemption body, the broker stores it on the device binding, and the
canonical device facts surface it as ``client_version`` — the key the Chat
device directory already judges (#6637 display tests cover that last hop).

This file exercises the real device HTTP envelope path: a pairing challenge,
then a redemption whose body carries (or omits) ``client_version``, then the
canonical ``device_directory`` projection. An out-of-shape version string is
dropped, never fatal — the pairing succeeds and the device simply reports
"version unknown".
"""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "padiem-control-plane"))
sys.path.insert(0, str(ROOT / "packages" / "padiem-control-plane" / "padiem_control_plane"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_local_agent_broker_device_truth import (  # noqa: E402
    AUTHORITY_REF,
    PEPPER,
    WORKSPACE_REF,
    _rpc_fixture,
)

from padiem_control_plane.local_agent_broker_pairing import (  # noqa: E402
    InMemoryBrokerPairingAuthority,
    InMemoryLocalAgentBrokerAuthority,
    pairing_proof_ref,
)

PAIRING_PEPPER = "cloudflare-do-connector-version-report-pairing-pepper"
CREDENTIAL = b"connector-version-report-test-credential"
ACCOUNT_REF = "acct.version-report.1"
DEVICE_ID = "device.version-report.1"
BINDING_REF = "bind.version-report.1"
PAIRING_CHALLENGE_ROUTE = "/v1/broker/pairings/challenge"
PAIRING_REDEEM_ROUTE = "/v1/broker/pairings/redeem"
BASE = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)


_NONCE = iter(range(1, 1000))


def _boot():
    _storage, _env, durable_object = _rpc_fixture()
    # Arm the pairing authority over the same broker authority this worker
    # serves, exactly as the device HTTP service composes it. The challenge is
    # issued server-side (by the page that starts the connection), so the test
    # issues it directly from this authority and drives only the redemption
    # through the real device HTTP envelope path.
    # The pairing authority must be backed by the same durable state the
    # directory reads — an isolated in-memory authority would register the
    # binding somewhere the device_directory can never see. The runtime's
    # facade owns the state-backed authority instance; its private attribute
    # is the only accessor this harness needs.
    pairing = InMemoryBrokerPairingAuthority(
        pepper=PAIRING_PEPPER.encode("utf-8"),
        authority=durable_object._runtime.facade()._authority,
        code_nonce_factory=lambda: format(next(_NONCE), "032x"),
        credential_factory=lambda: CREDENTIAL,
    )
    durable_object._device_http._pairing_authority = pairing
    return durable_object, pairing


def _envelope(route: str, payload: dict) -> dict:
    import json

    body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {
        "method": "POST",
        "route": route,
        "content_type": "application/json",
        "body_b64": base64.b64encode(body).decode("ascii"),
        "tls_verified": True,
    }


def _pair_device(durable_object: object, pairing: object, *, device_id: str, client_version: str | None) -> dict:
    """Real device HTTP path: challenge, then redemption carrying the version.

    ``handle_device_http`` answers the structured envelope ``{status, headers,
    body}`` — the JSON payload inside ``body`` is the pairing contract.
    """
    # The connector's registration redemption is the consent-scoped route: the
    # page that starts the connection issues the challenge bound to one
    # device under a stored consent, and the Connector proves possession of
    # the one-time code it was handed.
    challenge, code = pairing.issue_enrollment_challenge(
        account_ref=ACCOUNT_REF, workspace_ref=WORKSPACE_REF,
        consent_ref="consent.version-report.1", owner_ref="owner.version-report.1",
        device_id=device_id, now=BASE,
    )
    proof = pairing_proof_ref(
        challenge_id=challenge.challenge_id, device_id=device_id, pairing_code=code,
    )
    body = {
        "challenge_id": challenge.challenge_id,
        "device_id": device_id,
        "proof_ref": proof,
        "now": _iso(BASE + timedelta(seconds=30)),
    }
    if client_version is not None:
        body["client_version"] = client_version
    redeemed = asyncio.run(durable_object.handle_device_http(_envelope(PAIRING_REDEEM_ROUTE, body)))
    assert redeemed["status"] == 200, redeemed
    assert redeemed["body"]["ok"] is True, redeemed["body"]
    return redeemed["body"]


def _iso(value: datetime) -> str:
    return value.isoformat()


def _directory(durable_object: object) -> list[dict]:
    listed = asyncio.run(durable_object.device_directory(
        {"account_ref": ACCOUNT_REF, "workspace_ref": WORKSPACE_REF}
    ))
    assert listed.get("ok") is True, listed
    assert listed.get("available") is True, listed
    return listed["devices"]


def test_a_new_connector_reports_its_version_into_the_device_facts() -> None:
    durable_object, pairing = _boot()
    redeemed = _pair_device(durable_object, pairing, device_id=DEVICE_ID, client_version="0.3.0-rc1")
    assert redeemed["ok"] is True, redeemed

    devices = _directory(durable_object)
    assert len(devices) == 1, devices
    # The key the Chat device directory judges (#6637) sits at the fact root.
    assert devices[0]["client_version"] == "0.3.0-rc1", devices


def test_an_old_connector_that_omits_the_version_stays_unknown() -> None:
    durable_object, pairing = _boot()
    redeemed = _pair_device(durable_object, pairing, device_id=DEVICE_ID, client_version=None)
    assert redeemed["ok"] is True, redeemed

    devices = _directory(durable_object)
    assert len(devices) == 1, devices
    assert "client_version" not in devices[0], devices


@pytest.mark.parametrize("bogus", [
    "0.3.0-rc1" + "A" * 50000,          # length bomb
    "0.3.0\x00<script>alert(1)</script>",  # control characters + script
    "0.3.0\nDROP TABLE pc_device_links",   # newline smuggling
    "v0.3.0",                              # the grammar refuses a v-prefix
], ids=["length-bomb", "control-chars-script", "newline-smuggling", "v-prefix"])
def test_a_bogus_version_is_dropped_without_breaking_the_pairing(bogus: str) -> None:
    durable_object, pairing = _boot()
    redeemed = _pair_device(durable_object, pairing, device_id=DEVICE_ID, client_version=bogus)
    assert redeemed["ok"] is True, (redeemed, bogus)

    devices = _directory(durable_object)
    assert len(devices) == 1, devices
    assert "client_version" not in devices[0], (devices, bogus)


def test_a_second_device_reports_only_its_own_version() -> None:
    durable_object, pairing = _boot()
    other_device = "device.version-report.2"
    assert _pair_device(durable_object, pairing, device_id=DEVICE_ID, client_version="0.3.0-rc1")["ok"]
    assert _pair_device(durable_object, pairing, device_id=other_device, client_version=None)["ok"]

    devices = {row["binding"]["device_id"]: row for row in _directory(durable_object)}
    assert devices[DEVICE_ID]["client_version"] == "0.3.0-rc1"
    assert "client_version" not in devices[other_device]
