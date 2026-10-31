import asyncio
import json
import unittest
from types import SimpleNamespace

from app.shared_auth_compare_routes import comparison_routes


def run(value):
    return asyncio.run(value)


class CompareRoutesTests(unittest.TestCase):
    def test_disabled_is_unmounted_and_missing_dependencies_are_rejected(self):
        self.assertEqual(comparison_routes(), [])
        with self.assertRaises(ValueError):
            comparison_routes(enabled=True)

    def test_guarded_path_consumes_server_flow_and_returns_only_result(self):
        seen = []
        async def flow(request):
            seen.append('server_exchange')
            return 'synthetic-secret'
        async def compare(request, token):
            self.assertEqual(token, 'synthetic-secret')
            return 'MATCH'
        route = comparison_routes(enabled=True, operator_guard=lambda r: True, complete_flow=flow, comparator=compare)[0]
        response = run(route.endpoint(SimpleNamespace()))
        self.assertEqual(route.path, '/_test/auth/account-comparison')
        self.assertEqual(json.loads(response.body), {'result': 'MATCH'})
        self.assertNotIn(b'synthetic-secret', response.body)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(seen, ['server_exchange'])

    def test_unauthorized_request_never_reaches_flow(self):
        async def forbidden(_):
            raise AssertionError('flow reached')
        route = comparison_routes(enabled=True, operator_guard=lambda r: False, complete_flow=forbidden, comparator=forbidden)[0]
        response = run(route.endpoint(SimpleNamespace()))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(json.loads(response.body), {'result': 'UNKNOWN'})

    def test_failures_and_unexpected_results_are_unknown(self):
        async def fails(_):
            raise ValueError('sensitive diagnostic must not escape')
        async def unexpected(_, token):
            return 'bad'
        for flow, compare in [(fails, unexpected), (lambda r: 'synthetic', unexpected)]:
            route = comparison_routes(enabled=True, operator_guard=lambda r: True, complete_flow=flow, comparator=compare)[0]
            response = run(route.endpoint(SimpleNamespace()))
            self.assertEqual(json.loads(response.body), {'result': 'UNKNOWN'})
            self.assertNotIn(b'sensitive', response.body)
