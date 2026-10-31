import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('staging_verify', Path(__file__).parents[1] / 'scripts/staging_verify.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
VERSION = 'edc14cbb-f77b-48d1-ba0a-2fa8240333b8'

class VerifyStagingTest(unittest.TestCase):
    def test_d1_identity_and_active_version(self):
        module.verify_d1([{'name': module.DB_NAME, 'uuid': module.DB}])
        with self.assertRaises(ValueError):
            module.verify_d1([{'name': module.DB_NAME, 'uuid': 'wrong'}])
        self.assertEqual(module.active_version([{'versions': [{'version_id': VERSION, 'percentage': 100}]}]), VERSION)
        with self.assertRaises(ValueError):
            module.active_version([{'versions': [{'version_id': VERSION, 'percentage': 50}]}])

    def test_bindings_require_staging_database_and_exact_service(self):
        bindings = [{'type': 'd1', 'name': 'PADIEM_CHAT_DB', 'id': module.DB},
                    {'type': 'assets', 'name': 'ASSETS'}, {'type': 'version_metadata', 'name': 'CF_VERSION_METADATA'},
                    {'type': 'plain_text', 'name': 'PC_QUEUE_BACKEND', 'text': 'd1'},
                    {'type': 'plain_text', 'name': 'PC_QUEUE_ORIGIN', 'text': 'https://queue-staging.padiem.net'},
                    {'type': 'plain_text', 'name': 'PADIEM_CHAT_LIVE_ENABLED', 'text': 'false'},
                    {'type': 'plain_text', 'name': 'PADIEM_CHAT_RUNTIME_MODE', 'text': 'mock'},
                    {'type': 'plain_text', 'name': 'PADIEM_CHAT_SHARED_AUTH_COMPARE_ENABLED', 'text': 'false'},
                    {'type': 'plain_text', 'name': 'PADIEM_CHAT_SHARED_LOGIN_ENABLED', 'text': 'true'},
                    {'type': 'plain_text', 'name': 'PADIEM_CHAT_SHARED_AUTH_CLIENT_ID', 'text': 'b62-staging'},
                    {'type': 'plain_text', 'name': 'PADIEM_CHAT_SHARED_AUTH_CLIENT_KID', 'text': module.STAGING_CLIENT_KID},
                    *[{'type': 'secret_text', 'name': name} for name in module.STAGING_AUTH_SECRETS],
                    {'type': 'plain_text', 'name': 'PADIEM_CHAT_PUBLIC_BASE_URL', 'text': 'https://padiem-chat-staging.charliekant.workers.dev'}]
        service = {'type': 'service', 'name': 'IDENTITY_AUTHORITY_SERVICE', 'service': 'padiem-control-plane-identity'}
        module.verify_bindings({'resources': {'bindings': bindings}}, before=True)
        legacy = [dict(b) for b in bindings if b['name'] != 'PADIEM_CHAT_SHARED_AUTH_CLIENT_ID']
        next(b for b in legacy if b['name'] == 'PADIEM_CHAT_SHARED_LOGIN_ENABLED')['text'] = 'false'
        module.verify_bindings({'resources': {'bindings': legacy}}, before=True)
        module.verify_bindings({'resources': {'bindings': bindings + [service]}})
        module.verify_bindings({'resources': {'bindings': bindings + [service]}}, before=True)
        with self.assertRaises(ValueError):
            module.verify_bindings({'resources': {'bindings': bindings + [service, {'type': 'secret_text', 'name': 'UNAPPROVED'}]}})
        for secret in module.STAGING_AUTH_SECRETS:
            with self.subTest(missing=secret), self.assertRaises(ValueError):
                module.verify_bindings({'resources': {'bindings': [b for b in bindings if b['name'] != secret] + [service]}})
        for extra in ([], [{'type': 'service', 'name': 'PRODUCTION', 'service': 'other'}],
                      [{**service, 'service': 'other'}], [service, service],
                      [{**service, 'environment': 'staging'}], [{**service, 'entrypoint': 'other'}]):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                module.verify_bindings({'resources': {'bindings': bindings + extra}})
        with self.assertRaises(ValueError):
            module.verify_bindings({'resources': {'bindings': bindings + [service, {'type': 'service', 'name': 'OTHER', 'service': 'other'}]}})
        bindings[0]['id'] = 'wrong'
        with self.assertRaisesRegex(ValueError, 'staging D1 binding mismatch'):
            module.verify_bindings({'resources': {'bindings': bindings + [service]}})

if __name__ == '__main__':
    unittest.main()
