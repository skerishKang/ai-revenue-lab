"""Snapshot templates must not contain per-app authority or share mutable routes."""
from pathlib import Path
from starlette.routing import Route
from app.app_factory import _SNAPSHOT_BASE_ROUTES, create_app
from app.config import Settings


def test_snapshot_contains_only_static_route_definitions():
    assert _SNAPSHOT_BASE_ROUTES
    assert all(type(route) is Route for route in _SNAPSHOT_BASE_ROUTES)
    for route in _SNAPSHOT_BASE_ROUTES:
        assert callable(route.endpoint)
        assert isinstance(route.path, str)
        assert not hasattr(route, 'state')
        assert not hasattr(route, 'env')
        assert not hasattr(route, 'ctx')
        for value in vars(route).values():
            assert not isinstance(value, Settings)
            assert not type(value).__module__.startswith(('pyodide', 'js'))
    worker = (Path(__file__).parents[1] / 'worker.py').read_text(encoding='utf-8')
    assert 'from app.main import create_app' not in worker
    assert 'from app.app_factory import create_app' in worker


def test_route_objects_and_method_sets_are_per_app():
    synthetic = "snapshot-test-only-credential"
    one = create_app(settings=Settings(session_secret=synthetic))
    two = create_app(settings=Settings())
    assert synthetic not in repr([vars(route) for route in _SNAPSHOT_BASE_ROUTES])
    assert one.state.settings.session_secret == synthetic
    assert two.state.settings.session_secret is None
    assert one.routes[0] is not two.routes[0]
    assert one.routes[0] is not _SNAPSHOT_BASE_ROUTES[0]
    assert one.routes[0].methods is not two.routes[0].methods
    assert one.routes[-1] is not two.routes[-1]
