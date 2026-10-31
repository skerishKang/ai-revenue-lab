import importlib.util
import unittest
from unittest.mock import patch
from pathlib import Path
p = Path(__file__).resolve().parents[1] / 'scripts/padiem_auth_domain.py'
spec = importlib.util.spec_from_file_location('domain_gate', p)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def fake(domain=None, dns=None, account='approved'):
    def call(method, url, payload=None):
        assert method == 'GET'
        if '/zones?' in url:
            return {'success': True, 'result': [{'id': 'zone', 'name': m.ZONE, 'account': {'id': account}}]}
        if '/workers/domains' in url:
            return {'success': True, 'result': [] if domain is None else [domain]}
        if '/dns_records?' in url:
            return {'success': True, 'result': [] if dns is None else [dns]}
        raise AssertionError('unexpected request')
    return call


class Gate(unittest.TestCase):
    def test_absent_and_correct_existing(self):
        self.assertEqual(m.inspect(fake(), 'approved'), 'absent')
        self.assertEqual(m.inspect(fake({'hostname': m.HOST, 'service': m.WORKER}), 'approved'), 'already-attached')
    def test_conflicts_fail_closed(self):
        for call in (fake({'hostname': m.HOST, 'service': 'other'}), fake(dns={'name': m.HOST}), fake(account='other')):
            with self.assertRaises(ValueError):
                m.inspect(call, 'approved')
    def test_readonly_no_write_and_activate_only_exact_target(self):
        account = 'a' * 32
        applied = []
        entries = []
        def request(_token, method, url, payload=None):
            if method == 'PUT':
                applied.append(payload)
                entries.append({'hostname': payload['hostname'], 'service': payload['service']})
                return {'success': True, 'result': entries[-1]}
            if '/zones?' in url:
                return {'success': True, 'result': [{'id': 'zone', 'name': m.ZONE, 'account': {'id': account}}]}
            if '/dns_records?' in url:
                return {'success': True, 'result': []}
            if '/workers/domains' in url:
                return {'success': True, 'result': entries}
            if url.endswith('/workers/scripts'):
                return {'success': True, 'result': [{'id': m.WORKER}]}
            if url.endswith('/accounts/' + account):
                return {'success': True, 'result': {'id': account}}
            raise AssertionError('unexpected request')
        with patch.object(m.Path, 'read_text', return_value='Charliekant Account ID `' + account + '`'), patch.object(m, 'request', side_effect=request):
            m.run('readonly', account, 'synthetic')
            self.assertEqual(applied, [])
            m.run('activate', account, 'synthetic')
            self.assertEqual(applied, [{'hostname': m.HOST, 'service': m.WORKER, 'zone_name': m.ZONE}])
            m.run('activate', account, 'synthetic')
            self.assertEqual(len(applied), 1)
    def test_invalid_mode_never_mutates(self):
        account = 'a' * 32
        calls = []
        def request(_token, method, url, payload=None):
            calls.append(method)
            if url.endswith('/accounts/' + account):
                return {'success': True, 'result': {'id': account}}
            if url.endswith('/workers/scripts'):
                return {'success': True, 'result': [{'id': m.WORKER}]}
            return fake(account=account)(method, url, payload)
        with patch.object(m.Path, 'read_text', return_value='Charliekant Account ID `' + account + '`'), patch.object(m, 'request', side_effect=request):
            with self.assertRaises(ValueError):
                m.run('wrong', account, 'synthetic')
        self.assertNotIn('PUT', calls)

if __name__ == '__main__':
    unittest.main()
