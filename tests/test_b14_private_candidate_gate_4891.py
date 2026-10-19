from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

P = Path(__file__).resolve().parents[1] / ".github/scripts/b14_private_candidate_gate.py"
spec = spec_from_file_location("b14_private_candidate_gate", P)
mod = module_from_spec(spec)
spec.loader.exec_module(mod)

ID = "02a873cd-ef89-4d44-91b0-7215c39523e4"
SHA = "e23408873a53c2c1f13de2f2815c07801412012f"


def good():
    return (
        [{"id": ID, "annotations": {"workers/tag": "padiem-main-" + SHA, "workers/alias": "b14-4891-source"}}],
        {"status": "ok", "business14": {"providers": [{"has_key": True} for _ in range(11)]}},
        {"catalog": [{"id": "opaque"}]},
    )


def test_good_receipt_only():
    mod.verify_candidate(ID, SHA, *good())
    assert mod.resolve_preview_alias(ID, SHA, good()[0]) == "b14-4891-source"


@pytest.mark.parametrize("broken,reason", [
    (lambda a: a[0][0]["annotations"].update({"workers/tag": "padiem-main-" + "0" * 40}), "CANDIDATE_MAIN_ATTESTATION_MISSING"),
    (lambda a: a[0].clear(), "CANDIDATE_VERSION_NOT_UNIQUE_OR_ABSENT"),
    (lambda a: a[0][0]["annotations"].update({"workers/alias": "invalid/path"}), "CANDIDATE_PREVIEW_ALIAS_UNAVAILABLE"),
    (lambda a: a[0][0]["annotations"].pop("workers/alias"), "CANDIDATE_PREVIEW_ALIAS_UNAVAILABLE"),
    (lambda a: a[1]["business14"]["providers"].pop(), "CANDIDATE_PROVIDER_COUNT_UNEXPECTED"),
    (lambda a: a[1]["business14"]["providers"][0].update({"has_key": False}), "CANDIDATE_CREDENTIAL_GETTER_NOT_READY"),
    (lambda a: a[2]["catalog"].clear(), "CANDIDATE_CATALOG_NOT_AVAILABLE"),
])
def test_fail_closed(broken, reason):
    arguments=list(good())
    broken(arguments)
    with pytest.raises(ValueError, match=reason):
        mod.verify_candidate(ID, SHA, *arguments)


def test_dispatch_only_and_promotion_after_live_preflight():
    import yaml
    workflow = Path(__file__).resolve().parents[1] / '.github/workflows/b14-production-deploy-gate.yml'
    data = yaml.safe_load(workflow.read_text(encoding='utf-8'))
    jobs = data['jobs']
    promotion = jobs['promote-verified-private-candidate-b14']
    assert promotion['environment'] == 'production'
    assert promotion['if'] == "github.event.inputs.confirmation == 'PROMOTE_B14_VERIFIED_PRIVATE_CANDIDATE'"
    steps = promotion['steps']
    preflight = next(i for i, step in enumerate(steps) if step['name'].startswith('Check candidate'))
    deploy = next(i for i, step in enumerate(steps) if step['name'].startswith('Promote candidate'))
    assert preflight < deploy
    assert 'B14_CANDIDATE_MODEL_E2E=FAIL' in steps[preflight]['run']
    assert 'versions deploy' not in steps[preflight]['run']
    assert 'rollback' in steps[deploy]['run']
    assert "${{ github.event.inputs.candidate_version_id }}" in steps[deploy]['env'].values()
