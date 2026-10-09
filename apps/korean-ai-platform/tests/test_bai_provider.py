"""B.AI removed by owner: negative registration/dispatch regression."""
import pytest
from app.pilot.catalog import get_catalog_by_id
from app.pilot.platform_secrets import get_platform_provider
from app.pilot.router_core import resolve_manual_route
from app.pilot.errors import NoSafeRoute

def test_removed_qwen_not_registered():
    assert get_catalog_by_id("b-ai/qwen3.8-flash") is None
    assert get_platform_provider("b-ai") is None

def test_removed_qwen_cannot_execute():
    with pytest.raises(NoSafeRoute) as exc:
        resolve_manual_route("b-ai/qwen3.8-flash")
    assert exc.value.upstream_called is False
