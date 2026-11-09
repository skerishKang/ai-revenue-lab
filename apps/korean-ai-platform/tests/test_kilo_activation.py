from __future__ import annotations

from app.pilot.kilo_activation import (
    STATE_CONTRACT_VERIFIED,
    STATE_INACTIVE,
    STATE_LIVE_CALLABLE,
    evaluate_kilo_activation,
)

from _registry_values import (
    adapter_declaring_retired,
    placeholder_registry_active,
    requires_owner_document,
)


#: The volatile free roster this contract evaluates: the first three identities
#: the adapter keeps as its retirement metadata (the lanes it declares
#: unregistered). Read from the app rather than written here (#7241 3a). An owner
#: pin: the placeholder fixture carries no such roster, so B14 activation is not
#: exercised there.
@requires_owner_document
def _free_roster() -> tuple[str, ...]:
    provider_id, module, _retained = adapter_declaring_retired()
    own = {
        value
        for name, value in vars(module).items()
        if name.endswith("_MODEL_ID")
        and isinstance(value, str)
        and value.split("/", 1)[0] == provider_id
    }
    for value in vars(module).values():
        if isinstance(value, frozenset):
            own |= {
                identity for identity in value
                if isinstance(identity, str)
                and identity.split("/", 1)[0] == provider_id
            }
    declared = tuple(sorted(own)[:3])
    assert len(declared) == 3, "the selected adapter declares fewer lanes than this contract"
    return declared


ALLOWLIST: tuple[str, ...] = () if placeholder_registry_active() else _free_roster()
#: The roster's three lanes, in the adapter's own order: the pair that proves
#: live callability and the lane held at contract-verified state.
LAGUNA, NEMOTRON, HY3 = (ALLOWLIST + ("", "", ""))[:3]


def _model(model_id: str, prompt: object = "0", completion: object = "0") -> dict:
    return {
        "id": model_id,
        "object": "model",
        "pricing": {"prompt": prompt, "completion": completion},
    }


def test_current_catalog_and_positive_live_evidence_are_both_required() -> None:
    payload = {"data": [_model(LAGUNA), _model(NEMOTRON), _model(HY3)]}

    decisions = evaluate_kilo_activation(
        models_payload=payload,
        allowed_model_ids=ALLOWLIST,
        live_callability={LAGUNA: True, NEMOTRON: True, HY3: False},
    )
    by_id = {item.model_id: item for item in decisions}

    assert by_id[LAGUNA].state == STATE_LIVE_CALLABLE
    assert by_id[NEMOTRON].state == STATE_LIVE_CALLABLE
    assert by_id[HY3].state == STATE_CONTRACT_VERIFIED
    assert by_id[HY3].catalog_present is True
    assert by_id[HY3].zero_priced is True
    assert by_id[HY3].live_callable is False


def test_catalog_presence_and_zero_price_never_auto_promote_without_live_evidence() -> None:
    decisions = evaluate_kilo_activation(
        models_payload={"data": [_model(HY3)]},
        allowed_model_ids=(HY3,),
    )

    assert decisions[0].state == STATE_CONTRACT_VERIFIED
    assert decisions[0].reason == "zero_priced_but_live_callability_not_proven"


def test_missing_current_catalog_route_fails_closed() -> None:
    decisions = evaluate_kilo_activation(
        models_payload={"data": [_model(LAGUNA)]},
        allowed_model_ids=(LAGUNA, HY3),
        live_callability={LAGUNA: True, HY3: True},
    )
    by_id = {item.model_id: item for item in decisions}

    assert by_id[LAGUNA].state == STATE_LIVE_CALLABLE
    assert by_id[HY3].state == STATE_INACTIVE
    assert by_id[HY3].reason == "not_in_current_kilo_catalog"


def test_nonzero_or_malformed_price_fails_closed_even_with_live_flag() -> None:
    payload = {
        "data": [
            _model(LAGUNA, prompt="0.000001", completion="0"),
            _model(NEMOTRON, prompt="not-a-price", completion="0"),
            _model(HY3, prompt=True, completion="0"),
        ]
    }
    decisions = evaluate_kilo_activation(
        models_payload=payload,
        allowed_model_ids=ALLOWLIST,
        live_callability={model_id: True for model_id in ALLOWLIST},
    )

    assert all(item.state == STATE_INACTIVE for item in decisions)
    assert all(item.reason == "current_pricing_is_not_explicitly_zero" for item in decisions)


def test_malformed_models_payload_fails_closed_for_every_candidate() -> None:
    decisions = evaluate_kilo_activation(
        models_payload={"data": {"unexpected": "shape"}},
        allowed_model_ids=ALLOWLIST,
        live_callability={model_id: True for model_id in ALLOWLIST},
    )

    assert len(decisions) == 3
    assert all(item.state == STATE_INACTIVE for item in decisions)
    assert all(item.catalog_present is False for item in decisions)
