"""#2107 the Owner's COM2 secret and Provider screen, and the door it lives behind.

The completion criterion is the Owner typing a secret name and value on this host
and connecting several models to it, from a screen. These tests drive that from
the outermost boundary — a real HTTP request into the local ASGI app, a real file
in a real secret directory — and pin the four things that make it safe rather
than convenient: the Cloudflare door has no such route at all, the value never
appears in a response or a log, a name already bound in Cloudflare cannot be
re-used for a different Provider, and a Provider's models all share the one key.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app.local_runtime import SECRET_DIR_ENV, create_local_app
from app.pilot import com2_admin
from app.pilot.model_registry_file import REGISTRY_PATH, read_registry

APP_ROOT = REGISTRY_PATH.parents[2]
SECRETS = "/com2/admin/secrets"
PROVIDER_NEW = "/com2/admin/providers/new"
PROVIDER = "/com2/admin/providers"
SYNTHETIC = "PADIEM_SYNTHETIC_MANAGER_API_KEY"
SECRET_VALUE = "synthetic-manager-value-9f3c1a7d"
BASE_ORIGIN = "https://api.synthetic-manager.example/v1"


@pytest.fixture()
def host(tmp_path, monkeypatch):
    """A COM2-shaped host: a private secret directory and a copy of the registry."""
    secret_dir = tmp_path / "secrets"
    # StateDirectory hands the service a 0700 directory it owns, and the store
    # refuses a looser one rather than quietly tightening the operator's host.
    # A default mkdir() is 0755 under the usual umask, which is exactly the
    # posture a real COM2 must never be in.
    secret_dir.mkdir(mode=0o700)
    os.chmod(secret_dir, 0o700)
    registry = tmp_path / "b14_models.json"
    shutil.copyfile(REGISTRY_PATH, registry)
    monkeypatch.setenv(SECRET_DIR_ENV, str(secret_dir))
    monkeypatch.setenv("B14_REGISTRY_PATH", str(registry))
    monkeypatch.delenv(SYNTHETIC, raising=False)
    com2_admin.TEST_TRANSPORT = None
    yield {"secrets": secret_dir, "registry": registry}
    # install_models() mutates the live catalog; put the real registry back.
    from app.pilot.model_registry_file import install_models

    monkeypatch.delenv("B14_REGISTRY_PATH")
    install_models()


@pytest.fixture()
def admin(host):
    with TestClient(create_local_app()) as client:
        yield client


def test_the_cloudflare_door_has_no_secret_manager_route_at_all() -> None:
    """Authority by absence: create_app() is what the Worker builds.

    A browser-facing screen that writes credentials must not exist in the
    production deployment, so the check is that the route is not there rather
    than that some guard rejects the call.
    """
    from app.factory import create_app

    with TestClient(create_app()) as client:
        for path in (SECRETS, PROVIDER, PROVIDER_NEW, f"{SECRETS}/delete"):
            for method in (client.get, client.post):
                assert method(path).status_code == 404, f"{method} {path}"


def test_register_update_delete_round_trip(admin, host) -> None:
    response = admin.post(
        SECRETS, data={"name": SYNTHETIC.lower(), "value": SECRET_VALUE}, follow_redirects=False
    )
    assert response.status_code == 303
    location = response.headers["location"]
    assert "notice=saved" in location, location
    stored = host["secrets"] / SYNTHETIC
    assert stored.is_file()
    assert stored.read_text(encoding="utf-8") == SECRET_VALUE

    listing = admin.get(SECRETS).text
    assert SYNTHETIC in listing and "등록됨" in listing

    rotated = "synthetic-rotated-value-4b7e"
    admin.post(SECRETS, data={"name": SYNTHETIC, "value": rotated})
    assert stored.read_text(encoding="utf-8") == rotated

    unconfirmed = admin.post(
        SECRETS + "/delete", data={"name": SYNTHETIC}, follow_redirects=False
    )
    assert "confirm_required" in unconfirmed.headers["location"]
    assert stored.is_file()

    deleted = admin.post(
        SECRETS + "/delete",
        data={"name": SYNTHETIC, "confirm": "yes"},
        follow_redirects=False,
    )
    assert "notice=deleted" in deleted.headers["location"]
    assert not stored.exists()


def test_the_value_never_reaches_a_response_or_a_log(admin, host, caplog) -> None:
    with caplog.at_level("INFO"):
        saved = admin.post(
            SECRETS, data={"name": SYNTHETIC, "value": SECRET_VALUE}, follow_redirects=False
        )
        bodies = [saved.text, admin.get(SECRETS).text, admin.get(f"{SECRETS}?q={SYNTHETIC}").text]
        bodies.append(admin.post(
            f"{PROVIDER}/test", data={"provider_id": "yeta"}, follow_redirects=False
        ).text)
    joined = "\n".join(bodies) + "\n" + caplog.text
    # Prove the value really was stored first: otherwise a failed write would
    # look like a passing leak test for the wrong reason.
    assert (host["secrets"] / SYNTHETIC).read_text(encoding="utf-8") == SECRET_VALUE
    assert "등록됨" in bodies[1], bodies[1][:400]
    assert SECRET_VALUE not in joined
    # A masked preview is also a leak here: the screen reports state, not content.
    assert SECRET_VALUE[:6] not in joined


def test_a_name_cloudflare_already_binds_is_refused(admin, host) -> None:
    """Same name, two different values on two hosts is the aliasing hazard."""
    for reserved in ("PADIEM_B14_CREDENTIAL_01", "PADIEM_B14_CREDENTIAL_08"):
        response = admin.post(
            SECRETS, data={"name": reserved, "value": SECRET_VALUE}, follow_redirects=False
        )
        assert "reason=name_declared_as_cloudflare_binding" not in response.headers["location"]
        # The secret store reserves only for a NEW Provider; retyping the value
        # of a slot this host already reads is the Owner's own migration path.
        assert (host["secrets"] / reserved).read_text(encoding="utf-8") == SECRET_VALUE

    blocked = admin.post(
        PROVIDER,
        data={
            "provider_id": "aliasing-attempt", "provider_name": "Alias",
            "base_origin": BASE_ORIGIN, "credential_binding_name": "PADIEM_B14_CREDENTIAL_03",
            "value": "synthetic-alias-value-1234",
            "upstream_models": "some-model", "source": "https://example.invalid/docs",
            "source_checked_at": "2026-10-27",
        },
        follow_redirects=False,
    )
    assert "reason=name_declared_as_cloudflare_binding" in blocked.headers["location"]
    assert not (host["secrets"] / "PADIEM_B14_CREDENTIAL_03").exists()
    assert "aliasing-attempt" not in read_registry()["providers"]


def test_one_key_three_models_deepseek_first_and_still_unrouted(admin, host) -> None:
    response = admin.post(
        PROVIDER,
        data={
            "provider_id": "syntheticmanager", "provider_name": "Synthetic Manager",
            "base_origin": BASE_ORIGIN, "credential_binding_name": SYNTHETIC,
            "value": SECRET_VALUE,
            "upstream_models": "deepseek-v4.1-flash,glm-5.3-flash,deepseek-v4.1-flash-uncensored",
            "input_price_usd_per_1m": "0.08,0.08,0.08",
            "output_price_usd_per_1m": "0.35,0.42,0.35",
            "cached_input_price_usd_per_1m": "0.01,0.03,0.01",
            "context_window": "1000000,262000,1000000",
            "capabilities": "chat",
            "source": "https://synthetic-manager.example/account/models",
            "source_checked_at": "2026-10-27",
        },
        follow_redirects=False,
    )
    assert "notice=provider_saved" in response.headers["location"], response.headers["location"]

    registry = read_registry()
    provider = registry["providers"]["syntheticmanager"]
    assert provider["credential_binding_name"] == SYNTHETIC
    assert provider["allowed_hosts"] == ["api.synthetic-manager.example"]
    rows = [row for row in registry["models"] if row["provider_id"] == "syntheticmanager"]
    assert [row["id"] for row in rows] == [
        "syntheticmanager/deepseek-v4.1-flash",
        "syntheticmanager/glm-5.3-flash",
        "syntheticmanager/deepseek-v4.1-flash-uncensored",
    ]
    assert rows[0]["input_price_usd_per_1m"] == 0.08 and rows[0]["output_price_usd_per_1m"] == 0.35
    assert "cached input US$0.01" in rows[0]["source"]

    # One credential for the whole Provider, proven through a real request: the
    # host's per-request scope binds handles derived from the registry, so the
    # file written by the screen is what the health surface resolves. Outside a
    # request that file is deliberately invisible — resolve_secret reads the
    # environment, not the host directory.
    health = admin.get("/api/pilot/health").json()
    states = {row["id"]: row for row in health["business14"]["providers"]}
    assert states["syntheticmanager"]["has_key"] is True
    assert states["syntheticmanager"]["registered"] is True
    listing_text = admin.get(SECRETS).text
    assert "3개 활성 / 3개" in listing_text and SYNTHETIC in listing_text

    # Registered, not routed: no tier group moved, so no customer can select it.
    groups = json.loads(host["registry"].read_text(encoding="utf-8"))["groups"]
    assert groups == {"plus": [], "pro": [], "max": []}


def test_bad_origin_and_rejected_key_are_reported_without_a_write(admin, host, monkeypatch) -> None:
    for bad in ("http://api.synthetic-manager.example/v1", "https://127.0.0.1:8789/v1",
                "https://api.synthetic-manager.example/v1?token=1"):
        response = admin.post(
            PROVIDER,
            data={
                "provider_id": f"bad-{abs(hash(bad)) % 1000}", "provider_name": "Bad",
                "base_origin": bad, "credential_binding_name": f"BAD_ORIGIN_{abs(hash(bad)) % 1000}",
                "upstream_models": "m", "source": "https://example.invalid/docs",
                "source_checked_at": "2026-10-27",
            },
            follow_redirects=False,
        )
        assert "reason=upstream_origin_invalid" in response.headers["location"], bad
    assert not (host["secrets"] / "BAD_ORIGIN_0").exists()

    import httpx

    def reject(request):
        assert request.headers["Authorization"].endswith(SECRET_VALUE)
        return httpx.Response(401, json={"error": {"type": "new_api_error"}})

    monkeypatch.setattr(
        com2_admin, "TEST_TRANSPORT", httpx.MockTransport(reject)
    )
    admin.post(SECRETS, data={"name": SYNTHETIC, "value": SECRET_VALUE})
    tested = admin.post(
        PROVIDER + "/test",
        data={"base_origin": BASE_ORIGIN, "credential_binding_name": SYNTHETIC},
        follow_redirects=False,
    )
    assert "test=key_rejected" in tested.headers["location"]
    assert SECRET_VALUE not in tested.headers["location"] + tested.text


def test_a_loopback_origin_is_refused_even_when_it_would_answer(admin, host) -> None:
    """The screen runs on the host, so localhost must not become a fetch target."""
    response = admin.post(
        PROVIDER,
        data={
            "provider_id": "loopback-attempt", "provider_name": "Loop",
            "base_origin": "https://localhost:8789/v1",
            "credential_binding_name": "LOOPBACK_ATTEMPT_KEY",
            "upstream_models": "m", "source": "https://example.invalid/docs",
            "source_checked_at": "2026-10-27",
        },
        follow_redirects=False,
    )
    assert "reason=upstream_origin_invalid" in response.headers["location"]


@pytest.mark.skipif(os.name != "posix", reason="mode bits are only meaningful on the host OS")
def test_a_written_secret_is_private_enough_for_the_reader(admin, host) -> None:
    admin.post(SECRETS, data={"name": SYNTHETIC, "value": SECRET_VALUE})
    mode = (host["secrets"] / SYNTHETIC).stat().st_mode
    assert not (mode & 0o077), oct(stat.S_IMODE(mode))


@pytest.mark.skipif(os.name != "posix", reason="mode bits are only meaningful on the host OS")
def test_a_loose_secret_directory_is_refused_not_tightened(admin, host) -> None:
    """The store reports the host's fault instead of rewriting its permissions.

    A directory every user on the machine can read would put credentials where
    other tenants look, and chmod'ing it from a web request would silently
    change the operator's host. So: refuse, explain, write nothing.
    """
    os.chmod(host["secrets"], 0o755)
    response = admin.post(
        SECRETS, data={"name": SYNTHETIC, "value": SECRET_VALUE}, follow_redirects=False
    )
    assert "reason=secret_dir_not_writable" in response.headers["location"]
    assert not (host["secrets"] / SYNTHETIC).exists()
    assert SECRET_VALUE not in admin.get(SECRETS).text


def test_settings_survive_a_restart(admin, host) -> None:
    admin.post(SECRETS, data={"name": SYNTHETIC, "value": SECRET_VALUE})
    assert SYNTHETIC in admin.get(SECRETS).text

    # A fresh application process reads the same two files off the host: nothing
    # about a registration lives in memory, so a restart changes nothing.
    from app.pilot.model_registry_file import install_models

    install_models()
    with TestClient(create_local_app()) as restarted:
        listing = restarted.get(SECRETS).text
    assert SYNTHETIC in listing and "등록됨" in listing
    assert SYNTHETIC in {
        entry["credential_binding_name"]
        for entry in read_registry()["providers"].values()
    } or SYNTHETIC in listing


def test_the_existing_gemini_path_is_untouched(admin, host) -> None:
    """Regression: this screen must not re-point a live Provider's credential."""
    from app.pilot.platform_secrets import get_platform_provider

    google = get_platform_provider("google")
    assert google is not None
    assert google.credential_binding_name == "PADIEM_B14_CREDENTIAL_05"
    assert read_registry()["providers"]["google"]["enabled"] is True
    assert read_registry()["providers"]["google"]["credential_binding_name"] == (
        "PADIEM_B14_CREDENTIAL_05"
    )
