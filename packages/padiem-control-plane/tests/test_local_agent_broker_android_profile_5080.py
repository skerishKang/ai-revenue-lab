"""#5080 Android SAF profile: REAL binding/session auth + SQLite + private RPC.

The phone declares its owner-selected SAF folders through the same
device-authenticated HTTP surface as the installed-executable profile. These
tests drive the real canonical authority, a real SQLite table, credential
rotation and revocation, and the closed private reads the Chat directory and
the TXT trigger consume. No folder declaration is treated as execution.
"""
from __future__ import annotations

import json
from datetime import timedelta

from local_agent_broker_android_profile import (
    ANDROID_PROFILE_CONTRACT_VERSION, ANDROID_PROFILE_DEVICE_ROUTE,
    ANDROID_PROFILE_REF, BrokerAndroidSafProfileStore,
    android_saf_profile_rpc, android_saf_profiles_rpc,
    valid_saf_display_name, valid_saf_root_ref, AndroidProfileRefused,
)
from test_local_agent_broker_device_http import (
    BASE, CREDENTIAL, _encoded, _envelope, _service_fixture,
)
from test_local_agent_broker_text_results_4139 import Sql

PRIVATE = {
    "account_ref": "account.http.1",
    "workspace_ref": "workspace.http.1",
    "device_id": "device.http.1",
    "binding_ref": "binding.http.1",
    "profile_ref": ANDROID_PROFILE_REF,
}
FOLDERS = [
    {"root_ref": "safroot-documents", "display_name": "Documents"},
    {"root_ref": "safroot-notes", "display_name": "Notes"},
]


def build():
    state, authority, _, service = _service_fixture()
    sql = Sql()
    profiles = BrokerAndroidSafProfileStore(
        storage=type("Storage", (), {"sql": sql})(),
        state_port=state, authority_ref=service._authenticator.authority_ref,
        clock=lambda: BASE + timedelta(seconds=10),
    )
    service._android_profiles = profiles
    return authority, service, profiles


def post(service, *, session_id="session.android.profile.1", folders=FOLDERS,
         credential=CREDENTIAL, profile_ref=ANDROID_PROFILE_REF,
         contract_version=ANDROID_PROFILE_CONTRACT_VERSION, **extra):
    body = {
        "binding_ref": "binding.http.1",
        "credential_b64": _encoded(credential),
        "contract_version": contract_version,
        "session_id": session_id,
        "profile_ref": profile_ref,
        "folders": folders,
        **extra,
    }
    return service.handle(_envelope(
        json.dumps(body).encode("utf-8"), route=ANDROID_PROFILE_DEVICE_ROUTE
    ))


def open_session(authority, session_id="session.android.profile.1"):
    return authority.open_session(
        session_id=session_id,
        binding_ref="binding.http.1", credential=CREDENTIAL,
        account_ref="account.http.1", workspace_ref="workspace.http.1",
        now=BASE + timedelta(seconds=1),
    )


def test_credential_alone_is_not_enough_and_authenticated_set_is_durable():
    authority, service, profiles = build()
    assert post(service)["status"] == 409
    assert android_saf_profile_rpc(profiles, PRIVATE)["ok"] is False

    open_session(authority)
    response = post(service)
    assert response["status"] == 200
    stored = response["body"]["android_profile"]
    assert stored == {
        "accepted": True,
        "profile_ref": ANDROID_PROFILE_REF,
        "platform": "android",
        "folder_count": 2,
        "credential_generation": 1,
        "raw_device_credential": False,
        "saf_uri_exposed": False,
    }
    readable = android_saf_profile_rpc(profiles, PRIVATE)
    assert readable == {"ok": True, "profile": {
        **PRIVATE,
        "platform": "android",
        "capabilities": ["local.filesystem.read"],
        "read_suffix": ".txt",
        "folders": FOLDERS,
        "server_verified": True,
    }}
    # Scope is exact: another workspace or binding sees nothing.
    assert android_saf_profile_rpc(
        profiles, {**PRIVATE, "workspace_ref": "workspace.foreign"})["ok"] is False
    assert android_saf_profile_rpc(
        profiles, {**PRIVATE, "binding_ref": "binding.foreign"})["ok"] is False

    directory = android_saf_profiles_rpc(profiles, {
        "account_ref": "account.http.1", "workspace_ref": "workspace.http.1",
    })
    assert directory == {"ok": True, "platform": "android", "profiles": [{
        "binding_ref": "binding.http.1",
        "device_id": "device.http.1",
        "platform": "android",
        "capabilities": ["local.filesystem.read"],
        "read_suffix": ".txt",
        "folder_count": 2,
    }]}
    # The directory projection is presentation only: no folder references.
    assert "safroot" not in json.dumps(directory)


def test_rotation_and_revocation_invalidate_the_stored_declaration():
    authority, service, profiles = build()
    open_session(authority)
    assert post(service)["status"] == 200
    authority.rotate_credential(
        "binding.http.1", expected_generation=1,
        new_credential=b"rotated android credential 5080",
        now=BASE + timedelta(seconds=4),
    )
    assert post(service)["status"] == 401
    assert android_saf_profile_rpc(profiles, PRIVATE)["ok"] is False
    assert android_saf_profiles_rpc(profiles, {
        "account_ref": "account.http.1", "workspace_ref": "workspace.http.1",
    })["profiles"][0]["capabilities"] == []
    authority.revoke_binding("binding.http.1", now=BASE + timedelta(seconds=5))
    assert android_saf_profile_rpc(profiles, PRIVATE)["ok"] is False


def test_folder_bounds_uris_paths_and_closed_shapes_are_refused():
    authority, service, profiles = build()
    open_session(authority)
    for bad in (
        "content://com.android.externalstorage.documents/tree/primary%3ADocuments",
        "content:tree/primary",
        "/data/user/0/files",
        r"Documents\Notes",
        "..",
        "../escape",
        "saf root",
        "x" * 257,
    ):
        try:
            valid_saf_root_ref(bad)
        except AndroidProfileRefused:
            pass
        else:
            raise AssertionError("root_ref accepted: " + bad)
        assert post(service, folders=[{"root_ref": bad, "display_name": "Docs"}])["status"] == 409

    for bad_name in ("", "x" * 81, " padded", "bad/name", "bad\\name", "bad\x00name"):
        try:
            valid_saf_display_name(bad_name)
        except AndroidProfileRefused:
            pass
        else:
            raise AssertionError("display_name accepted: " + repr(bad_name))
        assert post(
            service, folders=[{"root_ref": "safroot-docs", "display_name": bad_name}]
        )["status"] == 409

    assert post(service, folders=[
        {"root_ref": "safroot-docs", "display_name": "Docs"},
        {"root_ref": "safroot-docs", "display_name": "Again"},
    ])["status"] == 409
    assert post(service, folders=[
        {"root_ref": f"safroot-{index}", "display_name": "Docs"}
        for index in range(9)
    ])["status"] == 409
    assert post(service, folders=[
        {"root_ref": "safroot-docs", "display_name": "Docs", "uri": "content://secret"},
    ])["status"] == 409
    assert post(service, profile_ref="profile.3140.python")["status"] == 409
    assert post(service, contract_version="other.contract")["status"] == 409
    assert post(service, owner_ref="foreign")["status"] == 409
    assert post(service, credential=b"wrong credential")["status"] == 401
    assert android_saf_profile_rpc(profiles, PRIVATE)["ok"] is False


def test_empty_set_is_a_truthful_withdrawal_and_replaces_atomically():
    authority, service, profiles = build()
    open_session(authority)
    assert post(service)["status"] == 200
    assert post(service, folders=[{"root_ref": "safroot-only", "display_name": "Only"}])["status"] == 200
    readable = android_saf_profile_rpc(profiles, PRIVATE)
    assert [item["root_ref"] for item in readable["profile"]["folders"]] == ["safroot-only"]
    # Withdrawal: the previous folder set must not linger beside the empty one.
    assert post(service, folders=[])["status"] == 200
    assert android_saf_profile_rpc(profiles, PRIVATE)["profile"]["folders"] == []
    assert android_saf_profiles_rpc(profiles, {
        "account_ref": "account.http.1", "workspace_ref": "workspace.http.1",
    })["profiles"][0]["folder_count"] == 0


def test_private_rpcs_require_the_closed_payload_shapes():
    _, _, profiles = build()
    for bad in (
        {k: v for k, v in PRIVATE.items() if k != "profile_ref"},
        {**PRIVATE, "extra": "x"},
        {**PRIVATE, "profile_ref": "other.profile"},
    ):
        assert android_saf_profile_rpc(profiles, bad)["ok"] is False
    for bad in (
        {"account_ref": "account.http.1"},
        {"account_ref": "account.http.1", "workspace_ref": "workspace.http.1", "extra": "x"},
    ):
        assert android_saf_profiles_rpc(profiles, bad)["ok"] is False
