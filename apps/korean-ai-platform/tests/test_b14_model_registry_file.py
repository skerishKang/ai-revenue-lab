"""Owner-approved single JSON registry, no real HTTP."""
import copy
import json
import pytest
from starlette.testclient import TestClient
from app.factory import create_app
from app.pilot.model_registry_file import read_registry, group_model_ids, installed_model_ids, ModelRegistryError
from app.pilot.catalog import CATALOG_BY_ID, get_catalog_by_id
from app.pilot.platform_secrets import list_platform_providers

RETIRED=frozenset({
 "b-ai/qwen3.8-flash","experiential/gpt-5.6-luna","infron/motif/motif-3",
 "kilo/nvidia-nemotron-3-ultra-550b-a55b-free","kilo/poolside-laguna-s-2.1-free"
})

def _invalid(tmp_path, mutate):
    config=copy.deepcopy(read_registry())
    mutate(config)
    path=tmp_path/"b14_models.json"
    path.write_text(json.dumps(config),encoding="utf-8")
    with pytest.raises(ModelRegistryError):
        read_registry(path)

def test_owner_registered_models_keep_five_retired():
    reg=read_registry()
    ids={m["id"] for m in reg["models"]}
    assert len(ids)==len(reg["models"])
    assert installed_model_ids()==frozenset(ids)==frozenset(CATALOG_BY_ID)
    assert ids.isdisjoint(RETIRED)
    assert not any(get_catalog_by_id(mid) for mid in RETIRED)
    assert "poolside/laguna-s-2.1" in ids

def test_b14_get_models_matches_json_exact():
    reg=read_registry()
    with TestClient(create_app()) as client:
        resp=client.get("/api/pilot/models")
    assert resp.status_code==200
    data=resp.json()
    expected={m["id"]:m for m in reg["models"]}
    assert {r["id"] for r in data["registered_routes"]}==set(expected)
    assert {r["id"] for r in data["catalog"]} == {m["id"] for m in reg["models"] if m["enabled"] and reg["providers"][m["provider_id"]]["enabled"]}
    for row in data["catalog"]:
        assert row["name"]==expected[row["id"]]["display_name"]
    assert data["model_groups"]==reg["groups"]==group_model_ids()
    assert "b14/auto" not in expected

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
        "assert ids.isdisjoint({'kilo','b-ai','infron'});"
        "assert 'experiential' in ids;"
        "assert len(CATALOG_BY_ID)==len(read_registry()[\'models\'])"
    )
    result=subprocess.run([sys.executable,"-c",child],capture_output=True,text=True,check=False)
    assert result.returncode == 0, result.stderr

@pytest.mark.parametrize("mutate",[
    lambda d:d["models"].append(dict(d["models"][0])),
    lambda d:d["models"][0].update({"provider_id":"unknown"}),
    lambda d:d["groups"]["plus"].append("unknown/model"),
    lambda d:d["groups"].update({"plus":[d["models"][0]["id"]],"pro":[d["models"][0]["id"]]}),
    lambda d:d["providers"][next(iter(d["providers"]))].update({"base_origin":"http://127.0.0.1"}),
    lambda d:d["models"][0].update({"capabilities":["chat","free"]}),
    lambda d:d["models"][0].update({"id":"b14/auto"}),
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
 ("atria_provider","register_atria_provider"),
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

    root = Path(__file__).resolve().parents[1]
    conf = tomllib.loads((root / "wrangler.toml").read_text(encoding="utf-8"))
    assert conf["main"] == "worker.py"
    assert conf["find_additional_modules"] is True
    assert conf["preserve_file_names"] is True
    assert any(
        rule.get("type") == "Text"
        and rule.get("globs") == ["app/pilot/b14_models.json"]
        and rule.get("fallthrough") is True
        for rule in conf["rules"]
    )
    assert (root / "app/pilot/b14_models.json").is_file()
    assert not (root / "app/pilot/_b14_models_embedded.py").exists()
    with pytest.raises(ModelRegistryError, match="invalid B14 JSON registry"):
        read_registry(tmp_path / "missing-b14_models.json")

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



def test_opencodego_catjam_and_owner_selected_muse_fallbacks_enabled():
    """The owner-approved Cat Jam route is enabled; unrelated Go and ZansLab routes remain OFF."""
    reg = read_registry()
    providers = reg["providers"]
    assert providers["opencode-go"]["base_origin"] == "https://opencode.ai/inference/go/v1"
    assert providers["opencode-go"]["credential_binding_name"] == "PADIEM_B14_CREDENTIAL_11"
    assert providers["zanslab"]["base_origin"] == "https://zanslab.id/v1"
    assert providers["zanslab"]["credential_binding_name"] == "PADIEM_ZANSLAB_API_KEY"
    assert providers["opencode-go"]["enabled"] is True
    assert providers["zanslab"]["enabled"] is False
    # Cat Jam is the only enabled Go route; other Go and ZansLab models stay disabled.
    rows = [row for row in reg["models"] if row["provider_id"] == "opencode-go"]
    assert {row["upstream_model"] for row in rows} == {
        "cat-jam-free", "longcat-2.5-preview-free", "step-5-preview-free",
        "muse-spark-1.3-contributor", "muse-spark-1.2-contributor", "gpt-6-luna", "claude-haiku-5-5",
    }
    assert [row["id"] for row in rows if row["enabled"]] == [
        "opencode-go/cat-jam-free",
        "opencode-go/muse-spark-1.2-contributor",
        "opencode-go/muse-spark-1.3-contributor",
    ]
    zans_rows = [row for row in reg["models"] if row["provider_id"] == "zanslab"]
    assert len(zans_rows) == 1
    assert zans_rows[0]["id"] == "zanslab/gpt-6-luna"
    assert zans_rows[0]["upstream_model"] == "op/gpt-6-luna"
    assert zans_rows[0]["enabled"] is False
    assert zans_rows[0]["context_window"] == 0
    assert zans_rows[0]["input_price_usd_per_1m"] is None
    assert zans_rows[0]["output_price_usd_per_1m"] is None
    assert "free" not in zans_rows[0]["capabilities"]
    assert get_catalog_by_id("zanslab/gpt-6-luna").enabled is False
    assert not any(model_id.startswith(("opencode-go/", "zanslab/"))
                   for tier in ("plus", "pro", "max") for model_id in reg["groups"][tier])
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    wrangler = (root / "wrangler.toml").read_text(encoding="utf-8")
    import tomllib
    bindings = tomllib.loads(wrangler)["secrets_store_secrets"]
    for name in ("PADIEM_B14_CREDENTIAL_11", "PADIEM_ZANSLAB_API_KEY"):
        matches = [x for x in bindings if x["binding"] == name]
        assert len(matches) == 1
        assert matches[0] == {
            "binding": name,
            "secret_name": name,
            "store_id": "f0b09ca04a7b43248154c773704a5616",
        }
    assert len({x["binding"] for x in bindings}) == len(bindings)
    assert "PADIEM_OPENCODE_GO_API_KEY" not in wrangler
