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

def test_nine_models_delete_five():
    reg=read_registry()
    ids={m["id"] for m in reg["models"]}
    assert len(ids)==9
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
    assert {r["id"] for r in data["catalog"]}==set(expected)
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
        "assert ids.isdisjoint({'kilo','b-ai','infron','experiential'});"
        "assert len(CATALOG_BY_ID)==9"
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
    lambda d:d["models"][0].update({"enabled":False}),
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
    assert len(read_registry(path)["models"])==9

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
    models=read_registry()["models"]
    for row in models:
        assert 'value="'+row["id"]+'"' in html
    for retired in RETIRED:
        assert 'value="'+retired+'"' not in html
    assert html.count('data-provider=') >= len(models)
