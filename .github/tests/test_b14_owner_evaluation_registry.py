"""Registry-driven B14 evaluation eligibility, no provider calls."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[2]
SCRIPTS=ROOT/".github"/"scripts"
sys.path.insert(0,str(SCRIPTS))
from b14_owner_evaluation_registry import (
    CANONICAL_REGISTRY, OWNER_RETIRED, authorize_exact_models,
    authorize_historical_selector, load_current_models, main,
)

TEN={
    "agnes-ai/agnes-3.0-flash",
    "atria/Atria-Dawn-Preview",
    "experiential/qwen3.8-flash-next-uncensored",
    "google/gemini-3.1-flash-lite",
    "google/gemini-3.5-flash-lite",
    "google/gemma-4-26b-a4b-it",
    "google/gemma-4-31b-it",
    "inception/mercury-2.5",
    "poolside/laguna-s-2.1",
    "sensenova/sensenova-6.8-flash-lite",
}

def test_current_roster_is_ten_registered_models_only():
    got=load_current_models()
    assert set(got)==TEN
    assert len(got)==10
    assert not (set(got)&OWNER_RETIRED)
    assert authorize_exact_models(tuple(got))==tuple(got)
    assert got["poolside/laguna-s-2.1"]["provider_id"]=="poolside"

@pytest.mark.parametrize("deleted", sorted(OWNER_RETIRED) + [
    "kilo/poolside/laguna-s-2.1:free",
    "kilo/poolside/laguna-s-2.1",
    "kilo/poolside-laguna-s-2.1",
    "kilo/nvidia-nemotron-3-ultra-550b-a55b:free",
    "kilo/stepfun/step-5-preview-free",
    "kilo/stepfun/step-3.7-flash:free",
    "kilo/stepfun-step-3.7-flash-free",
    "thinkingmachines/inkling-small:free",
    "kilo/thinkingmachines/inkling-small:free",
    "kilo/thinkingmachines-inkling-small-free",
])
def test_retired_discovered_or_draft_routes_cannot_be_evaluated(deleted):
    with pytest.raises(ValueError):
        authorize_exact_models((deleted,))

def test_retirement_is_exact_to_inkling_small_only():
    from b14_owner_evaluation_registry import _disallowed_model_id
    for name in (
        "thinkingmachines/inkling-small:free",
        "kilo/thinkingmachines/inkling-small:free",
        "kilo/thinkingmachines-inkling-small-free",
    ):
        assert _disallowed_model_id(name)
    for allowed in (
        "thinkingmachines/inkling-smallish:free",
        "thinkingmachines/inkling-large:free",
        "cohere/north-mini-code:free",
        "stepfun/step-5-preview-free",
    ):
        assert not _disallowed_model_id(allowed)


def test_stepfun_37_retirement_is_not_overridden_by_a_future_registry(tmp_path):
    canonical=json.loads(CANONICAL_REGISTRY.read_text(encoding="utf-8"))
    # Even a future accidentally introduced provider/registration must fail
    # before an eval caller reaches credentials or network.
    canonical["providers"]["kilo"]={
        "base_origin":"https://api.kilo.ai/api/gateway",
        "credential_source":"none",
        "enabled":True,
    }
    for mid,upstream in (
        ("kilo/stepfun/step-3.7-flash","stepfun/step-3.7-flash"),
        ("kilo/stepfun-step-3.7-flash-free","stepfun/step-3.7-flash"),
    ):
        data=json.loads(json.dumps(canonical))
        data["models"].append({
            "id":mid,"provider_id":"kilo","upstream_model":upstream,"enabled":True
        })
        path=tmp_path/(str(len(mid))+".json")
        path.write_text(json.dumps(data),encoding="utf-8")
        with pytest.raises(ValueError,match="owner_retired_model_in_registry"):
            load_current_models(path)


def test_owner_retired_inkling_small_cannot_be_reintroduced_via_registry(tmp_path):
    source = json.loads(CANONICAL_REGISTRY.read_text(encoding="utf-8"))
    source["providers"]["kilo"] = {
        "base_origin": "https://api.kilo.ai/api/gateway",
        "credential_source": "none",
        "enabled": True,
    }
    for public_id, upstream in [
        ("kilo/thinkingmachines/inkling-small:free", "thinkingmachines/inkling-small:free"),
        ("kilo/safe-model", "thinkingmachines/inkling-small:free"),
    ]:
        mutated = json.loads(json.dumps(source))
        mutated["models"].append({
            "id": public_id,
            "provider_id": "kilo",
            "upstream_model": upstream,
            "enabled": True,
        })
        path=tmp_path/(public_id.split("/")[-1] + ".json")
        path.write_text(json.dumps(mutated), encoding="utf-8")
        with pytest.raises(ValueError, match="owner_retired_model_in_registry"):
            load_current_models(path)


def test_no_duplicate_batch_or_implicit_auto():
    one = next(iter(load_current_models()))
    with pytest.raises(ValueError,match="evaluation_duplicate_candidates"):
        authorize_exact_models((one, one))
    for name in ("b14/auto","all-five","poolside","google/gemini-3.1-flash-lite-preview"):
        with pytest.raises(ValueError):
            authorize_exact_models((name,))

@pytest.mark.parametrize("selector,model",[
    ("agnes","agnes-ai/agnes-3.0-flash"),
    ("atria","atria/Atria-Dawn-Preview"),
    ("mercury","inception/mercury-2.5"),
])
def test_legacy_surviving_selectors_must_pass_central_registry(selector,model):
    assert authorize_historical_selector(selector)==(model,)

@pytest.mark.parametrize("selector",["motif","luna","all-five","poolside","b14/auto","stepfun"])
def test_legacy_retired_or_unregistered_selector_is_blocked(selector):
    with pytest.raises(ValueError):
        authorize_historical_selector(selector)

def test_exact_poolside_provider_route_cannot_drift_to_kilo(tmp_path):
    data=json.loads(CANONICAL_REGISTRY.read_text(encoding="utf-8"))
    for change in ("id","provider_id","upstream_model","base_origin","credential_binding_name"):
        mutated=json.loads(json.dumps(data))
        model=next(row for row in mutated["models"] if row["id"]=="poolside/laguna-s-2.1")
        if change=="base_origin":
            mutated["providers"]["poolside"]["base_origin"]="https://api.kilo.ai/api/gateway"
        elif change=="credential_binding_name":
            mutated["providers"]["poolside"]["credential_binding_name"]="PADIEM_KILO_API_KEY"
        else:
            model[change]="kilo/poolside/laguna-s-2.1:free"
        path=tmp_path/(change+".json")
        path.write_text(json.dumps(mutated),encoding="utf-8")
        with pytest.raises(ValueError):
            load_current_models(path)

def test_main_inert_list_and_only_exact_selector(capsys):
    assert main(["--list"])==0
    out=json.loads(capsys.readouterr().out)
    assert set(out["model_ids"])==TEN
    assert out["network_calls"]==0
    assert out["automatic_fallbacks"]==0
    assert not out["production_changed"]
    assert main(["--check","poolside/laguna-s-2.1"])==0
    assert json.loads(capsys.readouterr().out)["candidate_count"]==1
    assert main(["--legacy-check","motif"])==2
    assert "BLOCKED" in capsys.readouterr().out

def test_legacy_real_runner_checks_registry_before_any_transport(monkeypatch,capsys):
    spec=importlib.util.spec_from_file_location("b14_model_evaluation_live",SCRIPTS/"b14_model_evaluation_live.py")
    module=importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name]=module
    spec.loader.exec_module(module)
    def forbidden(*args,**kwargs):
        raise AssertionError("retired route reached transport")
    monkeypatch.setattr(module,"urllib_transport",forbidden)
    for selector in ("motif","luna","all-five"):
        assert module.main([selector,"--authorized-live-run"])==2
        assert "LIVE_PROVIDER_CALL=0" in capsys.readouterr().out

def test_legacy_dispatch_dropdown_excludes_retired_live_selectors():
    wf=(ROOT/".github/workflows/b14-model-evaluation-live.yml").read_text(encoding="utf-8")
    block=wf.split("candidate_selector:",1)[1].split("expected_b14_version:",1)[0]
    assert "- all-five" not in block
    assert "- motif" not in block
    assert "- luna" not in block
    for selected in ("agnes","atria","mercury"):
        assert "- "+selected in block
    assert "Owner registry evaluation preflight" in wf
    assert "b14_owner_evaluation_registry.py --legacy-check" in wf
