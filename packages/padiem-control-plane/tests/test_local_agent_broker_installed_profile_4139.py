"""#4139 installed profile: REAL canonical binding/session + SQLite + device HTTP.

The new RPC must not be a stub: we post through canonical device authentication,
persist to the real SQL table, read via the private RPC, and invalidate when the
current credential generation changes or the binding is revoked.
"""
from __future__ import annotations

import json
from datetime import timedelta

from local_agent_broker_installed_profile import (
    PROFILE_CONTRACT_VERSION, PROFILE_DEVICE_ROUTE, PROFILE_REF,
    BrokerInstalledExecutionProfileStore, installed_execution_profile_rpc,
    valid_installed_executable_path, InstalledProfileRefused,
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
    "profile_ref": PROFILE_REF,
}
PATH = r"C:\Installed\Padiem\python.exe"


def build():
    state, authority, _, service = _service_fixture()
    sql = Sql()
    profile = BrokerInstalledExecutionProfileStore(
        storage=type("Storage", (), {"sql": sql})(),
        state_port=state, authority_ref=service._authenticator.authority_ref,
        clock=lambda: BASE + timedelta(seconds=10),
    )
    service._execution_profiles = profile
    return authority, service, profile


def post(service, *, session_id="session.profile.1", path=PATH,
         credential=CREDENTIAL, profile_ref=PROFILE_REF, **extra):
    body = {
        "binding_ref": "binding.http.1",
        "credential_b64": _encoded(credential),
        "contract_version": PROFILE_CONTRACT_VERSION,
        "session_id": session_id,
        "profile_ref": profile_ref,
        "executable_path": path,
        **extra,
    }
    return service.handle(_envelope(
        json.dumps(body).encode("utf-8"), route=PROFILE_DEVICE_ROUTE
    ))


def test_actual_authenticated_session_post_durable_read_rotation_revocation():
    authority, service, profiles = build()
    # A credential alone is insufficient: there must be a live canonical session.
    assert post(service)["status"] == 409
    assert installed_execution_profile_rpc(profiles, PRIVATE)["ok"] is False

    authority.open_session(
        session_id="session.profile.1",
        binding_ref="binding.http.1", credential=CREDENTIAL,
        account_ref="account.http.1", workspace_ref="workspace.http.1",
        now=BASE + timedelta(seconds=1),
    )
    response = post(service)
    assert response["status"] == 200
    assert response["body"]["execution_profile"]["credential_generation"] == 1
    verified = installed_execution_profile_rpc(profiles, PRIVATE)
    assert verified == {"ok": True, "profile": {
        **PRIVATE, "executable_path": PATH, "server_verified": True,
    }}
    assert installed_execution_profile_rpc(profiles, {
        **PRIVATE, "workspace_ref": "another-workspace",
    })["ok"] is False

    # Old/stolen credential after rotation must neither update nor retrieve
    # the profile; the stored row is not an authority independent of binding.
    authority.rotate_credential(
        "binding.http.1", expected_generation=1,
        new_credential=b"rotated credential 4139",
        now=BASE + timedelta(seconds=4),
    )
    assert post(service)["status"] == 401
    assert installed_execution_profile_rpc(profiles, PRIVATE)["ok"] is False
    authority.revoke_binding("binding.http.1", now=BASE + timedelta(seconds=5))
    assert installed_execution_profile_rpc(profiles, PRIVATE)["ok"] is False


def test_profile_ref_path_scope_and_noncanonical_envelope_fail_closed():
    authority, service, profiles = build()
    authority.open_session(
        session_id="session.profile.1",
        binding_ref="binding.http.1", credential=CREDENTIAL,
        account_ref="account.http.1", workspace_ref="workspace.http.1",
        now=BASE + timedelta(seconds=1),
    )
    for bad in (
        "python.exe", "/usr/bin/python", r"\\server\share\python.exe",
        r"C:python.exe", r"C:\Installed\..\python.exe",
        r"C:\Wrong\app.exe /unsafe", r"C:\Installed\python.dll",
    ):
        try:
            valid_installed_executable_path(bad)
        except InstalledProfileRefused:
            pass
        else:
            raise AssertionError("path accepted: " + bad)
        assert post(service, path=bad)["status"] == 409
    assert post(service, profile_ref="other.profile")["status"] == 409
    assert post(service, owner_ref="foreign")["status"] == 409
    assert post(service, credential=b"wrong credential")["status"] == 401
    assert installed_execution_profile_rpc(profiles, PRIVATE)["ok"] is False


def test_an_authenticated_profile_update_is_exact_and_generation_pinned():
    authority, service, profiles = build()
    authority.open_session(
        session_id="session.profile.1",
        binding_ref="binding.http.1", credential=CREDENTIAL,
        account_ref="account.http.1", workspace_ref="workspace.http.1",
        now=BASE + timedelta(seconds=1),
    )
    assert post(service)["status"] == 200
    newer = r"C:\Installed\PadiemV2\python.exe"
    assert post(service, path=newer)["status"] == 200
    assert installed_execution_profile_rpc(profiles, PRIVATE)["profile"]["executable_path"] == newer
    invalid = dict(PRIVATE)
    invalid["binding_ref"] = "binding.foreign"
    assert installed_execution_profile_rpc(profiles, invalid)["ok"] is False
