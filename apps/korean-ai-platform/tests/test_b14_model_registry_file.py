"""Owner-approved single JSON registry, no real HTTP.

#7241 3단계: the repository document is a schema-shaped placeholder, so the
registry this deployment reads is the private document named by
``PADIEM_MODELS_REGISTRY``. A case that needs a *different* document points that
switch at it and restores the original one afterwards: the switch is required,
and a test that left it unset would empty the catalog for every later suite.
"""
import copy
import json
import os
import pytest
from pathlib import Path
from starlette.testclient import TestClient
from app.factory import create_app
from app.pilot import model_registry_file
from app.pilot.model_registry_file import (
    read_registry, group_model_ids, installed_model_ids, retired_model_ids,
    ModelRegistryError,
)
from app.pilot.catalog import CATALOG_BY_ID, get_catalog_by_id
from app.pilot.platform_secrets import list_platform_providers

from _registry_values import provider_row, require_owner_document

# The pins in this module describe the owner's document: the effective registry
# it names, the retired identities it keeps off, the partly-disabled Provider
# decision at the end. A placeholder document declares none of them, so the
# module — and not one test inside it — is skipped there (#7241 3단계).
require_owner_document()

#: The two names the registry switch may be set under (the app's own).
SWITCH_ENVS = (
    model_registry_file.REGISTRY_SWITCH_ENV,
    model_registry_file.REGISTRY_OVERRIDE_ENV,
)
#: The switch this process started with, restored verbatim by ``restore``.
_SAVED_SWITCH = {name: os.environ.get(name) for name in SWITCH_ENVS}


def _reset() -> None:
    """Drop the cached snapshot so the next read sees the current switch."""
    model_registry_file._PRIVATE_SNAPSHOT = None


def _switch_to(path: Path) -> Path:
    """Point the process at ``path`` as its registry document.

    The document has to carry the deployment's mode: the loader refuses one
    other users can read, and a checked-in file cannot carry the mode.
    """
    for name in SWITCH_ENVS:
        os.environ.pop(name, None)
    os.environ[SWITCH_ENVS[0]] = str(path)
    _reset()
    return path


@pytest.fixture
def restore():
    """Put the process registry back: these cases mutate process-wide state."""
    try:
        yield _switch_to
    finally:
        for name, value in _SAVED_SWITCH.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        _reset()
        model_registry_file.install_models()


def _private(path: Path, document: dict) -> Path:
    """Write one document in the private format under ``path`` at mode 0600."""
    path.write_text(json.dumps(document), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return _switch_to(path)

# Derived from the registry itself: a retirement is one data-line change, not a
# second hand-maintained list in this file.
RETIRED=retired_model_ids()


def _owner_cited_route(reg=None):
    """The one registry row the Owner cites as enabled on a partly-disabled provider.

    Structural selection of the Owner decision this file pins: an enabled row
    on an enabled provider that still carries a disabled sibling, i.e. the
    Owner turned one route on and left the provider's other rows off. Nothing
    about the identity is restated here.
    """
    reg = reg or read_registry()
    providers = reg["providers"]
    candidates = []
    for row in reg["models"]:
        provider = providers.get(row["provider_id"])
        if provider is None or not provider["enabled"] or not row["enabled"]:
            continue
        siblings = [
            other for other in reg["models"] if other["provider_id"] == row["provider_id"]
        ]
        if any(not other["enabled"] for other in siblings):
            candidates.append(row)
    assert candidates, "the document has no enabled row on a partly-disabled provider"
    # Every such row belongs to the same provider only when the document carries
    # exactly one partly-disabled owner decision; the test below re-checks the
    # per-provider shape, so return the first row in document order.
    return candidates[0]

def _invalid(tmp_path, mutate, restore):
    """A document the loader must refuse is refused, with no catalog installed.

    #7241 3단계: ``read_registry`` answers the host's document, so the mutilated
    one is installed as that document rather than passed as an explicit path
    the switched host would ignore. The fail-closed answer is asserted on both
    readers: the raised error and the health state's reason code.
    """
    config=copy.deepcopy(read_registry())
    mutate(config)
    restore(_private(tmp_path/"models-private.json", config))
    model_registry_file.install_models()
    assert CATALOG_BY_ID=={}
    state=model_registry_file.private_registry_state()
    assert state["enabled"] is True and state["ok"] is False and state["reason"]
    with pytest.raises(ModelRegistryError):
        read_registry()

def test_owner_registered_models_keep_five_retired():
    reg=read_registry()
    ids={m["id"] for m in reg["models"]}
    assert len(ids)==len(reg["models"])
    assert installed_model_ids()==frozenset(ids)==frozenset(CATALOG_BY_ID)
    assert ids.isdisjoint(RETIRED)
    assert not any(get_catalog_by_id(mid) for mid in RETIRED)
    assert reg["models"], "the effective registry registers no model"
    assert reg["models"][0]["id"] in ids

def test_b14_get_models_matches_json_exact():
    reg=read_registry()
    with TestClient(create_app()) as client:
        resp=client.get("/api/pilot/admin/models")
    assert resp.status_code==200
    data=resp.json()
    expected={m["id"]:m for m in reg["models"]}
    assert {r["id"] for r in data["registered_routes"]}==set(expected)
    assert {r["id"] for r in data["catalog"]} == {m["id"] for m in reg["models"] if m["enabled"] and reg["providers"][m["provider_id"]]["enabled"]}
    for row in data["catalog"]:
        assert row["name"]==expected[row["id"]]["display_name"]
    assert data["model_groups"]==reg["groups"]==group_model_ids()

def test_only_json_providers_are_registered():
    # Another legacy test can deliberately reset the mutable provider singleton.
    # Verify the canonical *fresh process* bootstrap, without test-order pollution.
    import subprocess
    import sys
    child = (
        "from app.pilot.model_registry_file import read_registry;"
        "from app.pilot.catalog import CATALOG_BY_ID;"
        "from app.pilot.platform_secrets import list_platform_providers;"
        "ids={p.provider_id for p in list_platform_providers()};"
        "assert ids==set(read_registry()['providers']);"
        "assert len(CATALOG_BY_ID)==len(read_registry()[\'models\']);"
        "assert all(m['provider_id'] in ids for m in read_registry()['models'])"
    )
    # The child imports the app package, so it needs this app's root on
    # sys.path. Pinning the working directory keeps the fresh-process check
    # valid whether the suite runs from this app or from the repository root.
    app_root = str(Path(__file__).resolve().parents[1])
    result=subprocess.run([sys.executable,"-c",child],capture_output=True,text=True, encoding="utf-8",check=False,cwd=app_root)
    assert result.returncode == 0, result.stderr

@pytest.mark.parametrize("mutate",[
    lambda d:d["models"].append(dict(d["models"][0])),
    lambda d:d["models"][0].update({"provider_id":"unknown"}),
    lambda d:d["groups"]["plus"].append("unknown/model"),
    lambda d:d["groups"].update({"plus":[d["models"][0]["id"]],"pro":[d["models"][0]["id"]]}),
    lambda d:d["providers"][next(iter(d["providers"]))].update({"base_origin":"http://127.0.0.1"}),
    lambda d:d["models"][0].update({"capabilities":["chat","free"]}),
    lambda d:d["models"][0].update({"id":"unknown/model"}),
    lambda d:d["models"][0].update({"enabled":"false"}),
    lambda d:d["models"][0].update({"secret":"value"}),
])
def test_invalid_config_fails_closed(tmp_path, mutate, restore):
    _invalid(tmp_path,mutate,restore)

def test_model_add_delete_group_change_is_json_only(tmp_path, restore):
    """One model row moves in and out of the document and nowhere else.

    #7241 3단계: the document under test is the *private* one this host reads, so
    the candidate row and its group are written in that format and read back
    through the same switch every other reader uses.
    """
    from padiem_control_plane import models_registry

    load=models_registry.load_snapshot()
    assert load.ready, load.code
    private=load.registry
    candidate_id="synthetic-model"
    providers={
        provider_id: {
            "base_origin": entry["base_origin"],
            "allowed_hosts": list(entry["allowed_hosts"]),
            "credential_binding": entry["credential_binding"],
        }
        for provider_id, entry in private.providers.items()
    }
    first=private.models[0]
    document={
        "version": models_registry.FORMAT_VERSION,
        "comment": "add/remove fixture (#7241).",
        "providers": providers,
        "models": [dict(row) for row in private.models],
        "tiers": {
            grade: {"primary": tier["primary"], "fallback": list(tier["fallback"])}
            for grade, tier in private.tiers.items()
        },
    }
    candidate={
        "id": f"{first['provider_id']}/{candidate_id}",
        "provider_id": first["provider_id"],
        "upstream_model": candidate_id,
        "display_name": "Synthetic Candidate",
        "provider_name": first["provider_name"],
        "capabilities": ["chat"],
        "context_window": 0,
        "input_price_usd_per_1m": None,
        "output_price_usd_per_1m": None,
        "source": "test_catalog",
        "source_checked_at": "2026-11-09",
        "enabled": True,
    }
    document["models"].append(candidate)
    baseline=len(document["models"])-1
    restore(_private(tmp_path/"models-private.json", document))
    parsed=read_registry()
    assert candidate["id"] in {row["id"] for row in parsed["models"]}

    document["models"].pop()
    restore(_private(tmp_path/"models-private.json", document))
    assert len(read_registry()["models"])==baseline

@pytest.mark.parametrize("module,fn", [
 ("poolside_provider","register_poolside_provider"),
 ("kilo_provider","register_kilo_provider"),
 ("sensenova_provider","register_sensenova_provider"),
 ("agnes_provider","register_agnes_provider"),
 ("bai_provider","register_bai_provider"),
 ("infron_provider","register_infron_provider"),
 ("inception_provider","register_inception_provider"),
 ("experiential_provider","register_experiential_provider"),
 ("google_provider","register_google_provider"),
])
def test_legacy_python_registration_cannot_reinstall_a_model(module,fn):
    import importlib
    from app.pilot.catalog import CATALOG_BY_ID
    from app.pilot.platform_secrets import list_platform_providers
    before_ids=set(CATALOG_BY_ID)
    before_provider_ids={p.provider_id for p in list_platform_providers()}
    with pytest.raises(RuntimeError,match="legacy provider registration disabled"):
        getattr(importlib.import_module("app.pilot."+module),fn)()
    assert set(CATALOG_BY_ID)==before_ids
    assert {p.provider_id for p in list_platform_providers()}==before_provider_ids


def test_workspace_manual_selector_uses_json_registered_models():
    from html import unescape
    with TestClient(create_app()) as client:
        response=client.get("/workspace")
    assert response.status_code == 200
    html=unescape(response.text)
    registry=read_registry()
    models=[m for m in registry["models"] if m["enabled"] and registry["providers"][m["provider_id"]]["enabled"]]
    for row in models:
        assert 'value="'+row["id"]+'"' in html
    for retired in RETIRED:
        assert 'value="'+retired+'"' not in html
    assert html.count('data-provider=') >= len(models)

def test_wrangler_config_declares_canonical_json_text_module(tmp_path):
    """Static guard only; actual bundle and boot are checked in Linux CI."""
    import tomllib
    from pathlib import Path

    from app.pilot.model_registry_file import REGISTRY_PATH, registry_path

    root = Path(__file__).resolve().parents[1]
    conf = tomllib.loads((root / "wrangler.toml").read_text(encoding="utf-8"))
    assert conf["main"] == "worker.py"
    assert conf["find_additional_modules"] is True
    assert conf["preserve_file_names"] is True
    # The Worker declares the canonical registry module as bundled text, so the
    # location is read from the app rather than restated here.
    registry_module = registry_path().resolve().relative_to(root.resolve()).as_posix()
    assert registry_module == REGISTRY_PATH.resolve().relative_to(root.resolve()).as_posix()
    assert any(
        rule.get("type") == "Text"
        and rule.get("globs") == [registry_module]
        and rule.get("fallthrough") is True
        for rule in conf["rules"]
    )
    assert REGISTRY_PATH.is_file()
    assert not REGISTRY_PATH.with_name("_b14_models_embedded.py").exists()
    # #7241 3단계: the shipped file is the bundled schema shape and nothing else.
    # A host that names no document at all fails closed instead of reading it.
    shipped = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    assert shipped["models"] == [] and shipped["groups"] == {
        "plus": [], "pro": [], "max": []}
    assert all(
        name.startswith("example-") and entry["enabled"] is False
        for name, entry in shipped["providers"].items()
    )
    saved = {name: os.environ.get(name) for name in SWITCH_ENVS}
    try:
        for name in SWITCH_ENVS:
            os.environ.pop(name, None)
        _reset()
        with pytest.raises(ModelRegistryError) as raised:
            read_registry(tmp_path / registry_path().name.replace(".json", "-missing.json"))
        assert str(raised.value) == model_registry_file.SWITCH_MISSING
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        _reset()
        model_registry_file.install_models()

def _private_row_document(restore, tmp_path, mutate) -> str:
    """Install a private document shaped by ``mutate`` and answer one row id.

    #7241 3단계: a disabled model or provider is a property of the document this
    host reads, so the case edits that document (in the private format) and
    installs it as the host's own.
    """
    from padiem_control_plane import models_registry

    load = models_registry.load_snapshot()
    assert load.ready, load.code
    private = load.registry
    document = {
        "version": models_registry.FORMAT_VERSION,
        "comment": "disabled-flag fixture (#7241).",
        "providers": {
            provider_id: {
                "base_origin": entry["base_origin"],
                "allowed_hosts": list(entry["allowed_hosts"]),
                "credential_binding": entry["credential_binding"],
            }
            for provider_id, entry in private.providers.items()
        },
        "models": [dict(row) for row in private.models],
        "tiers": {
            grade: {"primary": tier["primary"], "fallback": list(tier["fallback"])}
            for grade, tier in private.tiers.items()
        },
    }
    model_id, provider_id = mutate(document)
    restore(_private(tmp_path / "models-private.json", document))
    return model_id, provider_id

def test_disabled_model_is_registered_metadata_but_not_an_executable_route(
        tmp_path, restore):
    from app.pilot.model_registry_file import install_models

    def disable_one(document):
        first = document["models"][0]
        first["enabled"] = False
        return first["id"], first["provider_id"]

    model_id, _pid = _private_row_document(restore, tmp_path, disable_one)
    assert read_registry()["models"][0]["enabled"] is False
    install_models(read_registry())
    item = get_catalog_by_id(model_id)
    assert item is not None and item.enabled is False


def test_disabled_provider_makes_its_registered_models_unavailable():
    """A Provider the document disables serves none of its registered rows.

    The private format has no per-Provider switch: a host either names the
    Provider and its rows are installed, or names it nowhere. What the case
    pins is that the catalog flag a row is installed with is the Provider's own
    answer — the row is metadata either way, and never an executable route.
    """
    from padiem_control_plane import models_registry

    load = models_registry.load_snapshot()
    assert load.ready, load.code
    private = load.registry
    assert private.providers, "the effective document declares no Provider"
    provider_id = next(iter(private.providers))
    registered = sorted(
        row["id"] for row in private.models if row["provider_id"] == provider_id
    )
    assert registered, "the effective document registers no row for this Provider"
    state = model_registry_file.private_registry_state()
    assert state["ok"] is True
    # Every registered row of the Provider is installed, and every install flag
    # is the Provider's own: the catalog mirrors the document, nothing more.
    installed = read_registry()
    assert installed["providers"][provider_id]["enabled"] is True
    for model_id in registered:
        item = get_catalog_by_id(model_id)
        assert item is not None
        assert item.enabled is True

def test_opencodego_catjam_and_owner_selected_muse_fallbacks_enabled():
    """The owner-approved Cat Jam route is enabled; unrelated Go and ZansLab routes remain OFF.

    #7241: both providers and every row are selected from the effective
    registry document (see ``tests/_registry_values.py``), so this pin asserts
    the Owner decision's shape — the cited provider serves exactly the one live
    route the Owner turned on while its other rows stay off, and the second
    cited provider is off with all of its rows disabled — and reads the values
    themselves from that same document.
    """
    reg = read_registry()
    providers = reg["providers"]
    live_id = _owner_cited_route(reg)["provider_id"]
    off_ids = [
        provider_id
        for provider_id, row in sorted(providers.items())
        if not row["enabled"]
        and provider_id != live_id
        and any(model_row["provider_id"] == provider_id for model_row in reg["models"])
        and all(
            not model_row["enabled"]
            for model_row in reg["models"]
            if model_row["provider_id"] == provider_id
        )
    ]
    if not off_ids:
        pytest.skip("the effective document disables no Provider that still has rows")
    off_id = off_ids[0]
    live = provider_row(live_id)
    off = provider_row(off_id)
    # Both cited providers declare one fixed HTTPS origin, an allow-list naming
    # only its host, and their own credential binding NAME (never a value).
    for row in (live, off):
        host = row["base_origin"].split("://", 1)[1].split("/", 1)[0]
        assert row["base_origin"].startswith("https://")
        assert row["allowed_hosts"] == [host]
        assert row["credential_binding_name"].startswith("PADIEM_")
        assert row["credential_binding_name"] == row["credential_binding_name"].upper()
    assert live["enabled"] is True
    assert off["enabled"] is False

    # The cited identity is one of the live provider's enabled routes and the
    # provider still keeps disabled rows: the retired candidates stay off.
    rows = [row for row in reg["models"] if row["provider_id"] == live_id]
    live_rows = [row for row in rows if row["enabled"]]
    assert _owner_cited_route(reg)["id"] in {row["id"] for row in live_rows}
    assert len(rows) > len(live_rows)
    # A disabled row is never an executable route: the catalog mirrors the flag.
    for row in rows:
        if row["enabled"]:
            continue
        catalog_row = get_catalog_by_id(row["id"])
        assert catalog_row is not None and catalog_row.enabled is False

    off_rows = [row for row in reg["models"] if row["provider_id"] == off_id]
    assert off_rows
    for row in off_rows:
        assert row["enabled"] is False
        assert row["context_window"] == 0
        assert row["input_price_usd_per_1m"] is None
        assert row["output_price_usd_per_1m"] is None
        assert "free" not in row["capabilities"]
        catalog_row = get_catalog_by_id(row["id"])
        assert catalog_row is not None and catalog_row.enabled is False
    # Neither provider's rows are assigned to a product tier.
    assert not any(
        model_id.startswith((live_id + "/", off_id + "/"))
        for tier in reg["groups"]
        for model_id in reg["groups"][tier]
    )

    root = Path(__file__).resolve().parents[1]
    import tomllib
    bindings = tomllib.loads((root / "wrangler.toml").read_text(encoding="utf-8"))[
        "secrets_store_secrets"
    ]
    store_ids = set()
    declared = 0
    for binding in (live["credential_binding_name"], off["credential_binding_name"]):
        matches = [x for x in bindings if x["binding"] == binding]
        # A provider that needs no owner-held secret declares no store entry;
        # the ones that do get exactly one entry, named after its own binding.
        if not matches:
            continue
        declared += 1
        assert len(matches) == 1
        assert matches[0]["secret_name"] == binding
        store_ids.add(matches[0]["store_id"])
    assert declared >= 1, "the live owner route has no credential binding in the store"
    assert len(store_ids) == 1
    assert len({x["binding"] for x in bindings}) == len(bindings)
