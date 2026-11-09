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

from app.local_runtime import SECRET_DIR_ENV
from app.com2_admin_runtime import create_admin_app
from app.pilot import com2_admin, com2_secret_store
from app.pilot.model_registry_file import REGISTRY_PATH, read_registry

from _registry_values import (
    credential_binding_slot, native_wire_owner, process_catalog_restored, registry,
)

APP_ROOT = REGISTRY_PATH.parents[2]
SECRETS = "/com2/admin/secrets"
PROVIDER_NEW = "/com2/admin/providers/new"
PROVIDER = "/com2/admin/providers"
SYNTHETIC = "PADIEM_SYNTHETIC_MANAGER_API_KEY"
#: A slot-shaped name the Cloudflare deployment does not declare: the private
#: format requires the ``PADIEM_B14_CREDENTIAL_`` prefix, and a fresh Provider
#: may only take a name that is not already a Cloudflare binding.
_SYNTHETIC_BINDING = "PADIEM_B14_CREDENTIAL_99"
SECRET_VALUE = "synthetic-manager-value-9f3c1a7d"
BASE_ORIGIN = "https://api.synthetic-manager.example/v1"
#: A synthetic Provider id for the one-key/many-models screen exercise. Nothing
#: in the deployment declares it, so it stays a test-only name.
_SYNTHETIC_PROVIDER = "syntheticmanager"


class _SyntheticDocument:
    """A private-v1 document that stands where the shipped placeholder stood.

    A host used to keep its catalog in the shipped ``b14_models.json``, so the
    COM2 host fixture handed the screen a copy of that file. The document is the
    switch now (#7241 3단계), and the shipped file is a schema-shaped placeholder
    whose empty tier groups cannot be written again. The stand-in the fixture
    writes is the effective document in the same private-v1 shape, with the same
    name and parent directory as the shipped file, so the screen's read and write
    paths are the ones under test. Its identity/tier ids come from the effective
    document: nothing here is a deployment value.
    """

    @staticmethod
    def private_document(registry_file) -> dict:
        document = registry()
        model_ids = [row["id"] for row in document["models"]]
        groups = document["groups"]
        # A grade roster needs a primary, and the private format names every
        # grade the loader requires. The effective document may carry neither a
        # group's rows nor every grade name (the placeholder carries no rows at
        # all), so the names the loader requires come from the loader and a row-
        # less grade is filled from the identities the document does install.
        loader = registry_file._private_module()
        names = tuple(loader.REQUIRED_TIER_NAMES) + tuple(loader.OPTIONAL_TIER_NAMES)
        primary = next(
            (groups[name][0] for name in names
             if groups.get(name)), model_ids[0])
        tiers = {
            name: {
                "primary": groups[name][0] if groups.get(name) else primary,
                "fallback": list(groups.get(name, [])[1:]),
            }
            for name in names if name in groups or name in loader.REQUIRED_TIER_NAMES
        }
        return {
            "version": "padiem.models.private.v1",
            "comment": "#2107 host fixture: the effective document (#7241 3b)",
            "providers": {
                provider_id: {
                    "base_origin": row["base_origin"],
                    "allowed_hosts": list(row["allowed_hosts"]),
                    "credential_binding": row["credential_binding_name"],
                }
                for provider_id, row in document["providers"].items()
            },
            "models": [
                {key: (list(value) if isinstance(value, (list, tuple)) else value)
                 for key, value in row.items()}
                for row in document["models"]
            ],
            "tiers": tiers,
            "retired_models": list(document.get("retired_models") or []),
        }

def _install_document(registry_file) -> dict:
    """The effective registry in the install shape the screen reads.

    ``com2_provider_settings`` reads through ``read_registry()``, which answers
    the private document in *install* shape. The fixture derives that shape from
    the effective document, so the identity the suite reasons about is the same
    one the app answers (#7241 3b).
    """
    document = registry()
    return {
        "schema_version": 1,
        "comment": "#2107 host fixture, install shape (#7241 3b)",
        "providers": {
            provider_id: {
                "base_origin": row["base_origin"],
                "allowed_hosts": list(row["allowed_hosts"]),
                "credential_source": row["credential_source"],
                "credential_binding_name": row["credential_binding_name"],
                "enabled": row["enabled"],
            }
            for provider_id, row in document["providers"].items()
        },
        "models": [
            {key: (list(value) if isinstance(value, (list, tuple)) else value)
             for key, value in row.items()}
            for row in document["models"]
        ],
        "groups": {group: [] for group in registry_file._GROUPS},
        "retired_models": list(document.get("retired_models") or []),
    }


@pytest.fixture()
def host(tmp_path, monkeypatch):
    """A COM2-shaped host: a private secret directory and a copy of the registry.

    The document this host reads is a *copy* on the same path shape as the
    shipped file, and it is named by the required switch, so the screen writes
    through the private path it writes through in deployment. The switch itself
    is restored verbatim afterwards: clearing it would leave every later suite
    with no catalog at all (#7241 3단계).
    """
    from app.pilot import model_registry_file as registry_file

    saved_switch = {name: os.environ.get(name) for name in (
        registry_file.REGISTRY_SWITCH_ENV, registry_file.REGISTRY_OVERRIDE_ENV)}
    secret_dir = tmp_path / "secrets"
    # StateDirectory hands the service a 0700 directory it owns, and the store
    # refuses a looser one rather than quietly tightening the operator's host.
    # A default mkdir() is 0755 under the usual umask, which is exactly the
    # posture a real COM2 must never be in.
    secret_dir.mkdir(mode=0o700)
    os.chmod(secret_dir, 0o700)
    registry = tmp_path / "b14_models.json"
    shutil.copyfile(REGISTRY_PATH, registry)
    # The copy is the path shape the screen knows; its content is the host's own
    # private document, written in the private format the loader accepts.
    registry.write_text(
        json.dumps(_SyntheticDocument.private_document(registry_file),
                   ensure_ascii=False),
        encoding="utf-8")
    token = tmp_path / "admin-token"
    token.write_text("test-admin-token-" + "z" * 40, encoding="utf-8")
    token.chmod(0o600)
    monkeypatch.setenv("B14_ADMIN_TOKEN_FILE", str(token))
    monkeypatch.setenv(SECRET_DIR_ENV, str(secret_dir))
    monkeypatch.setenv("B14_REGISTRY_PATH", str(registry))
    monkeypatch.delenv(SYNTHETIC, raising=False)
    com2_admin.TEST_TRANSPORT = None
    # The screen reads the document the switch names, so the fixture switches
    # this process to the host's copy and installs it. The switch, the cached
    # snapshot and the Provider table all outlive the test, so every one of
    # them is put back — including when the test itself fails (#7241 3b).
    with process_catalog_restored():
        monkeypatch.setenv(registry_file.REGISTRY_SWITCH_ENV, str(registry))
        monkeypatch.delenv(registry_file.REGISTRY_OVERRIDE_ENV, raising=False)
        registry_file._PRIVATE_SNAPSHOT = None
        registry_file.install_models()
        try:
            yield {"secrets": secret_dir, "registry": registry}
        finally:
            # install_models() mutates the live catalog; put the host back.
            monkeypatch.delenv("B14_REGISTRY_PATH")
            for name, value in saved_switch.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
            registry_file._PRIVATE_SNAPSHOT = None
            registry_file.install_models()


class LoggedInAdmin(TestClient):
    def __init__(self):
        super().__init__(create_admin_app(), base_url="http://127.0.0.1:8781")

    def login(self):
        response = super().post("/login", data={"token": "test-admin-token-" + "z" * 40}, follow_redirects=False)
        assert response.status_code == 303

    def post(self, url, *, data=None, **kwargs):
        import re
        page = self.get(SECRETS)
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        assert csrf is not None
        return super().post(url, data={**(data or {}), "csrf_token": csrf.group(1)}, **kwargs)

@pytest.fixture()
def admin(host):
    with LoggedInAdmin() as client:
        client.login()
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
    """Same name, two different values on two hosts is the aliasing hazard.

    The reserved NAME set is the deployment's own (the Worker manifest the store
    reads), and the two names exercised are the first and the eighth slot the app
    publishes — a name is never written here (#7241 3b).
    """
    for reserved in (credential_binding_slot(1), credential_binding_slot(8)):
        response = admin.post(
            SECRETS, data={"name": reserved, "value": SECRET_VALUE}, follow_redirects=False
        )
        assert "reason=name_declared_as_cloudflare_binding" not in (
            response.headers.get("location") or "")
        # The secret store reserves only for a NEW Provider; retyping the value
        # of a slot this host already reads is the Owner's own migration path.
        assert (host["secrets"] / reserved).read_text(encoding="utf-8") == SECRET_VALUE

    blocked = admin.post(
        PROVIDER,
        data={
            "provider_id": "aliasing-attempt", "provider_name": "Alias",
            "base_origin": BASE_ORIGIN,
            "credential_binding_name": credential_binding_slot(3),
            "value": "synthetic-alias-value-1234",
            "upstream_models": "some-model", "source": "https://example.invalid/docs",
            "source_checked_at": "2026-10-27",
        },
        follow_redirects=False,
    )
    assert "reason=name_declared_as_cloudflare_binding" in blocked.headers["location"]
    assert not (host["secrets"] / credential_binding_slot(3)).exists()
    assert "aliasing-attempt" not in read_registry()["providers"]


def test_one_key_three_models_deepseek_first_and_still_unrouted(admin, host) -> None:
    # One key, three models, one Provider. Every governed slot name is already
    # declared as a Cloudflare binding, so a *new* Provider is refused that
    # name; this exercise therefore takes the suite's own undeclared name
    # through the app's settings layer, the same writer the screen calls after
    # its reserved-name check. The name and the upstream identities are test
    # inputs, never deployment values (#7241 3b).
    from app.local_runtime import create_local_app
    from app.pilot import com2_provider_settings as settings

    binding = _SYNTHETIC_BINDING
    models = [
        ("synthetic-upstream-one", 0.08, 0.35, 0.01, 1000000),
        ("synthetic-upstream-two", 0.08, 0.42, 0.03, 262000),
        ("synthetic-upstream-three", 0.08, 0.35, 0.01, 1000000),
    ]
    admin.post(SECRETS, data={"name": binding, "value": SECRET_VALUE})
    assert (host["secrets"] / binding).read_text(encoding="utf-8") == SECRET_VALUE

    ids, code = settings.save(
        provider_id=_SYNTHETIC_PROVIDER,
        base_origin=BASE_ORIGIN,
        allowed_hosts=[],
        credential_binding_name=binding,
        provider_name="Synthetic Manager",
        models=[
            {
                "upstream_model": upstream,
                "display_name": upstream,
                "capabilities": ["chat"],
                "context_window": context,
                "input_price_usd_per_1m": price_in,
                "output_price_usd_per_1m": price_out,
                "cached_input_price_usd_per_1m": cached,
                "source": "https://synthetic-manager.example/account/models",
                "source_checked_at": "2026-10-27",
            }
            for upstream, price_in, price_out, cached, context in models
        ],
    )
    assert code == settings.OK, code
    assert ids == [f"{_SYNTHETIC_PROVIDER}/{row[0]}" for row in models]

    registry = read_registry()
    provider = registry["providers"][_SYNTHETIC_PROVIDER]
    assert provider["credential_binding_name"] == binding
    assert provider["allowed_hosts"] == ["api.synthetic-manager.example"]
    rows = [
        row for row in registry["models"]
        if row["provider_id"] == _SYNTHETIC_PROVIDER
    ]
    assert [row["upstream_model"] for row in rows] == [row[0] for row in models]
    first = rows[0]
    assert first["input_price_usd_per_1m"] == models[0][1]
    assert first["output_price_usd_per_1m"] == models[0][2]
    # The registry carries one input and one output price, so the cached figure
    # is preserved in the provenance field rather than dropped.
    assert f"cached input US${models[0][3]}" in first["source"]

    # One credential for the whole Provider, proven through a real request: the
    # host's per-request scope binds handles derived from the registry, so the
    # file written by the screen is what the host resolves. Outside a request
    # that file is deliberately invisible.
    with TestClient(create_local_app()) as main_client:
        health = main_client.get("/api/pilot/admin/health").json()
    states = {row["id"]: row for row in health["business14"]["providers"]}
    assert states[_SYNTHETIC_PROVIDER]["has_key"] is True
    assert states[_SYNTHETIC_PROVIDER]["registered"] is True
    listing_text = admin.get(SECRETS).text
    assert binding in listing_text
    assert f"{len(models)}개 활성 / {len(models)}개" in listing_text

    # Registered, not routed: the write appended a Provider and its rows, it
    # never re-decided a grade roster, so no customer can select the new models.
    tiers = json.loads(host["registry"].read_text(encoding="utf-8"))["tiers"]
    installed = {row["id"] for row in registry["models"]}
    new_ids = {row["id"] for row in rows}
    for entry in tiers.values():
        assert entry["primary"] in installed
        assert entry["primary"] not in new_ids
        assert not new_ids & set(entry["fallback"])


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
    with LoggedInAdmin() as restarted:
        restarted.login()
        listing = restarted.get(SECRETS).text
    assert SYNTHETIC in listing and "등록됨" in listing
    assert SYNTHETIC in {
        entry["credential_binding_name"]
        for entry in read_registry()["providers"].values()
    } or SYNTHETIC in listing


def test_the_existing_gemini_path_is_untouched(admin, host) -> None:
    """Regression: this screen must not re-point a live Provider's credential.

    The Provider under test is the one the native-wire adapter itself serves —
    read from the adapter, not named here — and the slot it must keep is the
    one the effective document declares for it (#7241 3b).
    """
    from app.pilot.platform_secrets import get_platform_provider

    provider_id = native_wire_owner()
    live = get_platform_provider(provider_id)
    if live is None or provider_id not in registry()["providers"]:
        pytest.skip(
            "no owner registry document serves the native-wire Provider "
            "(placeholder fixture)")
    declared = registry()["providers"][provider_id]
    assert declared["enabled"] is True
    assert live.credential_binding_name == declared["credential_binding_name"]
