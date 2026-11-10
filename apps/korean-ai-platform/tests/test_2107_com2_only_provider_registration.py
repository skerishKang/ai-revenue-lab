"""#2107 a new Provider is onboarded by its credential NAME and its model rows.

Owner decision: an existing Cloudflare Secret stays as it is, a new Provider's
key is typed on COM2 under the name the registry declares, and no duplicate key
is minted. That only holds if nothing else has to change, so this pins the three
claims that make it true: the registry is the sole source of credential names,
the COM2 host resolves a name that has no Cloudflare binding, and the Worker
still fails closed for that same name instead of borrowing another Provider's
credential.
"""

from __future__ import annotations

import ast
import json
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.local_runtime import SECRET_DIR_ENV, FileOrEnvSecret
from app.pilot import model_registry_file
from app.pilot.model_registry_file import (
    credential_binding_names, read_registry,
)
from app.pilot.platform_secrets import (
    CredentialSource, PlatformProviderSpec, resolve_secret,
)
from app.pilot.worker_env import (
    bind_request_env, collect_request_bindings, load_request_secret,
    reset_request_env, secret_status,
)
from padiem_control_plane import models_registry

from _registry_values import process_catalog_restored

WORKER_SRC = (APP_ROOT / "worker.py").read_text(encoding="utf-8")
#: A credential NAME in the private document's own naming shape (the loader
#: owns that rule), for a Provider nothing has ever registered (#7241 3단계).
#: No index of the deployment's slots is reused, so the name is unused.
NEW_NAME = models_registry._CREDENTIAL_BINDING_PREFIX + "907"
NEW_ORIGIN = "https://api.synthetic-new.example/v1"
#: The two names the registry switch may be set under (the app's own).
SWITCH_ENVS = (
    model_registry_file.REGISTRY_SWITCH_ENV,
    model_registry_file.REGISTRY_OVERRIDE_ENV,
)
#: The switch this process started with: no test may leave the process without
#: a catalog, so it is restored verbatim (#7241 3단계).
_SAVED = {name: os.environ.get(name) for name in SWITCH_ENVS}


def spec_from(provider_id: str, entry: dict) -> PlatformProviderSpec:
    """The same spec the catalog installs from, built without import order."""
    return PlatformProviderSpec(
        provider_id=provider_id,
        credential_source=CredentialSource(entry["credential_source"]),
        credential_binding_name=entry["credential_binding_name"],
        base_origin=entry["base_origin"],
        allowed_hosts=tuple(entry["allowed_hosts"]),
        enabled=entry["enabled"],
    )


def new_provider_spec() -> PlatformProviderSpec:
    return PlatformProviderSpec(
        provider_id="synthetic-new",
        credential_source=CredentialSource.PLATFORM_SECRET,
        credential_binding_name=NEW_NAME,
        base_origin=NEW_ORIGIN,
        allowed_hosts=("api.synthetic-new.example",),
    )


def registry_with_new_provider(tmp_path: Path) -> Path:
    """The current registry plus one Provider no entrypoint has ever heard of.

    #7241 3단계: the composed document is returned in the *private* format the
    host actually reads (``PADIEM_MODELS_REGISTRY``), so a caller that reads it
    back goes through the same loader as the deployment. Its model identity is
    derived from the new Provider's own id.
    """
    from padiem_control_plane import models_registry

    load = models_registry.load_snapshot()
    assert load.ready, load.code
    private = load.registry
    providers = {
        provider_id: {
            "base_origin": entry["base_origin"],
            "allowed_hosts": list(entry["allowed_hosts"]),
            "credential_binding": entry["credential_binding"],
        }
        for provider_id, entry in private.providers.items()
    }
    providers["synthetic-new"] = {
        "base_origin": NEW_ORIGIN,
        "allowed_hosts": ["api.synthetic-new.example"],
        "credential_binding": NEW_NAME,
    }
    probe_id = "synthetic-new/probe-model"
    models = [dict(row) for row in private.models]
    models.append({
        "id": probe_id,
        "provider_id": "synthetic-new",
        "upstream_model": "probe-model",
        "display_name": "Synthetic Probe",
        "provider_name": "Synthetic New",
        "capabilities": ["chat"],
        "context_window": 0,
        "input_price_usd_per_1m": None,
        "output_price_usd_per_1m": None,
        "source": f"{NEW_ORIGIN}/docs",
        "source_checked_at": "2026-10-27",
        "enabled": True,
    })
    document = {
        "version": models_registry.FORMAT_VERSION,
        "comment": "Synthetic Provider onboarding fixture (#2107).",
        "providers": providers,
        "models": models,
        "tiers": {
            grade: {"primary": tier["primary"], "fallback": list(tier["fallback"])}
            for grade, tier in private.tiers.items()
        },
    }
    # Refuse to write a document the host would refuse to read.
    models_registry.validate_document(document)
    path = tmp_path / "models-private.json"
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    path.chmod(0o600)
    return path


@pytest.fixture()
def switched_to(tmp_path):
    """Read the registry this deployment would read, swapping the document.

    #7241 3단계: ``read_registry`` answers the host's document, so a case that
    needs a *different* document points the process switch at it. The switch
    this process started with is restored verbatim and the catalog reinstalled,
    because leaving an empty one behind would fail every later suite.
    """
    def _swap(path: Path):
        for name in SWITCH_ENVS:
            os.environ.pop(name, None)
        os.environ[SWITCH_ENVS[0]] = str(path)
        model_registry_file._PRIVATE_SNAPSHOT = None

    with process_catalog_restored():
        try:
            yield _swap
        finally:
            for name, value in _SAVED.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
            model_registry_file._PRIVATE_SNAPSHOT = None
            model_registry_file.install_models()


def _worker_env_keys(registry_path: Path | None = None) -> set[str]:
    """Evaluate worker.py's own _ENV_KEYS expression instead of reimplementing it.

    A hand-written union here would still pass when the entrypoint stopped
    unioning, which is the exact regression this file must catch. Passing a
    registry path answers the owner's question: what the Worker collects once
    the new Provider exists in the JSON and in nowhere else.
    """
    reader = credential_binding_names
    if registry_path is not None:
        def reader():  # type: ignore[no-redef]
            return credential_binding_names(registry_path)

    scope: dict[str, object] = {}
    globals_ = {"credential_binding_names": reader, "frozenset": frozenset}
    for node in ast.parse(WORKER_SRC).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name)
            and target.id in {"_FIXED_ENV_KEYS", "_ENV_KEYS"}
            for target in node.targets
        ):
            exec(compile(ast.Module(body=[node], type_ignores=[]), "worker.py", "exec"),
                 globals_, scope)
    assert "_ENV_KEYS" in scope, "worker.py no longer defines a request scope"
    return set(scope["_ENV_KEYS"])


def test_the_registry_is_the_only_source_of_a_credential_name(tmp_path, switched_to) -> None:
    """Adding a Provider reaches the Worker scope without editing either file."""
    assert NEW_NAME not in credential_binding_names()
    assert NEW_NAME not in _worker_env_keys()
    assert NEW_NAME not in WORKER_SRC

    switched_to(registry_with_new_provider(tmp_path))
    added = credential_binding_names()
    assert NEW_NAME in added
    # The entrypoint file is untouched by that edit, and its own expression
    # already collects the name it has never seen.
    assert NEW_NAME in _worker_env_keys()


async def test_com2_resolves_a_name_with_no_cloudflare_binding(tmp_path, monkeypatch) -> None:
    """The value typed on the host is what the registry name reads back."""
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir()
    handle = secret_dir / NEW_NAME
    handle.write_text("  synthetic_host_only_value\n", encoding="utf-8")
    os.chmod(handle, stat.S_IRUSR | stat.S_IWUSR)
    monkeypatch.setenv(SECRET_DIR_ENV, str(secret_dir))
    monkeypatch.delenv(NEW_NAME, raising=False)

    assert await FileOrEnvSecret(NEW_NAME).get() == "synthetic_host_only_value"


async def test_the_worker_fails_closed_for_that_name_and_never_borrows(
    tmp_path, switched_to,
) -> None:
    """An unbound name is absent from the scope; a peer key cannot fill it."""
    peer_id, peer_entry = next(
        (pid, entry)
        for pid, entry in read_registry()["providers"].items()
        if entry["credential_source"] == "platform_secret"
        and entry["credential_binding_name"] != NEW_NAME
    )
    peer_name = peer_entry["credential_binding_name"]
    # The scope after the Provider is registered in the JSON, on a deployment
    # that has no such binding: the name is collected, resolves to nothing.
    switched_to(registry_with_new_provider(tmp_path))
    scope = _worker_env_keys()
    assert peer_name in scope and NEW_NAME in scope

    async def peer_read() -> str:
        return "synthetic_peer_key"

    collected = collect_request_bindings(
        SimpleNamespace(**{peer_name: SimpleNamespace(get=peer_read)}), scope
    )
    assert peer_name in collected and NEW_NAME not in collected

    token = bind_request_env(collected)
    try:
        await load_request_secret(peer_name)
        await load_request_secret(NEW_NAME)
        assert resolve_secret(spec_from(peer_id, peer_entry)) == "synthetic_peer_key"
        assert resolve_secret(new_provider_spec()) == ""
        # The posture an operator sees on this deployment for a host-only key.
        assert secret_status(NEW_NAME) == "missing"
    finally:
        reset_request_env(token)
