import unittest
from starlette.routing import Route

from app.app_factory import create_app
from app.config import Settings


class Flow:
    def routes(self, *, enabled):
        assert enabled is True
        return [Route('/_test/auth/account-comparison/start', lambda request: None)]


class FactoryTests(unittest.TestCase):
    def test_test_routes_are_unmounted_by_default_and_precede_static_when_injected(self):
        settings = Settings.from_values(runtime_mode='mock', auth_mode='off')
        default = create_app(settings=settings)
        self.assertFalse(any(getattr(route, 'path', '').startswith('/_test/auth/account-comparison') for route in default.routes))
        injected = create_app(settings=settings, shared_auth_comparison_flow=Flow())
        self.assertEqual(injected.routes[0].path, '/_test/auth/account-comparison/start')
