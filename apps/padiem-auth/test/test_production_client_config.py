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


    def test_chat_comparison_has_exact_callback_and_public_key(self):
        config = tomllib.loads((pathlib.Path(__file__).parents[1] / 'wrangler.toml').read_text())
        client = json.loads(config['vars']['PADIEM_AUTH_CLIENTS'])['b62']
        self.assertEqual(client['id'], 'b62')
        self.assertEqual(client['redirect_uris'], [
            'https://chat.padiem.net/_test/auth/account-comparison/callback',
            'https://chat.padiem.net/auth/shared/callback',
        ])
        keys = client['jwks']['keys']
        self.assertEqual(len(keys), 1)
        self.assertEqual(keys[0]['kid'], 'b62-42c57a6725c907f7f3cf')
        self.assertEqual(keys[0]['kty'], 'EC')
        self.assertEqual(keys[0]['crv'], 'P-256')
        self.assertNotIn('d', keys[0])

if __name__ == '__main__':
    unittest.main()
