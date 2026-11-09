"""B.AI removed by owner: negative registration/dispatch regression.

#7241 3단계: the retired deployment identity is never written here. The
subject is read from the registry's own retirement list — the identities the
owner removed from the shipped document — and its Provider is the owner part of
that identity, so the negative registration and execution contracts run over
whatever the retirement list names.
"""
import pytest
from app.pilot.catalog import get_catalog_by_id
from app.pilot.model_registry_file import retired_model_ids
from app.pilot.platform_secrets import get_platform_provider
from app.pilot.router_core import resolve_manual_route
from app.pilot.errors import NoSafeRoute


def _removed_identity() -> tuple[str, str]:
    """(model_id, provider_id) of a retired identity with no platform Provider.

    The registry's retirement list is the app's own record of what the owner
    removed. A retired row whose Provider has no registered Platform Provider is
    exactly the "removed registration" this suite pins, so both ids are derived
    from the document rather than spelled (#7241).
    """
    for model_id in sorted(retired_model_ids()):
        provider_id = model_id.split("/", 1)[0]
        if get_platform_provider(provider_id) is None:
            return model_id, provider_id
    raise AssertionError("the registry retired no identity whose Provider is unregistered")


def test_removed_qwen_not_registered():
    model_id, provider_id = _removed_identity()
    assert get_catalog_by_id(model_id) is None
    assert get_platform_provider(provider_id) is None


def test_removed_qwen_cannot_execute():
    model_id, _provider_id = _removed_identity()
    with pytest.raises(NoSafeRoute) as exc:
        resolve_manual_route(model_id)
    assert exc.value.upstream_called is False
