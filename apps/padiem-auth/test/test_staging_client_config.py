import json
import pathlib
import tomllib
import unittest

class StagingClientConfigTest(unittest.TestCase):
    def test_isolated_client_registration(self):
        config = tomllib.loads((pathlib.Path(__file__).parents[1] / 'wrangler.toml').read_text(encoding='utf-8'))
        clients = json.loads(config['vars']['PADIEM_AUTH_CLIENTS'])
        stage, prod = clients['b62-staging'], clients['b62']
        self.assertEqual(stage['id'], 'b62-staging')
        self.assertEqual(stage['redirect_uris'], ['https://padiem-chat-staging.charliekant.workers.dev/auth/shared/callback'])
        self.assertEqual(stage['profile_claims'], ['email', 'email_verified', 'name', 'picture'])
        self.assertEqual(len(stage['jwks']['keys']), 1)
        key = stage['jwks']['keys'][0]
        self.assertNotIn('d', key)
        self.assertTrue(key['kid'].startswith('b62-staging-'))
        self.assertNotEqual(key['kid'], prod['jwks']['keys'][0]['kid'])
        self.assertEqual((key['kty'], key['crv'], key['alg']), ('EC', 'P-256', 'ES256'))

if __name__ == '__main__':
    unittest.main()
