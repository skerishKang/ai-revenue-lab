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

    def test_bindings_require_staging_database_and_no_service(self):
        bindings = [{'type': 'd1', 'name': 'PADIEM_CHAT_DB', 'id': module.DB},
                    {'type': 'assets', 'name': 'ASSETS'}, {'type': 'version_metadata', 'name': 'CF_VERSION_METADATA'},
                    {'type': 'plain_text', 'name': 'PC_QUEUE_BACKEND', 'text': 'd1'},
                    {'type': 'plain_text', 'name': 'PADIEM_CHAT_SHARED_LOGIN_ENABLED', 'text': 'false'},
                    {'type': 'plain_text', 'name': 'PADIEM_CHAT_PUBLIC_BASE_URL', 'text': 'https://padiem-chat-staging.charliekant.workers.dev'}]
        module.verify_bindings({'resources': {'bindings': bindings}})
        with self.assertRaises(ValueError):
            module.verify_bindings({'resources': {'bindings': bindings + [{'type': 'service', 'name': 'PRODUCTION'}]}})
        bindings[0]['id'] = 'wrong'
        with self.assertRaises(ValueError):
            module.verify_bindings({'resources': {'bindings': bindings}})

if __name__ == '__main__':
    unittest.main()
