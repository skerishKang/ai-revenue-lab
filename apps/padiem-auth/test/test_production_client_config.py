import json
import pathlib
import tomllib
import unittest

class AuthClientConfigTest(unittest.TestCase):
    def test_lovetree_callbacks_and_public_keys(self):
        config = tomllib.loads((pathlib.Path(__file__).parents[1] / 'wrangler.toml').read_text())
        client = json.loads(config['vars']['PADIEM_AUTH_CLIENTS'])['lovetree-4-0']
        self.assertEqual(set(client['redirect_uris']), {
            'https://lovetree-4-0.pages.dev/auth/callback',
            'https://ai-astra4-preview-auth-callb.lovetree-4-0.pages.dev/auth/callback',
        })
        keys = client['jwks']['keys']
        self.assertEqual(len(keys), 2)
        self.assertEqual(len({key['kid'] for key in keys}), 2)
        self.assertTrue(all(key.get('kty') == 'EC' and key.get('crv') == 'P-256' and 'd' not in key for key in keys))

if __name__ == '__main__':
    unittest.main()
