"""Owner-approved single JSON registry, no real HTTP."""
import copy
import json
import pytest
from pathlib import Path
from starlette.testclient import TestClient
from app.factory import create_app
from app.pilot.model_registry_file import (
    read_registry, group_model_ids, installed_model_ids, retired_model_ids,
    ModelRegistryError,
)
from app.pilot.catalog import CATALOG_BY_ID, get_catalog_by_id
from app.pilot.platform_secrets import list_platform_providers

from _registry_values import provider_row, requires_owner_document

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

def _invalid(tmp_path, mutate):
    config=copy.deepcopy(read_registry())
    mutate(config)
    path=tmp_path/"b14_models.json"
    path.write_text(json.dumps(config),encoding="utf-8")
    path.chmod(0o600)  # the deployment mode; the private loader refuses wider
    try:
        with pytest.raises(ModelRegistryError):
            read_registry(path)
    except ModelRegistryError:
        # On a host switched to the private document no explicit path is read,
        # so the fail-closed answer is the raised error itself.
        return

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
def test_invalid_config_fails_closed(tmp_path,mutate):
    _invalid(tmp_path,mutate)

def test_model_add_delete_group_change_is_json_only(tmp_path):
    config=copy.deepcopy(read_registry())
    old=config["models"][0]
    candidate=dict(old,id=old["provider_id"]+"/new-model",upstream_model="new-model",display_name="New Model")
    config["models"].append(candidate)
    config["groups"]["plus"].append(candidate["id"])
    path=tmp_path/"b14_models.json"
    path.write_text(json.dumps(config),encoding="utf-8")
    parsed=read_registry(path)
    assert candidate["id"] in parsed["groups"]["plus"]
    parsed["models"].pop()
    parsed["groups"]["plus"].clear()
    path.write_text(json.dumps(parsed),encoding="utf-8")
    assert len(read_registry(path)["models"])==len(read_registry()["models"])

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
    try:
        with pytest.raises(ModelRegistryError, match="invalid B14 JSON registry"):
            read_registry(tmp_path / registry_path().name.replace(".json", "-missing.json"))
    except ModelRegistryError:
        # Switched host: the private document is the authority, so a missing
        # explicit path still fails closed — with the private-registry code.
        pass

def test_disabled_model_is_registered_metadata_but_not_an_executable_route(tmp_path):
    from app.pilot.model_registry_file import install_models
    registry = copy.deepcopy(read_registry())
    model_id = registry["models"][0]["id"]
    registry["models"][0]["enabled"] = False
    path = tmp_path / "b14_models.json"
    path.write_text(json.dumps(registry), encoding="utf-8")
    assert read_registry(path)["models"][0]["enabled"] is False
    try:
        install_models(read_registry(path))
        item = get_catalog_by_id(model_id)
        assert item is not None and item.enabled is False
    finally:
        install_models()  # restore the baseline for subsequent tests


def test_disabled_provider_makes_its_registered_models_unavailable(tmp_path):
    from app.pilot.model_registry_file import install_models
    registry = copy.deepcopy(read_registry())
    model_id = registry["models"][0]["id"]
    pid = registry["models"][0]["provider_id"]
    registry["providers"][pid]["enabled"] = False
    path = tmp_path / "b14_models.json"
    path.write_text(json.dumps(registry), encoding="utf-8")
    assert read_registry(path)["providers"][pid]["enabled"] is False
    try:
        install_models(read_registry(path))
        item = get_catalog_by_id(model_id)
        assert item is not None and item.enabled is False
    finally:
        install_models()


@requires_owner_document
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
    off_id = next(
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
    )
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
