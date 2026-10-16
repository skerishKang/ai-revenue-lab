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
        [{"id": ID, "annotations": {"workers/tag": "padiem-main-" + SHA}}],
        {"status": "ok", "business14": {"providers": [{"has_key": True} for _ in range(11)]}},
        {"catalog": [{"id": "opaque"}]},
    )


def test_good_receipt_only():
    mod.verify_candidate(ID, SHA, *good())


@pytest.mark.parametrize("broken,reason", [
    (lambda a: a[0][0]["annotations"].update({"workers/tag": "padiem-main-" + "0" * 40}), "CANDIDATE_MAIN_ATTESTATION_MISSING"),
    (lambda a: a[0].clear(), "CANDIDATE_VERSION_NOT_UNIQUE_OR_ABSENT"),
    (lambda a: a[1]["business14"]["providers"].pop(), "CANDIDATE_PROVIDER_COUNT_UNEXPECTED"),
    (lambda a: a[1]["business14"]["providers"][0].update({"has_key": False}), "CANDIDATE_CREDENTIAL_GETTER_NOT_READY"),
    (lambda a: a[2]["catalog"].clear(), "CANDIDATE_CATALOG_NOT_AVAILABLE"),
])
def test_fail_closed(broken, reason):
    arguments=list(good())
    broken(arguments)
    with pytest.raises(ValueError, match=reason):
        mod.verify_candidate(ID, SHA, *arguments)
