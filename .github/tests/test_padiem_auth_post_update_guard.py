import hashlib
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from padiem_auth_client_delta import fingerprints
from padiem_auth_post_update_guard import verify_after


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class PostUpdate(unittest.TestCase):
    def test_only_staging_addition_and_no_other_binding_changes(self):
        before_clients = json.dumps({'b62': {'value': 'existing'}})
        after_clients = json.dumps({'b62': {'value': 'existing'}, 'b62-staging': {'value': 'approved'}})
        bindings = [{'name': 'PADIEM_AUTH_CLIENTS', 'type': 'plain_text', 'sha256': digest(before_clients)}, {'name': 'KEY', 'type': 'secret_text'}]
        before = {'success': True, 'result': {'bindings': bindings}, 'client_fingerprints': fingerprints(before_clients)}
        after = {'success': True, 'result': {'bindings': [{**bindings[0], 'sha256': digest(after_clients)}, bindings[1]]}}
        config = {'vars': {'PADIEM_AUTH_CLIENTS': after_clients}}
        self.assertTrue(verify_after(before, after, config, config))
        for modified in ({'success': True, 'result': {'bindings': after['result']['bindings'][:-1]}}, {'success': False}, before):
            with self.subTest(case=modified), self.assertRaises(ValueError):
                verify_after(before, modified, config, config)
        bad = json.dumps({'b62': {'value': 'changed'}, 'b62-staging': {'value': 'approved'}})
        with self.assertRaises(ValueError):
            verify_after(before, after, {'vars': {'PADIEM_AUTH_CLIENTS': bad}}, config)


if __name__ == '__main__':
    unittest.main()
