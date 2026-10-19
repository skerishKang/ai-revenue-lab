from app.b66_drive_connection import (
    B66DriveConnectedAccount,
    B66DriveConnectionStatus,
    B66DriveDestinationAuthority,
    B66DriveFreezeDurableGrantBackend,
    B66DriveInMemoryConnectionStore,
    B66DriveConnectionRecord,
    B66_DRIVE_DURABLE_CREDENTIAL_BACKEND,
    connection_record_from_trusted_result,
    trusted_owner,
)


def google_account(sub="google-sub-12345678", email="g@drive.test"):
    return B66DriveConnectedAccount(google_sub=sub, email=email)


def conn(authority, owner="cgi-owner-a", sub="google-sub-12345678", email="g@drive.test", grant="grant-a"):
    return authority.connect_destination(
        owner_b66_user_id=owner,
        drive_account=google_account(sub=sub, email=email),
        grant_reference=grant,
    )


def test_unconnected_owners():
    authority = B66DriveDestinationAuthority(B66DriveInMemoryConnectionStore())
    assert authority.public_status("cgi-owner-a")["status"] == B66DriveConnectionStatus.NOT_CONNECTED.value
    assert authority.public_status("cgi-owner-b")["status"] == B66DriveConnectionStatus.NOT_CONNECTED.value


def test_owner_isolation():
    authority = B66DriveDestinationAuthority(B66DriveInMemoryConnectionStore())
    conn(authority, owner="cgi-owner-a", sub="google-sub-a12345678", email="a@drive.test", grant="grant-a")
    a = authority.public_status("cgi-owner-a")
    b = authority.public_status("cgi-owner-b")
    assert a["status"] == "connected"
    assert a["destination_sub"] == "google-sub-a12345678"
    assert b["status"] == "not_connected"
    assert b["destination_sub"] is None
    assert authority.load_connection("cgi-owner-b") is None


def test_reconnect_required_state():
    authority = B66DriveDestinationAuthority(B66DriveInMemoryConnectionStore())
    record = authority.mark_reconnect_required(
        owner_b66_user_id="cgi-owner-a",
        drive_account=google_account(),
        grant_reference="grant-a",
        reason="revoked",
    )
    assert record.status == B66DriveConnectionStatus.RECONNECT_REQUIRED
    assert authority.public_status("cgi-owner-a")["status"] == "reconnect_required"


def test_durable_continuity_is_honest_seam():
    authority = B66DriveDestinationAuthority(B66DriveInMemoryConnectionStore())
    conn(authority, owner="cgi-owner-a")
    status = authority.public_status("cgi-owner-a")
    assert status["status"] == "connected"
    assert status["durable_credential_backend"] == "ABSENT_NOT_PROVEN"


def test_disconnect_only_clears_selected_owner():
    authority = B66DriveDestinationAuthority(B66DriveInMemoryConnectionStore())
    conn(authority, owner="cgi-owner-a", sub="google-sub-a12345678", email="a@drive.test", grant="grant-a")
    authority.disconnect_destination("cgi-owner-a")
    assert authority.public_status("cgi-owner-a")["status"] == "not_connected"
    conn(authority, owner="cgi-owner-b", sub="google-sub-b12345678", email="b@drive.test", grant="grant-b")
    assert authority.public_status("cgi-owner-b")["status"] == "connected"


def test_owner_claim_is_trusted_server_input():
    authority = B66DriveDestinationAuthority(B66DriveInMemoryConnectionStore())
    for bad in (None, "", "owner with spaces", "attacker\nadmin"):
        try:
            authority.public_status(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"untrusted owner accepted: {bad!r}")
    trusted_owner("cgi-owner-a")


def test_actor_spoof_forbidden_fields_are_rejected():
    payloads = (
        {
            "owner_b66_user_id": "cgi-owner-a",
            "drive_account": {"google_sub": "google-sub-12345678", "email": "g@drive.test"},
            "google_grant_reference": "grant-a",
            "access_token": "secret",
        },
        {
            "owner_b66_user_id": "cgi-owner-a",
            "drive_account": {"google_sub": "google-sub-12345678", "email": "g@drive.test", "refresh_token": "secret"},
            "google_grant_reference": "grant-a",
        },
    )
    for payload in payloads:
        try:
            connection_record_from_trusted_result(payload)
        except ValueError:
            pass
        else:
            raise AssertionError("forbidden authority accepted")


def test_public_status_never_exposes_secrets():
    authority = B66DriveDestinationAuthority(B66DriveInMemoryConnectionStore())
    conn(authority, owner="cgi-owner-a", sub="google-sub-drive12345", email="g@drive.test", grant="grant-a")
    status = authority.public_status("cgi-owner-a")
    forbidden = {"access_token", "refresh_token", "token", "secret", "bearer", "private"}
    assert not (forbidden & {key.lower() for key in status})
    for word in forbidden:
        assert word not in str(status).lower()
    record = authority.load_connection("cgi-owner-a")
    assert "<redacted>" in repr(record)
    assert "grant-a" not in repr(record)


def test_honest_backend_state():
    assert B66_DRIVE_DURABLE_CREDENTIAL_BACKEND == "ABSENT_NOT_PROVEN"
    authority = B66DriveDestinationAuthority(B66DriveInMemoryConnectionStore())
    conn(authority)
    status = authority.public_status("cgi-owner-a")
    assert status["status"] == "connected"
    assert status["durable_credential_backend"] == "ABSENT_NOT_PROVEN"


def test_fail_closed_backend():
    backend = B66DriveFreezeDurableGrantBackend()
    assert backend.load("cgi-owner-a") is None
    # Exercise save() itself; the old test raised during conn() first.
    memory = B66DriveDestinationAuthority(B66DriveInMemoryConnectionStore())
    record = conn(memory, owner="cgi-owner-z", sub="google-sub-z12345678",
                  email="z@drive.test", grant="grant-z")
    try:
        backend.save(record)
    except RuntimeError:
        pass
    else:
        raise AssertionError("placeholder backend saved")
    assert backend.load("cgi-owner-z") is None
    backend.delete("cgi-owner-a")


def test_unconfigured_default_denies_connected_claim():
    authority = B66DriveDestinationAuthority()
    assert authority.durable_backend_proven is False
    assert authority.public_status("cgi-owner-a")["status"] == "not_connected"
    try:
        conn(authority)
    except RuntimeError:
        pass
    else:
        raise AssertionError("default authority accepted unverified Drive grant")
    assert authority.public_status("cgi-owner-a")["status"] == "not_connected"


def test_in_memory_seam_cannot_prove_encrypted_oauth_durability():
    authority = B66DriveDestinationAuthority(B66DriveInMemoryConnectionStore())
    conn(authority)
    assert authority.public_status("cgi-owner-a")["status"] == "connected"
    assert authority.durable_backend_proven is False
    # A separate process/browser cannot inherit this ephemeral map.
    assert B66DriveDestinationAuthority().public_status("cgi-owner-a")["status"] == "not_connected"


def test_verified_google_destination_is_accepted_and_unknown_fields_denied():
    verified = {
        "owner_b66_user_id": "cgi-owner-a",
        "drive_account": {"google_sub": "google-sub-12345678", "email": "g@drive.test"},
        "google_grant_reference": "reference-not-secret",
        "connected_at": "2026-10-16T00:00:00Z",
    }
    record = connection_record_from_trusted_result(verified)
    assert record.owner_b66_user_id == "cgi-owner-a"
    assert record.drive_account.google_sub == "google-sub-12345678"
    assert record.public_status()["destination_account"] == "g@drive.test"
    assert "reference-not-secret" not in str(record.public_status())
    for bad in ({**verified, "user_id": "forged"}, {**verified, "grant": "forged"},
                {**verified, "drive_account": {**verified["drive_account"], "token": "secret"}}):
        try:
            connection_record_from_trusted_result(bad)
        except ValueError:
            pass
        else:
            raise AssertionError("untrusted extra field accepted")


def test_independent_b66_owners_may_choose_same_google_destination():
    authority = B66DriveDestinationAuthority(B66DriveInMemoryConnectionStore())
    conn(authority, owner="cgi-owner-a", sub="google-sub-same1234", grant="grant-a")
    conn(authority, owner="cgi-owner-b", sub="google-sub-same1234", grant="grant-b")
    assert authority.load_connection("cgi-owner-a").google_grant_reference == "grant-a"
    assert authority.load_connection("cgi-owner-b").google_grant_reference == "grant-b"
    authority.disconnect_destination("cgi-owner-a")
    assert authority.public_status("cgi-owner-a")["status"] == "not_connected"
    assert authority.public_status("cgi-owner-b")["status"] == "connected"
